; 归墟 Windows 安装包（Inno Setup 6）
;
; 设计取舍：
;   - 默认装到 %LOCALAPPDATA%\Programs\GuiXu，不弹 UAC；
;   - 用户数据在 %LOCALAPPDATA%\GuiXu，和安装目录分开，卸载不删；
;   - 只做 64 位；WebView2 / Edge 用系统的，不随包；
;   - 窗口外壳、标题栏、左栏、三页内容全部自绘，安装引擎仍由 Inno 负责。

#define MyAppName "归墟"
#define MyAppVersion "1.3.0"
#define MyAppPublisher "GuiXu"
#define MyAppExeName "GuiXu.exe"

[Setup]
AppId={{8cecc5d0-0696-4360-a7e1-1ea313624d75}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\GuiXu
DefaultGroupName={#MyAppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=GuiXu-Setup-{#MyAppVersion}
SetupIconFile=..\archive\brand\guixu.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern dark
WizardBackColor=#0c0c0b
WizardBackColorDynamicDark=#0c0c0b
WizardImageBackColor=#0c0c0b
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
UsePreviousAppDir=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "{#SourcePath}\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式:"

[Files]
Source: "..\dist\GuiXu\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

Source: "installer-brand-bg.bmp"; Flags: dontcopy
Source: "installer-logo.bmp"; Flags: dontcopy
Source: "installer-check-off.bmp"; Flags: dontcopy
Source: "installer-check-on.bmp"; Flags: dontcopy
Source: "installer-folder.bmp"; Flags: dontcopy
Source: "installer-path-bg.bmp"; Flags: dontcopy
Source: "installer-btn-primary.bmp"; Flags: dontcopy
Source: "installer-btn-ghost.bmp"; Flags: dontcopy
Source: "installer-btn-change.bmp"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动{#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
const
  WM_SYSCOMMAND = $0112;
  SC_DRAGMOVE = $F012;
  GCL_STYLE = -26;
  CS_DROPSHADOW = $00020000;
  DWMWA_WINDOW_CORNER_PREFERENCE = 33;
  DWMWCP_ROUND = 2;
  SM_CXSCREEN = 0;
  SM_CYSCREEN = 1;
  SW_MINIMIZE = 6;

  { TColor 是 BGR：$00BBGGRR }
  COL_SURFACE = $0C0C0B;
  COL_BRAND = $17191A;
  COL_TITLE = $131516;
  COL_INK = $EEF1F2;
  COL_MUTED = $7F8485;
  COL_DIM = $65696A;
  COL_FAINT = $484C4D;
  COL_BLUE = $FF7D3D;
  COL_LIGHT = $CBCECF;
  COL_HAIR = $2F3233;
  COL_HAIR_SOFT = $232526;
  COL_NOTE = $0E0F0F;
  COL_META = $585C5D;
  COL_TITLE_HAIR = $252728;

function ReleaseCapture: Boolean; external 'ReleaseCapture@user32.dll stdcall';
function SendMessage(hWnd: HWND; Msg: UINT; wParam: Longint; lParam: Longint): Longint;
  external 'SendMessageW@user32.dll stdcall';
function GetClassLong(hWnd: HWND; nIndex: Integer): DWORD;
  external 'GetClassLongW@user32.dll stdcall';
function SetClassLong(hWnd: HWND; nIndex: Integer; dwNewLong: DWORD): DWORD;
  external 'SetClassLongW@user32.dll stdcall';
function DwmSetWindowAttribute(hwnd: HWND; dwAttribute: DWORD; var pvAttribute: Integer;
  cbAttribute: DWORD): Longint; external 'DwmSetWindowAttribute@dwmapi.dll stdcall';
function CreateRoundRectRgn(x1, y1, x2, y2, w, h: Integer): THandle;
  external 'CreateRoundRectRgn@gdi32.dll stdcall';
function SetWindowRgn(hWnd: HWND; hRgn: THandle; bRedraw: BOOL): Integer;
  external 'SetWindowRgn@user32.dll stdcall';
function GetSystemMetrics(nIndex: Integer): Integer;
  external 'GetSystemMetrics@user32.dll stdcall';
function ShowWindow(hWnd: HWND; nCmdShow: Integer): BOOL;
  external 'ShowWindow@user32.dll stdcall';

var
  Page1: TWizardPage;

  TitleBar, TitleHair, BrandPanel, BrandRule, ContentPanel: TPanel;
  TitleText, WinMin, WinClose, DragZone: TLabel;
  BrandName, BrandSub, BrandVer, BrandTagA, BrandTagB, BrandTagC, BrandFoot: TLabel;

  Page1Panel, InstallPanel, FinishPanel: TPanel;

  Kicker, Headline, Lead: TLabel;
  PathLabel, PathText: TLabel;
  FolderIcon, PathBg: TBitmapImage;
  ChangeBg: TBitmapImage;
  ChangeText: TLabel;

  Check1Icon, Check2Icon: TBitmapImage;
  Check1Text, Check2Text: TLabel;
  Check1On, Check2On: Boolean;

  NoteOuter, NoteInner, NoteBar: TPanel;
  NoteBold, NoteBody, NoteBody2: TLabel;

  ActionPanel: TPanel;
  MetaText: TLabel;
  GhostBg: TBitmapImage;
  GhostText: TLabel;
  PrimaryBg: TBitmapImage;
  PrimaryText: TLabel;

  InstallKicker, InstallHeadline, InstallLead: TLabel;
  ProgressTrack, ProgressFill: TPanel;
  ProgressText, ProgressFile: TLabel;

  FinishKicker, FinishHeadline, FinishLead: TLabel;
  FinishNote: TLabel;

  ChromePref: Integer;

{ ---------- 控件工厂 ---------- }

function MakePanel(Parent: TWinControl; L, T, W, H: Integer; Color: TColor): TPanel;
begin
  Result := TPanel.Create(WizardForm);
  Result.Parent := Parent;
  Result.BevelOuter := bvNone;
  Result.Color := Color;
  Result.ParentBackground := False;
  Result.StyleElements := [];
  Result.SetBounds(ScaleX(L), ScaleY(T), ScaleX(W), ScaleY(H));
end;

function MakeLabel(Parent: TWinControl; Caption: String; L, T, W, H, Size: Integer;
  Color: TColor; Bold: Boolean): TLabel;
begin
  Result := TLabel.Create(WizardForm);
  Result.Parent := Parent;
  Result.Caption := Caption;
  Result.Transparent := True;
  Result.StyleElements := [];
  Result.AutoSize := False;
  Result.WordWrap := False;
  Result.Font.Name := 'Microsoft YaHei';
  Result.Font.Size := Size;
  Result.Font.Color := Color;
  if Bold then
    Result.Font.Style := [fsBold];
  Result.SetBounds(ScaleX(L), ScaleY(T), ScaleX(W), ScaleY(H));
end;

function MakeMono(Parent: TWinControl; Caption: String; L, T, W, H, Size: Integer;
  Color: TColor): TLabel;
begin
  Result := MakeLabel(Parent, Caption, L, T, W, H, Size, Color, False);
  Result.Font.Name := 'Consolas';
end;

function MakeImage(Parent: TWinControl; FileName: String; L, T, W, H: Integer): TBitmapImage;
begin
  ExtractTemporaryFile(FileName);
  Result := TBitmapImage.Create(WizardForm);
  Result.Parent := Parent;
  Result.Bitmap.LoadFromFile(ExpandConstant('{tmp}\') + FileName);
  Result.Stretch := True;
  Result.SetBounds(ScaleX(L), ScaleY(T), ScaleX(W), ScaleY(H));
end;

{ ---------- 窗口外壳 ---------- }

procedure TitleMouseDown(Sender: TObject; Button: TMouseButton; Shift: TShiftState;
  X, Y: Integer);
begin
  if Button = mbLeft then
  begin
    ReleaseCapture;
    SendMessage(WizardForm.Handle, WM_SYSCOMMAND, SC_DRAGMOVE, 0);
  end;
end;

procedure MinClick(Sender: TObject);
begin
  ShowWindow(WizardForm.Handle, SW_MINIMIZE);
end;

procedure CloseClick(Sender: TObject);
begin
  WizardForm.CancelButton.OnClick(WizardForm.CancelButton);
end;

procedure ApplyChrome;
var
  Version: TWindowsVersion;
  Rgn: THandle;
begin
  { 无边框窗口默认没有投影，挂一个 drop shadow }
  SetClassLong(WizardForm.Handle, GCL_STYLE,
    GetClassLong(WizardForm.Handle, GCL_STYLE) or CS_DROPSHADOW);

  GetWindowsVersionEx(Version);
  if Version.Build >= 22000 then
  begin
    ChromePref := DWMWCP_ROUND;
    DwmSetWindowAttribute(WizardForm.Handle, DWMWA_WINDOW_CORNER_PREFERENCE,
      ChromePref, SizeOf(ChromePref));
  end
  else
  begin
    { Win10 没有 DWM 圆角，用窗口区域裁一个 }
    Rgn := CreateRoundRectRgn(0, 0, WizardForm.Width + 1, WizardForm.Height + 1,
      ScaleX(20), ScaleY(20));
    SetWindowRgn(WizardForm.Handle, Rgn, True);
  end;
end;

procedure BuildTitleBar;
begin
  TitleBar := MakePanel(WizardForm, 0, 0, 780, 38, COL_TITLE);

  MakeImage(TitleBar, 'installer-logo.bmp', 14, 11, 16, 16);

  TitleText := MakeLabel(TitleBar, '归墟 · 安装程序', 36, 0, 300, 38, 8, COL_MUTED, False);
  TitleText.Layout := tlCenter;

  { TPanel 没有鼠标事件；用透明 TLabel 覆盖标题栏做拖动区 }
  DragZone := MakeLabel(TitleBar, '', 0, 0, 700, 38, 8, COL_TITLE, False);
  DragZone.OnMouseDown := @TitleMouseDown;
  DragZone.BringToFront;

  WinMin := MakeLabel(TitleBar, '—', 708, 7, 32, 24, 9, COL_MUTED, False);
  WinMin.Alignment := taCenter;
  WinMin.Layout := tlCenter;
  WinMin.Cursor := crHand;
  WinMin.OnClick := @MinClick;

  WinClose := MakeLabel(TitleBar, '×', 744, 7, 32, 24, 9, COL_LIGHT, False);
  WinClose.Alignment := taCenter;
  WinClose.Layout := tlCenter;
  WinClose.Cursor := crHand;
  WinClose.OnClick := @CloseClick;

  TitleHair := MakePanel(TitleBar, 0, 37, 780, 1, COL_TITLE_HAIR);
end;

procedure BuildBrand;
begin
  BrandPanel := MakePanel(WizardForm, 0, 38, 242, 482, COL_BRAND);
  MakeImage(BrandPanel, 'installer-brand-bg.bmp', 0, 0, 242, 482);

  BrandName := MakeLabel(BrandPanel, '归墟', 24, 114, 180, 38, 24, COL_INK, True);

  BrandSub := MakeLabel(BrandPanel, '数据处理 Agent', 24, 154, 180, 16, 8, COL_MUTED, False);

  BrandVer := MakeMono(BrandPanel, 'VERSION {#MyAppVersion} · WIN64', 24, 189, 190, 14, 7, COL_DIM);

  BrandRule := MakePanel(BrandPanel, 24, 219, 194, 1, COL_HAIR);

  BrandTagA := MakeMono(BrandPanel, 'LOCAL', 24, 238, 180, 14, 7, COL_DIM);
  BrandTagB := MakeMono(BrandPanel, 'DATA', 24, 256, 180, 14, 7, COL_DIM);
  BrandTagC := MakeMono(BrandPanel, 'WORKBENCH', 24, 274, 180, 14, 7, COL_DIM);

  BrandFoot := MakeMono(BrandPanel, 'GUIXU · INSTALLER', 24, 448, 180, 14, 7, COL_FAINT);
end;

{ ---------- 第一页 ---------- }

procedure ToggleCheck1(Sender: TObject);
begin
  Check1On := not Check1On;
  if Check1On then
    Check1Icon.Bitmap.LoadFromFile(ExpandConstant('{tmp}\installer-check-on.bmp'))
  else
    Check1Icon.Bitmap.LoadFromFile(ExpandConstant('{tmp}\installer-check-off.bmp'));
  if Assigned(WizardForm.TasksList) and (WizardForm.TasksList.Items.Count > 0) then
    WizardForm.TasksList.Checked[0] := Check1On;
end;

procedure ToggleCheck2(Sender: TObject);
begin
  Check2On := not Check2On;
  if Check2On then
    Check2Icon.Bitmap.LoadFromFile(ExpandConstant('{tmp}\installer-check-on.bmp'))
  else
    Check2Icon.Bitmap.LoadFromFile(ExpandConstant('{tmp}\installer-check-off.bmp'));
end;

procedure ChangeClick(Sender: TObject);
var
  Dir: String;
begin
  Dir := WizardForm.DirEdit.Text;
  if BrowseForFolder('选择安装目录', Dir, True) then
  begin
    WizardForm.DirEdit.Text := Dir;
    PathText.Caption := Dir;
  end;
end;

procedure PrimaryClick(Sender: TObject);
begin
  { 标准按钮被隐藏，但导航空壳仍然负责推进向导 }
  WizardForm.NextButton.OnClick(WizardForm.NextButton);
end;

procedure CancelClick(Sender: TObject);
begin
  WizardForm.CancelButton.OnClick(WizardForm.CancelButton);
end;

procedure BuildPage1;
begin
  Page1Panel := MakePanel(ContentPanel, 0, 0, 538, 482, COL_SURFACE);

  Kicker := MakeMono(Page1Panel, '01 / 03  ·  安装位置', 38, 34, 300, 16, 8, COL_BLUE);
  Kicker.Layout := tlCenter;

  Headline := MakeLabel(Page1Panel, '把归墟装到这台电脑', 38, 58, 460, 40, 20, COL_INK, True);
  Headline.Layout := tlCenter;

  Lead := MakeLabel(Page1Panel, '本地运行，数据不离开本机。安装只替换程序文件，不会动你的数据库。',
    38, 102, 440, 24, 9, COL_MUTED, False);
  Lead.Layout := tlCenter;

  PathLabel := MakeLabel(Page1Panel, '安装目录', 38, 148, 200, 16, 8, COL_DIM, False);
  PathLabel.Layout := tlCenter;

  PathBg := MakeImage(Page1Panel, 'installer-path-bg.bmp', 38, 168, 462, 42);

  FolderIcon := MakeImage(Page1Panel, 'installer-folder.bmp', 51, 182, 14, 14);

  if WizardForm.DirEdit.Text = '' then
    WizardForm.DirEdit.Text := ExpandConstant('{localappdata}\Programs\GuiXu');
  PathText := MakeMono(Page1Panel, WizardForm.DirEdit.Text, 75, 168, 330, 42, 8, COL_LIGHT);
  PathText.Layout := tlCenter;

  ChangeBg := MakeImage(Page1Panel, 'installer-btn-change.bmp', 446, 177, 46, 24);
  ChangeBg.Cursor := crHand;
  ChangeBg.OnClick := @ChangeClick;
  ChangeText := MakeLabel(Page1Panel, '更改', 446, 177, 46, 24, 7, COL_MUTED, False);
  ChangeText.Alignment := taCenter;
  ChangeText.Layout := tlCenter;
  ChangeText.Cursor := crHand;
  ChangeText.OnClick := @ChangeClick;

  Check1On := True;
  Check1Icon := MakeImage(Page1Panel, 'installer-check-on.bmp', 38, 227, 14, 14);
  Check1Icon.Cursor := crHand;
  Check1Icon.OnClick := @ToggleCheck1;
  Check1Text := MakeLabel(Page1Panel, '创建桌面快捷方式', 58, 227, 140, 14, 8, COL_MUTED, False);
  Check1Text.Layout := tlCenter;
  Check1Text.Cursor := crHand;
  Check1Text.OnClick := @ToggleCheck1;

  Check2On := True;
  Check2Icon := MakeImage(Page1Panel, 'installer-check-on.bmp', 200, 227, 14, 14);
  Check2Icon.Cursor := crHand;
  Check2Icon.OnClick := @ToggleCheck2;
  Check2Text := MakeLabel(Page1Panel, '安装完成后启动归墟', 220, 227, 160, 14, 8, COL_MUTED, False);
  Check2Text.Layout := tlCenter;
  Check2Text.Cursor := crHand;
  Check2Text.OnClick := @ToggleCheck2;

  NoteOuter := MakePanel(Page1Panel, 38, 267, 462, 58, COL_HAIR_SOFT);
  NoteInner := MakePanel(NoteOuter, 1, 1, 460, 56, COL_NOTE);
  NoteBar := MakePanel(NoteOuter, 1, 1, 2, 56, COL_BLUE);

  NoteBold := MakeLabel(NoteInner, '你的数据不会被覆盖。', 12, 8, 430, 16, 8, COL_LIGHT, False);
  NoteBold.AutoSize := True;
  NoteBold.Layout := tlTop;

  NoteBody := MakeLabel(NoteInner,
    '数据库、会话、导出和密钥保存在 %LOCALAPPDATA%\GuiXu，卸载',
    12 + NoteBold.Width + 2, 8, 340, 16, 8, COL_MUTED, False);
  NoteBody.Layout := tlTop;

  NoteBody2 := MakeLabel(NoteInner, '时保留。', 12, 26, 430, 16, 8, COL_MUTED, False);
  NoteBody2.Layout := tlTop;
end;

{ ---------- 第二页 ---------- }

procedure BuildInstallPage;
begin
  InstallPanel := MakePanel(ContentPanel, 0, 0, 538, 482, COL_SURFACE);

  InstallKicker := MakeMono(InstallPanel, '02 / 03  ·  安装中', 38, 34, 300, 16, 8, COL_BLUE);
  InstallKicker.Layout := tlCenter;

  InstallHeadline := MakeLabel(InstallPanel, '正在写入程序文件', 38, 58, 460, 40, 20, COL_INK, True);
  InstallHeadline.Layout := tlCenter;

  InstallLead := MakeLabel(InstallPanel, '安装只需要几十秒，期间请不要关闭窗口。',
    38, 102, 440, 24, 9, COL_MUTED, False);
  InstallLead.Layout := tlCenter;

  ProgressTrack := MakePanel(InstallPanel, 38, 190, 462, 6, COL_HAIR_SOFT);
  ProgressFill := MakePanel(ProgressTrack, 0, 0, 0, 6, COL_BLUE);

  ProgressText := MakeMono(InstallPanel, '0%', 38, 206, 100, 16, 7, COL_DIM);
  ProgressFile := MakeMono(InstallPanel, '', 38, 228, 462, 16, 7, COL_FAINT);
end;

{ ---------- 第三页 ---------- }

procedure BuildFinishPage;
begin
  FinishPanel := MakePanel(ContentPanel, 0, 0, 538, 482, COL_SURFACE);

  FinishKicker := MakeMono(FinishPanel, '03 / 03  ·  完成', 38, 34, 300, 16, 8, COL_BLUE);
  FinishKicker.Layout := tlCenter;

  FinishHeadline := MakeLabel(FinishPanel, '归墟已经装好了', 38, 58, 460, 40, 20, COL_INK, True);
  FinishHeadline.Layout := tlCenter;

  FinishLead := MakeLabel(FinishPanel,
    '程序文件已写入安装目录。你的数据库、会话和导出都还在原来的位置。',
    38, 102, 440, 44, 9, COL_MUTED, False);
  FinishLead.WordWrap := True;

  FinishNote := MakeLabel(FinishPanel,
    '首次启动会打开开机动画，让你填写模型配置。之后随时可以在设置里更换。',
    38, 170, 440, 44, 9, COL_DIM, False);
  FinishNote.WordWrap := True;
end;

{ ---------- 底部操作行 ---------- }

procedure BuildActions;
begin
  { 独立一层放底部操作行，避免被页面面板盖住 }
  ActionPanel := MakePanel(ContentPanel, 0, 422, 538, 34, COL_SURFACE);

  MetaText := MakeMono(ActionPanel, '约 440 MB · 不需要管理员权限', 38, 0, 260, 34, 7, COL_META);
  MetaText.Layout := tlCenter;

  GhostBg := MakeImage(ActionPanel, 'installer-btn-ghost.bmp', 328, 0, 62, 34);
  GhostBg.Cursor := crHand;
  GhostBg.OnClick := @CancelClick;
  GhostText := MakeLabel(ActionPanel, '取消', 328, 0, 62, 34, 8, COL_MUTED, False);
  GhostText.Alignment := taCenter;
  GhostText.Layout := tlCenter;
  GhostText.Cursor := crHand;
  GhostText.OnClick := @CancelClick;

  PrimaryBg := MakeImage(ActionPanel, 'installer-btn-primary.bmp', 400, 0, 100, 34);
  PrimaryBg.Cursor := crHand;
  PrimaryBg.OnClick := @PrimaryClick;
  PrimaryText := MakeLabel(ActionPanel, '开始安装 →', 400, 0, 100, 34, 8, clWhite, False);
  PrimaryText.Alignment := taCenter;
  PrimaryText.Layout := tlCenter;
  PrimaryText.Cursor := crHand;
  PrimaryText.OnClick := @PrimaryClick;
end;

{ ---------- 页面切换 ---------- }

procedure ShowStep(N: Integer);
begin
  Page1Panel.Visible := N = 1;
  InstallPanel.Visible := N = 2;
  FinishPanel.Visible := N = 3;

  MetaText.Visible := N <> 2;
  GhostBg.Visible := N <> 3;
  GhostText.Visible := N <> 3;
  PrimaryBg.Visible := N <> 2;
  PrimaryText.Visible := N <> 2;

  case N of
    1:
      begin
        MetaText.Caption := '约 440 MB · 不需要管理员权限';
        PrimaryText.Caption := '开始安装 →';
      end;
    2:
      begin
        MetaText.Caption := '正在安装，请稍候';
        MetaText.Visible := True;
      end;
    3:
      begin
        MetaText.Caption := '安装完成';
        PrimaryText.Caption := '完成';
      end;
  end;

  { 页面切换后把自绘层顶上去 }
  ActionPanel.BringToFront;
  ContentPanel.BringToFront;
  BrandPanel.BringToFront;
  TitleBar.BringToFront;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  WizardForm.NextButton.Visible := True;
  WizardForm.BackButton.Visible := False;
  WizardForm.CancelButton.Visible := True;

  if CurPageID = Page1.ID then
  begin
    { UsePreviousAppDir / /DIR 可能晚于 InitializeWizard 才落到 DirEdit }
    if WizardForm.DirEdit.Text <> '' then
      PathText.Caption := WizardForm.DirEdit.Text;
    ShowStep(1);
  end
  else if CurPageID = wpPreparing then
    ShowStep(2)
  else if CurPageID = wpInstalling then
    ShowStep(2)
  else if CurPageID = wpFinished then
  begin
    if Assigned(WizardForm.RunList) and (WizardForm.RunList.Items.Count > 0) then
      WizardForm.RunList.Checked[0] := Check2On;
    ShowStep(3);
  end;
end;

procedure CurInstallProgressChanged(CurProgress, MaxProgress: Integer);
begin
  if Assigned(ProgressFill) and (MaxProgress > 0) then
  begin
    ProgressFill.Width := ScaleX(462) * CurProgress div MaxProgress;
    ProgressText.Caption := IntToStr(CurProgress * 100 div MaxProgress) + '%';
    ProgressFile.Caption := WizardForm.FilenameLabel.Caption;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    if Assigned(WizardForm.TasksList) and (WizardForm.TasksList.Items.Count > 0) then
      WizardForm.TasksList.Checked[0] := Check1On;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { 自定义页已经画了桌面快捷方式，标准任务页不再出现 }
  Result := PageID = wpSelectTasks;
end;

{ ---------- 入口 ---------- }

procedure InitializeWizard;
begin
  Page1 := CreateCustomPage(wpWelcome, '', '');

  { 勾选框两态位图都要先释放到临时目录，切换时才读得到 }
  ExtractTemporaryFile('installer-check-off.bmp');
  ExtractTemporaryFile('installer-check-on.bmp');

  { 换掉整副外壳：无边框、固定尺寸、整窗深色 }
  WizardForm.BorderStyle := bsNone;
  WizardForm.Color := COL_SURFACE;
  WizardForm.Width := ScaleX(780);
  WizardForm.Height := ScaleY(520);

  { 标准页头与按钮全部退场，自绘层接管 }
  WizardForm.PageNameLabel.Visible := False;
  WizardForm.PageDescriptionLabel.Visible := False;
  WizardForm.Bevel.Visible := False;
  { Next / Cancel 保持可见但被自绘层盖住：隐藏它们会让 Inno 内部的导航 OnClick 失效 }
  WizardForm.NextButton.Visible := True;
  WizardForm.BackButton.Visible := False;
  WizardForm.CancelButton.Visible := True;

  BuildTitleBar;
  BuildBrand;
  ContentPanel := MakePanel(WizardForm, 242, 38, 538, 482, COL_SURFACE);

  BuildPage1;
  BuildInstallPage;
  BuildFinishPage;
  BuildActions;

  Page1Panel.Visible := True;
  InstallPanel.Visible := False;
  FinishPanel.Visible := False;

  WizardForm.Left := (GetSystemMetrics(SM_CXSCREEN) - WizardForm.Width) div 2;
  WizardForm.Top := (GetSystemMetrics(SM_CYSCREEN) - WizardForm.Height) div 2;

  ApplyChrome;
end;
