"""İnce WMI sarmalayıcı (pywin32). Arayüz iş parçacığında ÇAĞIRMA: sorgular yavaş olabilir.

Her iş parçacığı COM'u kendisi başlatmalı: `with com_thread():` ya da tek tek `query()` (kendisi başlatır).
Hata olursa boş liste döner ve error.log'a not düşer; asla fırlatmaz."""
import datetime
import threading

from ..config import log_error

_local = threading.local()


class com_thread:
    """Bu iş parçacığında COM'u başlatır / kapatır (iç içe kullanılabilir)."""

    def __enter__(self):
        import pythoncom
        depth = getattr(_local, "depth", 0)
        if depth == 0:
            pythoncom.CoInitialize()
            _local.services = {}
        _local.depth = depth + 1
        return self

    def __exit__(self, *exc):
        import pythoncom
        _local.depth -= 1
        if _local.depth == 0:
            _local.services = {}
            pythoncom.CoUninitialize()
        return False


def _service(namespace):
    svc = _local.services.get(namespace)
    if svc is None:
        import win32com.client
        svc = win32com.client.GetObject("winmgmts:{impersonationLevel=impersonate}!\\\\.\\" + namespace)
        _local.services[namespace] = svc
    return svc


def query(wql, namespace="root\\cimv2", quiet=False):
    """WQL sorgusu -> [{özellik: değer}]. Değerler Python türlerine çevrilir (tuple -> list)."""
    with com_thread():
        # COM nesneleri ayrı işlevin yerel değişkenlerinde kalsın: CoUninitialize'dan önce bırakılsınlar
        return _run(wql, namespace, quiet)


def _run(wql, namespace, quiet):
    try:
        rows = []
        for obj in _service(namespace).ExecQuery(wql):
            d = {}
            for p in obj.Properties_:
                v = p.Value
                if isinstance(v, tuple):
                    v = list(v)
                elif v is not None and not isinstance(v, (str, int, float, bool)):
                    v = None            # gömülü COM nesneleri (ör. SupportedDisplayFeatures) taşınmaz
                d[p.Name] = v
            rows.append(d)
        return rows
    except Exception as e:
        if not quiet:
            log_error(f"WMI {namespace}: {wql}: {e!r}")
        return []


def first(wql, namespace="root\\cimv2", quiet=False):
    rows = query(wql, namespace, quiet)
    return rows[0] if rows else {}


def cim_date(s):
    """CIM_DATETIME ("20240131120000.000000+180") -> datetime (yerel), çözülemezse None."""
    if not s:
        return None
    if isinstance(s, datetime.datetime):
        return s.replace(tzinfo=None)
    try:
        return datetime.datetime.strptime(str(s)[:14], "%Y%m%d%H%M%S")
    except ValueError:
        try:
            return datetime.datetime.strptime(str(s)[:8], "%Y%m%d")
        except ValueError:
            return None


def clean(s):
    """WMI metinlerindeki boşlukları ve "To Be Filled By O.E.M." gibi boş değerleri temizler."""
    if s is None:
        return None
    s = str(s).strip().strip("\x00").strip()
    if not s or s.lower() in ("to be filled by o.e.m.", "default string", "system product name",
                              "system manufacturer", "not applicable", "none", "n/a", "0", "unknown"):
        return None
    return " ".join(s.split())
