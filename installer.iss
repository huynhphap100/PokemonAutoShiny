; ===========================================================================
; PokemonAutoShiny — Inno Setup 6 installer script
;
; Requirements before compiling:
;   1. Run:  pyinstaller PokemonAutoShiny.spec --noconfirm
;   2. Ensure vc_redist.x64.exe is present in project root
;   3. Compile this script with Inno Setup 6
;
; Output: installer\PokemonAutoShiny_Setup.exe
; ===========================================================================

#define MyAppName      "Pokemon Auto Shiny"
#define MyAppVersion   "1.0"
#define MyAppPublisher "PokemonAutoShiny"
#define MyAppExeName   "PokemonAutoShiny.exe"
#define MySourceDir    "dist\PokemonAutoShiny"

#ifndef CompressionMode
  #define CompressionMode "lzma2/fast"
#endif

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisherURL=https://github.com
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=installer
OutputBaseFilename=PokemonAutoShiny_Setup
Compression={#CompressionMode}
SolidCompression=yes
LZMANumBlockThreads=6
LZMAUseSeparateProcess=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
; Require admin privileges so VC++ Redistributable can be installed system-wide
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
; Minimum Windows 10
MinVersion=10.0.17763

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
  GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; ── VC++ 2022 Redistributable (bundled, deleted after install) ──────────────
Source: "vc_redist.x64.exe"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall; Check: VCRedistNeedsInstall

; ── Main application (entire PyInstaller dist folder) ───────────────────────
Source: "{#MySourceDir}\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"; \
  Tasks: desktopicon

[Run]
; 1 — Install VC++ Redistributable silently (skip if already installed)
Filename: "{tmp}\vc_redist.x64.exe"; \
  Parameters: "/install /quiet /norestart"; \
  StatusMsg: "Installing Visual C++ 2022 Runtime…"; \
  Flags: waituntilterminated; Check: VCRedistNeedsInstall

; 2 — Launch app after install (user can uncheck)
Filename: "{app}\{#MyAppExeName}"; \
  Description: "Launch {#MyAppName} now"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove everything including user-written data folder
Type: filesandordirs; Name: "{app}"

[Code]
// ── Helpers ──────────────────────────────────────────────────────────────────

// Check if VC++ 2022 x64 Runtime is already installed.
function VCRedistNeedsInstall: Boolean;
var
  installed: Cardinal;
begin
  Result := True; // default: install
  // VS2022 / VS2019 / VS2017 all share the same 14.x runtime key
  if RegQueryDWordValue(HKLM,
       'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
       'Installed', installed) then
  begin
    if installed = 1 then
      Result := False;
  end;
end;
