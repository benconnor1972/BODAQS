Param(
    [switch]$IncludeSessionNotebook,
    [switch]$KeepOutputs,
    [int]$TimeoutSeconds = 1200
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$analysisDir = Join-Path $repoRoot "analysis"
$pythonExe = Join-Path $repoRoot ".venv\\Scripts\\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Expected venv Python at '$pythonExe'."
}

$runtimeDir = Join-Path $analysisDir ".jupyter_runtime"
$outputDir = Join-Path $analysisDir ".nb_smoke_exec"
$ipythonDir = Join-Path $analysisDir ".ipython"

if (-not (Test-Path $runtimeDir)) {
    New-Item -ItemType Directory -Path $runtimeDir | Out-Null
}
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}
if (-not (Test-Path $ipythonDir)) {
    New-Item -ItemType Directory -Path $ipythonDir | Out-Null
}

$env:JUPYTER_ALLOW_INSECURE_WRITES = "1"
$env:JUPYTER_RUNTIME_DIR = $runtimeDir
$env:IPYTHONDIR = $ipythonDir

$notebooks = @(
    "bodaqs_widget_test_notebook.ipynb",
    "bodaqs_event_schema_test_harness.ipynb"
)

if ($IncludeSessionNotebook) {
    $notebooks += "bodaqs_session_test_notebook.ipynb"
}

Push-Location $analysisDir
try {
    foreach ($nb in $notebooks) {
        $name = [IO.Path]::GetFileNameWithoutExtension($nb)
        $outFile = "__exec_$name.ipynb"

        Write-Host "Executing $nb ..."
        & $pythonExe -m jupyter nbconvert `
            --to notebook `
            --execute $nb `
            --output $outFile `
            --ExecutePreprocessor.timeout=$TimeoutSeconds

        if ($LASTEXITCODE -ne 0) {
            throw "Notebook execution failed: $nb"
        }

        $src = Join-Path $analysisDir $outFile
        $dst = Join-Path $outputDir $outFile
        Move-Item -Force -Path $src -Destination $dst
        Write-Host "Wrote $dst"
    }
}
finally {
    Pop-Location
}

if (-not $KeepOutputs) {
    Get-ChildItem -Path $outputDir -Filter "__exec_*.ipynb" -ErrorAction SilentlyContinue | Remove-Item -Force
    Write-Host "Removed temporary executed notebooks from $outputDir"
}

Write-Host "Notebook smoke tests completed successfully."
