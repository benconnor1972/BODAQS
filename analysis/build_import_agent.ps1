param(
    [string]$PythonExe = "",
    [switch]$InstallPyInstaller,
    [ValidateSet("cli", "setup", "all")]
    [string]$Target = "cli"
)

$ErrorActionPreference = "Stop"

$analysisDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $analysisDir

if (-not $PythonExe) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $PythonExe = $venvPython
    } else {
        $PythonExe = "python"
    }
}

Write-Host "Using Python:" $PythonExe

if ($InstallPyInstaller) {
    & $PythonExe -m pip install pyinstaller
}

& $PythonExe -c "import PyInstaller" | Out-Null

$distDir = Join-Path $analysisDir "dist\pyinstaller"
$buildDir = Join-Path $analysisDir "build\pyinstaller"
$targets = switch ($Target) {
    "cli" {
        @(
            @{
                SpecPath = Join-Path $analysisDir "bodaqs_import_agent_cli.spec"
                OutputDir = Join-Path $distDir "bodaqs-import"
                Executable = Join-Path $distDir "bodaqs-import\bodaqs-import.exe"
                WorkDir = Join-Path $buildDir "bodaqs_import_agent_cli"
            }
        )
    }
    "setup" {
        @(
            @{
                SpecPath = Join-Path $analysisDir "bodaqs_import_agent_setup.spec"
                OutputDir = Join-Path $distDir "bodaqs-import-setup"
                Executable = Join-Path $distDir "bodaqs-import-setup\bodaqs-import-setup.exe"
                WorkDir = Join-Path $buildDir "bodaqs_import_agent_setup"
            }
        )
    }
    "all" {
        @(
            @{
                SpecPath = Join-Path $analysisDir "bodaqs_import_agent_cli.spec"
                OutputDir = Join-Path $distDir "bodaqs-import"
                Executable = Join-Path $distDir "bodaqs-import\bodaqs-import.exe"
                WorkDir = Join-Path $buildDir "bodaqs_import_agent_cli"
            },
            @{
                SpecPath = Join-Path $analysisDir "bodaqs_import_agent_setup.spec"
                OutputDir = Join-Path $distDir "bodaqs-import-setup"
                Executable = Join-Path $distDir "bodaqs-import-setup\bodaqs-import-setup.exe"
                WorkDir = Join-Path $buildDir "bodaqs_import_agent_setup"
            }
        )
    }
}

foreach ($buildTarget in $targets) {
    if (Test-Path $buildTarget.OutputDir) {
        Remove-Item -Recurse -Force $buildTarget.OutputDir
    }
    if (Test-Path $buildTarget.WorkDir) {
        Remove-Item -Recurse -Force $buildTarget.WorkDir
    }
}

Push-Location $analysisDir
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

Write-Host ""
Write-Host "Build complete."
foreach ($buildTarget in $targets) {
    Write-Host "Output directory:" $buildTarget.OutputDir
    Write-Host "Executable:" $buildTarget.Executable
}
