"""mergen uçtan uca testi. Gerçek tercihlere, kayıt defterine ve ağa dokunmaz; ekranda pencere açmaz.
Gerçek fan / güç / Windows ayarı yazımı bu testte ASLA yapılmaz.

Kullanım: python tests/smoke_test.py"""
import json
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="mergen_test_")
os.environ["LOCALAPPDATA"] = TMP
os.environ["MERGEN_DATA_DIR"] = os.path.join(TMP, "mergen")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

fails = []


def _raises(fn, exc=NotImplementedError):
    try:
        fn()
    except exc:
        return True
    return False


def check(name, cond):
    print(("  ok   " if cond else "  HATA ") + name)
    if not cond:
        fails.append(name)


import mergen  # noqa: E402
from mergen import config, i18n, theme as T  # noqa: E402
from mergen.config import prefs  # noqa: E402

print("çekirdek")
check("sürüm biçimi", mergen.__version__.count(".") == 2)
check("tercihler geçici klasörde", prefs.path.startswith(TMP))
prefs.set("last_page", "programs")
check("tercih diske yazılır", json.load(open(prefs.path, encoding="utf-8"))["last_page"] == "programs")
config.log_error("deneme satırı")
check("error.log yazılır", "deneme satırı" in open(config.ERROR_LOG, encoding="utf-8").read())
check("logo dosyaları", os.path.exists(config.asset("logo.png")) and os.path.exists(config.asset("logo.ico")))

print("dil")
tr, en = i18n._load("tr"), i18n._load("en")
check("tr / en anahtarları aynı", set(tr) == set(en) and len(tr) > 10)
check("Türkçe varsayılan", i18n.t("page_system") == "Sistem")
check("biçimlendirme", i18n.t("search_placeholder", page="X") == "X içinde ara")
check("bilinmeyen anahtar kendisi döner", i18n.t("yok_boyle_bir_sey") == "yok_boyle_bir_sey")

print("tema")
yz = os.path.join(ROOT, "..", "yazıt", "yazit", "theme.py")
tp = os.path.join(ROOT, "..", "tamga", "tamga", "palette.py")
for other in (yz, tp):
    if os.path.exists(other):
        ns = {}
        src = open(other, encoding="utf-8").read()
        start = src.index("ACCENTS = {")
        end = src.index('_LEGACY = {"dark": "amoled", "light": "white"}')
        exec(src[start:end], ns)
        check("paletler birebir aynı: " + os.path.basename(os.path.dirname(other)),
              ns["ACCENTS"] == T.ACCENTS and ns["PALETTES"] == T.PALETTES and ns["VARIANTS"] == T.VARIANTS)
sync_src = os.path.join(ROOT, "..", "tamga", "sync", "tamga_sync.py")
if os.path.exists(sync_src):
    check("tamga_sync birebir kopya", open(sync_src, "rb").read()
          == open(os.path.join(ROOT, "mergen", "tamga_sync.py"), "rb").read())
for v in T.VARIANTS:
    prefs.data["theme"] = v
    check("stil sayfası: " + v, "#SideBar" in T.stylesheet() and "purple" not in T.stylesheet())
prefs.data["theme"] = "amoled"
check("vurgu varsayılanı gri", T.accent() == "#c4c4c4")

print("sistem bilgisi (salt okunur, gerçek WMI)")
import time  # noqa: E402
from mergen.collect import fmt, report, system as S  # noqa: E402
prefs.data["language"] = "tr"
check("bayt biçimi", fmt.text(fmt.B(16 * 2 ** 30)) == "16 GB" and fmt.text(fmt.B(1310720)) == "1,25 MB"
      and fmt.text(fmt.B(512110190592)) == "477 GB")
check("sayı biçimi tr", fmt.text(fmt.N(47160, "mWh")) == "47.160 mWh" and fmt.text(fmt.N(86.56, "%", 1)) == "%86,6"
      and fmt.text(fmt.N(16.416, "V", 2)) == "16,42 V")
prefs.data["language"] = "en"
check("sayı biçimi en", fmt.text(fmt.N(47160, "mWh")) == "47,160 mWh" and fmt.text(fmt.N(86.56, "%", 1)) == "86.6%")
prefs.data["language"] = "tr"
check("boş değer —", fmt.text(None) == "—" and fmt.text(fmt.YES(True)) == "Evet")
check("WMI temizleme", S.wmi.clean("To Be Filled By O.E.M.") is None and S.wmi.clean("  ABRA  A5 ") == "ABRA A5")
check("ODM: Clevo / Monster", S._odm("Notebook", "ABRA A5 V17.2", "Notebook") == ("Monster Notebook", "Clevo"))
t0 = time.time()
data = S.collect()
ids = [s["id"] for s in data["sections"]]
check(f"tüm bölümler toplanır ({time.time() - t0:.1f} sn)", ids == S.SECTIONS and time.time() - t0 < 60)
check("JSON'a yazılabilir", bool(json.dumps(data)))
gen = {r["k"]: r for r in data["sections"][0]["rows"]}
check("genel: bilgisayar adı + Windows", gen["lbl_computer_name"]["v"] and gen["lbl_windows"]["v"])
check("seri no kişisel işaretli", gen["lbl_serial"].get("s") is True)
errs = [s["id"] for s in data["sections"] if s["rows"] and s["rows"][0]["k"] == "lbl_error"]
check("hiçbir bölüm hata vermedi " + str(errs), not errs)
check("bilgisayar adı ekranda görünür, raporda çıkarılır", gen["lbl_computer_name"].get("s") == "r")
fake = {"sections": [{"id": "general", "rows": [fmt.row("lbl_serial", "GIZLI-SERI-123", True),
                                                fmt.row("lbl_computer_name", "GIZLI-PC", "r"),
                                                fmt.row("lbl_model", "ABRA")], "groups": []}]}
check("kopyala yalnızca ekranda gizlileri çıkarır", "GIZLI-PC" in report.section_text(
    report._strip(fake, only_hidden=True)["sections"][0], __import__("mergen.i18n").i18n.t))
from mergen.i18n import t as tr_  # noqa: E402
for kind in ("txt", "html", "json"):
    p = os.path.join(TMP, "rapor." + kind)
    report.write(p, kind, fake, tr_, strip=True)
    body = open(p, encoding="utf-8").read()
    check(f"rapor {kind}: kişisel bilgi çıkarılır", "GIZLI-SERI-123" not in body and "GIZLI-PC" not in body
          and "ABRA" in body)
report.write(p, "txt", fake, tr_, strip=False)
check("rapor: çıkarma kapalıysa yazılır", "GIZLI-SERI-123" in open(p, encoding="utf-8").read())

print("canlı ölçüm (salt okunur; hiçbir süreç sonlandırılmaz)")
from mergen.collect import ntproc, pdh, perf, procs  # noqa: E402
snap = ntproc.snapshot()
me = next((e for e in snap if e["pid"] == os.getpid()), None)
check("ntproc: tüm süreçler tek çağrıda", len(snap) > 20 and me is not None and me["threads"] > 0
      and me["ws_private"] > 0 and me["create"] > 1e9)
fake_arr = {
    "pid_100_luid_0x00000000_0x0000FBB6_phys_0_eng_0_engtype_3D": 30.0,
    "pid_200_luid_0x00000000_0x0000FBB6_phys_0_eng_0_engtype_3D": 25.0,
    "pid_200_luid_0x00000000_0x0000FBB6_phys_0_eng_3_engtype_VideoDecode": 40.0,
    "pid_300_luid_0x00000001_0x00000002_phys_0_eng_1_engtype_Copy": 5.0,
}
ad, per = pdh.gpu_engines(fake_arr)
check("GPU motoru: bağdaştırıcı = en meşgul motor", ad[0xFBB6]["util"] == 55.0 and ad[0xFBB6]["types"]["VideoDecode"] == 40)
check("GPU motoru: süreç başına en meşgul motor", per[200] == (40.0, "VideoDecode", 0xFBB6) and
      pdh.luid_of("luid_0x00000001_0x00000002_phys") == (1 << 32) | 2)
smp = perf.SystemSampler()
time.sleep(0.5)
s1 = smp.sample()
check("sistem örnekleyici", 0 <= s1["cpu"]["util"] <= 100 and s1["cpu"]["cores"] and s1["mem"]["total"] > 0
      and isinstance(s1["disks"], list) and isinstance(s1["gpus"], list))
smp.close()
ps = procs.ProcessSampler()
rows = ps.sample()
time.sleep(0.3)
rows = ps.sample()
mine = next((r for r in rows if r["pid"] == os.getpid()), None)
check("süreç örnekleyici", len(rows) > 20 and mine is not None and mine["self"] and mine["exe"]
      and all(r["group"] in ("apps", "background", "windows") for r in rows) and all(r["pid"] != 0 for r in rows))

print("programlar ve sürücüler (salt okunur; hiçbir şey kaldırılmaz / değiştirilmez)")
from mergen.collect import drivers, paths, programs, services, startup  # noqa: E402
from mergen.collect import wmi as W  # noqa: E402
progs = programs.collect()
check("programlar okunur", len(progs) > 5 and all(p["name"] and p["id"] for p in progs))
check("Store adları çözülür", not any(p["name"].startswith(("ms-resource", "@{")) for p in progs))
check("başlangıç değeri: etkin = 02…", startup.approved_value(True) == bytes([2]) + bytes(11))
dv = startup.approved_value(False)
check("başlangıç değeri: devre dışı = 03 + FILETIME", len(dv) == 12 and dv[0] == 3 and dv[4:] != bytes(8))
check("komut satırı -> exe", startup.command_exe('"C:\\A B\\x.exe" --tray') == "C:\\A B\\x.exe"
      and startup.command_exe("C:\\Prog\\y.exe -m") == "C:\\Prog\\y.exe")
sr = os.environ.get("SystemRoot", r"C:\Windows")
check("servis yolu çözülür", services.service_exe(r"\SystemRoot\System32\drivers\x.sys") ==
      os.path.normpath(sr + r"\System32\drivers\x.sys") and
      services.service_exe(r"system32\drivers\y.sys") == os.path.normpath(os.path.join(sr, r"system32\drivers\y.sys")))
with W.com_thread():
    svcs = services.collect()
    drv = drivers.collect()
check("servisler okunur", len(svcs) > 50 and any(s["state"] == "running" for s in svcs))
check("başlangıç okunur", isinstance(startup.collect(svcs), list))
check("sürücüler okunur", len(drv) > 20 and any(d.get("sys") for d in drv))
pth = paths.collect()
check("yollar: PATH + bilinen klasörler", any(p["kind"] == "path" for p in pth) and
      any(p["kind"] == "known" and p["name"] == "kf_profile" for p in pth))
sz_root = os.path.join(TMP, "boyut")
os.makedirs(os.path.join(sz_root, "a", "b"))
for rel, n in (("a\\1.bin", 1000), ("a\\b\\2.bin", 500), ("3.bin", 7)):
    with open(os.path.join(sz_root, rel), "wb") as f:
        f.write(b"x" * n)
sz = {r["name"]: r for r in paths.folder_sizes(sz_root)}
check("klasör boyutu", sz["a"]["size"] == 1500 and sz["a"]["files"] == 2 and sz[None]["size"] == 7)

print("sensörler (yardımcı YÜKSELTİLMEDEN; görev oluşturulmaz, UAC açılmaz, fan/güç yazılmaz)")
import xml.etree.ElementTree as ET  # noqa: E402
from mergen import helper_client  # noqa: E402
x = ET.fromstring(helper_client.task_xml(r"C:\Program Files\mergen-helper\mergen-helper.exe",
                                          "S-1-5-21-1-2-3-1001").split("?>", 1)[1])
ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
check("görev XML: en yüksek ayrıcalık, tetikleyicisiz, kullanıcıya yalnızca okuma+çalıştırma",
      x.find(".//t:RunLevel", ns).text == "HighestAvailable" and len(x.find("t:Triggers", ns)) == 0
      and "(A;;GRGX;;;S-1-5-21-1-2-3-1001)" in x.find(".//t:SecurityDescriptor", ns).text
      and x.find(".//t:Command", ns).text.startswith(helper_client.SECURE_DIR[:3]))
check("görev exe'si yalnızca yöneticinin yazabildiği yerde", helper_client.SECURE_EXE.lower().startswith(
    os.environ.get("ProgramFiles", r"C:\Program Files").lower()))

print("cihaz (yalnızca okuma; SetDCHU_Data / WriteAppSettings / güç planı yazımı YOK)")
from mergen import vendors  # noqa: E402
from mergen.collect import power  # noqa: E402
from mergen.vendors import clevo  # noqa: E402
fake = bytearray(256)
fake[2:4] = (490).to_bytes(2, "big")
fake[4:6] = (683).to_bytes(2, "big")
fake[16], fake[18], fake[19], fake[21] = 186, 58, 145, 49
fans = clevo.parse_live(bytes(fake), 2)
check("Clevo canlı arabellek çözülür", fans == [{"name": "cpu", "rpm": 4401, "duty": 73, "temp": 58},
                                              {"name": "gpu", "rpm": 3157, "duty": 57, "temp": 49}])
check("Clevo: duran fan 0 dev/dk", clevo.rpm(0) == 0)
check("Clevo fan / klavye yazma kapalı", _raises(clevo.vendor.set_fan) and _raises(clevo.vendor.set_keyboard))
# set_power_mode gerçek yazma yapar: testte yalnızca geçersiz değerin yazmadan ÖNCE reddedildiği denetlenir
check("Clevo güç modu: geçersiz değer yazılmadan reddedilir", _raises(lambda: clevo.vendor.set_power_mode(99), ValueError)
      and _raises(lambda: clevo.vendor.set_power_mode(4), ValueError))
check("Clevo modülü yazma işlevi bağlamaz", "SetDCHU_Data" not in open(clevo.__file__, encoding="utf-8").read()
      .split("def _lib", 1)[1].split("def _buffer", 1)[0] and "WriteAppSettings(" not in
      open(clevo.__file__, encoding="utf-8").read())
_orig_dir = clevo.service_dir
clevo.service_dir = lambda: None
check("Clevo yoksa üretici modülü algılanmaz", vendors.detect_any() is None)
clevo.service_dir = _orig_dir
g = "ded574b5-45a0-4f42-8737-46345c09c238"
check("GUID gidiş-dönüş", str(power.GUID.of(g)) == g)
pw = power.collect()
check("güç planları okunur", pw["plans"] and pw["active"] in [p_[0] for p_ in pw["plans"]])
check("güç kaynağı okunur", set(pw["status"]) == {"ac", "battery", "saver"})
if vendors.detect_any() is not None:
    r = vendors.detect_any().read()
    check("Clevo okunur (bu makine)", r["fans"] and r["fans"][0]["rpm"] >= 0 and r["power_mode"] is not None)

print("arayüz")
from PyQt6.QtWidgets import QApplication  # noqa: E402
app = QApplication(sys.argv)
from mergen import tamga_sync  # noqa: E402
from mergen.theme import theme  # noqa: E402
from mergen.window import MainWindow  # noqa: E402
theme.apply()
tamga_sync.install(prefs, theme)
w = MainWindow()
w.show()
app.processEvents()
check("son sekme hatırlanır", w.current == "programs")
keys = [c.key for c in w.page_classes]
check("sekmeler", keys[:5] == ["system", "programs", "sensors", "performance", "processes"] and "tweaks" in keys)
check("Cihaz sekmesi (Windows güç ayarları her bilgisayarda)", "device" in keys)
for k in keys:
    w.show_page(k)
    app.processEvents()
    check("sekme açılır: " + k, w.stack.currentWidget() is w.pages[k] and w.nav[k].isChecked())
dp = w.pages["device"]
for _ in range(100):
    app.processEvents()
    if not dp._busy and dp._power is not None:
        break
    time.sleep(0.05)
check("cihaz sekmesi: güç planı seçili", dp.cb_plan.currentIndex() >= 0)
check("cihaz sekmesi gizliyken okumaz", not dp.timer.isActive())
w.show_page("system")
w.titlebar.search.setText("intel")
check("arama sekmeye gider", w.pages["system"].filter_text == "intel")
w.show_page("programs")
check("arama sekme başına", w.titlebar.search.text() == "" and w.pages["programs"].filter_text == "")
w.show_page("system")
check("arama geri gelir", w.titlebar.search.text() == "intel")

sp = w.pages["system"]
deadline = time.time() + 60
while sp._running and time.time() < deadline:      # arka plan okuması bitsin (arayüz donmadan)
    app.processEvents()
    time.sleep(0.02)
check("sistem sekmesi doldu", not sp._running and sp.cards["cpu"].data is not None)
check("önbellek yazıldı", os.path.exists(os.path.join(os.environ["MERGEN_DATA_DIR"], "cache", "system.json")))
w.titlebar.search.setText("")
app.processEvents()
check("kişisel bilgiler varsayılan gizli", sp.show_personal is False and any(
    v.hidden() for v in sp.cards["general"].values))
w.titlebar.search.setText("Yonga seti")
app.processEvents()
check("arama: yalnızca eşleşen kart", sp.cards["board"].wanted and not sp.cards["memory"].wanted)
w.titlebar.search.setText("bulunamayacak-metin-xyz")
app.processEvents()
check("arama: eşleşme yoksa not", not sp.no_match.isHidden())
w.titlebar.search.setText("")
from PyQt6.QtGui import QGuiApplication  # noqa: E402
serial = next(r["v"] for r in sp.cards["general"].data["rows"] if r["k"] == "lbl_serial")
sp.cards["general"].copy()
clip = QGuiApplication.clipboard().text()
check("kopyala: gizliyken seri panoya gitmez", "Bilgisayar adı" in clip and (not serial or serial not in clip))
sp.toggle_personal()
check("göz düğmesi hepsini gösterir", not any(v.hidden() for v in sp.cards["general"].values)
      and prefs.get("system_show_personal") is True)
sp.toggle_personal()

# Sensör servisi: sahte ölçümlerle min / maks / ort, uyarı, CSV
from mergen import sensor_service  # noqa: E402
from mergen.pages.sensors import fmt as sfmt  # noqa: E402
svc = sensor_service.service()
svc.alert.disconnect()                       # testte bildirim gösterme
alerts = []
svc.alert.connect(lambda n, v: alerts.append((n, v)))
prefs.set("sensors_alert", True)
prefs.set("sensors_alert_temp", 80)
prefs.set("sensors_alert_secs", 0)
prefs.set("sensors_csv", True)


def fake_msg(tval, tt):
    return {"type": "sensors", "t": tt, "hardware": [
        {"id": "/cpu/0", "name": "Test CPU", "type": "Cpu", "parent": None, "sensors": [
            {"id": "/cpu/0/temperature/0", "name": "Package", "type": "Temperature", "index": 0, "value": tval},
            {"id": "/cpu/0/load/0", "name": "Total", "type": "Load", "index": 0, "value": None}]}]}


for i, v in enumerate((60.0, 70.0, 85.0)):
    svc._on_sensors(fake_msg(v, 1_700_000_000 + i))
mn, mx, avg = svc.stat("/cpu/0/temperature/0")
check("sensör: en düşük / en yüksek / ortalama", (mn, mx, round(avg, 1)) == (60.0, 85.0, 71.7)
      and svc.stat("/cpu/0/load/0") == (None, None, None))
check("sensör: eşik aşılınca uyarı (bir kez)", len(alerts) == 1 and alerts[0][1] == 85.0)
svc._on_sensors(fake_msg(90.0, 1_700_000_010))
check("sensör: aynı sensöre 5 dk içinde ikinci uyarı yok", len(alerts) == 1)
svc._close_csv()
logs = os.listdir(sensor_service.LOG_DIR)
rows_csv = open(os.path.join(sensor_service.LOG_DIR, logs[0]), encoding="utf-8-sig").read().splitlines()
check("sensör: CSV kaydı", len(logs) == 1 and "Test CPU / Package [°C]" in rows_csv[0] and len(rows_csv) == 5)
svc.reset()
check("sensör: sıfırla", svc.stat("/cpu/0/temperature/0") == (None, None, None))
prefs.set("sensors_alert", False)
prefs.set("sensors_csv", False)
check("sensör biçimi", sfmt(51.0, "Temperature") == "51,0 °C" and sfmt(3.1, "Load") == "%3,1"
      and sfmt(1234, "Fan") == "1234 RPM" and sfmt(None, "Power") == "—")

if helper_client.helper_path():
    got = []
    svc.c.sensors.connect(lambda m: got.append(m))
    w.show_page("sensors")
    deadline = time.time() + 20
    while len(got) < 2 and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    sp_ = w.pages["sensors"]
    app.processEvents()
    check("yardımcı: kanal + canlı sensörler (yükseltilmeden)", len(got) >= 2 and svc.c.last_info is not None
          and svc.c.last_info.get("version"))
    check("sensörler sekmesi doldu", len(sp_.items) > 0 and sp_.model.rowCount() > 0)
    check("sınırlı modda açıklama görünür", svc.c.last_info.get("admin") or not sp_.banner.isHidden())
    w.titlebar.search.setText("bulunamayacak-sensor-xyz")
    app.processEvents()
    check("sensör araması", sp_.proxy.rowCount() == 0)
    w.titlebar.search.setText("")
    w.show_page("system")
    app.processEvents()
    check("gizli sekmede abonelik biter", not svc.c._want)
else:
    print("  (yardımcı derlenmemiş: canlı kanal testi atlandı)")

# Programlar sekmesi: her alt sekme arka planda dolar, arama süzer (işlem menüleri çalıştırılmaz)
w.show_page("programs")
pg = w.pages["programs"]
for key in ("programs", "startup", "services", "drivers", "paths"):
    pg.show_tab(key)
    tab = pg.tab(key)
    deadline = time.time() + 30
    while not tab.loaded and time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)
    check(f"alt sekme doldu: {key}", tab.loaded and len(tab.table.rows()) > 0)
    from PyQt6.QtWidgets import QMenu  # noqa: E402
    ok_menu = True
    for r in tab.table.rows()[:40]:          # menü kurulur, hiçbir eylem tetiklenmez
        mm = QMenu()
        try:
            tab.menu(mm, r)
        except Exception as e:
            ok_menu = False
            print("     ", key, r.get("id"), repr(e))
            break
    check(f"sağ tık menüsü kurulur: {key}", ok_menu)
pg.show_tab("programs")
first = pg.tab("programs").table.rows()[0]["name"]
w.titlebar.search.setText(first)
app.processEvents()
pt = pg.tab("programs")
check("programlarda arama", 0 < pt.table.visible_count() < len(pt.table.rows()))
w.titlebar.search.setText("")
pg.show_tab("drivers")
dt = pg.tab("drivers")
dt.cb_problems.setChecked(True)
check("yalnızca sorunlu sürücüler", dt.table.visible_count() == sum(1 for r in dt.table.rows() if r.get("problem")))
dt.cb_problems.setChecked(False)
check("alt sekme hatırlanır", prefs.get("programs_tab") == "drivers")
pg.show_tab("sizes")
st = pg.tab("sizes")
st.set_root(sz_root)
deadline = time.time() + 10
while st.loading and time.time() < deadline:
    app.processEvents()
    time.sleep(0.03)
check("klasör boyutları sekmesi", len(st.table.rows()) == 2)
pg.show_tab("programs")

# Görev yöneticisi: model / süzgeç (sahte satırlar) + canlı veri
from mergen.pages.processes import ProcModel, ProcProxy  # noqa: E402
fake = [
    {"key": "10:1", "pid": 10, "ppid": 4, "name": "uygulama.exe", "exe": r"C:\x\uygulama.exe", "start": 1,
     "cpu": 5.0, "mem": 1 << 20, "disk": 0.0, "gpu": 0.0, "group": "apps"},
    {"key": "11:2", "pid": 11, "ppid": 10, "name": "yardimci.exe", "exe": None, "start": 2,
     "cpu": 1.0, "mem": 1 << 19, "disk": 0.0, "gpu": 0.0, "group": "background"},
    {"key": "12:3", "pid": 12, "ppid": 999, "name": "svchost.exe", "exe": None, "start": 3,
     "cpu": 0.0, "mem": 1 << 18, "disk": 0.0, "gpu": 0.0, "group": "windows"},
]
pm = ProcModel()
pm.grouped, pm.tree = True, True
pm.set_rows(fake)
check("süreç modeli: 3 grup", pm.rowCount() == 3 and pm.data(pm.index(0, 0)).startswith("Uygulamalar"))
apps = pm.index(0, 0)
check("süreç modeli: ağaçta çocuk üst sürecin altında",
      pm.rowCount(apps) == 1 and pm.rowCount(pm.index(0, 0, apps)) == 1)
pm.tree = False
pm.relayout()
check("süreç modeli: ağaç kapalıyken düz", pm.rowCount(pm.index(1, 0)) == 1)
pm.grouped = False
pm.relayout()
check("süreç modeli: grupsuz", pm.rowCount() == 3)
px = ProcProxy()
px.setSourceModel(pm)
px.set_text("svchost")
check("süreç süzgeci", px.rowCount() == 1)
pm.set_rows([dict(r, cpu=50.0) for r in fake])
check("süreç modeli: yerinde güncelleme", pm.row_for(pm.index(0, 0))["cpu"] == 50.0)

from mergen.monitor import monitor  # noqa: E402
w.show_page("processes")
pp = w.pages["processes"]
deadline = time.time() + 20
while pp.model.rowCount() == 0 and time.time() < deadline:
    app.processEvents()
    time.sleep(0.05)
check("görev yöneticisi doldu", pp.model.rowCount() == 3 and len(pp.model.rows) > 20)
w.titlebar.search.setText(os.path.basename(sys.executable))
app.processEvents()
check("görev yöneticisi araması", 0 < pp.proxy.rowCount() <= 3)
w.titlebar.search.setText("")
w.show_page("performance")
pf = w.pages["performance"]
deadline = time.time() + 10
while not pf.tiles and time.time() < deadline:
    app.processEvents()
    time.sleep(0.05)
check("performans kutucukları", "cpu" in pf.tiles and "mem" in pf.tiles)
for k in list(pf.tiles):
    pf.select(k)
    app.processEvents()
check("performans: her kaynak ayrıntısı açılır", pf.detail.key == list(pf.tiles)[-1])
pf.select("cpu")
pf.toggle_cores()
app.processEvents()
check("performans: çekirdek başına grafik", len(pf.detail.graph_widgets) == len(monitor().last["cpu"]["cores"]))
pf.toggle_cores()
pf.set_window(300)
check("performans: geçmiş süresi kaydedilir", prefs.get("perf_window") == 300)
w.show_page("system")

w.titlebar.search.setText("intel")
w.toggle_theme()
check("tema düğmesi açığa geçer", T.current_variant() == "white" and prefs.get("theme") == "white")
w.toggle_theme()
check("tema düğmesi koyuya döner", T.current_variant() == "amoled")
m = w.build_prefs_menu()
check("tercihler menüsü", [a.text() for a in m.actions() if a.text()][:3] == ["Tema", "Vurgu rengi", "Dil"])

# tamga başlatıcısı tercih dosyasına ortak anahtar yazınca anında uygulanır
d = json.load(open(prefs.path, encoding="utf-8"))
d.update({"theme": "cream", "accent": "teal"})
with open(prefs.path, "w", encoding="utf-8") as f:
    json.dump(d, f)
os.utime(prefs.path, (1_000_000_000, 1_000_000_000))   # mtime kesin değişsin (0 olmasın)
tamga_sync._state["check"]()
check("tamga ortak ayarı alınır", T.current_variant() == "cream" and T.accent() == "#1fc7b6")

w.close()
app.processEvents()
monitor().stop()
check("pencere konumu kaydedilir", bool(json.load(open(prefs.path, encoding="utf-8")).get("window_geometry")))

print()
if fails:
    print(f"{len(fails)} HATA")
    sys.exit(1)
print("hepsi tamam")
