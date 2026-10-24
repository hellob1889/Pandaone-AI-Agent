; ============================================================
; Pandaone AI Agent Inno Setup 安装脚本（Phase 9: 级联右键菜单）
; ============================================================
;
; 用法：
;   1. 安装 Inno Setup 6 (https://jrsoftware.org/isinfo.php)
;   2. 编译: iscc installer\pandaone.iss  (由 build_pyinstaller.py 渲染生成)
;   3. 产物: installer\Output\PandaoneSetup-x.y.z-x64.exe
;
; 第一性原理：
;   - 单文件安装包，便于分发
;   - 自动加入 PATH，无需用户配置
;   - 右键菜单级联（4 个子动作：init / lock / unlock / status）
;   - 安装/卸载幂等（可重复运行）
;   - 检查 git 可用性，缺失时友好提示
;
; ============================================================

#define MyAppName "Pandaone"
#define MyAppVersion "0.7.2"
#define MyAppPublisher "Pandaone AI Agent Project"
#define MyAppURL "https://github.com/hellob1889/Pandaone-AI-Agent"
#define MyAppExeName "pandaone.exe"

[Setup]
; 基本信息
AppId={{A4F8B5C2-1D3E-4F2A-9B8C-1E5D7F9A3B6C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; 输出设置
OutputDir=Output
OutputBaseFilename=Pandaone-Setup-{#MyAppVersion}

; 压缩（最大压缩减少分发体积）
Compression=lzma2/ultra64
SolidCompression=yes

; 权限：默认免管理员（装到 %LOCALAPPDATA%\Pandaone）；用户可在安装向导切到管理员模式
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; 美化
WizardStyle=modern
SetupIconFile=assets\pandaone.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; 版本信息
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=AI Agent Code Audit Gateway

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Types]
Name: "full"; Description: "完整安装（含右键菜单）"; Flags: iscustom
Name: "minimal"; Description: "仅命令行（不创建右键菜单）"

[Components]
Name: "main"; Description: "Pandaone 主程序"; Types: full minimal; Flags: fixed
Name: "contextmenu"; Description: "Windows 右键菜单（级联）"; Types: full

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add {#MyAppName} to system PATH"; GroupDescription: "System integration:"; Flags: checkedonce
Name: "installmcp"; Description: "Register Pandaone MCP server into detected IDE configs (Claude Desktop / Cursor / Trae)"; GroupDescription: "Integrations:"; Flags: unchecked

[Files]
; 主程序（来自 PyInstaller 打包）
Source: "..\dist\pandaone\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\templates"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\{#MyAppName} CLI"; Filename: "{cmd}"; Parameters: "/K cd /d ""{app}"" && pandaone --help"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; ============================================================
; 右键菜单（Pandaone -> Init / Lock / Status / Unlock）
; HKCU 用户级，无需管理员。三个位置都注册：
;   1) 任意文件  HKCU\Software\Classes\*\shell\Pandaone
;   2) 文件夹    HKCU\Software\Classes\Directory\shell\Pandaone
;   3) 空白处    HKCU\Software\Classes\Directory\Background\shell\Pandaone
;
; 结构（与 src/pandaone/cli_chunks/part_006.py 一致，Win11 实测可见）：
;   <base>                          MUIVerb / Icon / ExtendedSubCommandsKey
;   <base>\Shell\<verb>            显示名 + Icon
;   <base>\Shell\<verb>\command   实际命令
;
; 为什么不用 SubCommands：它依赖 HKLM\...\Explorer\CommandStore（需管理员），
; HKCU 注册不进去 -> Explorer 静默隐藏整个级联菜单（实测 0 个动词）。
; ExtendedSubCommandsKey 指向 HKCU 内相对路径，普通用户即可用。
; ============================================================
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Pandaone 审计工具 / Audit Tools"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone"; ValueType: string; ValueName: "ExtendedSubCommandsKey"; ValueData: "Pandaone\Shell"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone\Shell\Init"; ValueType: string; ValueName: ""; ValueData: "Pandaone Init (init)"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone\Shell\Init"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone\Shell\Init\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --silent init --root ""%V"""; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone\Shell\Lock"; ValueType: string; ValueName: ""; ValueData: "Pandaone Lock (lock)"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone\Shell\Lock"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone\Shell\Lock\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --silent lock --root ""%V"""; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone\Shell\Status"; ValueType: string; ValueName: ""; ValueData: "Pandaone Status (status)"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone\Shell\Status"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone\Shell\Status\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --silent status --root ""%V"""; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone\Shell\Unlock"; ValueType: string; ValueName: ""; ValueData: "Pandaone Unlock (unlock)"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone\Shell\Unlock"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\Pandaone\Shell\Unlock\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --silent unlock --root ""%V"""; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Pandaone 审计工具 / Audit Tools"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone"; ValueType: string; ValueName: "ExtendedSubCommandsKey"; ValueData: "Pandaone\Shell"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone\Shell\Init"; ValueType: string; ValueName: ""; ValueData: "Pandaone Init (init)"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone\Shell\Init"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone\Shell\Init\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --silent init --root ""%V"""; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone\Shell\Lock"; ValueType: string; ValueName: ""; ValueData: "Pandaone Lock (lock)"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone\Shell\Lock"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone\Shell\Lock\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --silent lock --root ""%V"""; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone\Shell\Status"; ValueType: string; ValueName: ""; ValueData: "Pandaone Status (status)"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone\Shell\Status"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone\Shell\Status\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --silent status --root ""%V"""; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone\Shell\Unlock"; ValueType: string; ValueName: ""; ValueData: "Pandaone Unlock (unlock)"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone\Shell\Unlock"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Pandaone\Shell\Unlock\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --silent unlock --root ""%V"""; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Pandaone 审计工具 / Audit Tools"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone"; ValueType: string; ValueName: "ExtendedSubCommandsKey"; ValueData: "Pandaone\Shell"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone\Shell\Init"; ValueType: string; ValueName: ""; ValueData: "Pandaone Init (init)"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone\Shell\Init"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone\Shell\Init\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --silent init --root ""%V"""; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone\Shell\Lock"; ValueType: string; ValueName: ""; ValueData: "Pandaone Lock (lock)"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone\Shell\Lock"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone\Shell\Lock\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --silent lock --root ""%V"""; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone\Shell\Status"; ValueType: string; ValueName: ""; ValueData: "Pandaone Status (status)"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone\Shell\Status"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone\Shell\Status\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --silent status --root ""%V"""; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone\Shell\Unlock"; ValueType: string; ValueName: ""; ValueData: "Pandaone Unlock (unlock)"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone\Shell\Unlock"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Components: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Pandaone\Shell\Unlock\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --silent unlock --root ""%V"""; Flags: uninsdeletekey; Components: contextmenu

; 清理旧版遗留结构（兼容之前版本）
Root: HKCU; Subkey: "Software\Classes\Directory\shell\PandaoneInit"; Flags: deletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\PandaoneInit"; Flags: deletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\PandaoneWatch"; Flags: deletekey
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\PandaoneInit"; Flags: deletekey

; PATH（用户级，不需要管理员）
; v0.7.27.0: **前置** {app}，不再追加到末尾。
;   旧写法 `{olddata};{app}` 会让 pip 版 pandaone（Python\Scripts\，通常更靠前）
;   继续抢占 `pandaone` 命令 -> 装完 exe 版却像"没生效"。
;   {olddata} 保留 -> 卸载时 Inno 能把 Path 恢复成安装前的值。
;   去重 + 幂等由 [Code] 的 CurStepChanged(ssPostInstall) 兜底。
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{app};{olddata}"; Tasks: addtopath; Check: NeedsAddPath('{app}')

[Run]
; 安装后首次运行探测
Filename: "{app}\{#MyAppExeName}"; Parameters: "install-git --probe-only"; Description: "Probe git availability"; Flags: runmaximized nowait postinstall skipifsilent runascurrentuser
; v0.7.28.0: 清理 PATH 里抢占命令的旧版 pandaone。
;   背景（真机实测）：Windows PATH = 机器级 + 用户级（机器级在前），
;   pip 版 pandaone 在 Python\Scripts\（机器级）时，用户级前置**够不着**它，
;   装完 exe 版敲 pandaone 仍是旧版 —— 只能把旧的改名备份。
;   注意：**不能**加 skipifsilent —— 静默安装正是最需要清理的场景。
Filename: "{app}\{#MyAppExeName}"; Parameters: "doctor --clean-conflicts"; Description: "Rename older pandaone binaries shadowing the command"; Flags: runmaximized nowait postinstall runascurrentuser
Filename: "{app}\{#MyAppExeName}"; Parameters: "install-mcp --client auto --absolute-command"; Description: "Register Pandaone MCP server in detected IDE configs"; Flags: runmaximized nowait postinstall skipifsilent runascurrentuser; Tasks: installmcp

[UninstallRun]
; 卸载时清理用户配置（仅 fingerprint）
Filename: "{cmd}"; Parameters: "/C for /f ""delims="" %%i in ('dir /b /s /ah ""{userdocs}\Pandaone\.pandaone_fp.txt"" 2^>nul') do del /f /q ""%%i"""; Flags: runmaximized

[UninstallDelete]
; 清理模板和日志
Type: filesandordirs; Name: "{app}\templates"
Type: filesandordirs; Name: "{app}\*.log"

[Code]
// ============================================================
// Inno Setup Pascal Script
// ============================================================

function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;

// v0.7.27.0: 广播环境变量变更（WM_SETTINGCHANGE / "Environment"）
//   目的：装完后**已经打开**的终端也能立刻拿到新 PATH，不用重开。
//   参考 cmd_setup.py 的 _broadcast_env_change()（同一条 Win32 消息）。
//   注意：Inno Pascal Script 只认基础整数类型（LongWord/LongInt）和 String，
//   WPARAM/LPARAM/LRESULT/Cardinal/PChar 在 Inno 6 里都未定义，会报 "Unknown type"。
//   Inno 的 String 本身就是 null-terminated AnsiString，可以直接当 PChar 传。
function SendMessageTimeout(hWnd: LongWord; Msg: LongWord; wParam: LongWord;
  lParam: String; fuFlags: LongWord; uTimeout: LongWord;
  var lpdwResult: LongInt): LongInt;
  external 'SendMessageTimeoutA@user32.dll stdcall';

procedure BroadcastEnvChange;
var
  Dummy: LongInt;
begin
  // HWND_BROADCAST = $FFFF，SMTO_ABORTIFHUNG = 2
  SendMessageTimeout(LongWord($FFFF), $001A, 0, 'Environment', 2, 5000, Dummy);
end;

// 从用户 PATH 里移除 {app}（卸载时用）
procedure RemoveAppFromPath;
var
  OrigPath, NewPath, Item, AppPath: string;
  I, J: Integer;
  Changed: Boolean;
begin
  AppPath := ExpandConstant('{app}');
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
    Exit;

  NewPath := '';
  Changed := False;
  I := 1;
  while I <= Length(OrigPath) do
  begin
    J := Pos(';', Copy(OrigPath, I, MaxInt));
    if J = 0 then
    begin
      Item := Copy(OrigPath, I, MaxInt);
      I := Length(OrigPath) + 1;
    end
    else
    begin
      Item := Copy(OrigPath, I, J - 1);
      I := I + J;
    end;
    Item := Trim(Item);
    if Item = '' then
      Continue;
    if CompareText(Item, AppPath) = 0 then
    begin
      Changed := True;
      Continue;
    end;
    if NewPath = '' then
      NewPath := Item
    else
      NewPath := NewPath + ';' + Item;
  end;

  if not Changed then
    Exit;

  RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', NewPath);
  BroadcastEnvChange;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // 卸载时把 {app} 从用户 PATH 摘掉 —— 否则目录被删后 PATH 里留一行坏路径，
  // 用户敲 `pandaone` 会得到"不是内部或外部命令"。
  if CurUninstallStep = usUninstall then
    RemoveAppFromPath;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  OrigPath, NewPath, Item, AppPath: string;
  I, J: Integer;
begin
  if (CurStep <> ssPostInstall) or (not WizardIsTaskSelected('addtopath')) then
    Exit;

  // v0.7.27.0: PATH **前置**而非追加。
  //   背景：pip 版 pandaone 装在 Python\Scripts\，通常排在用户 PATH 靠前。
  //   旧写法 `{olddata};{app}` 追加到末尾 —— 装完 exe 版后 `pandaone` 仍然
  //   命中旧 pip 版，用户体感就是"装了新版没生效"。
  //   同时做去重：{app} 已存在时先摘掉再前置，避免出现两行。
  AppPath := ExpandConstant('{app}');
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
    OrigPath := '';

  NewPath := '';
  I := 1;
  while I <= Length(OrigPath) do
  begin
    J := Pos(';', Copy(OrigPath, I, MaxInt));
    if J = 0 then
    begin
      Item := Copy(OrigPath, I, MaxInt);
      I := Length(OrigPath) + 1;
    end
    else
    begin
      Item := Copy(OrigPath, I, J - 1);
      I := I + J;
    end;
    Item := Trim(Item);
    if (Item = '') or (CompareText(Item, AppPath) = 0) then
      Continue;
    if NewPath = '' then
      NewPath := Item
    else
      NewPath := NewPath + ';' + Item;
  end;

  if NewPath = '' then
    NewPath := AppPath
  else
    NewPath := AppPath + ';' + NewPath;

  RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', NewPath);
  BroadcastEnvChange;
end;

function InitializeSetup: boolean;
begin
  // 检查 git 是否可用
  Result := True;
end;