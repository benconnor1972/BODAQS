#ifndef AppVersion
  #define AppVersion "0.1.0-dev"
#endif

#ifndef StageRoot
  #error "StageRoot define is required. Run via analysis\\build_import_agent.ps1 -Target installer."
#endif

#ifndef InstallerOutputDir
  #define InstallerOutputDir AddBackslash(SourcePath) + "..\\..\\dist\\installer\\windows"
#endif

#define MyAppId "{{A214DDDC-4A8A-412A-9B75-4C62AB3F1DAA}"
#define MyAppName "BODAQS Import Agent"
#define MyAppPublisher "BODAQS"
#define MyAppExeName "bodaqs-import-setup.exe"
#define MyCliExeName "bodaqs-import.exe"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\BODAQS Import Agent
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#InstallerOutputDir}
OutputBaseFilename=bodaqs-import-agent-setup-{#AppVersion}
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
Source: "{#StageRoot}\cli\*"; DestDir: "{app}\cli"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\manager\{#MyAppExeName}"; Parameters: "--app-config-mode installed"; WorkingDir: "{app}\manager"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\manager\{#MyAppExeName}"; Parameters: "--app-config-mode installed"; WorkingDir: "{app}\manager"; Tasks: desktopicon

[Run]
Filename: "{app}\manager\{#MyAppExeName}"; Parameters: "--app-config-mode installed"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
