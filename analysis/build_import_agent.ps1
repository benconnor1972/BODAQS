param(
    [string]$PythonExe = "",
    [switch]$InstallPyInstaller
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
$specPath = Join-Path $analysisDir "bodaqs_import_agent_cli.spec"

if (Test-Path $distDir) {
    Remove-Item -Recurse -Force $distDir
}
if (Test-Path $buildDir) {
    Remove-Item -Recurse -Force $buildDir
}

Push-Location $analysisDir
try {
    & $PythonExe -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $distDir `
        --workpath $buildDir `
        $specPath
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Build complete."
Write-Host "Output directory:" (Join-Path $distDir "bodaqs-import")
Write-Host "Executable:" (Join-Path $distDir "bodaqs-import\bodaqs-import.exe")
