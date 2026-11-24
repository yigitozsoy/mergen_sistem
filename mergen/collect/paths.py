"""Dosya yolları: ortam değişkenleri (kullanıcı + sistem), PATH girdileri (var olmayanlar işaretli), bilinen
klasörler (SHGetKnownFolderPath) ve isteğe bağlı klasör boyutu taraması. Salt okunur."""
import ctypes
import os
import uuid
import winreg
from ctypes import wintypes

ENV_KEYS = [
    ("user", winreg.HKEY_CURRENT_USER, "Environment"),
    ("system", winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
]
# (anahtar, KNOWNFOLDERID)
KNOWN = [
    ("kf_profile", "5E6C858F-0E22-4760-9AFE-EA3317B67173"), ("kf_desktop", "B4BFCC3A-DB2C-424C-B029-7FE99A87C641"),
    ("kf_documents", "FDD39AD0-238F-46AF-ADB4-6C85480369C7"), ("kf_downloads", "374DE290-123F-4565-9164-39C4925E467B"),
    ("kf_pictures", "33E28130-4E1E-4676-835A-98395C3BC3BB"), ("kf_music", "4BD8D571-6D19-48D3-BE97-422220080E43"),
    ("kf_videos", "18989B1D-99B5-455B-841C-AB7C74E4DDFC"), ("kf_appdata", "3EB685DB-65F9-4CF6-A03A-E3EF65729F3D"),
    ("kf_localappdata", "F1B32785-6FBA-4FCF-9D55-7B8E7F157091"),
    ("kf_programdata", "62AB5D82-FDC1-4DC3-A9DD-070D1D495D97"),
    ("kf_programfiles", "905E63B6-C1BF-494E-B29C-65B732D3D21A"),
    ("kf_programfilesx86", "7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E"),
    ("kf_startmenu", "625B53C3-AB48-4EC1-BA1F-A1EF4146FC19"), ("kf_startup", "B97D20BB-F46A-4C97-BA10-5E3608430854"),
    ("kf_sendto", "8983036C-27C0-404B-8F08-102D10DCFD74"), ("kf_fonts", "FD228CB7-AE11-4AE3-864C-16F3910AB8FE"),
    ("kf_windows", "F38BF404-1D43-42F2-9305-67DE0B28FC23"), ("kf_system", "1AC14E77-02E7-4E5D-B744-2EB1AE5198B7"),
    ("kf_temp", None), ("kf_onedrive", "A52BBA46-E9E1-435F-B3D9-28DAA648C0F6"),
    ("kf_savedgames", "4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4"),
]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, s):
        u = uuid.UUID(s)
        g = cls()
        g.Data1, g.Data2, g.Data3 = u.fields[0], u.fields[1], u.fields[2]
        g.Data4[:] = u.bytes[8:]
        return g


def known_folder(guid):
    p = ctypes.c_wchar_p()
    try:
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(GUID.of(guid)), 0, None, ctypes.byref(p))
    except Exception:
        return None
    try:
        return p.value if hr == 0 else None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(p)


def env_vars():
    rows = []
    for scope, hive, key in ENV_KEYS:
        try:
            k = winreg.OpenKey(hive, key)
        except OSError:
            continue
        with k:
            i = 0
            while True:
                try:
                    name, val, typ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                raw = str(val)
                rows.append({"id": f"env:{scope}:{name}", "kind": "env", "name": name, "scope": scope, "raw": raw,
                             "value": winreg.ExpandEnvironmentStrings(raw) if typ == winreg.REG_EXPAND_SZ else raw})
    return rows


def path_entries(env=None):
    env = env if env is not None else env_vars()
    rows = []
    seen = set()
    # Windows PATH'i sistem + kullanıcı sırasıyla birleştirir
    for scope in ("system", "user"):
        for e in env:
            if e["scope"] != scope or e["name"].lower() != "path":
                continue
            for i, part in enumerate(e["raw"].split(";")):
                if not part.strip():
                    continue
                exp = os.path.normpath(winreg.ExpandEnvironmentStrings(part.strip()))
                dup = os.path.normcase(exp) in seen
                seen.add(os.path.normcase(exp))
                rows.append({"id": f"path:{scope}:{i}", "kind": "path", "name": part.strip(), "value": exp,
                             "scope": scope, "exists": os.path.isdir(exp), "duplicate": dup, "order": len(rows) + 1})
    return rows


def known_folders():
    rows = []
    for key, guid in KNOWN:
        p = os.environ.get("TEMP") if guid is None else known_folder(guid)
        if p:
            rows.append({"id": "kf:" + key, "kind": "known", "name": key, "value": p, "scope": None,
                         "exists": os.path.isdir(p)})
    return rows


def collect():
    env = env_vars()
    return env + path_entries(env) + known_folders()


def folder_sizes(root, cancelled=lambda: False, progress=None):
    """root'un doğrudan alt klasörleri (ve köke ait dosyalar) için toplam boyut. Bağlantı noktalarına (junction,
    sembolik bağ) girilmez; OneDrive "yalnızca çevrimiçi" dosyalar indirilmez (yalnızca stat, boyut = mantıksal)."""
    out = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return out
    loose = 0
    for e in entries:
        if cancelled():
            break
        try:
            if e.is_symlink() or (e.is_dir(follow_symlinks=False) and _is_reparse(e)):
                continue
            if e.is_file(follow_symlinks=False):
                loose += e.stat(follow_symlinks=False).st_size
                continue
            if not e.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if progress:
            progress(e.path)
        size, files = _tree_size(e.path, cancelled)
        out.append({"id": "size:" + e.path, "path": e.path, "name": e.name, "size": size, "files": files})
    if loose:
        out.append({"id": "size:" + root + ":files", "path": root, "name": None, "size": loose, "files": None})
    return out


def _is_reparse(entry):
    try:
        return bool(entry.stat(follow_symlinks=False).st_file_attributes & 0x400)   # FILE_ATTRIBUTE_REPARSE_POINT
    except (OSError, AttributeError):
        return False


def _tree_size(path, cancelled):
    total = files = 0
    stack = [path]
    while stack:
        if cancelled():
            break
        p = stack.pop()
        try:
            it = os.scandir(p)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                    if st.st_file_attributes & 0x400:      # bağlantı noktası: atla
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    else:
                        total += st.st_size
                        files += 1
                except OSError:
                    continue
    return total, files
