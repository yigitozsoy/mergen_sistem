; mergen — Inno Setup 6 kurulum betiği (tamga ailesi)
; Doğrudan değil, packaging\build.ps1 üzerinden derleyin (önce PyInstaller çıktısı + helper\mergen-helper.exe gerekir).
; Yönetici izni istemez: varsayılan olarak %LOCALAPPDATA%\Programs\mergen klasörüne kurulur.
; Kullanıcı verileri (%LOCALAPPDATA%\mergen: tercihler, önbellek, günlükler) kaldırmada SİLİNMEZ.
; Not: kullanıcı "Her seferinde sorma" ile yönetici görevi oluşturduysa (mergen-helper zamanlanmış görevi +
; %ProgramFiles%\mergen-helper kopyası) onu mergen içinden kaldırması gerekir (Sensörler › Görünüm); kurulum yönetici
; izni istemediği için bunlara dokunamaz.

#include "version.iss"
#define AppName "mergen"
#define AppExe "mergen.exe"
#define AppUserModelID "tamga.mergen"

[Setup]
; AppId DEĞİŞTİRME (CLAUDE.md)
AppId={{98384CE8-F966-4B98-BEB8-3AFB0064834E}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=tamga
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\build\installer
OutputBaseFilename=mergen-setup-{#AppVersion}
SetupIconFile=..\mergen\assets\logo.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
LicenseFile=..\LICENSE
VersionInfoDescription={#AppName} kurulumu
VersionInfoProductName={#AppName}
VersionInfoVersion={#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
turkish.Desc=Sistem bilgisi, donanım izleme ve görev yöneticisi
english.Desc=System information, hardware monitor and task manager
turkish.LaunchApp=mergen'i aç
english.LaunchApp=Open mergen

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\build\dist\mergen\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; güncellemede eski sürümden kalan Python / Qt dosyaları karışmasın
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "{cm:Desc}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "{cm:Desc}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExe}"; ValueType: string; ValueData: "{app}\{#AppExe}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[Code]
// /NOQUIT parametresi: test kurulumu çalışan mergen'e dokunmasın
function ShouldQuitRunning(): Boolean;
begin
  Result := ExpandConstant('{param:NOQUIT|0}') = '0';
end;

// Çalışan mergen'i ("mergen.exe --quit") ve yardımcısını kapat; 2 sn'de kapanmazsa zorla.
// Yükseltilmiş yardımcı (zamanlanmış görev) kullanıcı tarafından kapatılamaz; ama son istemci gidince 15 sn içinde
// kendiliğinden kapanır ve görev %ProgramFiles%'taki kopyayı çalıştırdığı için kurulum dosyalarını kilitlemez.
procedure QuitRunning();
var
  Code: Integer;
  Exe: String;
begin
  if not ShouldQuitRunning() then Exit;
  Exe := ExpandConstant('{app}\{#AppExe}');
  if FileExists(Exe) then
  begin
    Exec(Exe, '--quit', '', SW_HIDE, ewNoWait, Code);
    Sleep(2000);
  end;
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM {#AppExe} /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM mergen-helper.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  QuitRunning();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    QuitRunning();
end;
