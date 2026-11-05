; Inno Setup script for the desktop app. CI: ISCC /DAppVersion=x.y.z desktop\installer.iss
; Expects dist\LabERP (PyInstaller) and dist\MicrosoftEdgeWebview2Setup.exe (Evergreen bootstrapper).
#ifndef AppVersion
  #define AppVersion "1.5.11"
#endif

[Setup]
AppId={{8C5E2B1A-6F3D-4B7E-9A21-5D4C3B2A1F09}
AppName=LAB ERP
AppVersion={#AppVersion}
AppVerName=LAB ERP {#AppVersion}
; Updates keep the folder of the first install (AppId); new installs use LabERP
DefaultDirName={autopf}\LabERP
DefaultGroupName=LAB ERP
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=LabERP-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\LabERP.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\LabERP\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2

[InstallDelete]
; Old bundle files (renamed or removed modules); user data lives elsewhere
Type: filesandordirs; Name: "{app}\_internal"
; Before 1.4.1 the app was "Parça Takip ERP" (ParcaTakipERP.exe)
Type: files; Name: "{app}\ParcaTakipERP.exe"
Type: files; Name: "{group}\Parça Takip ERP.lnk"
Type: files; Name: "{autodesktop}\Parça Takip ERP.lnk"

[Icons]
Name: "{group}\LAB ERP"; Filename: "{app}\LabERP.exe"
Name: "{autodesktop}\LAB ERP"; Filename: "{app}\LabERP.exe"; Tasks: desktopicon

[Run]
; Server mode: let other computers and phones reach the app (only possible when installed as admin;
; otherwise Windows asks once when the server starts)
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Parca Takip ERP"""; Flags: runhidden waituntilterminated; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""LAB ERP"""; Flags: runhidden waituntilterminated; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""LAB ERP"" dir=in action=allow program=""{app}\LabERP.exe"" enable=yes profile=private,domain"; StatusMsg: "Güvenlik duvarı izni ekleniyor..."; Flags: runhidden waituntilterminated; Check: IsAdminInstallMode
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Microsoft Edge WebView2 kuruluyor..."; Check: NeedsWebView2; Flags: waituntilterminated
; Also runs after a silent update (no skipifsilent), so the app comes back by itself
Filename: "{app}\LabERP.exe"; Description: "{cm:LaunchProgram,LAB ERP}"; Flags: nowait postinstall

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""LAB ERP"""; Flags: runhidden; Check: IsAdminInstallMode; RunOnceId: "DelFwRule"

[Code]
const
  WV2 = '\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function HasWebView2(Root: Integer; Key: String): Boolean;
var
  V: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', V) and (V <> '') and (V <> '0.0.0.0');
end;

function NeedsWebView2: Boolean;
begin
  Result := not (HasWebView2(HKLM, 'SOFTWARE\WOW6432Node' + WV2) or HasWebView2(HKLM, 'SOFTWARE' + WV2) or
                 HasWebView2(HKCU, 'Software' + WV2));
end;
