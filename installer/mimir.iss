; MIMIR Windows installer. Build: iscc /DAppVersion=X.Y.Z installer\mimir.iss
; Expects the PyInstaller onedir output in dist\MIMIR (relative to the repo root).

#ifndef AppVersion
  #error Pass /DAppVersion=X.Y.Z (CI takes it from the git tag)
#endif

[Setup]
; Never change AppId: it is how a new version finds and upgrades the old install.
AppId={{6F2B8C1E-4D7A-4E9B-9C3F-2A1D5E8B7C40}
AppName=MIMIR
AppVersion={#AppVersion}
AppPublisher=MIMIR
AppPublisherURL=https://github.com/KethanSaiV/mimir_web
DefaultDirName={autopf}\MIMIR
DefaultGroupName=MIMIR
DisableProgramGroupPage=yes
; Per-user install: no admin prompt, goes to %LOCALAPPDATA%\Programs\MIMIR.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=mimir.ico
UninstallDisplayIcon={app}\MIMIR.exe
OutputDir=..\dist
OutputBaseFilename=MIMIR-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\MIMIR\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Drop files from the previous version so stale modules can't linger after an upgrade.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\MIMIR"; Filename: "{app}\MIMIR.exe"
Name: "{autodesktop}\MIMIR"; Filename: "{app}\MIMIR.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MIMIR.exe"; Description: "{cm:LaunchProgram,MIMIR}"; Flags: nowait postinstall skipifsilent
