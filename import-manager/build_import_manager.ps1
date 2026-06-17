param(
    [string]$PythonExe = "",
    [switch]$InstallPyInstaller,
    [switch]$SkipPyInstallerBuild,
    [ValidateSet("cli", "setup", "installer", "all")]
    [string]$Target = "cli",
    [string]$InnoSetupExe = "",
    [string]$AppVersion = "0.1.4-dev"
)

$ErrorActionPreference = "Stop"

$importManagerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $importManagerDir
$analysisDir = Join-Path $repoRoot "analysis"

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
}

$pyinstallerTargetNames = switch ($Target) {
    "cli" { @("cli") }
    "setup" { @("setup") }
    "installer" { @("setup") }
    "all" { @("cli", "setup") }
}
$installerRequested = $Target -in @("installer", "all")
$targets = @($pyinstallerTargetNames | ForEach-Object { $pyinstallerTargetsByName[$_] })

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
        Pop-Location
    }
} else {
    foreach ($buildTarget in $targets) {
        if (-not (Test-Path $buildTarget.Executable)) {
            throw "SkipPyInstallerBuild was requested, but the expected bundle executable does not exist: $($buildTarget.Executable)"
        }
    }
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
    $finalInstallerPath = Join-Path $installerOutputDir ("bodaqs-import-manager-setup-" + $AppVersion + ".exe")

    Ensure-CleanDirectory -Path $installerStageDir
    if (-not (Test-Path $installerOutputDir)) {
        New-Item -ItemType Directory -Force -Path $installerOutputDir | Out-Null
    }

    $managerStageDir = Join-Path $installerStageDir "manager"
    New-Item -ItemType Directory -Force -Path $managerStageDir | Out-Null

    Copy-Item (Join-Path $distDir "bodaqs-import-setup\*") $managerStageDir -Recurse -Force

    Write-Host ""
    Write-Host "Installer staging directory:" $installerStageDir

    $resolvedInnoSetupExe = Resolve-InnoSetupCompiler -ExplicitPath $InnoSetupExe
    if (-not $resolvedInnoSetupExe) {
        Write-Warning "Inno Setup compiler (ISCC.exe) was not found. Installer staging is ready, but compilation was skipped."
        Write-Host "Expected installer script:" $installerScript
        Write-Host "Stage contents:" $installerStageDir
    } else {
        Write-Host "Using Inno Setup compiler:" $resolvedInnoSetupExe
        & $resolvedInnoSetupExe `
            "/DStageRoot=$installerStageDir" `
            "/DAppVersion=$AppVersion" `
            "/DInstallerOutputDir=$installerOutputDir" `
            $installerScript
        Write-Host "Installer output:" $finalInstallerPath
    }
}
