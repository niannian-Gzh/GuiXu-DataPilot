; 归墟 Windows 安装包（Inno Setup 6）
;
; 设计取舍：
;   - 默认装到 %LOCALAPPDATA%\Programs\GuiXu，不弹 UAC；
;   - 用户数据在 %LOCALAPPDATA%\GuiXu，和安装目录分开，卸载不删；
;   - 只做 64 位；WebView2 / Edge 用系统的，不随包。

#define MyAppName "归墟"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "GuiXu"
#define MyAppExeName "GuiXu.exe"

[Setup]
AppId={{8cecc5d0-0696-4360-a7e1-1ea313624d75}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\GuiXu
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=GuiXu-Setup-{#MyAppVersion}
SetupIconFile=..\archive\brand\guixu.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
; 品牌化：暗色向导 + 归墟左侧大图/右上标记。Inno 6.7 的 dark 模式
; 会把按钮、输入框等一起切到暗色，不是只换背景。
WizardStyle=modern dark
WizardBackColor=#0c0c0b
WizardBackColorDynamicDark=#0c0c0b
WizardImageFile=..\archive\brand\installer-banner.png
WizardSmallImageFile=..\archive\brand\installer-small.png
WizardImageBackColor=#0c0c0b
DisableWelcomePage=no
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
UsePreviousAppDir=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "{#SourcePath}\ChineseSimplified.isl"

[Messages]
WelcomeLabel1=欢迎安装 归墟
WelcomeLabel2=归墟是一个本地数据处理 Agent。%n%n安装不会覆盖你的数据；用户数据保存在本机的 GuiXu 数据目录，卸载时会保留。%n%n建议继续前关闭其他应用程序。
FinishedHeadingLabel=归墟 安装完成
FinishedLabel=归墟已安装到你的计算机。%n%n用户数据保存在本机的 GuiXu 数据目录，卸载不会删除它。

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式:"

[Files]
Source: "..\dist\GuiXu\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动{#MyAppName}"; Flags: nowait postinstall skipifsilent
