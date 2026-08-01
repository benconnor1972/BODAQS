#ifndef AppVersion
  #define AppVersion "0.2.1-beta"
#endif

#ifndef StageRoot
  #error "StageRoot define is required. Run via import-manager\\build_demo_library_installer.ps1."
#endif

#ifndef InstallerOutputDir
  #define InstallerOutputDir AddBackslash(SourcePath) + "..\\..\\dist\\demo-library-installer\\windows"
#endif

#define MyAppId "{{9AC44A6D-0F5D-4BE6-9ED7-971F44B859B5}"
#define MyAppName "BODAQS Demo Library"
#define DemoLibraryId "bodaqs-demo"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
AppPublisher=BODAQS
DefaultDirName={tmp}\bodaqs-demo-library-installer
DisableDirPage=yes
DisableProgramGroupPage=yes
CreateUninstallRegKey=no
Uninstallable=no
OutputDir={#InstallerOutputDir}
OutputBaseFilename=bodaqs-demo-library-setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#SourcePath}bodaqs_import_agent.ico
ArchitecturesAllowed=x64compatible
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#StageRoot}\demo-assets\*"; DestDir: "{code:GetWorkspaceRoot}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Code]
var
  WorkspaceRootPage: TInputDirWizardPage;

function GetWorkspaceRoot(Param: String): String;
begin
  Result := WorkspaceRootPage.Values[0];
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ExistingDefinition: String;
begin
  Result := True;
  if CurPageID = WorkspaceRootPage.ID then begin
    if Trim(WorkspaceRootPage.Values[0]) = '' then begin
      MsgBox('Choose a workspace root before continuing.', mbError, MB_OK);
      Result := False;
      exit;
    end;
    ExistingDefinition := AddBackslash(WorkspaceRootPage.Values[0]) +
      'libraries\\{#DemoLibraryId}\\library_definition.json';
    if FileExists(ExistingDefinition) then begin
      MsgBox(
        'A BODAQS Demo Library already exists in the selected workspace. ' +
        'This installer will not overwrite it. Choose another workspace or remove the existing demo library first.',
        mbError,
        MB_OK
      );
      Result := False;
    end;
  end;
end;

procedure InitializeWizard;
begin
  WorkspaceRootPage := CreateInputDirPage(
    wpWelcome,
    'Choose BODAQS workspace',
    'Select the workspace root for the demo library',
    'The installer will add the BODAQS Demo Library to the selected workspace. ' +
    'It does not install the BODAQS Desktop application.',
    False,
    ''
  );
  WorkspaceRootPage.Add('Workspace root:');
  WorkspaceRootPage.Values[0] := ExpandConstant('{userdocs}\\BODAQS-data');
end;
