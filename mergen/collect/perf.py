"""Sistem geneli canlı ölçümler (Performans sekmesi): CPU, bellek, diskler, ağ, GPU'lar.

SystemSampler örnekleyici iş parçacığında oluşturulur ve saniyede bir sample() çağrılır.
Not: NVIDIA sıcaklığı burada OKUNMAZ — NVML'i her saniye sorgulamak Optimus dizüstülerde harici GPU'nun
uykuya geçmesini engeller (Sensörler sekmesi ayrıca ele alacak)."""
import time

import psutil

from . import dxgi, pdh, wmi
from ..config import log_error


class SystemSampler:
    def __init__(self):
        self.c = pdh.Counters()
        add = self.c.add
        add("cpu_total", r"\Processor Information(_Total)\% Processor Utility")
        add("cpu_cores", r"\Processor Information(*)\% Processor Utility")
        add("cpu_perf", r"\Processor Information(_Total)\% Processor Performance")
        add("cpu_freq", r"\Processor Information(_Total)\Processor Frequency")
        add("procs", r"\System\Processes")
        add("threads", r"\System\Threads")
        add("handles", r"\Process(_Total)\Handle Count")
        add("commit", r"\Memory\Committed Bytes")
        add("commit_limit", r"\Memory\Commit Limit")
        add("paged", r"\Memory\Pool Paged Bytes")
        add("nonpaged", r"\Memory\Pool Nonpaged Bytes")
        for k in ("Standby Cache Core Bytes", "Standby Cache Normal Priority Bytes", "Standby Cache Reserve Bytes",
                  "Modified Page List Bytes"):
            add("cache:" + k, "\\Memory\\" + k)
        add("disk_idle", r"\PhysicalDisk(*)\% Idle Time")
        add("disk_read", r"\PhysicalDisk(*)\Disk Read Bytes/sec")
        add("disk_write", r"\PhysicalDisk(*)\Disk Write Bytes/sec")
        add("disk_resp", r"\PhysicalDisk(*)\Avg. Disk sec/Transfer")
        add("gpu_engine", r"\GPU Engine(*)\Utilization Percentage")
        add("gpu_ded", r"\GPU Adapter Memory(*)\Dedicated Usage")
        add("gpu_shared", r"\GPU Adapter Memory(*)\Shared Usage")
        self.c.collect()

        self.ncpu = psutil.cpu_count() or 1
        self.adapters = []
        try:
            self.adapters = [a for a in dxgi.adapters(features=False) if not a.get("software")]
        except Exception as e:
            log_error(f"perf adapters: {e!r}")
        self.disk_models = {}
        try:
            for d in wmi.query("SELECT Index,Model FROM Win32_DiskDrive", quiet=True):
                self.disk_models[str(d.get("Index"))] = wmi.clean(d.get("Model"))
        except Exception:
            pass
        self._net_prev = None
        self._t_prev = None
        self.gpu_per_pid = {}

    def close(self):
        self.c.close()

    def sample(self):
        now = time.time()
        self.c.collect()
        c = self.c
        out = {"t": now}

        cores = {}
        for inst, v in c.array("cpu_cores").items():
            if "_Total" in inst:
                continue
            try:
                g, n = inst.split(",")
                cores[(int(g), int(n))] = min(100.0, v)
            except ValueError:
                continue
        total = c.value("cpu_total")
        if total is None:
            total = psutil.cpu_percent()
        perf, freq = c.value("cpu_perf"), c.value("cpu_freq")
        boot = psutil.boot_time()
        out["cpu"] = {
            "util": min(100.0, total or 0.0),
            "cores": [cores[k] for k in sorted(cores)],
            "mhz": (perf * freq / 100) if perf and freq else None,
            "base_mhz": freq,
            "procs": int(c.value("procs") or 0) or len(psutil.pids()),
            "threads": int(c.value("threads") or 0) or None,
            "handles": int(c.value("handles") or 0) or None,
            "uptime": now - boot,
        }

        vm = psutil.virtual_memory()
        cached = sum(c.value("cache:" + k) or 0 for k in ("Standby Cache Core Bytes", "Standby Cache Normal Priority Bytes",
                                                         "Standby Cache Reserve Bytes", "Modified Page List Bytes"))
        out["mem"] = {"total": vm.total, "used": vm.total - vm.available, "avail": vm.available,
                      "util": vm.percent, "commit": c.value("commit"), "commit_limit": c.value("commit_limit"),
                      "cached": cached or None, "paged": c.value("paged"), "nonpaged": c.value("nonpaged")}

        idle, rd, wr, resp = (c.array(k) for k in ("disk_idle", "disk_read", "disk_write", "disk_resp"))
        disks = []
        for inst in sorted(idle):
            if inst == "_Total":
                continue
            num, _, letters = inst.partition(" ")
            disks.append({"id": num, "letters": letters.strip(), "model": self.disk_models.get(num),
                          "active": max(0.0, min(100.0, 100.0 - idle[inst])),
                          "read": rd.get(inst, 0.0), "write": wr.get(inst, 0.0),
                          "resp_ms": resp.get(inst, 0.0) * 1000})
        out["disks"] = disks

        nets = []
        try:
            io = psutil.net_io_counters(pernic=True)
            stats = psutil.net_if_stats()
        except Exception:
            io, stats = {}, {}
        dt = (now - self._t_prev) if self._t_prev else None
        for name, s in stats.items():
            if not s.isup or name.lower().startswith("loopback") or name not in io:
                continue
            cur = io[name]
            prev = (self._net_prev or {}).get(name)
            send = recv = 0.0
            if prev and dt:
                send = max(0, cur.bytes_sent - prev.bytes_sent) * 8 / dt
                recv = max(0, cur.bytes_recv - prev.bytes_recv) * 8 / dt
            nets.append({"name": name, "send": send, "recv": recv, "speed": s.speed * 1_000_000 if s.speed else None})
        self._net_prev = io
        self._t_prev = now
        out["nets"] = nets

        adapters_util, self.gpu_per_pid = pdh.gpu_engines(c.array("gpu_engine"))
        ded = {pdh.luid_of(k): v for k, v in c.array("gpu_ded").items()}
        shared = {pdh.luid_of(k): v for k, v in c.array("gpu_shared").items()}
        gpus = []
        for i, a in enumerate(self.adapters):
            u = adapters_util.get(a["luid"], {"util": 0.0, "types": {}})
            gpus.append({"index": i, "luid": a["luid"], "name": a["name"], "util": u["util"], "types": u["types"],
                         "ded_used": ded.get(a["luid"]), "ded_total": a.get("dedicated") or None,
                         "shared_used": shared.get(a["luid"]), "shared_total": a.get("shared") or None})
        out["gpus"] = gpus
        return out
