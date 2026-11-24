// mergen-helper — mergen'in yükseltilmiş (yönetici) yardımcısı.
//
// LibreHardwareMonitorLib (MPL-2.0) ile sıcaklık / fan / voltaj / güç / saat / yük okur ve adlandırılmış kanaldan
// (\\.\pipe\mergen-helper-<kullanıcı>) satır satır JSON yollar. Kanal yalnızca aynı kullanıcıya (ve SYSTEM'e) açıktır.
//
// Protokol (her satır bir JSON nesnesi):
//   istemci -> {"cmd":"info"}                                      => {"type":"info", ...}
//   istemci -> {"cmd":"subscribe","interval":1000,"groups":[...]}  => saniyede bir {"type":"sensors", ...}
//   istemci -> {"cmd":"unsubscribe"} | {"cmd":"snapshot"} | {"cmd":"bye"} | {"cmd":"quit"}
// Yalnızca bu bilinen komutlar kabul edilir; rastgele komut / betik çalıştıran bir kapı YOKTUR. Yazma komutları
// (fan, güç modu) sonraki aşamalarda, her biri ayrı ve tipli olarak eklenecek.
//
// Ömür: hiç istemci bağlanmazsa 60 sn, son istemci ayrıldıktan 15 sn sonra kendiliğinden kapanır.

using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using LibreHardwareMonitor.Hardware;

namespace Mergen.Helper;

internal static class Program
{
    const string Version = "0.1.0";
    static readonly object Lock = new();
    static Computer? _computer;
    static string _groupsKey = "";
    static int _clients;
    static DateTime _lastClientLeft = DateTime.UtcNow;
    static readonly CancellationTokenSource Quit = new();
    static StreamWriter? _log;

    static int Main(string[] args)
    {
        if (args.Contains("--selfcheck"))
            return SelfCheck();
        string pipeName = "mergen-helper-" + (Environment.GetEnvironmentVariable("USERNAME") ?? "user");
        foreach (var a in args)
            if (a.StartsWith("--pipe=")) pipeName = a[7..];
        try
        {
            var dir = Environment.GetEnvironmentVariable("MERGEN_DATA_DIR") ?? Path.Combine(
                Environment.GetEnvironmentVariable("LOCALAPPDATA") ??
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "mergen");
            Directory.CreateDirectory(dir);
            _log = new StreamWriter(Path.Combine(dir, "helper.log"), append: false) { AutoFlush = true };
        }
        catch { /* günlük isteğe bağlı */ }
        Log($"mergen-helper {Version} başladı, yönetici={IsAdmin()}, kanal={pipeName}");

        var started = DateTime.UtcNow;
        _ = Task.Run(async () =>
        {
            while (!Quit.IsCancellationRequested)
            {
                await Task.Delay(1000);
                bool idle;
                lock (Lock)
                    idle = _clients == 0 && (DateTime.UtcNow - (_lastClientLeft > started ? _lastClientLeft : started))
                        .TotalSeconds > (_lastClientLeft > started ? 15 : 60);
                if (idle) { Log("istemci yok, kapanıyor"); Quit.Cancel(); }
            }
        });

        try
        {
            while (!Quit.IsCancellationRequested)
            {
                var server = CreatePipe(pipeName);
                try { server.WaitForConnectionAsync(Quit.Token).GetAwaiter().GetResult(); }
                catch (OperationCanceledException) { server.Dispose(); break; }
                lock (Lock) _clients++;
                _ = Task.Run(() => Serve(server));
            }
        }
        catch (Exception e) { Log("kanal hatası: " + e); return 2; }
        finally
        {
            lock (Lock) { _computer?.Close(); _computer = null; }
            Log("kapandı");
        }
        return 0;
    }

    static NamedPipeServerStream CreatePipe(string name)
    {
        var sec = new PipeSecurity();
        var me = WindowsIdentity.GetCurrent().User!;
        sec.AddAccessRule(new PipeAccessRule(me, PipeAccessRights.ReadWrite | PipeAccessRights.CreateNewInstance,
            AccessControlType.Allow));
        sec.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null),
            PipeAccessRights.FullControl, AccessControlType.Allow));
        return NamedPipeServerStreamAcl.Create(name, PipeDirection.InOut, 8, PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous, 4096, 65536, sec);
    }

    static async Task Serve(NamedPipeServerStream pipe)
    {
        var reader = new StreamReader(pipe, new UTF8Encoding(false));
        var writer = new StreamWriter(pipe, new UTF8Encoding(false)) { AutoFlush = true, NewLine = "\n" };
        var sendLock = new SemaphoreSlim(1, 1);
        CancellationTokenSource? sub = null;

        async Task Send(JsonNode n)
        {
            await sendLock.WaitAsync();
            try { await writer.WriteLineAsync(n.ToJsonString()); }
            finally { sendLock.Release(); }
        }

        try
        {
            while (!Quit.IsCancellationRequested && pipe.IsConnected)
            {
                var line = await reader.ReadLineAsync(Quit.Token);
                if (line == null) break;
                if (line.Length > 8192) continue;                 // makul olmayan uzunlukta satır: yok say
                JsonObject? msg;
                try { msg = JsonNode.Parse(line) as JsonObject; } catch { continue; }
                var cmd = msg?["cmd"]?.GetValue<string>();
                switch (cmd)
                {
                    case "info":
                        await Send(Info());
                        break;
                    case "snapshot":
                        await Send(Snapshot(Groups(msg!)));
                        break;
                    case "subscribe":
                        sub?.Cancel();
                        sub = new CancellationTokenSource();
                        var interval = Math.Clamp(msg!["interval"]?.GetValue<int>() ?? 1000, 250, 10000);
                        var groups = Groups(msg!);
                        var token = sub.Token;
                        _ = Task.Run(async () =>
                        {
                            while (!token.IsCancellationRequested && pipe.IsConnected)
                            {
                                var t0 = DateTime.UtcNow;
                                try { await Send(Snapshot(groups)); }
                                catch { break; }
                                var wait = interval - (int)(DateTime.UtcNow - t0).TotalMilliseconds;
                                try { await Task.Delay(Math.Max(50, wait), token); } catch { break; }
                            }
                        });
                        break;
                    case "unsubscribe":
                        sub?.Cancel();
                        break;
                    case "bye":
                        sub?.Cancel();
                        pipe.Disconnect();
                        break;
                    case "quit":                  // mergen yardımcıyı yönetici olarak yeniden açmadan önce
                        Log("quit komutu");
                        Quit.Cancel();
                        pipe.Disconnect();
                        break;
                    default:
                        await Send(new JsonObject { ["type"] = "error", ["error"] = "unknown command" });
                        break;
                }
            }
        }
        catch (Exception e) when (e is IOException or OperationCanceledException or ObjectDisposedException) { }
        catch (Exception e) { Log("istemci hatası: " + e); }
        finally
        {
            sub?.Cancel();
            pipe.Dispose();
            lock (Lock) { _clients--; _lastClientLeft = DateTime.UtcNow; }
        }
    }

    static HashSet<string> Groups(JsonObject msg)
    {
        var all = new[] { "cpu", "gpu", "memory", "motherboard", "controller", "storage", "network", "battery", "psu" };
        if (msg["groups"] is JsonArray arr)
            return arr.Select(x => x?.GetValue<string>() ?? "").Where(all.Contains).ToHashSet();
        return all.ToHashSet();
    }

    static Computer EnsureComputer(HashSet<string> groups)
    {
        var key = string.Join(",", groups.OrderBy(x => x));
        if (_computer != null && key == _groupsKey) return _computer;
        _computer?.Close();
        var c = new Computer
        {
            IsCpuEnabled = groups.Contains("cpu"), IsGpuEnabled = groups.Contains("gpu"),
            IsMemoryEnabled = groups.Contains("memory"), IsMotherboardEnabled = groups.Contains("motherboard"),
            IsControllerEnabled = groups.Contains("controller"), IsStorageEnabled = groups.Contains("storage"),
            IsNetworkEnabled = groups.Contains("network"), IsBatteryEnabled = groups.Contains("battery"),
            IsPsuEnabled = groups.Contains("psu"),
        };
        var t0 = DateTime.UtcNow;
        c.Open();
        Log($"Computer.Open ({key}) {(DateTime.UtcNow - t0).TotalMilliseconds:F0} ms, {c.Hardware.Count} donanım");
        _computer = c;
        _groupsKey = key;
        return c;
    }

    static JsonObject Snapshot(HashSet<string> groups)
    {
        var hw = new JsonArray();
        lock (Lock)
        {
            var c = EnsureComputer(groups);
            foreach (var h in c.Hardware)
                AddHardware(hw, h, null);
        }
        return new JsonObject
        {
            ["type"] = "sensors", ["t"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0, ["hardware"] = hw,
        };
    }

    static void AddHardware(JsonArray list, IHardware h, string? parent)
    {
        try { h.Update(); } catch (Exception e) { Log($"{h.Name} güncellenemedi: {e.Message}"); }
        var sensors = new JsonArray();
        foreach (var s in h.Sensors)
        {
            sensors.Add(new JsonObject
            {
                ["id"] = s.Identifier.ToString(), ["name"] = s.Name, ["type"] = s.SensorType.ToString(),
                ["index"] = s.Index, ["value"] = Num(s.Value), ["min"] = Num(s.Min), ["max"] = Num(s.Max),
            });
        }
        list.Add(new JsonObject
        {
            ["id"] = h.Identifier.ToString(), ["name"] = h.Name, ["type"] = h.HardwareType.ToString(),
            ["parent"] = parent, ["sensors"] = sensors,
        });
        foreach (var sub in h.SubHardware)
            AddHardware(list, sub, h.Identifier.ToString());
    }

    static JsonNode? Num(float? v) => v is { } f && float.IsFinite(f) ? JsonValue.Create(Math.Round(f, 3)) : null;

    static JsonObject Info()
    {
        bool installed = false;
        string? ver = null;
        try
        {
            installed = LibreHardwareMonitor.PawnIo.PawnIo.IsInstalled;
            ver = LibreHardwareMonitor.PawnIo.PawnIo.Version?.ToString();
        }
        catch (Exception e) { Log("PawnIO durumu okunamadı: " + e.Message); }
        return new JsonObject
        {
            ["type"] = "info", ["version"] = Version, ["admin"] = IsAdmin(), ["pid"] = Environment.ProcessId,
            ["lhm"] = typeof(Computer).Assembly.GetName().Version?.ToString(),
            ["pawnio_installed"] = installed, ["pawnio_version"] = ver,
        };
    }

    static bool IsAdmin()
    {
        using var id = WindowsIdentity.GetCurrent();
        return new WindowsPrincipal(id).IsInRole(WindowsBuiltInRole.Administrator);
    }

    static int SelfCheck()
    {
        Console.OutputEncoding = Encoding.UTF8;
        Console.WriteLine(Info().ToJsonString());
        var snap = Snapshot(new HashSet<string> { "cpu", "gpu", "memory", "motherboard", "storage", "battery" });
        var hw = (JsonArray)snap["hardware"]!;
        foreach (var h in hw)
            Console.WriteLine($"{h!["type"]}: {h["name"]} — {((JsonArray)h["sensors"]!).Count} sensör");
        lock (Lock) _computer?.Close();
        return 0;
    }

    static void Log(string s)
    {
        try { _log?.WriteLine($"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {s}"); } catch { }
    }
}
