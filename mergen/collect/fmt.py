"""Toplanan değerlerin dilden bağımsız biçimi ve ekranda / raporda metne çevrilmesi.

Toplayıcılar JSON'a yazılabilir değerler üretir (önbellek + JSON rapor):
  str / int / float / None           olduğu gibi (None -> "—")
  {"t": "bytes", "v": n}             1.5 GB
  {"t": "mhz", "v": n}               2.70 GHz
  {"t": "bool", "v": b}              Evet / Hayır
  {"t": "on", "v": b}                Açık / Kapalı
  {"t": "date", "v": "2024-01-31"}   31.01.2024
  {"t": "dt", "v": "2024-01-31T12:00:00"}
  {"t": "key", "v": "val_x", "a": {...}}   yerelleştirilmiş sabit metin
  {"t": "list", "v": [değer, ...]}   virgülle birleşir
Satır:  {"k": "lbl_x", "v": değer, "s": True}   (s = kişisel / kimlik bilgisi: True varsayılan gizli,
        "r" yalnızca raporda çıkarılır;
        "l": "C:" verilirse etiket çevrilmeden o metin)
Bölüm:  {"id": "cpu", "rows": [satır], "groups": [{"title": değer, "rows": [satır], "badge": değer}]}"""
import datetime


def B(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    return {"t": "bytes", "v": n} if n > 0 else None


def MHz(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return None
    return {"t": "mhz", "v": n} if n > 0 else None


def YES(b):
    return None if b is None else {"t": "bool", "v": bool(b)}


def ON(b):
    return None if b is None else {"t": "on", "v": bool(b)}


def DATE(d):
    if d is None:
        return None
    if isinstance(d, datetime.datetime):
        d = d.date()
    return {"t": "date", "v": d.isoformat()}


def DT(d):
    return None if d is None else {"t": "dt", "v": d.replace(microsecond=0).isoformat()}


def K(key, **args):
    return {"t": "key", "v": key, "a": args} if args else {"t": "key", "v": key}


def L(items):
    items = [i for i in items if i not in (None, "")]
    return {"t": "list", "v": items} if items else None


def N(x, unit="", digits=0):
    """Sayı + birim; ondalık ayırıcı ve binlik gruplama dile göre (16,42 V / 47.160 mWh)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return {"t": "num", "v": x, "u": unit, "d": digits}


def row(k, v, sensitive=False):
    """sensitive: True = ekranda gizli + raporda çıkarılır; "r" = ekranda görünür, yalnızca raporda çıkarılır
    (bilgisayar / kullanıcı adı gibi)."""
    r = {"k": k, "v": v}
    if sensitive:
        r["s"] = sensitive
    return r


def label(r, t=None):
    """Satırın etiketi: "l" (çevrilmeyen metin) varsa o, yoksa t("lbl_…")."""
    if r.get("l"):
        return r["l"]
    if t is None:
        from ..i18n import t
    return t(r["k"])


def human_bytes(n, tr=True):
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    f = float(n)
    i = 0
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    if i == 0 or f >= 100:
        s = f"{f:.0f}"
    elif f >= 10:
        s = f"{f:.1f}"
    else:
        s = f"{f:.2f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if tr:
        s = s.replace(".", ",")
    return f"{s} {units[i]}"


def text(v, t=None):
    """Değeri gösterilecek metne çevirir. t: i18n.t (verilmezse mergen.i18n.t)."""
    if t is None:
        from ..i18n import t
    from ..i18n import is_tr
    tr = is_tr()
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return t("yes") if v else t("no")
    if isinstance(v, (int, float, str)):
        return str(v)
    if isinstance(v, dict):
        kind, x = v.get("t"), v.get("v")
        if kind == "bytes":
            return human_bytes(x, tr)
        if kind == "mhz":
            s = f"{x / 1000:.2f} GHz" if x >= 1000 else f"{x:.0f} MHz"
            return s.replace(".", ",") if tr else s
        if kind == "num":
            d = int(v.get("d") or 0)
            s = f"{x:,.{d}f}"
            if tr:
                s = s.translate(str.maketrans(",.", ".,"))
            u = v.get("u") or ""
            if u == "%":
                return ("%" + s) if tr else (s + "%")
            return f"{s} {u}".strip()
        if kind == "bool":
            return t("yes") if x else t("no")
        if kind == "on":
            return t("on") if x else t("off")
        if kind == "date":
            try:
                d = datetime.date.fromisoformat(x)
                return d.strftime("%d.%m.%Y") if tr else d.isoformat()
            except ValueError:
                return str(x)
        if kind == "dt":
            try:
                d = datetime.datetime.fromisoformat(x)
                return d.strftime("%d.%m.%Y %H:%M") if tr else d.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                return str(x)
        if kind == "key":
            args = {k: text(a, t) if isinstance(a, dict) else a for k, a in (v.get("a") or {}).items()}
            return t(x, **args)
        if kind == "list":
            return ", ".join(text(i, t) for i in x)
    if isinstance(v, list):
        return ", ".join(text(i, t) for i in v)
    return str(v)
