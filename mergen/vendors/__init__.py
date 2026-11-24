"""Üretici cihaz modülleri (mergen/vendors/<üretici>.py). Ortak arayüz vendors/base.py'de."""


def modules():
    """Algılama sırasıyla modül örnekleri (içe aktarma tembel: açılışta yük olmasın)."""
    from . import clevo
    return [clevo.vendor]


def detect_any():
    """Bu bilgisayarı destekleyen ilk modül ya da None. Algılama hiçbir şeye yazmaz, DLL yüklemez."""
    for mod in modules():
        try:
            if mod.detect():
                return mod
        except Exception:
            continue
    return None
