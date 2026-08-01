param(
    [string]$DemoLibraryVersion = "0.2.1-beta",
    [string]$InnoSetupExe = "",
    [string]$DemoAssetsSource = ""
)

$ErrorActionPreference = "Stop"

$importManagerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $importManagerDir
if (-not $DemoAssetsSource) {
    $DemoAssetsSource = Join-Path $repoRoot "demo-assets"
}
if (-not (Test-Path (Join-Path $DemoAssetsSource "libraries\bodaqs-demo\library_definition.json"))) {
    throw "A packaged BODAQS Demo Library was not found under: $DemoAssetsSource"
}

function Resolve-InnoSetupCompiler {
    param([string]$ExplicitPath)

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
    return if ($command) { $command.Source } else { $null }
}

function Reset-Directory {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (Test-Path $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

$buildRoot = Join-Path $importManagerDir "build\demo-library-installer\windows"
$stageRoot = Join-Path $buildRoot "staging"
$stageAssets = Join-Path $stageRoot "demo-assets"
$outputDir = Join-Path $importManagerDir "dist\demo-library-installer\windows"
$installerScript = Join-Path $importManagerDir "packaging\windows\bodaqs_demo_library_windows.iss"
$expectedInstaller = Join-Path $outputDir "bodaqs-demo-library-setup-$DemoLibraryVersion.exe"

Reset-Directory -Path $stageRoot
New-Item -ItemType Directory -Force -Path $stageAssets | Out-Null

# Demo video files are intentionally distributed separately from this lightweight installer.
Get-ChildItem -LiteralPath $DemoAssetsSource -Recurse -Force | ForEach-Object {
    $relativePath = $_.FullName.Substring((Resolve-Path $DemoAssetsSource).Path.Length).TrimStart('\')
    if (-not $relativePath -or $relativePath -match '^(video|\.bodaqs_library_api_cache)(\\|$)') {
        return
    }
    $destination = Join-Path $stageAssets $relativePath
    if ($_.PSIsContainer) {
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
    } else {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
    }
}

if (Test-Path (Join-Path $stageAssets "video")) {
    throw "Video assets were unexpectedly staged."
}

# Do not leave attachment records that point to videos intentionally omitted from this package.
Get-ChildItem -LiteralPath $stageAssets -Recurse -Filter "session_videos.json" -File | Remove-Item -Force
$manifestPath = Join-Path $stageAssets "demo_manifest.json"
if (Test-Path $manifestPath) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $manifest.videos = @()
    $manifest | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
}

$iscc = Resolve-InnoSetupCompiler -ExplicitPath $InnoSetupExe
if (-not $iscc) {
    throw "Inno Setup compiler (ISCC.exe) was not found."
}
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
& $iscc "/DStageRoot=$stageRoot" "/DAppVersion=$DemoLibraryVersion" "/DInstallerOutputDir=$outputDir" $installerScript

if (-not (Test-Path $expectedInstaller)) {
    throw "Demo library installer was not produced: $expectedInstaller"
}

Write-Host "Demo library installer:" $expectedInstaller
