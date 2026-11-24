"""Sensör servisi (arayüzsüz): yardımcıdan gelen ölçümlerin en düşük / en yüksek / ortalamasını tutar, isteğe bağlı
sıcaklık uyarısı (Windows bildirimi) ve CSV günlüğü yazar.

Yardımcıya abonelik yalnızca gerektiğinde: Sensörler sekmesi görünürken, ya da uyarı / CSV kaydı açıkken (ikisi de
varsayılan kapalı). Hiçbir veri ağa gönderilmez."""
import csv
import datetime
import os
import time

from PyQt6.QtCore import QObject, pyqtSignal

from .config import DATA_DIR, log_error, prefs
from .helper_client import client

GROUPS = ["cpu", "gpu", "memory", "motherboard", "storage", "battery", "controller", "network", "psu"]
DEFAULT_GROUPS = ["cpu", "gpu", "memory", "motherboard", "storage", "battery", "controller"]
UNITS = {"Temperature": "°C", "Fan": "RPM", "Voltage": "V", "Power": "W", "Clock": "MHz", "Load": "%",
         "Control": "%", "Level": "%", "Data": "GB", "SmallData": "MB", "Throughput": "B/s", "Energy": "mWh",
         "Current": "A", "Frequency": "Hz", "Noise": "dBA", "Humidity": "%", "Factor": "", "TimeSpan": "s",
         "Conductivity": "µS/cm", "Timing": "ns"}
LOG_DIR = os.path.join(DATA_DIR, "logs")


def groups():
    g = prefs.get("sensors_groups")
    return [x for x in g if x in GROUPS] if isinstance(g, list) else list(DEFAULT_GROUPS)


class SensorService(QObject):
    updated = pyqtSignal(dict)          # son ölçüm (yardımcı biçimi)
    alert = pyqtSignal(str, float)      # sensör adı, değer

    def __init__(self):
        super().__init__()
        self.c = client()
        self.c.sensors.connect(self._on_sensors)
        self.visible = False
        self.last = None
        self.stats = {}                 # id -> [min, max, toplam, n]
        self.since = time.time()
        self._hot_since = {}            # id -> ilk aşım zamanı
        self._alerted = {}              # id -> son bildirim zamanı
        self._csv = None                # (dosya, yazıcı, imza)
        self._tray = None
        self.alert.connect(self._notify)
        self.apply()

    # ---- abonelik
    def needed(self):
        return self.visible or bool(prefs.get("sensors_alert", False)) or bool(prefs.get("sensors_csv", False))

    def apply(self):
        self.c.want(self.needed(), groups(), 1000)
        if not prefs.get("sensors_csv", False):
            self._close_csv()

    def set_visible(self, on):
        self.visible = on
        self.apply()

    def reset(self):
        self.stats = {}
        self.since = time.time()
        self.updated.emit(self.last or {"hardware": []})

    def stop(self):
        self._close_csv()
        if self._tray is not None:
            self._tray.hide()
        self.c.stop()

    # ---- veri
    def _on_sensors(self, msg):
        self.last = msg
        now = msg.get("t") or time.time()
        for h in msg.get("hardware", []):
            for s in h.get("sensors", []):
                v = s.get("value")
                if v is None:
                    continue
                st = self.stats.get(s["id"])
                if st is None:
                    self.stats[s["id"]] = [v, v, v, 1]
                else:
                    st[0] = min(st[0], v)
                    st[1] = max(st[1], v)
                    st[2] += v
                    st[3] += 1
        if prefs.get("sensors_alert", False):
            self._check_alerts(msg, now)
        if prefs.get("sensors_csv", False):
            self._write_csv(msg, now)
        self.updated.emit(msg)

    def stat(self, sid):
        st = self.stats.get(sid)
        if not st:
            return None, None, None
        return st[0], st[1], st[2] / st[3]

    # ---- uyarı: CPU / GPU sıcaklığı eşiği belirli süre aşarsa bildirim (aynı sensör için en çok 5 dk'da bir)
    def _check_alerts(self, msg, now):
        limit = float(prefs.get("sensors_alert_temp", 95))
        hold = float(prefs.get("sensors_alert_secs", 30))
        for h in msg.get("hardware", []):
            if not (h["type"] == "Cpu" or h["type"].startswith("Gpu")):
                continue
            for s in h.get("sensors", []):
                if s["type"] != "Temperature" or s.get("value") is None:
                    continue
                if s["value"] >= limit:
                    first = self._hot_since.setdefault(s["id"], now)
                    if now - first >= hold and now - self._alerted.get(s["id"], 0) > 300:
                        self._alerted[s["id"]] = now
                        self.alert.emit(f"{h['name']} — {s['name']}", s["value"])
                else:
                    self._hot_since.pop(s["id"], None)

    def _notify(self, name, value):
        """Windows bildirimi (tepsi simgesi yalnızca bildirim için görünür olur)."""
        from PyQt6.QtGui import QIcon
        from PyQt6.QtWidgets import QSystemTrayIcon
        from .config import asset
        from .i18n import t
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        if self._tray is None:
            self._tray = QSystemTrayIcon(QIcon(asset("logo.ico")))
            self._tray.setToolTip("mergen")
        self._tray.show()
        v = f"{value:.0f} °C"
        self._tray.showMessage("mergen", t("alert_text", name=name, value=v),
                               QSystemTrayIcon.MessageIcon.Warning, 10000)

    # ---- CSV
    def _write_csv(self, msg, now):
        cols = [(s["id"], f"{h['name']} / {s['name']} [{UNITS.get(s['type'], '')}]".replace(" []", ""))
                for h in msg.get("hardware", []) for s in h.get("sensors", [])]
        sig = tuple(c[0] for c in cols)
        try:
            if self._csv is None or self._csv[2] != sig:
                self._close_csv()
                os.makedirs(LOG_DIR, exist_ok=True)
                name = datetime.datetime.now().strftime("sensors-%Y%m%d-%H%M%S.csv")
                f = open(os.path.join(LOG_DIR, name), "w", encoding="utf-8-sig", newline="")
                w = csv.writer(f, delimiter=";")
                w.writerow(["time"] + [c[1] for c in cols])
                self._csv = (f, w, sig)
            f, w, _ = self._csv
            vals = {s["id"]: s.get("value") for h in msg.get("hardware", []) for s in h.get("sensors", [])}
            w.writerow([datetime.datetime.fromtimestamp(now).isoformat(" ", "seconds")] +
                       ["" if vals.get(c[0]) is None else vals[c[0]] for c in cols])
            f.flush()
        except OSError as e:
            log_error(f"sensors csv: {e!r}")
            prefs.set("sensors_csv", False)
            self._close_csv()

    def _close_csv(self):
        if self._csv is not None:
            try:
                self._csv[0].close()
            except OSError:
                pass
            self._csv = None


_service = None


def service():
    global _service
    if _service is None:
        _service = SensorService()
    return _service
