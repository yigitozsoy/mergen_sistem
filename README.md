```powershell
$ProgressPreference = 'SilentlyContinue'; $a = (irm https://api.github.com/repos/yigitozsoy/mergen_sistem/releases/latest).assets | ? name -like '*setup*.exe' | select -First 1; irm $a.browser_download_url -OutFile "$env:TEMP\$($a.name)"; & "$env:TEMP\$($a.name)"
```

<sub>PowerShell'e yapıştırın: son sürümü indirip kurulumu açar. Elle indirmek için [Releases](../../releases/latest).</sub>

<h1 align="center">mergen</h1>

<p align="center">
  Sistem bilgisi, donanım izleme ve görev yöneticisi — tek, sade pencerede.<br>
  <sub>tamga ailesinden · Windows 10 / 11 (64-bit) · ön sürüm</sub>
</p>

## Özellikler

- **Sistem.** dxdiag gibi: işlemci, bellek modülleri, ekran kartları (DirectX / ışın izleme), ekranlar, diskler, ağ,
  pil sağlığı. TXT / HTML / JSON rapor; seri no, MAC, IP gibi kişisel bilgiler varsayılan gizli.
- **Programlar ve sürücüler.** Kurulu programlar ve Store uygulamaları (kurulum klasörüyle), başlangıç öğeleri
  (silmeden kapat), servisler, sürücüler (.inf / .sys yolu, sorunlu aygıtlar), ortam değişkenleri ve PATH.
- **Sensörler.** Sıcaklık, fan, voltaj, güç, saat hızı; anlık / en düşük / en yüksek / ortalama, sıcaklık uyarısı,
  CSV kaydı. [LibreHardwareMonitorLib](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) üstüne küçük bir
  yardımcı (`mergen-helper`); yönetici izni yalnızca bu yardımcı için, isteğe bağlı.
- **Performans.** Görev Yöneticisi gibi canlı grafikler: CPU (çekirdek başına), bellek, diskler, ağ, her GPU motoru.
- **Görevler.** Süreç listesi (ağaç, gruplar, exe yolu, komut satırı, GPU), sonlandır / öncelik / benzeşim.
- **Cihaz.** Windows güç planı, güç modu, parlaklık. Clevo tabanlı dizüstülerde (Monster, Tulpar, Excalibur…)
  fan devri ve sıcaklıkları, Control Center'ın güç modu.

Hiçbir veri ağa gönderilmez. Sistemi değiştiren her işlem önce onay ister.

## Kaynaktan çalıştırma

```powershell
python -m pip install -r requirements.txt
python main.py
```

Derleme: `powershell -ExecutionPolicy Bypass -File packaging\build.ps1` (Python 3.14, .NET 10 SDK, Inno Setup 6).

## Lisans

GPL-3.0. Sensör yardımcısı LibreHardwareMonitorLib'i (MPL-2.0) kullanır.
