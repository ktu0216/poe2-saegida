; POE2 새기다 설치 프로그램 (Inno Setup 6)
; build_release.bat 이 ISCC /DMyAppVersion=x.y.z 로 컴파일한다. 먼저 build.bat 으로 dist\poe2-saegida 를 만든다.
;
; 사용자별 설치: 관리자 권한 없이 %LOCALAPPDATA%\Programs\poe2-saegida 에 설치 (guides 데이터도 고칠 수 있게)
; 제거해도 설정·진행 기록(%APPDATA%\poe2-saegida)은 남긴다 → 다시 설치하면 이어서 쓴다

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "POE2 Saegida"
#define MyAppExe "poe2-saegida.exe"

[Setup]
AppId={{6E2B6F4A-3C1D-4E8B-9A57-2F0D8C1B7E64}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=ktu0216
AppPublisherURL=https://github.com/ktu0216/poe2-saegida
AppSupportURL=https://github.com/ktu0216/poe2-saegida/issues
DefaultDirName={localappdata}\Programs\poe2-saegida
DefaultGroupName=POE2 Saegida
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=poe2-saegida-setup-{#MyAppVersion}
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 실행 중이면 닫고 설치 (덮어쓰기 업데이트)
CloseApplications=force
RestartApplications=no
LicenseFile=..\LICENSE
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
korean.StartupTask=Windows 시작 시 자동 실행
english.StartupTask=Start with Windows
korean.LaunchNow=지금 실행
english.LaunchNow=Launch now

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "{cm:StartupTask}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\poe2-saegida\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; 이전 버전 런타임 파일 정리 (데이터 파일 이름이 바뀌어도 옛 파일이 남지 않게)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchNow}"; Flags: nowait postinstall skipifsilent
