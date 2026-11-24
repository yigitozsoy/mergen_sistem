"""Ekran kartları: DXGI (EnumAdapters1), D3D12 özellik desteği, WDDM sürümü (D3DKMT) ve NVIDIA için NVML.

Hepsi ctypes ile; COM arayüzleri sanal tablo (vtable) sırasıyla çağrılır. Herhangi biri başarısızsa o alan None
kalır, asla fırlatmaz. Not: D3D12 aygıtı oluşturmak harici GPU'yu (Optimus) kısa süre uyandırabilir; bu yüzden
sonuç önbelleğe alınır ve yalnızca Sistem sekmesi tazelenirken çağrılır."""
import ctypes
from ctypes import wintypes

from ..config import log_error


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, s):
        import uuid
        u = uuid.UUID(s)
        g = cls()
        g.Data1, g.Data2, g.Data3 = u.fields[0], u.fields[1], u.fields[2]
        for i, b in enumerate(u.bytes[8:]):
            g.Data4[i] = b
        return g


IID_IDXGIFactory1 = GUID.parse("770aae78-f26f-4dba-a829-253c83d1b387")
IID_ID3D12Device = GUID.parse("189819f1-1db6-4b57-be54-1821339b85f7")


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [("Description", wintypes.WCHAR * 128), ("VendorId", wintypes.UINT), ("DeviceId", wintypes.UINT),
                ("SubSysId", wintypes.UINT), ("Revision", wintypes.UINT),
                ("DedicatedVideoMemory", ctypes.c_size_t), ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t), ("AdapterLuid", LUID), ("Flags", wintypes.UINT)]


def _method(obj, index, restype, *argtypes):
    """COM nesnesinin vtable'ındaki index'inci yöntemi çağrılabilir yapar (ilk argüman this)."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    fn = proto(vtbl[index])
    return lambda *a: fn(obj, *a)


def _release(obj):
    if obj:
        try:
            _method(obj, 2, wintypes.ULONG)()
        except Exception:
            pass


VENDORS = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x1022: "AMD", 0x8086: "Intel", 0x1414: "Microsoft",
           0x5143: "Qualcomm", 0x13B5: "ARM", 0x1AB8: "Parallels", 0x15AD: "VMware", 0x80EE: "VirtualBox"}

FEATURE_LEVELS = [(0xC200, "12_2"), (0xC100, "12_1"), (0xC000, "12_0"), (0xB100, "11_1"), (0xB000, "11_0")]


def adapters(features=True):
    """[{name, vendor_id, device_id, vendor, dedicated, shared, luid, software}] — DXGI sırası (ana GPU ilk)."""
    out = []
    try:
        dxgi = ctypes.windll.dxgi
    except OSError:
        return out
    factory = ctypes.c_void_p()
    if dxgi.CreateDXGIFactory1(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(factory)) != 0:
        return out
    try:
        enum1 = _method(factory, 12, ctypes.HRESULT, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))
        i = 0
        while i < 16:
            ad = ctypes.c_void_p()
            try:
                enum1(i, ctypes.byref(ad))
            except OSError:          # DXGI_ERROR_NOT_FOUND: liste bitti
                break
            try:
                desc = DXGI_ADAPTER_DESC1()
                _method(ad, 10, ctypes.HRESULT, ctypes.POINTER(DXGI_ADAPTER_DESC1))(ctypes.byref(desc))
                info = {
                    "name": desc.Description, "vendor_id": desc.VendorId, "device_id": desc.DeviceId,
                    "vendor": VENDORS.get(desc.VendorId), "dedicated": desc.DedicatedVideoMemory,
                    "dedicated_sys": desc.DedicatedSystemMemory, "shared": desc.SharedSystemMemory,
                    "luid": (desc.AdapterLuid.HighPart << 32) | desc.AdapterLuid.LowPart,
                    "software": bool(desc.Flags & 2) or desc.VendorId == 0x1414,
                }
                if features and not info["software"]:   # features=False: GPU uyandırmadan yalnızca ad/bellek
                    info.update(_d3d12(ad))
                    info["wddm"] = _wddm(desc.AdapterLuid)
                out.append(info)
            finally:
                _release(ad)
            i += 1
    except Exception as e:
        log_error(f"DXGI: {e!r}")
    finally:
        _release(factory)
    return out


# ---------------------------------------------------------------------- D3D12
class FEATURE_LEVELS_DATA(ctypes.Structure):
    _fields_ = [("NumFeatureLevels", wintypes.UINT), ("pFeatureLevelsRequested", ctypes.POINTER(ctypes.c_int)),
                ("MaxSupportedFeatureLevel", ctypes.c_int)]


def _d3d12(adapter):
    res = {"d3d12": False}
    try:
        d3d12 = ctypes.windll.d3d12
    except OSError:
        return res
    dev = ctypes.c_void_p()
    try:
        hr = d3d12.D3D12CreateDevice(adapter, 0xB000, ctypes.byref(IID_ID3D12Device), ctypes.byref(dev))
    except Exception:
        return res
    if hr != 0 or not dev:
        return res
    res["d3d12"] = True
    try:
        check = _method(dev, 13, ctypes.HRESULT, ctypes.c_int, ctypes.c_void_p, wintypes.UINT)

        def feature(code, struct):
            try:
                check(code, ctypes.byref(struct), ctypes.sizeof(struct))
                return True
            except OSError:
                return False

        levels = (ctypes.c_int * len(FEATURE_LEVELS))(*[c for c, _ in FEATURE_LEVELS])
        fl = FEATURE_LEVELS_DATA(len(FEATURE_LEVELS), levels, 0)
        if feature(2, fl):
            res["feature_level"] = dict(FEATURE_LEVELS).get(fl.MaxSupportedFeatureLevel)

        for sm in range(0x69, 0x5F, -1):       # en yüksek gölgelendirici modeli: 6.9'dan aşağı dene
            v = ctypes.c_int(sm)
            if feature(7, v):
                res["shader_model"] = f"{v.value >> 4}.{v.value & 0xF}"
                break

        o5 = (ctypes.c_int * 3)()               # OPTIONS5: ..., RenderPassesTier, RaytracingTier
        if feature(27, o5):
            rt = o5[2]                          # 0 yok, 10 = 1.0, 11 = 1.1, 12 = 1.2 …
            res["raytracing"] = f"1.{rt - 10}" if rt >= 10 else None
        o6 = (ctypes.c_int * 5)()               # OPTIONS6: ..., VariableShadingRateTier, ...
        if feature(30, o6):
            res["vrs_tier"] = o6[2]
        o7 = (ctypes.c_int * 2)()               # OPTIONS7: MeshShaderTier, SamplerFeedbackTier
        if feature(32, o7):
            res["mesh_shader"] = o7[0] >= 10
            res["sampler_feedback"] = o7[1] >= 90
        res["dx12_ultimate"] = bool((res.get("raytracing") or "0") >= "1.1" and res.get("vrs_tier", 0) >= 2
                                    and res.get("mesh_shader") and res.get("sampler_feedback"))
    except Exception as e:
        log_error(f"D3D12: {e!r}")
    finally:
        _release(dev)
    return res


# ---------------------------------------------------------------------- WDDM (D3DKMT)
class D3DKMT_OPENADAPTERFROMLUID(ctypes.Structure):
    _fields_ = [("AdapterLuid", LUID), ("hAdapter", wintypes.UINT)]


class D3DKMT_QUERYADAPTERINFO(ctypes.Structure):
    _fields_ = [("hAdapter", wintypes.UINT), ("Type", ctypes.c_int), ("pPrivateDriverData", ctypes.c_void_p),
                ("PrivateDriverDataSize", wintypes.UINT)]


def _wddm(luid):
    try:
        gdi = ctypes.windll.gdi32
        op = D3DKMT_OPENADAPTERFROMLUID(luid, 0)
        if gdi.D3DKMTOpenAdapterFromLuid(ctypes.byref(op)) != 0:
            return None
        try:
            ver = ctypes.c_int(0)
            q = D3DKMT_QUERYADAPTERINFO(op.hAdapter, 13, ctypes.cast(ctypes.byref(ver), ctypes.c_void_p),
                                        ctypes.sizeof(ver))
            if gdi.D3DKMTQueryAdapterInfo(ctypes.byref(q)) != 0 or not ver.value:
                return None
            v = ver.value                       # 1000 = 1.0, 1105 = 1.1, 2100 = 2.1, 3200 = 3.2
            major, minor = divmod(v, 1000)
            return f"{major}.{minor // 100}"
        finally:
            h = wintypes.UINT(op.hAdapter)
            gdi.D3DKMTCloseAdapter(ctypes.byref(h))
    except Exception:
        return None


# ---------------------------------------------------------------------- NVML
def nvidia():
    """NVIDIA kartları için NVML ayrıntıları: [{name, pcie, pcie_max, power_limit, vbios, memory, driver}]."""
    try:
        import pynvml
    except ImportError:
        return []
    try:
        pynvml.nvmlInit()
    except Exception:
        return []
    out = []
    try:
        try:
            drv = pynvml.nvmlSystemGetDriverVersion()
        except Exception:
            drv = None

        def get(fn, *a):
            try:
                return fn(*a)
            except Exception:
                return None

        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            gen, width = get(pynvml.nvmlDeviceGetCurrPcieLinkGeneration, h), get(pynvml.nvmlDeviceGetCurrPcieLinkWidth, h)
            mgen, mwidth = get(pynvml.nvmlDeviceGetMaxPcieLinkGeneration, h), get(pynvml.nvmlDeviceGetMaxPcieLinkWidth, h)
            mem = get(pynvml.nvmlDeviceGetMemoryInfo, h)
            pl = get(pynvml.nvmlDeviceGetPowerManagementLimit, h)
            pci = get(pynvml.nvmlDeviceGetPciInfo, h)
            out.append({
                "name": get(pynvml.nvmlDeviceGetName, h),
                "pcie": f"PCIe {gen}.0 x{width}" if gen and width else None,
                "pcie_max": f"PCIe {mgen}.0 x{mwidth}" if mgen and mwidth else None,
                "power_limit": round(pl / 1000) if pl else None,
                "vbios": get(pynvml.nvmlDeviceGetVbiosVersion, h),
                "memory": mem.total if mem else None,
                "device_id": (pci.pciDeviceId >> 16) if pci else None,
                "driver": drv,
            })
    except Exception as e:
        log_error(f"NVML: {e!r}")
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
    return out
