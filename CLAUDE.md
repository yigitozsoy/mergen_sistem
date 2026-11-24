# mergen — Claude için proje notları ve yapım planı

Bu dosya hem proje belleği hem de **ilk yapım planı**. Repo şu an boş; yeni oturum bu planı izleyerek kurar.
Plan bittikçe bu dosyayı "plan" yerine "nasıl çalışıyor / bilinen tuzaklar" notlarına dönüştür (diğer tamga
uygulamalarının CLAUDE.md'leri gibi).

---

## 1. Proje nedir

**mergen**, tamga ailesinin **sistem bilgisi + donanım izleme + görev yöneticisi** uygulaması. Göktürkçe/eski Türkçe
"usta, keskin nişancı, bilge". Ad her yerde küçük harf: **mergen**.

Hedef: **her Windows 10/11 64-bit bilgisayarda** çalışan, dxdiag + Aygıt Yöneticisi + Programlar ve Özellikler +
Görev Yöneticisi + HWiNFO/LibreHardwareMonitor tarzı sensör ekranı + Chris Titus Tech WinUtil tarzı Windows
ince ayarlarını (telemetri, sağ tık menüsü, OneDrive, debloat) tek, sade, tamga görünümlü pencerede toplayan
çok detaylı bir araç. Üretici kontrol yazılımları (Clevo Control Center gibi) ek **cihaz modülleri** olarak gelir;
çekirdek uygulama hiçbir üreticiye bağımlı değildir.

Çıkış noktası: kullanıcının laptopu (Monster Abra A5 V17.2, Clevo tabanlı, i5-11400H, RTX 3050 Ti, BIOS 1.07.11)
fan/ısı ayarlarını Clevo "Control Center 3.0" ile yapıyor; mergen onun yerini de alabilmeli ama bu yalnızca bir modül.

### tamga ailesi
- Aile: **erk** (planlayıcı, `Desktop\erk`), **bediz** (Bambu yazıcı, `Desktop\bediz`, .NET), **kamug** (oynatıcı,
  `Desktop\kamug`), **yazıt** (not/çizim, `Desktop\yazıt`), **tamga** (başlatıcı, `Desktop\tamga`), **mergen** (bu repo).
- Çalışma tarzı, tasarım zevki ve iş akışı kuralları **kamug ile aynı**: `..\kamug\CLAUDE.md` bölüm 2'yi baştan sona oku.
  Özet: Türkçe yaz, makul varsayılanla ilerle; sade varsayılanlar, her şey açılıp kapatılabilir; **gri vurgu, AMOLED
  siyah, mor/eflatun yok**; önce gerçekten çalıştırıp doğrula; derleme/commit/push yalnızca istenince.
- Uygulamaların eski adları (gamma, alpha, beta, delta) hiçbir yerde görünmez.
- Logo: Göktürk **m** harfi 𐰢 (U+10C22), diğerleri gibi `packaging/make_logo.py` üretir (logo.png beyaz saydam,
  logo.ico açık gri kare + koyu harf; bediz/kamug'un make_logo.py'sini örnek al).
- Tema: `mergen/theme.py` = `..\yazıt\yazit\theme.py` / `..\tamga\tamga\palette.py` ile **birebir aynı** tema çeşitleri ve
  vurgular. Ortak ayarlar için `..\tamga\sync\tamga_sync.py`'nin kopyası `mergen/tamga_sync.py` (ortak anahtarlar:
  `theme`, `dark_variant`, `light_variant`, `accent`, `language`; tercihler `%LOCALAPPDATA%\mergen\preferences.json`).
- tamga başlatıcısına kart eklenecek: `..\tamga\tamga\apps.py` kataloğuna mergen girdisi (o repoda ayrı iş, yalnızca
  kullanıcı isteyince). mergen'in Inno **AppId**'si: `{98384CE8-F966-4B98-BEB8-3AFB0064834E}` (değiştirme).
- Kimlikler: paket `mergen/`, `mergen.exe`, kurulum `{autopf}\mergen` (kullanıcı başına, yönetici istemeyen Inno
  kurulumu; diğerleri gibi), veri `%LOCALAPPDATA%\mergen`, tek örnek `QLocalServer` adı `mergen-<kullanıcı>`,
  AppUserModelID `tamga.mergen`, çıktı `mergen-setup-<sürüm>.exe` + `mergen-portable-<sürüm>.zip`.
- Sürüm tek yerde: `mergen/__init__.py` → `__version__` (0.1.0 ile başla). GitHub deposu: `yigitozsoy/mergen_sistem`
  önerisi — depo açmak / push kullanıcıya sorulur.

---

## 2. Teknoloji

- **Python 3.14 · PyQt6** (ailenin geri kalanıyla aynı). Python tam yolu:
  `%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe` (çıplak `python` bu makinede bazen takılıyor).
- `psutil` (süreçler, CPU/RAM/disk/ağ sayaçları), `pywin32` (WMI/COM, servisler, kayıt defteri, PDH),
  canlı grafikler QPainter ile elle çizilir (`pages/performance.py` Graph; pyqtgraph denendi, gereksiz bulundu), `pynvml` (NVIDIA GPU, isteğe bağlı), `ctypes` (Win32, DXGI, SetupAPI).
- **Sensör yardımcısı** (sıcaklık, fan, voltaj, güç): **LibreHardwareMonitorLib** (.NET, MPL-2.0) üstüne küçük bir
  C# konsol uygulaması `sensors/mergen-sensors.exe`. Ana uygulama Python; yardımcıyı alt süreç olarak çalıştırır,
  adlandırılmış kanal (`\\.\pipe\mergen-sensors`) üzerinden saniyede bir JSON alır.
  - Neden ayrı süreç: LHM .NET; pythonnet paketlemeyi zorlaştırıyor ve sensör okuma **yönetici izni** ister.
    Ana pencere yöneticisiz kalır, yalnızca yardımcı yükseltilmiş çalışır.
  - UAC'ı her açılışta sormamak için: ilk kurulumda (kullanıcı onayıyla) "en yüksek ayrıcalıkla" çalışan bir
    Görev Zamanlayıcı görevi `mergen-sensors` oluşturulur; ana uygulama onu `schtasks /run` ile başlatır.
    Kullanıcı istemezse sensör sekmesi "yönetici izni gerekli — şimdi aç" düğmesiyle tek seferlik UAC ister.
  - Sürücü: LHM'nin yeni sürümleri çekirdek erişimi için **PawnIO** kullanır (eski WinRing0, Defender'da
    "savunmasız sürücü" olarak işaretleniyor — **WinRing0 kullanma**). PawnIO kurulu değilse kullanıcıya açıkla,
    onayla kur; kurulmazsa yalnızca WMI/ACPI + NVML ile gelebilen sensörler gösterilir.
  - .NET: yardımcıyı self-contained, tek dosya yayınla (kullanıcıda .NET runtime şartı olmasın). bediz'in
    `windows\build.ps1`'i dotnet publish örneği.
- Yönetici gerektiren tüm yazma işlemleri (fan, güç modu, sürücü/servis değişikliği, Windows ayarları) yardımcıdan
  geçer. Yardımcı yalnızca sensör okumadığı için adı **`mergen-helper`** olsun (exe, kanal `\\.\pipe\mergen-helper`,
  zamanlanmış görev); yukarıdaki "mergen-sensors" adları bununla değiştirilir. Yardımcı yalnızca bilinen, tipli komutlar
  kabul eder (rastgele komut/betik çalıştıran genel bir kapı açma); kanal yalnızca aynı kullanıcıya açık.

---

## 3. Arayüz

Çerçevesiz pencere + kamug/yazıt ile aynı başlık çubuğu. Solda dar dikey sekme çubuğu (simge + ad), sağda içerik.
Üstte arama kutusu: hangi sekmedeysen onu süzer (program adı, süreç, aygıt, sürücü). Varsayılan sade; ayrıntılı
sütunlar "•••" › Tercihler › Kişiselleştirme'den açılır.

### Sekme 1 — Sistem (dxdiag gibi, salt okunur)
Kart kart, her kartta "Kopyala" ve tümü için **Rapor dışa aktar** (TXT / HTML / JSON). Açılışta önbellekten hızlı
gösterir, arka planda (QThread) WMI'dan tazeler — WMI sorguları yavaş, arayüzü asla dondurma.
- **Genel:** bilgisayar adı, üretici/model (Win32_ComputerSystem), Windows sürümü + derleme + yükleme tarihi + son
  açılış, kullanıcı, dil/bölge, etkinleştirme durumu, Güvenli Önyükleme, TPM, BIOS/UEFI.
- **İşlemci:** ad, çekirdek/iş parçacığı, taban/en yüksek saat, önbellekler (L1/L2/L3), soket, mikrokod, sanallaştırma,
  komut setleri (AVX2, AVX-512…, `IsProcessorFeaturePresent` + cpuid).
- **Anakart + BIOS:** üretici, model, seri (gizlenebilir), BIOS sürümü/tarihi.
- **Bellek:** toplam/kullanılabilir, **her modül** (Win32_PhysicalMemory: yuva, boyut, hız, yapılandırılmış hız,
  üretici, parça no), kanal düzeni, boş yuvalar (Win32_PhysicalMemoryArray).
- **Ekran kartları:** her GPU (DXGI EnumAdapters1: ad, adanmış/paylaşılan bellek, LUID), sürücü sürümü/tarihi,
  **DirectX** özellik düzeyi, WDDM sürümü, DirectX 12 Ultimate / ray tracing desteği (D3D12 CheckFeatureSupport),
  NVIDIA ise NVML'den PCIe bağı, güç sınırı, VBIOS.
- **Ekranlar:** her monitör (EDID: WmiMonitorID / kayıt defteri), çözünürlük, yenileme hızı, HDR, ölçek, bağlı GPU.
- **Depolama:** fiziksel diskler (MSFT_PhysicalDisk: model, tür SSD/HDD/NVMe, veri yolu, boyut, sağlık),
  **SMART / NVMe sağlık** (sıcaklık, kalan ömür, çalışma saati — yardımcı üzerinden), bölümler ve birimler.
- **Ses, Ağ, USB, Bluetooth:** aygıtlar, MAC/IP (gizlenebilir), bağlantı hızı, Wi-Fi standardı.
- **Pil (varsa):** tasarım kapasitesi, tam şarj kapasitesi, **sağlık %**, çevrim sayısı, kimya, üretici
  (root\WMI BatteryStaticData / BatteryFullChargedCapacity / BatteryCycleCount; yedek: `powercfg /batteryreport`).

### Sekme 2 — Programlar ve sürücüler
Alt sekmeler (üstte çip çubuğu, erk'in ChipBar'ı gibi):
- **Programlar:** kayıt defteri Uninstall anahtarları (HKLM, HKLM WOW6432Node, HKCU) + Microsoft Store paketleri
  (Get-AppxPackage eşdeğeri, `winrt`/PowerShell). Sütunlar: ad, yayımcı, sürüm, kurulum tarihi, boyut, **kurulum
  klasörü**, kaldırma komutu. Sağ tık: klasörü aç, kaldır (Windows'un kendi kaldırıcısını çalıştırır), kayıt defterinde göster.
- **Başlangıç:** Run anahtarları, Başlangıç klasörleri, zamanlanmış görevler (oturum açılışında), servisler
  (otomatik). Aç/kapat = Görev Yöneticisi'nin kullandığı `StartupApproved` anahtarı (silmeden devre dışı bırakır).
- **Servisler:** ad, durum, başlangıç türü, exe yolu, açıklama; başlat/durdur yönetici ister.
- **Sürücüler:** Win32_PnPSignedDriver + SetupAPI: aygıt, sınıf, sağlayıcı, sürüm, tarih, **.inf ve .sys yolu**,
  imza; sorunlu aygıtlar (ConfigManagerErrorCode ≠ 0) en üstte kırmızı değil **gri vurgulu rozet**le.
- **Dosya yolları:** ortam değişkenleri, PATH girdileri (var olmayanlar işaretli), bilinen klasörler, büyük klasörler
  (isteğe bağlı disk kullanımı taraması, arka planda).

### Sekme 3 — Sensörler
- Ağaç/kart görünümü: donanım başına (CPU, GPU, anakart, diskler, pil) sıcaklık, fan devri / %, voltaj, güç (W),
  saat hızı, yük. Her değerde **anlık / en düşük / en yüksek / ortalama** (HWiNFO gibi), sıfırla düğmesi.
- Uyarılar (varsayılan kapalı): "CPU 95 °C'yi 30 sn aşarsa bildirim" — Windows bildirimi, AUMID `tamga.mergen`.
- Kayıt: CSV'ye günlük (varsayılan kapalı).

### Sekme 4 — Performans (Görev Yöneticisi'nin Performans sekmesi gibi)
- Solda küçük canlı mini grafikler: CPU, Bellek, her disk, her ağ bağdaştırıcısı, her GPU. Seçileni sağda büyük.
- CPU: toplam + **çekirdek başına** grafik, saat hızı, süreç/iş parçacığı/tanıtıcı sayısı, çalışma süresi.
- GPU: **tüm üreticiler** için "GPU Engine" / "GPU Adapter Memory" PDH sayaçları (3D, Copy, Video Decode/Encode
  motorları, adanmış/paylaşılan bellek) — Task Manager da bunu kullanır; NVIDIA'da ek olarak NVML (sıcaklık, güç, saat).
- Grafik geçmişi 60 sn varsayılan, 5/10 dk seçilebilir. QPainter, saniyede 1 güncelleme, gizli sekmede çizim yok.

### Sekme 5 — Görev yöneticisi
- Süreç listesi (psutil): ad, PID, CPU %, bellek, disk, ağ (ETW yoksa yalnızca disk G/Ç), GPU % (PDH, PID başına),
  **exe yolu**, komut satırı, kullanıcı, başlama zamanı, öncelik. Ağaç görünümü (üst süreç) aç/kapa.
- Sağ tık: sonlandır / süreç ağacını sonlandır (onay ister), öncelik, benzeşim, dosya konumunu aç, özellikler, çevrimiçi ara.
- Uygulamalar / arka plan süreçleri / Windows süreçleri grupları (Task Manager gibi).

### Sekme 6 — Cihaz (yalnızca desteklenen donanımda görünür)
Üretici modülleri `mergen/vendors/<üretici>.py`, ortak arayüz: `detect() -> bool`, `capabilities()`,
`read() -> dict`, `set_fan(...)`, `set_power_mode(...)`, `set_keyboard(...)`. Desteklenmeyen cihazda sekme hiç görünmez.

**İlk modül: Clevo (Monster, Tulpar ve diğer Clevo tabanlılar)** — bu makinede bulunanlar (2026-11-24):
- Control Center 3.0 bir MSIX paketi (`CLEVOCO.ControlCenter3.0` 7.68.1.0); yanında `CLEVOCO.LedKeyboardSetting`,
  `CLEVOCO.Flexikey`, `CLEVOCO.FnhotkeysandOSD`. Servis `CCDCHUService`
  (`C:\Windows\System32\DriverStore\FileRepository\acpibridge1.inf_amd64_*\DCHUService.exe`).
- Donanıma giden yol: **`InsydeDCHU.dll`** (aynı DriverStore klasöründe; Control Center kendi kopyasını da taşır) →
  **`AcpiBridge1.sys`** sürücüsü. DLL'nin dışa açtığı fonksiyonlar:
  `GetDCHU_Data_Integer`, `GetDCHU_Data_Buffer`, `SetDCHU_Data`, `ReadAppSettings`, `WriteAppSettings`.
- Algılama: Win32_ComputerSystem üretici "Notebook" / Clevo + `CCDCHUService` var + DriverStore'da `InsydeDCHU.dll`.
  DLL'yi **DriverStore'dan yükle**, kopyalama/paketleme (Clevo'nun dosyası, dağıtma).
- **Komut kodları belgesiz.** İmzalar ve kodlar (fan duty, fan modu otomatik/max/özel, güç modu Quiet/Power Saving/
  Entertainment/Performance, klavye rengi/parlaklık/uyku süresi, CPU/GPU sıcaklık ve fan RPM okuma) açık kaynak Clevo
  projelerinden araştırılıp doğrulanmalı; gerekirse Control Center'ın DLL çağrıları (API Monitor / x64dbg
  kesme noktası) izlenerek çıkarılır.
- **Güvenlik kuralı:** önce yalnızca `Get*` okuma çağrıları. Her `SetDCHU_Data` kodunu ilk kez denemeden önce
  kullanıcıya hangi kodu, ne değerle göndereceğini söyle ve **onay al**. Fan "özel" modunda bir güvenlik ağı olsun:
  CPU/GPU 90 °C'yi geçerse otomatik moda dön. Uygulama kapanırken/çökerken fan otomatik moda döndürülür.
- Control Center ile aynı anda fanı yönetme: ikisi birbirini ezer. Cihaz sekmesinde "Control Center açık" uyarısı.
- Kural motoru (varsayılan kapalı): "CPU > X °C → Performans modu + fan max; Y °C altına inince eski moda dön",
  "fişten çekilince Güç Tasarrufu".
- Sonraki aday modüller (araştırıp ekle, yalnızca istenince): Lenovo Legion (WMI), ASUS (ATKACPI/WMI),
  MSI (EC/WMI), Dell (dell-smm / WMI), HP Omen (WMI).

Genel (üreticiden bağımsız) ayarlar da bu sekmede: **Windows güç planı / güç modu** (powercfg, `PowerSetActiveOverlayScheme`),
ekran parlaklığı (WmiMonitorBrightnessMethods).

### Sekme 7 — Windows ayarları (Chris Titus Tech WinUtil entegrasyonu)
Kullanıcı Chris Titus Tech'in **WinUtil** debloater'ının (github.com/ChrisTitusTech/winutil, **MIT lisanslı**) tüm
işlevlerinin mergen'de olmasını istiyor (2026-11-24): telemetri kapatma, sağ tık menüsü, OneDrive'ı kaldırma, gereksiz
uygulamaları silme vb.

**Nasıl entegre edilir (kural):**
- WinUtil'i **asla** `irm christitus.com/win | iex` ile çalıştırma ve çalışma anında internetten betik indirme.
  Belirli bir sürüm etiketini (release tag) seç, deposundaki **`config/*.json`** dosyalarını (tweaks.json,
  applications.json, feature.json, preset.json, dns.json…) `mergen/winutil/data/` altına **kopyala**, sürümü ve
  commit'i `mergen/winutil/VERSION` dosyasına yaz, MIT lisans metnini `mergen/winutil/LICENSE-winutil` olarak koy ve
  Hakkında penceresinde "Windows ayarları Chris Titus Tech WinUtil'den uyarlandı (MIT)" diye atıf ver.
  Güncelleme = yeni etiketin JSON'larını elle alıp farkı gözden geçirmek (bir betik `tools/update_winutil.py` yardım eder).
- O JSON'larda her ayar zaten yapısal: `registry` (Path, Name, Type, **Value**, **OriginalValue**), `service`
  (Name, StartupType, OriginalType), `ScheduledTask` (State, OriginalState), `appx`, `InvokeScript` / `UndoScript`
  (PowerShell). mergen bunları **kendi Python motoruyla** uygular (`mergen/winutil/engine.py`):
  kayıt defteri `winreg`, servisler `sc`/pywin32, görevler `schtasks`, appx PowerShell. Yalnızca `InvokeScript`
  içeren ayarlarda PowerShell betiği çalışır; bu betikler ekranda gösterilir, gözden geçirilmeden uygulanmaz.
- **Her uygulama geri alınabilir:** uygulamadan önce o anki gerçek değerler okunup
  `%LOCALAPPDATA%\mergen\tweaks-undo.json`'a yazılır (JSON'daki OriginalValue'ya güvenme; makinedeki gerçek değer esas).
  İlk ayar uygulanmadan önce (kullanıcı onayıyla) **sistem geri yükleme noktası** oluştur (`Checkpoint-Computer`
  eşdeğeri). "Geri al" düğmesi tek tek ya da hepsi.
- Önizleme: "Uygula"ya basınca ne değişecek tam liste (kayıt defteri yolu: eski → yeni, servis, görev, betik) gösterilir,
  sonra onay. Yönetici isteyen değişiklikler yükseltilmiş yardımcıdan geçer (bkz. bölüm 2; yardımcının adı bu yüzden
  genel: `mergen-helper`, sensör okuma + sistem yazma).

**Alt sekmeler** (WinUtil'in sekmelerine karşılık, mergen görünümünde):
- **Önerilen / Gelişmiş ayarlar (Tweaks):** telemetri ve veri toplama, Etkinlik Geçmişi, konum izleme, Copilot / Recall,
  Bing araması, Wi-Fi Sense, hazırda bekletme, servisleri elle başlata alma, Edge/Store önerileri, reklam kimliği, vb.
  WinUtil'in "Standard / Minimal" ön ayarları (preset.json) tek tıkla seçilebilir. "Gelişmiş — dikkat" grubu ayrı
  ve varsayılan kapalı.
- **Tercihler (anlık açma/kapama anahtarları):** koyu tema, klasik sağ tık menüsü (Windows 11), dosya uzantılarını
  göster, gizli dosyalar, Bing arama, Num Lock açılışta, yapışkan tuşlar, görev çubuğu ayarları, fare hızlandırma vb.
- **Sağ tık menüsü (mergen'in kendi eklentisi, WinUtil'de tam yok):**
  Windows 11 klasik/yeni menü anahtarı (`HKCU\Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32`
  boş varsayılan değer) + **menü düzenleyici**: `HKCR\*\shell`, `Directory\shell`, `Directory\Background\shell`,
  `Drive\shell`, `shellex\ContextMenuHandlers` ve Windows 11 paketli menü öğeleri listelenir; her öğe kapatılabilir
  (silmeden: `LegacyDisable` değeri ya da `Shell Extensions\Blocked` anahtarı), geri açılabilir. Explorer'ı yeniden
  başlat düğmesi.
- **Uygulamalar:** WinUtil'in applications.json listesiyle **winget** üzerinden toplu kurulum/güncelleme (seçilenleri
  kur) + yerleşik Store uygulamalarını kaldırma (debloat). Kaldırılacaklar listesi önizlenir; Store, Fotoğraflar,
  Hesap Makinesi gibi temel uygulamalar varsayılan seçili değil.
- **OneDrive:** iki ayrı işlem, ikisi de ayrı onaylı:
  1. **Klasörleri OneDrive'dan geri al** (Known Folder Move'u geri çevir): `HKCU\...\Explorer\User Shell Folders`
     ve `Shell Folders` içindeki Masaüstü/Belgeler/Resimler… yolları `%USERPROFILE%\OneDrive\...` yerine
     `%USERPROFILE%\...` olur, **dosyalar taşınır** (kopyala → doğrula → sonra eskisini kaldır; asla önce silme).
  2. **OneDrive'ı tamamen kaldır** (WinUtil'in RemoveOnedrive ayarı): yalnızca 1. adım bittikten ve dosyaların
     yerel kopyası doğrulandıktan sonra izin verilir; "çevrimiçi yalnız" (Files On-Demand, yerelde olmayan) dosya
     varsa işlem durur ve listeler.
  ⚠ **Bu makinede kullanıcının tüm projeleri `C:\Users\yigit\OneDrive\Desktop\` altında** (mergen dahil, tamga
  ailesi, yigitozsoy.net). Taşıma; repoların CLAUDE.md'lerindeki mutlak yolları, Claude Code proje bellek
  klasörlerini (yol adından türetiliyor), kısayolları ve kurulu uygulamaların tercihlerindeki yolları kırar.
  Bu makinede uygulamadan önce kullanıcıyla ayrıca konuş; mergen geliştirilirken bu işlemi **gerçek sistemde test
  etme** (yalnızca sahte kayıt defteri/klasörle birim testi ya da sanal makine).
- **Windows Update:** WinUtil'in Varsayılan / Yalnızca güvenlik / Kapalı seçenekleri (kapalı = kırmızı değil, açık
  uyarılı gri rozet).
- **Özellikler ve düzeltmeler (feature.json):** .NET 3.5, Hyper-V, WSL, Sandbox açma; Windows Update sıfırlama,
  ağ sıfırlama, `sfc /scannow` + `DISM /RestoreHealth` çalıştırma (çıktı canlı gösterilir).
- **DNS:** WinUtil'in dns.json listesi (Cloudflare, Google, Quad9…) ile bağdaştırıcı başına DNS seçimi.

Bu sekmedeki hiçbir işlem varsayılan olarak seçili gelmez; mergen yalnızca bilgi gösteren bir araç olarak açılır.

---

## 4. Klasör yapısı (hedef)
```
main.py                   kaynaktan başlatıcı (python main.py [--tray])
mergen/
  __init__.py             __version__, REPO
  app.py                  tek örnek (QLocalServer), dil, excepthook → %LOCALAPPDATA%\mergen\error.log
  config.py               yollar, Prefs (preferences.json)
  theme.py                yazıt/tamga ile birebir aynı tema çeşitleri + vurgular
  tamga_sync.py           ..\tamga\sync\tamga_sync.py kopyası (elle düzenleme; ana kopya tamga'da)
  i18n.py + locales/tr.json, en.json   (Türkçe varsayılan)
  window.py               çerçevesiz ana pencere, başlık çubuğu, sol sekme çubuğu, arama
  pages/                  system.py, programs.py, sensors.py, performance.py, processes.py, device.py, tweaks.py
  winutil/                data/*.json (WinUtil sürüm kopyası), VERSION, LICENSE-winutil, engine.py (uygula /
                          önizle / geri al), contextmenu.py (sağ tık düzenleyici), onedrive.py, winget.py
  collect/                saf veri toplama (arayüzsüz, test edilebilir):
                          wmi.py, dxgi.py, registry.py, appx.py, drivers.py, startup.py, services.py,
                          pdh.py (performans sayaçları), procs.py, battery.py, edid.py, power.py (güç planı / modu /
                          parlaklık), report.py (dışa aktarım)
  helper_client.py        yardımcıyı başlatır (görev / yükseltilmemiş / tek seferlik UAC), kanaldan okur, yeniden dener
  sensor_service.py       min/maks/ort, sıcaklık uyarısı, CSV günlüğü (sekme kapalıyken de, açıksa)
  vendors/                base.py, clevo.py
  widgets/                grafik, kart, rozet, tablo modeli (QAbstractTableModel — büyük listeler için şart)
helper/                   C# mergen-helper (MergenHelper.csproj, Program.cs; LibreHardwareMonitorLib 0.9.6, MPL-2.0)
packaging/                build.ps1, mergen.spec (PyInstaller), installer.iss, make_logo.py, make_meta.py
tests/                    smoke_test.py (offscreen, geçici LOCALAPPDATA, ağ yok, gerçek fan/güç yazımı ASLA yok)
```

---

## 5. Yapım sırası (aşamalar)

Her aşama sonunda: `python tests/smoke_test.py` + `python -m pyflakes mergen tests` temiz, uygulamayı gerçekten
çalıştırıp ekran görüntüsüyle doğrula. Derleme yalnızca kullanıcı "derle" deyince.

1. ✅ (2026-11-24) **İskelet:** klasör yapısı, main.py, app.py (tek örnek), theme + tamga_sync, çerçevesiz pencere, boş 6 sekme,
   logo (Göktürk 𐰢), i18n, smoke test altyapısı. `git init`, .gitignore (build/, __pycache__/, *.log).
2. ✅ (2026-11-24) **Sistem sekmesi** (yönetici gerekmez): collect/wmi, dxgi, edid, battery + kartlar + rapor dışa aktarım.
   Bu makinede ve mümkünse bir masaüstü/AMD makinede doğrula (değer yoksa "—", asla çökme).
3. ✅ (2026-11-24) **Görev yöneticisi + Performans** (psutil + PDH): süreç tablosu (model/view, 300+ süreçte akıcı), grafikler.
4. ✅ (2026-11-24) **Programlar ve sürücüler:** programlar, başlangıç, servisler, sürücüler, dosya yolları.
5. ✅ (2026-11-24; yükseltilmiş yol + görev kullanıcı UAC onayıyla denenecek) **Sensör yardımcısı:** C# LHM yardımcısı, kanal protokolü, zamanlanmış görev ile yükseltme, PawnIO kontrolü,
   Sensörler sekmesi, min/max/ort.
6. ◐ (2026-11-24 okuma + güç modu yazma bitti; klavye ve fan kullanıcı onayı bekliyor) **Cihaz sekmesi / Clevo modülü:** önce okuma; sonra kullanıcı onayıyla adım adım yazma (güç modu → klavye ışığı
   → fan). Güvenlik ağı ve kural motoru en son.
7. **Windows ayarları (WinUtil):** JSON'ları kopyala + lisans/atıf, motor (önizleme, geri alma kaydı, geri yükleme
   noktası), önce Tercihler anahtarları ve sağ tık menüsü, sonra Tweaks/ön ayarlar, Uygulamalar (winget), DNS,
   özellikler/düzeltmeler, en son OneDrive. Testler sahte kayıt defteri kökü (`HKCU\Software\mergen-test\...`'e
   yönlendirilmiş motor) ile; gerçek sistem ayarı testte asla değişmez.
8. **Paketleme:** PyInstaller + Inno (yardımcı exe dahil), `mergen.exe --selfcheck`, taşınabilir zip; tamga
   kataloğuna ekleme (tamga reposunda, kullanıcı isteyince).

## 6. Dikkat
- Uygulama **her Windows'ta** çalışmalı: hiçbir alan belirli bir donanımı varsaymaz; sorgu başarısızsa "—" ve
  error.log'a not. Masaüstü (pilsiz), AMD, çift GPU, sanal makine durumlarını düşün.
- Seri numarası, MAC, IP, ürün anahtarı gibi kişisel/kimlik bilgileri varsayılan **gizli** (tıklayınca görünür) ve
  rapor dışa aktarımında "kişisel bilgileri çıkar" seçeneği varsayılan açık. Hiçbir veri ağa gönderilmez.
- WMI ve PDH çağrıları arayüz iş parçacığında yapılmaz. COM her iş parçacığında `CoInitialize` ister.
- Sistemi değiştiren her işlem (süreç sonlandırma, servis, başlangıç, kaldırma, fan, güç modu) onay ister ve geri
  alınabilir olanlar geri alınabilir olmalı.

## 7. Bilinen tuzaklar (yapım sırasında öğrenilenler)
- **WQL LIKE'ta ters bölü kullanma:** `DeviceID LIKE 'PCI\%'` 0 satır döner; `LIKE 'PCI%'` yaz.
- `MSFT_Partition` ve `MSFT_StorageReliabilityCounter` (SMART) yönetici ister → bölümler `Win32_LogicalDiskToPartition`
  ile, SMART yardımcıdan (5. aşama).
- pywin32 COM nesneleri `CoUninitialize`'dan önce bırakılmalı (`collect/wmi.py` `_run` ayrı işlevde bu yüzden);
  gömülü COM özellikleri (ör. `SupportedDisplayFeatures`) satıra taşınmaz.
- D3D12 aygıtı oluşturmak Optimus'ta harici GPU'yu kısa süre uyandırır; Sistem verisi önbelleğe alınır
  (`cache/system.json`), yalnızca sekme açılışında / Yenile'de tazelenir.
- D3D12 ışın izleme seviyesi 12 = 1.2 (Agility); enum'u sabit tabloyla değil `1.{v-10}` ile çöz.
- Kişisel satırlar: `s: True` ekranda gizli + raporda çıkarılır; `s: "r"` (bilgisayar/kullanıcı adı) ekranda görünür,
  yalnızca "kişisel bilgileri çıkar" açık raporda çıkarılır.
- Windows'ta Python ile dosya yamalarken `newline=""` kullan; aksi halde LF dosyalar CRLF'ye döner.
- **psutil süreç başına yavaş:** 300 süreçte `process_iter` + cpu/bellek/io 1,2 sn sürüyor. Sayılar
  `collect/ntproc.py` (tek `NtQuerySystemInformation(SystemProcessInformation)`, ~5 ms) ile; psutil yalnızca exe yolu /
  komut satırı / kullanıcı için, süreç başına bir kez ve tur başına 0,25 sn bütçeyle.
- **NVML'i saniyede bir sorgulama:** Optimus'ta harici GPU'yu uyanık tutar. Performans/Görev yöneticisi GPU verisi
  yalnızca PDH "GPU Engine" sayaçlarından; `dxgi.adapters(features=False)` D3D12 aygıtı oluşturmaz.
- PDH GPU motor türleri boşluksuz gelir (`VideoDecode`, `VideoEncode`, `OFA_0`, `LegacyOverlay`…); gösterirken
  `ENGINE_LABEL` ile çevir, ilk dört motoru `GPU_ENGINE_ORDER`'a göre seç.
- Stil sayfasında `QTreeView::item` kuralı varsa modelin BackgroundRole'ü yok sayılır → yoğunluk rengi
  `HeatDelegate` ile elle boyanır.
- Gri vurgu (#c4c4c4) açık temada grafik çizgisi olarak görünmez → `line_color()` karşıtlık düşükse text2 kullanır.
- Ortak örnekleyici `monitor.py`: tek iş parçacığı; Performans geçmişi sekme gizliyken de birikir (Görev Yöneticisi
  gibi), süreç listesi yalnızca Görevler sekmesi görünürken toplanır. Uygulama kapanırken `monitor().stop()`.
- **Win32_SystemDriver 7+ sn sürüyor:** sürücülerin .sys yolu `Services\<ad>\ImagePath`'ten (kayıt defteri), .inf'in
  DriverStore klasörü `HKLM\SYSTEM\DriverDatabase\DriverInfFiles\oemNN.inf`'ten. ImagePath önekleri (`\SystemRoot\`,
  `\??\`, `system32\`) `services.service_exe` ile çözülür.
- **Store paketleri:** Get-AppxPackage (~3 sn) yerine `HKCU\...\AppModel\Repository\Packages` okunur; "ms-resource:"
  adları `SHLoadIndirectString("@{TamAd?ms-resource://Ad/Resources/X}")` ile. Çözülemezse dönen değer "@{" ile başlar →
  başarısız say. `C:\Windows\SystemApps` paketleri (Windows bileşeni) listelenmez.
- **Başlangıç aç/kapat** Görev Yöneticisi'nin `StartupApproved` biçimiyle (02… etkin, 03+FILETIME devre dışı), girdi
  silinmez. HKCU doğrudan yazılır; HKLM, zamanlanmış görevler ve servis başlat/durdur şimdilik `actions.run_elevated`
  ile tek seferlik UAC (yalnızca reg.exe / schtasks / Start|Stop|Restart-Service) — 5. aşamada mergen-helper'a taşınacak.
- `widgets/table.py` (DataTable): tüm listeler için ortak model/proksi/görünüm; `Col(stretch=True)` kalan boşluğu
  doldurur ama tanımlı genişliğin altına inmez (QHeaderView Stretch çok sütunda sütunu eziyordu); `badge` bool ya da
  satır işlevi (gri hap).
- "Kayıt defterinde göster": regedit'in kendi `LastKey` değerine yazılır (kök adı dile göre "Bilgisayar"/"Computer",
  var olan değerden alınır) + `regedit /m`.
- **mergen-helper** (`helper/`): `dotnet publish -c Release -r win-x64 --self-contained -p:PublishSingleFile=true
  -p:IncludeNativeLibrariesForSelfExtract=true -p:EnableCompressionInSingleFile=true -o publish` → tek dosya ~40 MB.
  Kanal `\.\pipe\mergen-helper-<kullanıcı>`, DACL yalnızca kullanıcı SID + SYSTEM; satır başına JSON; komutlar
  yalnızca info / subscribe / unsubscribe / snapshot / bye / quit (yazma komutu YOK — 6. aşamada tipli eklenecek).
  İstemci yokken 60 sn, son istemciden 15 sn sonra kendiliğinden kapanır. Günlük `%LOCALAPPDATA%\mergen\helper.log`.
- LHM 0.9.6 PawnIO kullanır (WinRing0 yok). `PawnIo.IsInstalled`/`Version` statik, `IsLoaded` örnek özelliği.
  PawnIO yokken (ve yönetici değilken) işlemci sıcaklığı null, işlemci gücü/voltajı **0** döner → arayüz bunları gizler.
  Yönetici olmadan da NVIDIA/Intel GPU, bellek, pil okunur; diskler (SMART) ve anakart yönetici ister.
- **Zamanlanmış görev güvenliği:** görev, kullanıcının yazabildiği bir exe'yi en yüksek ayrıcalıkla çalıştırırsa UAC
  atlatma kapısı olur. Bu yüzden görev oluşturulurken (tek UAC) yardımcı `%ProgramFiles%\mergen-helper\`'a kopyalanır,
  görev oradan çalışır; görev XML'inin güvenlik tanımlayıcısı kullanıcıya yalnızca okuma+çalıştırma verir. Yardımcı
  sürümü değişince görev yeniden oluşturulmalı (Görünüm › görevi kaldır → yeniden "Her seferinde sorma").
- İstemci kanalı PeekNamedPipe ile yoklar: eşzamanlı tanıtıcıda bekleyen ReadFile aynı tanıtıcıdaki WriteFile'ı kilitler.
- GPU sensörlerini okumak (NVAPI/NVML) Optimus'ta harici GPU'yu uyanık tutar; sensörler yalnızca sekme görünürken
  (ya da uyarı/CSV açıkken) okunur, "Okunacak donanımlar" menüsünden ekran kartları kapatılabilir.
- **InsydeDCHU.dll arabellek taşması:** `GetDCHU_Data_Buffer` "256 bayt" arabelleğe **257 bayt** yazıyor (nöbetçi
  baytla ölçüldü). 256'lık ctypes arabelleği Python yığınını bozuyor → rastgele segfault (çıktı yönlendirilince
  görünür oldu). `vendors/clevo.py` 1024 baytlık arabellek kullanır; yeni bir DCHU çağrısında da büyük arabellek ver.
- Clevo okumaları (`GetDCHU_Data_Buffer` 12/13, `ReadAppSettings`) **yönetici istemez**; bir okuma turu ~60 ms.
  Bu makinede: buffer 13 [12] = 2 fan, [15] = klavye türü 6; ReadAppSettings(1,1,1) = güç modu (2 = Performans),
  (4,5,1) = fan modu (0 = otomatik), (4,7,1) = fan ofseti. DLL yalnızca CCDCHUService'in ImagePath klasöründen
  yüklenir (DriverStore'da eski kopyalar da var). `clevo.py`'de SetDCHU_Data / WriteAppSettings hiç bağlanmaz;
  smoke test bunu denetler.
- Control Center 3.0 süreci `ControlCenter30.exe` (MSIX, WindowsApps). `FnKey.exe` ve `DCHUService.exe` her zaman
  çalışır — "Control Center açık" uyarısı bunlara bakmaz.
- Cihaz sekmesi artık her bilgisayarda görünür (Windows güç planı / güç modu / parlaklık genel); üretici kartı
  yalnızca `vendors.detect_any()` bir modül döndürürse. Güç modu (overlay) yalnızca Dengeli planda seçilebilir;
  plan ve mod değişikliği onay ister, parlaklık kaydırıcısı (Windows'unki gibi) istemez.
- **Clevo güç modu yazma** (2026-11-24 kullanıcı onayıyla doğrulandı, 2 → 3 → 2): OutLog günlüğüne kaynak
  `PowerBIOSServer_Out` ile `clevocc30^101^<mod>` olayı yazılır (`win32evtlog.ReportEvent`, yönetici istemez).
  FnKey.exe olayı alır, BIOS'a `WMI_Write cmd=121 SubCMD=25 SetData=<mod>` yazar, fan tablosu / yenileme hızını
  ayarlar; ~1 sn sonra ReadAppSettings(1,1,1) yeni değeri döner. FnKey'in yaptıklarını görmek için OutLog'u oku
  (`Get-WinEvent -LogName OutLog -MaxEvents 15`). Smoke test `set_power_mode`'u yalnızca geçersiz değerle çağırır.
