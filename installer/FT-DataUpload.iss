#ifndef AppVersion
  #error AppVersion must be supplied by build_installer.py
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by build_installer.py
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by build_installer.py
#endif
#ifndef SetupIcon
  #error SetupIcon must be supplied by build_installer.py
#endif

[Setup]
AppId={{B85B27CF-32C2-4F80-A187-27B0FA7E0A15}
AppName=泛天贸易中心桌面助手
AppVersion={#AppVersion}
AppVerName=泛天贸易中心桌面助手 {#AppVersion}
AppPublisher=泛天贸易中心
DefaultDirName={autopf}\FT-DataUpload
DefaultGroupName=泛天贸易中心桌面助手
DisableDirPage=no
DisableProgramGroupPage=yes
; Installation is per-user so uninstalling can safely address that same user's
; LocalAppData. FT-DataUpload.exe independently requests elevation at launch.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=FT-DataUpload-v{#AppVersion}-setup
SetupIconFile={#SetupIcon}
UninstallDisplayIcon={app}\FT-DataUpload.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=FT-DataUpload.exe,FT-Capture.exe
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\泛天贸易中心桌面助手"; Filename: "{app}\FT-DataUpload.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\泛天贸易中心桌面助手"; Filename: "{app}\FT-DataUpload.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\FT-DataUpload.exe"; Description: "运行泛天贸易中心桌面助手"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataPath: String;
begin
  if CurUninstallStep <> usUninstall then
    Exit;

  UserDataPath := ExpandConstant('{localappdata}\FantianTradingHub\DesktopAssistant');
  if (ExtractFileName(UserDataPath) = 'DesktopAssistant') and
     (ExtractFileName(ExtractFileDir(UserDataPath)) = 'FantianTradingHub') and
     DirExists(UserDataPath) and
     (SuppressibleMsgBox(
       '是否同时删除桌面助手的本地配置、历史记录和截图？' + #13#10 +
       '默认保留；只有确认不再需要这些数据时才选择“是”。',
       mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES) then
  begin
    { DelTree removes a reparse-point directory itself without traversing its target. }
    if not DelTree(UserDataPath, True, True, True) then
      SuppressibleMsgBox('部分本地数据无法删除，请稍后手动清理：' + #13#10 + UserDataPath,
        mbError, MB_OK, IDOK);
  end;
end;
