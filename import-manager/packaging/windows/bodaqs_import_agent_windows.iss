#ifndef AppVersion
  #define AppVersion "0.1.5-dev"
#endif

#ifndef ImportManagerVersion
  #define ImportManagerVersion "0.1.5-beta"
#endif

#ifndef LibraryServiceVersion
  #define LibraryServiceVersion "0.1.0-dev"
#endif

#ifndef WorkbenchVersion
  #define WorkbenchVersion "0.1.0-dev"
#endif

#ifndef StageRoot
  #error "StageRoot define is required. Run via import-manager\\build_import_manager.ps1 -Target installer."
#endif

#ifndef InstallerOutputDir
  #define InstallerOutputDir AddBackslash(SourcePath) + "..\\..\\dist\\installer\\windows"
#endif

#define MyAppId "{{A214DDDC-4A8A-412A-9B75-4C62AB3F1DAA}"
#define MyAppName "BODAQS Desktop"
#define MyAppPublisher "BODAQS"
#define MyAppExeName "bodaqs-import-setup.exe"
#define MyManagerShortcutName "BODAQS Import Manager"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\BODAQS Desktop
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#InstallerOutputDir}
OutputBaseFilename=bodaqs-desktop-setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#SourcePath}bodaqs_import_agent.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\manager\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#StageRoot}\manager\*"; DestDir: "{app}\manager"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageRoot}\service\*"; DestDir: "{app}\service"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageRoot}\component_versions.json"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyManagerShortcutName}"; Filename: "{app}\manager\{#MyAppExeName}"; Parameters: "--app-config-mode installed"; WorkingDir: "{app}\manager"
Name: "{autodesktop}\{#MyManagerShortcutName}"; Filename: "{app}\manager\{#MyAppExeName}"; Parameters: "--app-config-mode installed"; WorkingDir: "{app}\manager"; Tasks: desktopicon

[Run]
Filename: "{app}\manager\{#MyAppExeName}"; Parameters: "--app-config-mode installed"; Description: "Launch {#MyManagerShortcutName}"; Flags: nowait postinstall skipifsilent
