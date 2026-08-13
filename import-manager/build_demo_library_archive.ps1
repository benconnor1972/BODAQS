param(
    [string]$DemoLibraryVersion = "0.2.2-beta",
    [string]$DemoAssetsSource = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

$importManagerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $importManagerDir
if (-not $DemoAssetsSource) {
    $DemoAssetsSource = Join-Path $repoRoot "demo-assets"
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $importManagerDir "dist\demo-library"
}

$sourceRoot = (Resolve-Path -LiteralPath $DemoAssetsSource).Path
$demoDefinition = Join-Path $sourceRoot "libraries\bodaqs-demo\library_definition.json"
if (-not (Test-Path -LiteralPath $demoDefinition)) {
    throw "A packaged BODAQS Demo Library was not found under: $sourceRoot"
}

$archiveName = "BODAQS-Demo-Library-$DemoLibraryVersion.zip"
$archivePath = Join-Path $OutputDir $archiveName
$manifestPath = Join-Path $OutputDir "BODAQS-Demo-Library-$DemoLibraryVersion.manifest.json"
if ((Test-Path -LiteralPath $archivePath) -or (Test-Path -LiteralPath $manifestPath)) {
    throw "Archive output already exists for $DemoLibraryVersion. Choose a new version or remove the existing archive and manifest first."
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$excludedRoots = @("video", ".bodaqs_library_api_cache")
$contents = New-Object System.Collections.Generic.List[object]
$sha256 = [System.Security.Cryptography.SHA256]::Create()
$archive = [System.IO.Compression.ZipFile]::Open($archivePath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $files = Get-ChildItem -LiteralPath $sourceRoot -Recurse -File | Sort-Object FullName
    foreach ($file in $files) {
        $relativePath = $file.FullName.Substring($sourceRoot.Length).TrimStart('\', '/') -replace '\\', '/'
        $pathParts = $relativePath.Split('/')
        if ($excludedRoots -contains $pathParts[0] -or $file.Name -eq "session_videos.json") {
            continue
        }

        $entry = $archive.CreateEntry($relativePath, [System.IO.Compression.CompressionLevel]::Optimal)
        $entryStream = $entry.Open()
        try {
            if ($relativePath -eq "demo_manifest.json") {
                $demoManifest = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
                $demoManifest.videos = @()
                $contentBytes = [System.Text.Encoding]::UTF8.GetBytes(($demoManifest | ConvertTo-Json -Depth 16) + "`n")
                $entryStream.Write($contentBytes, 0, $contentBytes.Length)
            } else {
                $contentBytes = [System.IO.File]::ReadAllBytes($file.FullName)
                $entryStream.Write($contentBytes, 0, $contentBytes.Length)
            }
        } finally {
            $entryStream.Dispose()
        }

        $contents.Add([ordered]@{
            path = $relativePath
            bytes = $contentBytes.Length
            sha256 = ($sha256.ComputeHash($contentBytes) | ForEach-Object { $_.ToString("x2") }) -join ""
        })
    }
} finally {
    $archive.Dispose()
    $sha256.Dispose()
}

$releaseManifest = [ordered]@{
    schema = "bodaqs.demo_library_archive_manifest"
    version = 1
    demo_library_version = $DemoLibraryVersion
    archive = [ordered]@{
        filename = $archiveName
        bytes = (Get-Item -LiteralPath $archivePath).Length
        sha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    excluded = @(
        "video/**",
        ".bodaqs_library_api_cache/**",
        "**/session_videos.json"
    )
    contents = $contents
}
$releaseManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "Demo library archive:" $archivePath
Write-Host "Archive manifest:" $manifestPath
