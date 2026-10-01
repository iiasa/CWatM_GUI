; ============================================================================
;  CWatM GUI - per-user (no-admin) installer  [Inno Setup 7]
;
;  Build the app first:   python -m PyInstaller cwatm_gui_dir.spec --noconfirm
;  Then compile this:      ISCC installer\CWatM_GUI.iss
;  Output:                 installer\Output\CWatM_GUI_Setup.exe
;
;  PrivilegesRequired=lowest -> installs per-user with NO admin prompt.
;  Under 'lowest', the {auto*} constants resolve to the current user's
;  locations ({autopf} = %LOCALAPPDATA%\Programs, {autoprograms} = user
;  Start menu, {autodesktop} = user desktop).
; ============================================================================

#define MyAppName      "CWatM GUI"

; --- version: scraped from the single source of truth, src\gui\__init__.py ----
; Bump __version__ = "X.YZ" there and both the app (About dialog) and this
; installer follow. The loop scans for the __version__ line and takes the text
; between its quotes; if it is not found the compile aborts rather than shipping
; a wrong version number. (Assign with #expr, not #define - a #define inside a
; #sub does not survive back into the global scope.)
#define VersionSource "..\src\gui\__init__.py"
#define VerFile
#define VerLine
#define MyAppVersion "NOTFOUND"

; Match the ASSIGNMENT, not any line mentioning __version__: the file's own comment
; ("keep the literal on one line as `__version__ = "X.YZ"`") also contains the word and
; a quoted string, so a looser test picked it up too. It happened to be harmless only
; because the real assignment comes later and overwrote it - a comment placed *below*
; the assignment would have shipped a wrong version without tripping the #error guard,
; which only catches NOTFOUND. Requiring the trimmed line to START with __version__
; rules the comment out (it starts with '#').
#sub ScanVersionLine
  #expr VerLine = FileRead(VerFile)
  #if Pos("__version__", Trim(VerLine)) == 1 && Pos('"', VerLine) > 0
    #expr MyAppVersion = Copy(VerLine, Pos('"', VerLine) + 1, RPos('"', VerLine) - Pos('"', VerLine) - 1)
  #endif
#endsub

#expr VerFile = FileOpen(VersionSource)
#for {0; VerFile && !FileEof(VerFile); 0} ScanVersionLine
#expr FileClose(VerFile)
#if MyAppVersion == "NOTFOUND"
  #error Could not read __version__ from src\gui\__init__.py
#endif

#define MyAppPublisher "IIASA"
#define MyAppURL       "https://cwatm.iiasa.ac.at"
#define MyAppExeName   "CWatM_GUI.exe"
#define MyAppIcon      "..\assets\cwatm.ico"
#define SourceDir      "..\dist\CWatM_GUI"

[Setup]
; A fixed AppId ties upgrades and the uninstaller to this product - do NOT change it.
AppId={{A7F3C2E1-9B4D-4E6A-8C1F-2D5E7A9B0C34}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}

; --- no-admin, per-user install -------------------------------------------
PrivilegesRequired=lowest
DefaultDirName={autopf}\CWatM_GUI
DisableDirPage=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Inno 6 hides the Welcome page by default, which is where the large left-side
; WizardImageFile appears. Show it so wizard_large.png is visible on Welcome + Finished.
DisableWelcomePage=no

; --- output ----------------------------------------------------------------
OutputDir=Output
OutputBaseFilename=CWatM_GUI_Setup
SetupIconFile={#MyAppIcon}
; CWatM branding on the wizard pages (portrait canvases composited from assets\cwatm.png).
WizardImageFile=assets\wizard_large.png
WizardSmallImageFile=assets\wizard_small.png
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
; Drop the stock "It is recommended that you close all other applications
; before continuing." sentence from the Welcome page.
WelcomeLabel2=This will install [name/ver] on your computer.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "iniassoc";    Description: "Add CWatM GUI to the 'Open with' menu for .ini settings files"; Flags: unchecked

[InstallDelete]
; An upgrade only overwrites files, it never removes what the new build no longer
; ships. A left-over package folder is then still importable as an empty namespace
; package (scipy after 1.10: dask's "import scipy.sparse" succeeded and the viewers
; failed with "scipy.sparse has no attribute spmatrix"). So clear _internal first -
; it holds only program files, no user data.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; Copy the entire one-folder PyInstaller build verbatim. 'recursesubdirs' +
; 'createallsubdirs' preserves _internal\ (holding CWatM_model.exe and all
; dependencies) exactly - its name/layout MUST NOT change.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; AppUserModelID = the ID cwatm_gui.py sets (_set_windows_app_id), so the taskbar
; matches the running window to this shortcut and shows its icon from the start.
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; AppUserModelID: "IIASA.CWatM.GUI"
Name: "{autodesktop}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"; AppUserModelID: "IIASA.CWatM.GUI"; Tasks: desktopicon

[Registry]
; --- optional .ini "Open with" association (per-user HKCU, no admin) --------
; Registers a private ProgID and adds it to the .ini "Open with" list. It does
; NOT hijack the default .ini handler - it only appears in the Open-with menu.
Root: HKCU; Subkey: "Software\Classes\CWatMGUI.inifile"; ValueType: string; ValueData: "CWatM settings file"; Flags: uninsdeletekey; Tasks: iniassoc
Root: HKCU; Subkey: "Software\Classes\CWatMGUI.inifile\DefaultIcon"; ValueType: string; ValueData: "{app}\{#MyAppExeName},0"; Tasks: iniassoc
Root: HKCU; Subkey: "Software\Classes\CWatMGUI.inifile\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: iniassoc
Root: HKCU; Subkey: "Software\Classes\.ini\OpenWithProgids"; ValueType: string; ValueName: "CWatMGUI.inifile"; ValueData: ""; Flags: uninsdeletevalue; Tasks: iniassoc
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey; Tasks: iniassoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
