; EmeraldTogether Windows installer (Inno Setup 6.3 or later; GitHub's windows-2022 image ships 6.7.1 as `iscc`).
;
; Built by scripts/windows-runtime/build_launcher.py --installer, which runs:
;   iscc /Qp /DAppVersion=<version label> /DSetupVersion=<file-name-safe version>
;        /DPackageDir=<...\dist\EmeraldTogether> /O<output folder> EmeraldTogether.iss
; and the result is EmeraldTogether-Setup-<SetupVersion>.exe. PackageDir is the finished PyInstaller
; folder: EmeraldTogether.exe, _internal\ (the launcher, the game manifest and runtime\ with the game),
; README.txt, QUICK-START.txt, HOSTING.txt and RELEASE-LIMITS.txt. Nothing else is packed.
;
; What it does:
;   * installs for the current Windows user only, without administrator rights, in
;     %LOCALAPPDATA%\Programs\EmeraldTogether ({userpf}); /CURRENTUSER is accepted and changes nothing;
;   * adds a Start menu shortcut and, if chosen, a desktop shortcut;
;   * upgrades or repairs in place: the same AppId finds the earlier installation, running copies are
;     closed (Restart Manager), the old program internals are removed and the new files written;
;   * never installs, replaces or removes the player's data: saves, characters, worlds and settings live
;     in %LOCALAPPDATA%\PokemonPrivate, outside {app}, and the uninstaller removes only what Setup installed.
; The installer is not code-signed, so Windows SmartScreen warns before it runs (QUICK-START.txt explains).

#if Ver < EncodeVer(6, 3, 0)
  #error EmeraldTogether.iss needs Inno Setup 6.3 or later
#endif
#ifndef AppVersion
  #error Pass /DAppVersion=<version label> (build_launcher.py --installer does)
#endif
#ifndef SetupVersion
  #error Pass /DSetupVersion=<file-name-safe version> (build_launcher.py --installer does)
#endif
#ifndef PackageDir
  #error Pass /DPackageDir=<the dist\EmeraldTogether folder> (build_launcher.py --installer does)
#endif

#define AppName "EmeraldTogether"
#define AppExe "EmeraldTogether.exe"

[Setup]
; Never change AppId: upgrades, repairs and the uninstaller find the installation by it ("{{" is a literal "{").
; InstalledBefore() in [Code] names the same GUID.
AppId={{CAC8954B-B6DB-4E29-AD98-412B39D18856}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=EmeraldTogether (private build for friends)
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
DefaultDirName={userpf}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=EmeraldTogether-Setup-{#SetupVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
InfoBeforeFile={#PackageDir}\RELEASE-LIMITS.txt
UsePreviousAppDir=yes
UsePreviousTasks=yes
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=This will install [name/ver] for your Windows user. It does not need administrator rights.%n%nEmeraldTogether is a private build for friends who own Pokemon Emerald. Please do not share this Setup file with anyone else.%n%nSetup never touches your saves, characters or worlds.
InfoBeforeLabel=Please read this before you install.
InfoBeforeClickLabel=It explains what this private build is and what is not finished yet. Click Next to continue.
FinishedLabel=EmeraldTogether is installed. Start it from the Start menu (EmeraldTogether) or from the desktop shortcut if you chose one.%n%nYour saves, characters and worlds are stored separately and are kept when you repair, update or uninstall EmeraldTogether.
ConfirmUninstall=Remove the %1 program from this PC?%n%nYour saves, characters and worlds are kept: they are stored separately, and uninstalling never deletes them.
UninstalledAll=%1 was removed from your PC. Your saves, characters and worlds were kept.

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[InstallDelete]
; Upgrade or repair: remove the earlier program internals first, so no file of another version stays next to
; the new game (the launcher refuses unknown programs or libraries in the game folder). Only inside {app}.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Comment: "Play EmeraldTogether"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Comment: "Play EmeraldTogether"; Tasks: desktopicon

[Run]
Filename: "{app}\QUICK-START.txt"; Description: "Open the quick start guide"; Flags: postinstall shellexec skipifsilent unchecked
Filename: "{app}\{#AppExe}"; Description: "Start EmeraldTogether now"; Flags: postinstall nowait skipifsilent

; There is deliberately no [UninstallDelete] section: the uninstaller removes only the files Setup installed.

[Code]
function InstalledBefore(): Boolean;
begin
  Result := RegKeyExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{CAC8954B-B6DB-4E29-AD98-412B39D18856}_is1');
end;

procedure InitializeWizard();
begin
  if InstalledBefore() then
    WizardForm.WelcomeLabel2.Caption :=
      'EmeraldTogether is already installed for your Windows user.' + #13#10#13#10 +
      'Setup will repair or update it: it closes EmeraldTogether if it is running and puts back every ' +
      'program file from this Setup file.' + #13#10#13#10 +
      'Your saves, characters and worlds are not touched.';
end;
