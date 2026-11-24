"""Tüm süreçleri tek çağrıda okur: NtQuerySystemInformation(SystemProcessInformation) — Görev Yöneticisi'nin kaynağı.

psutil süreç başına bu tabloyu yeniden okuduğu için 300 süreçte saniyeler sürüyor; bu yol ~5-15 ms.
Yönetici istemez; korumalı süreçler için de sayılar gelir (yalnızca exe yolu / komut satırı gelmeyebilir)."""
import ctypes
from ctypes import wintypes

ntdll = ctypes.windll.ntdll
ntdll.NtQuerySystemInformation.restype = ctypes.c_long   # NTSTATUS
STATUS_INFO_LENGTH_MISMATCH = ctypes.c_long(0xC0000004).value
EPOCH_DIFF = 11644473600          # 1601 -> 1970 (saniye)


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]


class SPI(ctypes.Structure):      # SYSTEM_PROCESS_INFORMATION (x64'te 256 bayt)
    _fields_ = [
        ("NextEntryOffset", wintypes.ULONG), ("NumberOfThreads", wintypes.ULONG),
        ("WorkingSetPrivateSize", ctypes.c_longlong), ("HardFaultCount", wintypes.ULONG),
        ("NumberOfThreadsHighWatermark", wintypes.ULONG), ("CycleTime", ctypes.c_ulonglong),
        ("CreateTime", ctypes.c_longlong), ("UserTime", ctypes.c_longlong), ("KernelTime", ctypes.c_longlong),
        ("ImageName", UNICODE_STRING), ("BasePriority", ctypes.c_long),
        ("UniqueProcessId", ctypes.c_void_p), ("InheritedFromUniqueProcessId", ctypes.c_void_p),
        ("HandleCount", wintypes.ULONG), ("SessionId", wintypes.ULONG), ("UniqueProcessKey", ctypes.c_size_t),
        ("PeakVirtualSize", ctypes.c_size_t), ("VirtualSize", ctypes.c_size_t), ("PageFaultCount", wintypes.ULONG),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivatePageCount", ctypes.c_size_t),
        ("ReadOperationCount", ctypes.c_longlong), ("WriteOperationCount", ctypes.c_longlong),
        ("OtherOperationCount", ctypes.c_longlong), ("ReadTransferCount", ctypes.c_longlong),
        ("WriteTransferCount", ctypes.c_longlong), ("OtherTransferCount", ctypes.c_longlong),
    ]


_buf = {"b": ctypes.create_string_buffer(1 << 20)}


def snapshot():
    """[{pid, ppid, name, threads, handles, session, create (unix sn), cpu_s, ws_private, ws, private,
    io_read, io_write, io_other, base_priority}]"""
    buf = _buf["b"]
    ret = wintypes.ULONG(0)
    for _ in range(8):
        st = ntdll.NtQuerySystemInformation(5, buf, len(buf), ctypes.byref(ret))
        if st == STATUS_INFO_LENGTH_MISMATCH:
            buf = ctypes.create_string_buffer(max(ret.value + (64 << 10), len(buf) * 2))
            _buf["b"] = buf
            continue
        if st < 0:
            raise OSError(f"NtQuerySystemInformation: 0x{st & 0xFFFFFFFF:08X}")
        break
    base = ctypes.addressof(buf)
    out = []
    off = 0
    while True:
        e = SPI.from_address(base + off)
        pid = e.UniqueProcessId or 0
        if pid == 0:
            name = "System Idle Process"
        elif e.ImageName.Buffer and e.ImageName.Length:
            name = ctypes.wstring_at(e.ImageName.Buffer, e.ImageName.Length // 2)
        else:
            name = "System" if pid == 4 else f"PID {pid}"
        out.append({
            "pid": pid, "ppid": e.InheritedFromUniqueProcessId or 0, "name": name,
            "threads": e.NumberOfThreads, "handles": e.HandleCount, "session": e.SessionId,
            "create": (e.CreateTime / 1e7 - EPOCH_DIFF) if e.CreateTime > 0 else 0.0,
            "cpu_s": (e.UserTime + e.KernelTime) / 1e7,
            "ws_private": e.WorkingSetPrivateSize, "ws": e.WorkingSetSize, "private": e.PrivatePageCount,
            "io_read": e.ReadTransferCount, "io_write": e.WriteTransferCount, "io_other": e.OtherTransferCount,
            "base_priority": e.BasePriority,
        })
        if not e.NextEntryOffset:
            break
        off += e.NextEntryOffset
    return out
