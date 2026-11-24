"""Ortak canlı örnekleyici: tek arka plan iş parçacığı saniyede bir sistem ölçümlerini (Performans) ve
istenirse süreç listesini (Görev yöneticisi) toplar, sinyallerle arayüze yollar.

Abonelik: monitor.want("perf", True) / monitor.want("procs", True). Kimse istemiyorsa iş parçacığı bekler
(gizli sekmede sorgu yok). Performans geçmişi burada tutulur: sekme gizliyken de birikir (Görev Yöneticisi gibi),
yalnızca çizim yapılmaz."""
import collections
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from .config import log_error

HISTORY = 600          # en çok 10 dk (saniyede bir)


class Monitor(QObject):
    sample = pyqtSignal(dict)          # sistem ölçümleri (perf.SystemSampler.sample)
    procs = pyqtSignal(list)           # süreç satırları (procs.ProcessSampler.sample)

    def __init__(self, interval=1.0):
        super().__init__()
        self.interval = interval
        self._wants = set()
        self._cv = threading.Condition()
        self._stop = False
        self._thread = None
        self.history = collections.deque(maxlen=HISTORY)
        self.last = None

    def want(self, what, on):
        with self._cv:
            if on:
                self._wants.add(what)
            else:
                self._wants.discard(what)
            self._cv.notify_all()
        if on and self._thread is None:
            self._thread = threading.Thread(target=self._run, name="mergen-monitor", daemon=True)
            self._thread.start()

    def stop(self):
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def _run(self):
        from .collect import perf, procs, wmi
        with wmi.com_thread():
            sysmp = prc = None
            try:
                while True:
                    with self._cv:
                        while not self._wants and not self._stop:
                            self._cv.wait()
                        if self._stop:
                            return
                        wants = set(self._wants)
                    t0 = time.time()
                    try:
                        if sysmp is None:
                            sysmp = perf.SystemSampler()
                        s = sysmp.sample()       # süreçlerin GPU sütunu da bu turdaki PDH verisinden gelir
                        self.last = s
                        self.history.append(s)
                        self.sample.emit(s)
                        if "procs" in wants:
                            if prc is None:
                                prc = procs.ProcessSampler()
                            self.procs.emit(prc.sample(sysmp.gpu_per_pid))
                    except Exception as e:
                        log_error(f"monitor: {e!r}")
                    with self._cv:
                        self._cv.wait(max(0.05, self.interval - (time.time() - t0)))
                        if self._stop:
                            return
            finally:
                if sysmp is not None:
                    sysmp.close()


_monitor = None


def monitor():
    global _monitor
    if _monitor is None:
        _monitor = Monitor()
    return _monitor
