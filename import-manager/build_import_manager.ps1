param(
    [string]$PythonExe = "",
    [switch]$InstallPyInstaller,
    [switch]$SkipPyInstallerBuild,
    [switch]$SkipWebAppBuild,
    [ValidateSet("cli", "setup", "service", "installer", "all")]
    [string]$Target = "cli",
    [string]$InnoSetupExe = "",
    [string]$BundleVersion = "0.1.5-dev",
    [string]$ImportManagerVersion = "0.1.5-beta",
    [string]$LibraryServiceVersion = "0.1.0-dev",
    [string]$WorkbenchVersion = "0.1.0-dev",
    [string]$AppVersion = "",
    [string]$WebAppDist = ""
)

$ErrorActionPreference = "Stop"

if ($AppVersion) {
    Write-Warning "-AppVersion is deprecated for desktop bundles. Treating it as -BundleVersion."
    $BundleVersion = $AppVersion
}

$importManagerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $importManagerDir
$analysisDir = Join-Path $repoRoot "analysis"
$webAppDir = Join-Path $repoRoot "application\cohort-workbench-prototype"

if (-not $PythonExe) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $PythonExe = $venvPython
    } else {
        $PythonExe = "python"
    }
}

Write-Host "Using Python:" $PythonExe

function Resolve-InnoSetupCompiler {
    param(
        [string]$ExplicitPath
    )

    if ($ExplicitPath) {
        if (-not (Test-Path $ExplicitPath)) {
            throw "Inno Setup compiler not found at: $ExplicitPath"
        }
        return (Resolve-Path $ExplicitPath).Path
    }

    $candidatePaths = @()
    if ($env:ProgramFiles) {
        $candidatePaths += (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    }
    if (${env:ProgramFiles(x86)}) {
        $candidatePaths += (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe")
    }
    if ($env:LOCALAPPDATA) {
        $candidatePaths += (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    }
    foreach ($candidate in $candidatePaths) {
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }

    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    return $null
}

function Ensure-CleanDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (Test-Path $Path) {
        Remove-Item -Recurse -Force $Path
    }
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Resolve-CommandPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    $command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Required command was not found on PATH: $CommandName"
    }
    return $command.Source
}

function Resolve-WebAppDist {
    if ($WebAppDist) {
        if (-not (Test-Path $WebAppDist)) {
            throw "Web app dist directory was not found: $WebAppDist"
        }
        return (Resolve-Path $WebAppDist).Path
    }

    $dist = Join-Path $webAppDir "dist"
    if (-not $SkipWebAppBuild) {
        if (-not (Test-Path (Join-Path $webAppDir "package.json"))) {
            throw "Web app package.json was not found: $webAppDir"
        }
        $npmExe = Resolve-CommandPath -CommandName "npm.cmd"
        Write-Host ""
        Write-Host "Building bundled web app..."
        Push-Location $webAppDir
        try {
            $buildOutput = & $npmExe run build
            $buildOutput | ForEach-Object { Write-Host $_ }
        } finally {
            Pop-Location
        }
    }

    if (-not (Test-Path (Join-Path $dist "index.html"))) {
        throw "Built web app index.html was not found. Run without -SkipWebAppBuild or provide -WebAppDist. Expected: $(Join-Path $dist "index.html")"
    }
    return (Resolve-Path $dist).Path
}

function Copy-WebAppDist {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceDir,
        [Parameter(Mandatory = $true)]
        [string]$DestinationDir
    )

    Ensure-CleanDirectory -Path $DestinationDir
    Copy-Item (Join-Path $SourceDir "*") $DestinationDir -Recurse -Force
}

if (-not $SkipPyInstallerBuild) {
    if ($InstallPyInstaller) {
        & $PythonExe -m pip install pyinstaller
    }

    & $PythonExe -c "import PyInstaller" | Out-Null
}

$distDir = Join-Path $importManagerDir "dist\pyinstaller"
$buildDir = Join-Path $importManagerDir "build\pyinstaller"
$pyinstallerTargetsByName = @{
    cli = @{
        Name = "cli"
        SpecPath = Join-Path $importManagerDir "bodaqs_import_agent_cli.spec"
        OutputDir = Join-Path $distDir "bodaqs-import"
        Executable = Join-Path $distDir "bodaqs-import\bodaqs-import.exe"
        WorkDir = Join-Path $buildDir "bodaqs_import_agent_cli"
    }
    setup = @{
        Name = "setup"
        SpecPath = Join-Path $importManagerDir "bodaqs_import_agent_setup.spec"
        OutputDir = Join-Path $distDir "bodaqs-import-setup"
        Executable = Join-Path $distDir "bodaqs-import-setup\bodaqs-import-setup.exe"
        WorkDir = Join-Path $buildDir "bodaqs_import_agent_setup"
    }
    service = @{
        Name = "service"
        SpecPath = Join-Path $importManagerDir "bodaqs_library_service.spec"
        OutputDir = Join-Path $distDir "bodaqs-library-service"
        Executable = Join-Path $distDir "bodaqs-library-service\bodaqs-library-service.exe"
        WorkDir = Join-Path $buildDir "bodaqs_library_service"
    }
}

$pyinstallerTargetNames = switch ($Target) {
    "cli" { @("cli") }
    "setup" { @("setup") }
    "service" { @("service") }
    "installer" { @("setup", "service") }
    "all" { @("cli", "setup", "service") }
}
$installerRequested = $Target -in @("installer", "all")
$targets = @($pyinstallerTargetNames | ForEach-Object { $pyinstallerTargetsByName[$_] })
$serviceRequested = $pyinstallerTargetNames -contains "service"

if (-not $SkipPyInstallerBuild) {
    foreach ($buildTarget in $targets) {
        if (Test-Path $buildTarget.OutputDir) {
            Remove-Item -Recurse -Force $buildTarget.OutputDir
        }
        if (Test-Path $buildTarget.WorkDir) {
            Remove-Item -Recurse -Force $buildTarget.WorkDir
        }
    }
}

if (-not $SkipPyInstallerBuild) {
    Push-Location $importManagerDir
    $previousImportManagerVersionEnv = $env:BODAQS_IMPORT_MANAGER_APP_VERSION
    $previousLibraryServiceVersionEnv = $env:BODAQS_LIBRARY_SERVICE_VERSION
    $env:BODAQS_IMPORT_MANAGER_APP_VERSION = $ImportManagerVersion
    $env:BODAQS_LIBRARY_SERVICE_VERSION = $LibraryServiceVersion
    try {
        foreach ($buildTarget in $targets) {
            & $PythonExe -m PyInstaller `
                --noconfirm `
                --clean `
                --distpath $distDir `
                --workpath $buildDir `
                $buildTarget.SpecPath
        }
    } finally {
        if ($null -eq $previousImportManagerVersionEnv) {
            Remove-Item Env:\BODAQS_IMPORT_MANAGER_APP_VERSION -ErrorAction SilentlyContinue
        } else {
            $env:BODAQS_IMPORT_MANAGER_APP_VERSION = $previousImportManagerVersionEnv
        }
        if ($null -eq $previousLibraryServiceVersionEnv) {
            Remove-Item Env:\BODAQS_LIBRARY_SERVICE_VERSION -ErrorAction SilentlyContinue
        } else {
            $env:BODAQS_LIBRARY_SERVICE_VERSION = $previousLibraryServiceVersionEnv
        }
        Pop-Location
    }
} else {
    foreach ($buildTarget in $targets) {
        if (-not (Test-Path $buildTarget.Executable)) {
            throw "SkipPyInstallerBuild was requested, but the expected bundle executable does not exist: $($buildTarget.Executable)"
        }
    }
}

if ($serviceRequested) {
    $resolvedWebAppDist = Resolve-WebAppDist
    $serviceWebDir = Join-Path $pyinstallerTargetsByName["service"].OutputDir "web"
    Copy-WebAppDist -SourceDir $resolvedWebAppDist -DestinationDir $serviceWebDir
    Write-Host "Bundled web app:" $serviceWebDir
}

Write-Host ""
Write-Host "Build complete."
foreach ($buildTarget in $targets) {
    Write-Host "Output directory:" $buildTarget.OutputDir
    Write-Host "Executable:" $buildTarget.Executable
}

if ($installerRequested) {
    $installerScript = Join-Path $importManagerDir "packaging\windows\bodaqs_import_agent_windows.iss"
    if (-not (Test-Path $installerScript)) {
        throw "Installer script not found: $installerScript"
    }

    $installerBuildDir = Join-Path $importManagerDir "build\installer\windows"
    $installerStageDir = Join-Path $installerBuildDir "staging"
    $installerOutputDir = Join-Path $importManagerDir "dist\installer\windows"
    $finalInstallerPath = Join-Path $installerOutputDir ("bodaqs-desktop-setup-" + $BundleVersion + ".exe")

    Ensure-CleanDirectory -Path $installerStageDir
    if (-not (Test-Path $installerOutputDir)) {
        New-Item -ItemType Directory -Force -Path $installerOutputDir | Out-Null
    }

    $managerStageDir = Join-Path $installerStageDir "manager"
    New-Item -ItemType Directory -Force -Path $managerStageDir | Out-Null

    Copy-Item (Join-Path $distDir "bodaqs-import-setup\*") $managerStageDir -Recurse -Force

    $serviceStageDir = Join-Path $installerStageDir "service"
    New-Item -ItemType Directory -Force -Path $serviceStageDir | Out-Null
    Copy-Item (Join-Path $distDir "bodaqs-library-service\*") $serviceStageDir -Recurse -Force

    $repoRoot = Split-Path -Parent $importManagerDir
    $demoAssetsSourceDir = Join-Path $repoRoot "demo-assets"
    $demoAssetsStageDir = Join-Path $installerStageDir "demo-assets"
    New-Item -ItemType Directory -Force -Path $demoAssetsStageDir | Out-Null
    if (Test-Path $demoAssetsSourceDir) {
        Copy-Item (Join-Path $demoAssetsSourceDir "*") $demoAssetsStageDir -Recurse -Force
    }

    $componentVersions = [ordered]@{
        bundle = [ordered]@{
            name = "BODAQS Desktop"
            version = $BundleVersion
        }
        components = @(
            [ordered]@{
                name = "BODAQS Import Manager"
                version = $ImportManagerVersion
                path = "manager\bodaqs-import-setup.exe"
            },
            [ordered]@{
                name = "BODAQS Library Service"
                version = $LibraryServiceVersion
                path = "service\bodaqs-library-service.exe"
            },
            [ordered]@{
                name = "BODAQS Workbench"
                version = $WorkbenchVersion
                path = "service\web\index.html"
            }
        )
    }
    $componentVersionsPath = Join-Path $installerStageDir "component_versions.json"
    $componentVersions | ConvertTo-Json -Depth 8 | Set-Content -Path $componentVersionsPath -Encoding UTF8

    Write-Host ""
    Write-Host "Installer staging directory:" $installerStageDir

    $resolvedInnoSetupExe = Resolve-InnoSetupCompiler -ExplicitPath $InnoSetupExe
    if (-not $resolvedInnoSetupExe) {
        Write-Warning "Inno Setup compiler (ISCC.exe) was not found. Installer staging is ready, but compilation was skipped."
        Write-Host "Expected installer script:" $installerScript
        Write-Host "Stage contents:" $installerStageDir
    } else {
        Write-Host "Using Inno Setup compiler:" $resolvedInnoSetupExe
        $innoArgs = @(
            "/DStageRoot=$installerStageDir",
            "/DAppVersion=$BundleVersion",
            "/DImportManagerVersion=$ImportManagerVersion",
            "/DLibraryServiceVersion=$LibraryServiceVersion",
            "/DWorkbenchVersion=$WorkbenchVersion",
            "/DInstallerOutputDir=$installerOutputDir"
        )
        if (Test-Path (Join-Path $demoAssetsStageDir "libraries\*\library_definition.json")) {
            $innoArgs += "/DHasDemoLibrary=1"
        }
        $innoArgs += $installerScript
        & $resolvedInnoSetupExe @innoArgs
        Write-Host "Installer output:" $finalInstallerPath
    }
}
