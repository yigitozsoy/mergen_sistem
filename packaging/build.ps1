<#
mergen — derleme betiği
  1) Bağımlılıkları kurar (isteğe bağlı)
  2) mergen-helper'ı (C#, .NET) tek dosya olarak yayımlar (helper\publish)
  3) PyInstaller ile build\dist\mergen\mergen.exe klasörünü üretir, yardımcıyı helper\ altına koyar, --selfcheck ile denetler
  4) Taşınabilir zip ve Inno Setup ile kurulum dosyası üretir (build\installer)

Kullanım (proje kökünden):
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-InstallDeps] [-SkipInstaller] [-SkipHelper] [-Python python]
#>
param(
    [switch]$InstallDeps,
    [switch]$SkipInstaller,
    [switch]$SkipHelper,
    [string]$Python = "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path $Python)) { $Python = "python" }

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

if ($InstallDeps) {
    Step "Bağımlılıklar kuruluyor"
    & $Python -m pip install -r requirements.txt pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "pip install başarısız" }
}

Step "Sürüm bilgisi üretiliyor"
$Version = (& $Python packaging\make_meta.py).Trim()
if ($LASTEXITCODE -ne 0) { throw "make_meta.py başarısız" }
Write-Host "Sürüm: $Version"

$HelperExe = Join-Path $Root "helper\publish\mergen-helper.exe"
if (-not $SkipHelper) {
    Step "mergen-helper (dotnet publish)"
    Push-Location helper
    dotnet publish -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true `
        -p:IncludeNativeLibrariesForSelfExtract=true -p:EnableCompressionInSingleFile=true -p:DebugType=none -o publish
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { throw "dotnet publish başarısız" }
}
if (-not (Test-Path $HelperExe)) { throw "helper\publish\mergen-helper.exe yok" }

Step "PyInstaller"
$Dist = Join-Path $Root "build\dist"
& $Python -m PyInstaller packaging\mergen.spec --noconfirm --clean --distpath $Dist --workpath (Join-Path $Root "build\work")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller başarısız" }
$App = Join-Path $Dist "mergen"

New-Item -ItemType Directory -Force (Join-Path $App "helper") | Out-Null
Copy-Item $HelperExe (Join-Path $App "helper\mergen-helper.exe") -Force
Copy-Item LICENSE (Join-Path $App "LICENSE.txt") -Force

Step "Paket denetimi (mergen.exe --selfcheck)"
$p = Start-Process (Join-Path $App "mergen.exe") -ArgumentList "--selfcheck" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "selfcheck başarısız (çıkış kodu $($p.ExitCode)); ayrıntı %LOCALAPPDATA%\mergen\error.log" }
Write-Host "tamam"

Step "Taşınabilir zip"
$Out = Join-Path $Root "build\installer"
New-Item -ItemType Directory -Force $Out | Out-Null
$Zip = Join-Path $Out "mergen-portable-$Version.zip"
if (Test-Path $Zip) { Remove-Item $Zip }
Compress-Archive -Path $App -DestinationPath $Zip -CompressionLevel Optimal
Write-Host $Zip

if (-not $SkipInstaller) {
    Step "Inno Setup ile kurulum dosyası"
    $Iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
    if (-not $Iscc) {
        foreach ($c in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                         "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
            if (Test-Path $c) { $Iscc = $c; break }
        }
    }
    if (-not $Iscc) {
        Write-Warning "Inno Setup 6 bulunamadı; kurulum dosyası atlandı. Kurmak için:  winget install JRSoftware.InnoSetup"
    } else {
        & $Iscc /Q packaging\installer.iss
        if ($LASTEXITCODE -ne 0) { throw "ISCC başarısız" }
    }
}

Step "Bitti"
Get-ChildItem $Out | Format-Table Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
