"""Giriş: tek örnek (ikinci açılış var olan pencereyi öne getirir), hata günlüğü, tema."""
import ctypes
import os
import sys
import traceback

from PyQt6.QtCore import Qt
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from .config import log_error

SERVER_NAME = "mergen-" + (os.environ.get("USERNAME") or "user")
AUMID = "tamga.mergen"


def _excepthook(etype, value, tb):
    log_error("".join(traceback.format_exception(etype, value, tb)))
    sys.__excepthook__(etype, value, tb)


def selfcheck():
    """Paket denetimi (build.ps1): tüm modüller içe aktarılır, varlıklar, dil dosyaları ve yardımcı bulunur.
    Pencere açmaz, sisteme yazmaz. 0 = tamam; hata error.log'a."""
    import importlib
    import json
    import pkgutil
    from . import config
    try:
        import mergen
        for m in pkgutil.walk_packages(mergen.__path__, "mergen."):
            importlib.import_module(m.name)
        for f in ("logo.ico", "logo.png"):
            if not os.path.isfile(config.asset(f)):
                raise FileNotFoundError(f)
        for lang in ("tr", "en"):
            json.load(open(os.path.join(config.BASE_DIR, "locales", lang + ".json"), encoding="utf-8"))
        from .helper_client import helper_path
        if getattr(sys, "frozen", False) and not helper_path():
            raise FileNotFoundError("helper\\mergen-helper.exe")
        return 0
    except Exception:
        log_error("selfcheck:\n" + traceback.format_exc())
        return 1


def _send(msg):
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        sock.write(msg + b"\n")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def _already_running():
    return _send(b"show")


def _bring_to_front(win):
    if win.isMinimized():
        win.showNormal()
    win.show()
    win.raise_()
    win.activateWindow()


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    sys.excepthook = _excepthook
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AUMID)
    except Exception:
        pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if "--selfcheck" in argv:
        return selfcheck()
    app = QApplication(argv)
    app.setApplicationName("mergen")
    if "--quit" in argv:              # kurulum / kaldırma: çalışan mergen'i kapat
        _send(b"quit")
        return 0
    if _already_running():
        return 0

    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    server.listen(SERVER_NAME)

    from . import tamga_sync
    from .config import prefs
    from .theme import theme
    theme.apply()
    tamga_sync.install(prefs, theme)

    from .window import MainWindow
    win = MainWindow()
    if "--tray" not in argv:          # tepsi simgesi sonraki aşamalarda; şimdilik yalnızca gizli başlar
        if prefs.get("window_maximized"):
            win.showMaximized()
        else:
            win.show()

    def on_conn():
        s = server.nextPendingConnection()
        if s is None:
            return

        def on_read():
            data = bytes(s.readAll())
            if b"quit" in data:
                win.close()
                app.quit()
            elif b"show" in data:
                _bring_to_front(win)
        s.readyRead.connect(on_read)
    server.newConnection.connect(on_conn)
    from . import sensor_service
    from .monitor import monitor
    if prefs.get("sensors_alert") or prefs.get("sensors_csv"):     # sekme açılmasa da uyarı / CSV çalışsın
        sensor_service.service()

    def on_quit():
        monitor().stop()
        if sensor_service._service is not None:
            sensor_service._service.stop()
    app.aboutToQuit.connect(on_quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
