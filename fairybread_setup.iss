; Fairybread 64-bit Windows Setup Script (Inno Setup 6)
; Compiled cleanly by build_release.py via ISCC.exe for Public and Developer editions.

#ifndef AppEdition
  #define AppEdition "Public"
#endif
#ifndef AppName
  #define AppName "Fairybread"
#endif
#ifndef AppDirName
  #define AppDirName "Fairybread"
#endif
#ifndef AppIdGuid
  #define AppIdGuid "{B7F4E2A1-6C3D-4B89-9E51-FA18B4EAD001}"
#endif
#ifndef AppDispVer
  #define AppDispVer "0.95"
#endif
#ifndef AppWinVer
  #define AppWinVer "0.95.0.0"
#endif
#ifndef DefaultIncludeSource
  #define DefaultIncludeSource "0"
#endif
#ifndef PyDistDir
  #define PyDistDir "build\pyi_public\Fairybread"
#endif
#ifndef SourceStageDir
  #define SourceStageDir "build\stage_public"
#endif
#ifndef OutputDirPath
  #define OutputDirPath "dist"
#endif
#ifndef OutputExeBase
  #define OutputExeBase "Fairybread_v0.95_Win_x64_Setup"
#endif

[Setup]
AppId={{#AppIdGuid}
AppName={#AppName}
AppVersion={#AppWinVer}
AppVerName={#AppName} (Beta v{#AppDispVer})
AppPublisher=Brett Martin Moore
AppPublisherURL=https://fairybread.me
AppSupportURL=https://fairybread.me
AppUpdatesURL=https://github.com/bm069au/fairybread/releases
DefaultDirName={autopf}\{#AppDirName}
DefaultGroupName={#AppName}
DisableDirPage=no
DisableProgramGroupPage=no
DisableWelcomePage=no
AllowNoIcons=yes
LicenseFile=LICENSE.md
SetupIconFile=fairybread_icon.ico
UninstallDisplayIcon={app}\Fairybread.exe
UninstallDisplayName={#AppName} (Beta v{#AppDispVer})
UninstallFilesDir={app}
CreateUninstallRegKey=yes
Uninstallable=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
OutputDir={#OutputDirPath}
OutputBaseFilename={#OutputExeBase}
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=Fairybread.exe,FairybreadMCP.exe
VersionInfoVersion={#AppWinVer}
VersionInfoTextVersion={#AppDispVer}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppWinVer}
VersionInfoCompany=Brett Martin Moore
VersionInfoDescription={#AppName} Multi-AI Workspace & Shared Memory Palace Setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
#if DefaultIncludeSource == "1"
Name: "withsource"; Description: "Complete Installation (Application + Packaged Python Source Code)"
Name: "standard"; Description: "Application Only (No Source Code Copy)"
#else
Name: "standard"; Description: "Standard Installation (Application Only — Recommended)"
Name: "withsource"; Description: "Application + Packaged Copy of Python Source Code (\source\)"
#endif
Name: "custom"; Description: "Custom Installation"; Flags: iscustom

[Components]
Name: "app"; Description: "Fairybread Desktop Application (Fairybread.exe, MCP Bridge & Offline Runtime)"; Types: standard withsource custom; Flags: fixed
Name: "source"; Description: "Install Packaged Copy of Fairybread Source Code (\source\ alongside installation)"; Types: withsource

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"; GroupDescription: "Shortcuts:"; Check: ShouldInstallApp
Name: "startmenuicon"; Description: "Create a &Start Menu shortcut"; GroupDescription: "Shortcuts:"; Check: ShouldInstallApp

[Files]
; Compiled standalone 64-bit application + shared _internal\ runtime + signed manifest + docs
Source: "{#PyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: ShouldInstallApp
; Packaged clean copy of Fairybread source code (\source\) — installed ONLY when selected or "Source Only" mode chosen
Source: "{#SourceStageDir}\*"; DestDir: "{app}\source"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: ShouldInstallSource

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Fairybread.exe"; IconFilename: "{app}\fairybread_icon.ico"; Comment: "Launch {#AppName} Multi-AI Workspace"; Tasks: startmenuicon; Check: ShouldInstallApp
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Fairybread.exe"; IconFilename: "{app}\fairybread_icon.ico"; Comment: "Launch {#AppName} Multi-AI Workspace"; Tasks: desktopicon; Check: ShouldInstallApp

[Run]
Filename: "{app}\Fairybread.exe"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent; Check: ShouldLaunchAfterInstall
Filename: "{app}\Fairybread.exe"; Flags: nowait postinstall skipifnotsilent; Check: ShouldAutoRelaunchUpdateOnly

[UninstallRun]
Filename: "{app}\FairybreadMCP.exe"; Parameters: "--cleanup-install-dir ""{app}"""; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "CleanupFairybreadMCP"

[Code]
var
  MaintPage: TInputOptionWizardPage;
  ExistingDetected: Boolean;
  FoundInstallDir: String;
  FoundUninstallStr: String;
  FoundRegKeyPath: String;
  ForceExitSetup: Boolean;
  DidInstallSourceOnly: Boolean;

procedure SplitCommandAndArgs(const RawCmd: String; var ExePath, Params: String);
var
  S: String;
  P, SpacePos: Integer;
begin
  ExePath := '';
  Params := '';
  S := Trim(RawCmd);
  if S = '' then Exit;
  if S[1] = '"' then
  begin
    Delete(S, 1, 1);
    P := Pos('"', S);
    if P > 0 then
    begin
      ExePath := Copy(S, 1, P - 1);
      Params := Trim(Copy(S, P + 1, Length(S)));
    end else
      ExePath := S;
  end else
  begin
    SpacePos := Pos(' ', S);
    if SpacePos > 0 then
    begin
      ExePath := Copy(S, 1, SpacePos - 1);
      Params := Trim(Copy(S, SpacePos + 1, Length(S)));
    end else
      ExePath := S;
  end;
end;

function ProbeUninstallHive(const RootKey: Integer): Boolean;
var
  OwnKey, BaseKey: String;
  SubNames: TArrayOfString;
  I: Integer;
  DName, Uninst, InstLoc: String;
begin
  Result := False;
  BaseKey := 'Software\Microsoft\Windows\CurrentVersion\Uninstall';
  OwnKey := BaseKey + '\{#AppIdGuid}_is1';
  if RegKeyExists(RootKey, OwnKey) then
  begin
    RegQueryStringValue(RootKey, OwnKey, 'UninstallString', Uninst);
    RegQueryStringValue(RootKey, OwnKey, 'InstallLocation', InstLoc);
    if InstLoc = '' then
      RegQueryStringValue(RootKey, OwnKey, 'Inno Setup: App Path', InstLoc);
    FoundUninstallStr := Uninst;
    FoundInstallDir := RemoveBackslashUnlessRoot(InstLoc);
    FoundRegKeyPath := OwnKey;
    Result := (FoundUninstallStr <> '') or (FoundInstallDir <> '');
    if Result then Exit;
  end;

  if RegGetSubkeyNames(RootKey, BaseKey, SubNames) then
  begin
    for I := 0 to GetArrayLength(SubNames) - 1 do
    begin
      if RegQueryStringValue(RootKey, BaseKey + '\' + SubNames[I], 'DisplayName', DName) then
      begin
        if (Pos('Fairybread', DName) = 1) then
        begin
          if ((Pos('Developer', '{#AppName}') > 0) = (Pos('Developer', DName) > 0)) then
          begin
            RegQueryStringValue(RootKey, BaseKey + '\' + SubNames[I], 'UninstallString', Uninst);
            RegQueryStringValue(RootKey, BaseKey + '\' + SubNames[I], 'InstallLocation', InstLoc);
            if (Uninst <> '') or (InstLoc <> '') then
            begin
              FoundUninstallStr := Uninst;
              FoundInstallDir := RemoveBackslashUnlessRoot(InstLoc);
              FoundRegKeyPath := BaseKey + '\' + SubNames[I];
              Result := True;
              Exit;
            end;
          end;
        end;
      end;
    end;
  end;
end;

procedure DetectExistingInstallation();
var
  DefaultDir: String;
begin
  ExistingDetected := False;
  FoundInstallDir := '';
  FoundUninstallStr := '';
  FoundRegKeyPath := '';

  if ProbeUninstallHive(HKLM64) then ExistingDetected := True
  else if ProbeUninstallHive(HKCU64) then ExistingDetected := True
  else if ProbeUninstallHive(HKLM32) then ExistingDetected := True
  else if ProbeUninstallHive(HKCU32) then ExistingDetected := True;

  DefaultDir := ExpandConstant('{autopf}\{#AppDirName}');
  if (FoundInstallDir = '') and (FileExists(DefaultDir + '\Fairybread.exe') or FileExists(DefaultDir + '\palace_gui.py')) then
  begin
    FoundInstallDir := DefaultDir;
    ExistingDetected := True;
  end;
end;

procedure StopRunningFairybread();
var
  RC: Integer;
begin
  Exec('taskkill.exe', '/F /T /IM Fairybread.exe', '', SW_HIDE, ewWaitUntilTerminated, RC);
  Exec('taskkill.exe', '/F /T /IM FairybreadMCP.exe', '', SW_HIDE, ewWaitUntilTerminated, RC);
  Sleep(250);
end;

function RunDetectedUninstaller(): Boolean;
var
  ExePath, Params, ExtraParams: String;
  RC: Integer;
begin
  Result := False;
  StopRunningFairybread();
  if FoundUninstallStr <> '' then
  begin
    SplitCommandAndArgs(FoundUninstallStr, ExePath, Params);
    if FileExists(ExePath) then
    begin
      ExtraParams := Params;
      if Pos('/VERYSILENT', UpperCase(ExtraParams)) = 0 then
      begin
        if (Pos('UNINS', UpperCase(ExtractFileName(ExePath))) = 1) then
          ExtraParams := Trim(ExtraParams + ' /SILENT /NORESTART')
        else if Pos('--quiet', LowerCase(ExtraParams)) = 0 then
          ExtraParams := Trim(ExtraParams + ' --quiet');
      end;
      if Exec(ExePath, ExtraParams, ExtractFileDir(ExePath), SW_SHOW, ewWaitUntilTerminated, RC) and (RC = 0) then
        Result := True;
    end;
  end;

  if (FoundInstallDir <> '') and DirExists(FoundInstallDir) then
  begin
    DelTree(FoundInstallDir, True, True, True);
    Result := True;
  end;
  if FoundRegKeyPath <> '' then
  begin
    RegDeleteKeyIncludingSubkeys(HKLM64, FoundRegKeyPath);
    RegDeleteKeyIncludingSubkeys(HKCU64, FoundRegKeyPath);
  end;
end;

function IsUpdateOnlyParam(): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
  begin
    if CompareText(ParamStr(I), '/UPDATEONLY') = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function SelectedMaintMode(): Integer;
begin
  // -1 = fresh install or standard silent, 0 = Update only, 1 = Reinstall Clean Copy, 2 = Source Only, 3 = Uninstall
  if IsUpdateOnlyParam() then
    Result := 0
  else if (not ExistingDetected) or (MaintPage = nil) then
    Result := -1
  else
    Result := MaintPage.SelectedValueIndex;
end;

function ShouldInstallApp(): Boolean;
begin
  Result := SelectedMaintMode() <> 2;
end;

function ShouldInstallSource(): Boolean;
var
  Mode: Integer;
begin
  Mode := SelectedMaintMode();
  if Mode = 2 then
    Result := True
  else if Mode = 0 then
    Result := DirExists(ExpandConstant('{app}\source'))
  else
    Result := WizardIsComponentSelected('source');
end;

function ShouldLaunchAfterInstall(): Boolean;
begin
  Result := ShouldInstallApp();
end;

function ShouldAutoRelaunchUpdateOnly(): Boolean;
begin
  Result := IsUpdateOnlyParam() and ShouldInstallApp();
end;

procedure InitializeWizard();
begin
  ForceExitSetup := False;
  DidInstallSourceOnly := False;
  DetectExistingInstallation();

  if ExistingDetected and IsUpdateOnlyParam() and (FoundInstallDir <> '') then
  begin
    WizardForm.DirEdit.Text := FoundInstallDir;
  end;

  if ExistingDetected and (not WizardSilent()) then
  begin
    MaintPage := CreateInputOptionPage(
      wpWelcome,
      'Existing {#AppName} Installation Detected',
      'Found installed copy at: ' + FoundInstallDir,
      'Choose how you would like Setup to proceed. Your encrypted API keys, settings, and databases in AppData are kept safe unless you choose to remove them during uninstall.',
      True,
      False
    );
    MaintPage.Add('1. Update only (Recommended — update binaries cleanly, touch no keys/data/settings, and relaunch)');
    MaintPage.Add('2. Reinstall clean copy (stop running app, clean program folder, and install fresh v{#AppDispVer})');
    MaintPage.Add('3. Install source code only (keep installed app intact and add/update packaged \source\)');
    MaintPage.Add('4. Uninstall existing copy (remove installed binaries, shortcuts, and registry entries)');
    MaintPage.SelectedValueIndex := 0;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (MaintPage <> nil) and (PageID <> MaintPage.ID) then
  begin
    if MaintPage.SelectedValueIndex = 0 then
    begin
      // Update-only mode updates installed binaries in place without re-asking folders, icons, or tasks
      if (PageID = wpSelectDir) or (PageID = wpSelectComponents) or (PageID = wpSelectProgramGroup) or (PageID = wpSelectTasks) then
        Result := True;
    end
    else if MaintPage.SelectedValueIndex = 2 then
    begin
      // Source-code-only mode goes directly to target check / Ready page without re-asking components or Start Menu icons
      if (PageID = wpSelectComponents) or (PageID = wpSelectProgramGroup) or (PageID = wpSelectTasks) then
        Result := True;
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  PromptAns: Integer;
begin
  Result := True;
  if (MaintPage <> nil) and (CurPageID = MaintPage.ID) then
  begin
    if MaintPage.SelectedValueIndex = 3 then
    begin
      PromptAns := MsgBox(
        'Uninstall the existing copy of {#AppName} from:'#13#10 + FoundInstallDir + '?'#13#10#13#10 +
        'Your encrypted API keys and Memory Palace databases under %LOCALAPPDATA%\Palace will NOT be deleted.',
        mbConfirmation,
        MB_YESNO or MB_DEFBUTTON2
      );
      if PromptAns <> IDYES then
      begin
        Result := False;
        Exit;
      end;
      if RunDetectedUninstaller() then
        MsgBox('Existing {#AppName} copy has been cleanly uninstalled.', mbInformation, MB_OK)
      else
        MsgBox('Uninstall finished cleanly.', mbInformation, MB_OK);
      ForceExitSetup := True;
      WizardForm.Close;
      Result := False;
      Exit;
    end;
    if ((MaintPage.SelectedValueIndex = 0) or (MaintPage.SelectedValueIndex = 2)) and (FoundInstallDir <> '') then
    begin
      WizardForm.DirEdit.Text := FoundInstallDir;
    end;
    DidInstallSourceOnly := (MaintPage.SelectedValueIndex = 2);
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if ForceExitSetup then
  begin
    Cancel := True;
    Confirm := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir: String;
  OldInternal: String;
  Mode: Integer;
begin
  if CurStep = ssInstall then
  begin
    StopRunningFairybread();
    Mode := SelectedMaintMode();
    if (Mode = 0) or (Mode = 1) then
    begin
      AppDir := ExpandConstant('{app}');
      OldInternal := AppDir + '\_internal';
      if DirExists(OldInternal) then DelTree(OldInternal, True, True, True);
      if FileExists(AppDir + '\Fairybread.exe') then DeleteFile(AppDir + '\Fairybread.exe');
      if FileExists(AppDir + '\FairybreadMCP.exe') then DeleteFile(AppDir + '\FairybreadMCP.exe');
      if (Mode = 1) and DirExists(AppDir + '\source') then DelTree(AppDir + '\source', True, True, True);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  LocalDataDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    StopRunningFairybread();
  end
  else if CurUninstallStep = usPostUninstall then
  begin
    if not UninstallSilent() then
    begin
      LocalDataDir := ExpandConstant('{localappdata}\Palace');
      if DirExists(LocalDataDir) then
      begin
        if MsgBox(
          '{#AppName} program files, shortcuts, and MCP registrations have been removed.'#13#10#13#10 +
          'Do you also want to delete your personal user data folder (' + LocalDataDir + '), including encrypted API keys and databases?'#13#10#13#10 +
          'Choose NO to keep your API keys and Memory Palace.',
          mbConfirmation,
          MB_YESNO or MB_DEFBUTTON2
        ) = IDYES then
        begin
          DelTree(LocalDataDir, True, True, True);
        end;
      end;
    end;
  end;
end;
