#Requires -Version 5.1

<#
.SYNOPSIS
Validates, signs, timestamps, and verifies a BODAQS Windows release candidate.

.DESCRIPTION
Accepts the GitHub Actions Certum signing-candidate ZIP, its extracted
directory, or the installer executable itself. The script verifies the
GitHub-generated SHA-256 checksum before doing any signing work, signs a copy
of the installer through the certificate exposed by SimplySign Desktop,
verifies the Authenticode signature and RFC 3161 timestamp, and writes a clean
release directory containing the signed installer and a new checksum.

The source candidate is never modified. The script never reads or stores a
SimplySign token, PIN, certificate private key, or other signing credential.

.PARAMETER CandidatePath
Path to the GitHub signing-candidate ZIP, its extracted directory, or the
unsigned bodaqs-desktop-setup-*.exe installer.

.PARAMETER CertificateThumbprint
SHA-1 thumbprint of the Certum code-signing certificate exposed in the current
user's Personal certificate store.

.PARAMETER OutputDirectory
Directory to receive the signed installer and its new .sha256 file. It must be
absent or empty. By default, a sibling directory with a -signed suffix is used.

.PARAMETER SignToolPath
Optional explicit path to signtool.exe. If omitted, the script searches PATH
and installed 64-bit Windows SDKs.

.PARAMETER TimestampUrl
RFC 3161 timestamp service. Defaults to Certum's documented endpoint.

.PARAMETER PreflightOnly
Validate the candidate, checksum, SignTool, and certificate without signing or
creating release output.

.EXAMPLE
.\import-manager\sign_windows_release.ps1 `
  -CandidatePath "$env:USERPROFILE\Downloads\windows-x64-0.3.0-beta-certum-signing-candidate.zip" `
  -CertificateThumbprint "0123456789ABCDEF0123456789ABCDEF01234567" `
  -PreflightOnly

.EXAMPLE
.\import-manager\sign_windows_release.ps1 `
  -CandidatePath "$env:USERPROFILE\Downloads\windows-x64-0.3.0-beta-certum-signing-candidate.zip" `
  -CertificateThumbprint "0123456789ABCDEF0123456789ABCDEF01234567"
#>

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$CandidatePath,

    [Parameter(Mandatory = $true)]
    [string]$CertificateThumbprint,

    [string]$OutputDirectory = "",
    [string]$SignToolPath = "",
    [string]$TimestampUrl = "http://time.certum.pl",
    [switch]$PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# PowerShell propagates -WhatIf into internal New-Item/Expand-Archive calls,
# which would prevent the temporary files needed to validate a ZIP. Treat it
# as the documented non-signing preflight instead; ShouldProcess is never
# reached in this mode.
if ($WhatIfPreference) {
    Write-Host "WhatIf mode: running the complete non-signing preflight."
    $PreflightOnly = $true
    $WhatIfPreference = $false
}

$codeSigningEkuOid = "1.3.6.1.5.5.7.3.3"
$temporaryRoot = $null

function New-SafeTemporaryDirectory {
    $systemTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $path = Join-Path $systemTemp ("bodaqs-windows-signing-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $path | Out-Null
    return (Resolve-Path -LiteralPath $path).Path
}

function Remove-SafeTemporaryDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return
    }

    $systemTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $resolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
    if (-not $resolved.StartsWith($systemTemp, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a temporary directory outside the system temp root: $resolved"
    }
    if (-not (Split-Path -Leaf $resolved).StartsWith("bodaqs-windows-signing-")) {
        throw "Refusing to remove a directory without the expected signing-work prefix: $resolved"
    }

    Remove-Item -LiteralPath $resolved -Recurse -Force
}

function Resolve-SignToolExecutable {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        if (-not (Test-Path -LiteralPath $ExplicitPath -PathType Leaf)) {
            throw "SignTool was not found at the supplied path: $ExplicitPath"
        }
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }

    $onPath = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if ($onPath) {
        return $onPath.Source
    }

    $sdkBinRoots = @()
    if (${env:ProgramFiles(x86)}) {
        $sdkBinRoots += (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin")
    }
    if ($env:ProgramFiles) {
        $sdkBinRoots += (Join-Path $env:ProgramFiles "Windows Kits\10\bin")
    }

    $candidates = @()
    foreach ($sdkBinRoot in ($sdkBinRoots | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $sdkBinRoot -PathType Container) {
            $candidates += Get-ChildItem -Path (Join-Path $sdkBinRoot "*\x64\signtool.exe") -File -ErrorAction SilentlyContinue
        }
    }

    $selected = $candidates |
        Sort-Object {
            $sdkVersion = [version]"0.0"
            if ([version]::TryParse($_.Directory.Parent.Name, [ref]$sdkVersion)) {
                return $sdkVersion
            }
            return [version]"0.0"
        } -Descending |
        Select-Object -First 1
    if (-not $selected) {
        throw "SignTool was not found. Install the Windows SDK signing tools or provide -SignToolPath."
    }
    return $selected.FullName
}

function Resolve-OutputPath {
    param(
        [Parameter(Mandatory = $true)][System.IO.FileSystemInfo]$Candidate,
        [string]$ExplicitPath
    )

    if ($ExplicitPath) {
        return [IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ExplicitPath))
    }

    if ($Candidate.PSIsContainer) {
        return Join-Path $Candidate.Parent.FullName ($Candidate.Name + "-signed")
    }

    $baseName = [IO.Path]::GetFileNameWithoutExtension($Candidate.Name)
    return Join-Path $Candidate.Directory.FullName ($baseName + "-signed")
}

function Assert-OutputDirectoryAvailable {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "The output path exists and is not a directory: $Path"
    }
    if (@(Get-ChildItem -LiteralPath $Path -Force).Count -gt 0) {
        throw "The output directory must be absent or empty: $Path"
    }
}

function Find-CandidateInstaller {
    param([Parameter(Mandatory = $true)][string]$SearchRoot)

    $installers = @(
        Get-ChildItem -LiteralPath $SearchRoot -Recurse -File -Filter "bodaqs-desktop-setup-*.exe"
    )
    if ($installers.Count -ne 1) {
        throw "Expected exactly one bodaqs-desktop-setup-*.exe under '$SearchRoot'; found $($installers.Count)."
    }
    return $installers[0]
}

function Read-ExpectedChecksum {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "The GitHub-generated checksum file was not found: $Path"
    }
    $content = (Get-Content -LiteralPath $Path -Raw).Trim()
    $match = [regex]::Match($content, "^(?<hash>[0-9A-Fa-f]{64})(?:\s+\*?.+)?$")
    if (-not $match.Success) {
        throw "The checksum file is not in the expected SHA-256 format: $Path"
    }
    return $match.Groups["hash"].Value.ToUpperInvariant()
}

function Resolve-CodeSigningCertificate {
    param([Parameter(Mandatory = $true)][string]$Thumbprint)

    $cleanThumbprint = ($Thumbprint -replace "[^0-9A-Fa-f]", "").ToUpperInvariant()
    if ($cleanThumbprint -notmatch "^[0-9A-F]{40}$") {
        throw "CertificateThumbprint must contain exactly 40 hexadecimal characters."
    }

    $certificatePath = "Cert:\CurrentUser\My\$cleanThumbprint"
    if (-not (Test-Path -LiteralPath $certificatePath)) {
        throw "The certificate was not found in the current user's Personal store: $cleanThumbprint"
    }
    $certificate = Get-Item -LiteralPath $certificatePath
    $now = Get-Date
    if ($certificate.NotBefore -gt $now) {
        throw "The selected certificate is not valid until $($certificate.NotBefore)."
    }
    if ($certificate.NotAfter -le $now) {
        throw "The selected certificate expired at $($certificate.NotAfter)."
    }
    if (-not $certificate.HasPrivateKey) {
        throw "The selected certificate is visible, but its private key is unavailable. Connect SimplySign Desktop with a fresh mobile token, then rerun the script."
    }

    $ekuOids = @(
        $certificate.EnhancedKeyUsageList | ForEach-Object {
            if ($_.ObjectId -is [string]) {
                $_.ObjectId
            } elseif ($null -ne $_.ObjectId -and $_.ObjectId.PSObject.Properties.Name -contains "Value") {
                $_.ObjectId.Value
            }
        }
    )
    if ($ekuOids -notcontains $codeSigningEkuOid) {
        throw "The selected certificate does not contain the Code Signing EKU ($codeSigningEkuOid)."
    }
    return $certificate
}

function Invoke-SignToolChecked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Operation
    )

    & $Executable @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Operation failed with SignTool exit code $exitCode. Review the SignTool output above."
    }
}

try {
    if (-not (Test-Path -LiteralPath $CandidatePath)) {
        throw "CandidatePath was not found: $CandidatePath"
    }

    $candidate = Get-Item -LiteralPath (Resolve-Path -LiteralPath $CandidatePath).Path
    $temporaryRoot = New-SafeTemporaryDirectory
    $candidateSearchRoot = $null
    $sourceInstaller = $null

    if ($candidate.PSIsContainer) {
        $candidateSearchRoot = $candidate.FullName
        $sourceInstaller = Find-CandidateInstaller -SearchRoot $candidateSearchRoot
    } elseif ($candidate.Extension -ieq ".zip") {
        $candidateSearchRoot = Join-Path $temporaryRoot "candidate"
        New-Item -ItemType Directory -Path $candidateSearchRoot | Out-Null
        Write-Host "Extracting signing candidate:" $candidate.FullName
        Expand-Archive -LiteralPath $candidate.FullName -DestinationPath $candidateSearchRoot
        $sourceInstaller = Find-CandidateInstaller -SearchRoot $candidateSearchRoot
    } elseif ($candidate.Extension -ieq ".exe" -and $candidate.Name -like "bodaqs-desktop-setup-*.exe") {
        $sourceInstaller = $candidate
    } else {
        throw "CandidatePath must be a signing-candidate ZIP, an extracted directory, or a bodaqs-desktop-setup-*.exe file."
    }

    $sourceChecksumPath = "$($sourceInstaller.FullName).sha256"
    $expectedHash = Read-ExpectedChecksum -Path $sourceChecksumPath
    $actualHash = (Get-FileHash -LiteralPath $sourceInstaller.FullName -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Candidate checksum mismatch. Expected $expectedHash but calculated $actualHash."
    }

    $existingSignature = Get-AuthenticodeSignature -LiteralPath $sourceInstaller.FullName
    if ($null -ne $existingSignature.SignerCertificate) {
        throw "The source candidate already contains an Authenticode signature. Use the original unsigned GitHub candidate."
    }

    $resolvedSignTool = Resolve-SignToolExecutable -ExplicitPath $SignToolPath
    $certificate = Resolve-CodeSigningCertificate -Thumbprint $CertificateThumbprint
    $resolvedOutputDirectory = Resolve-OutputPath -Candidate $candidate -ExplicitPath $OutputDirectory
    Assert-OutputDirectoryAvailable -Path $resolvedOutputDirectory

    Write-Host ""
    Write-Host "BODAQS Windows release-signing preflight passed." -ForegroundColor Green
    Write-Host "  Candidate source:" $candidate.FullName
    Write-Host "  Installer:" $sourceInstaller.Name
    Write-Host "  SHA-256:" $actualHash
    Write-Host "  SignTool:" $resolvedSignTool
    Write-Host "  Certificate subject:" $certificate.Subject
    Write-Host "  Certificate issuer:" $certificate.Issuer
    Write-Host "  Certificate expires:" $certificate.NotAfter
    Write-Host "  Certificate thumbprint:" $certificate.Thumbprint
    Write-Host "  Timestamp service:" $TimestampUrl
    Write-Host "  Release output:" $resolvedOutputDirectory

    if ($PreflightOnly) {
        Write-Host "Preflight-only mode: no installer was signed and no release output was created."
        return
    }

    $action = "Sign and timestamp with certificate '$($certificate.Subject)', verify, and create release output"
    $confirmationTarget = "$($candidate.FullName) -> $($sourceInstaller.Name)"
    if (-not $PSCmdlet.ShouldProcess($confirmationTarget, $action)) {
        Write-Host "Signing cancelled."
        return
    }

    $workDirectory = Join-Path $temporaryRoot "work"
    New-Item -ItemType Directory -Path $workDirectory | Out-Null
    $workingInstaller = Join-Path $workDirectory $sourceInstaller.Name
    Copy-Item -LiteralPath $sourceInstaller.FullName -Destination $workingInstaller

    Write-Host ""
    Write-Host "Requesting the Authenticode signature. Complete any SimplySign approval or PIN prompt on this PC."
    Invoke-SignToolChecked -Executable $resolvedSignTool -Operation "Signing" -Arguments @(
        "sign",
        "/sha1", $certificate.Thumbprint,
        "/fd", "SHA256",
        "/tr", $TimestampUrl,
        "/td", "SHA256",
        "/v",
        $workingInstaller
    )

    Write-Host ""
    Write-Host "Verifying the Authenticode signature and required timestamp."
    Invoke-SignToolChecked -Executable $resolvedSignTool -Operation "Signature verification" -Arguments @(
        "verify",
        "/pa",
        "/all",
        "/tw",
        "/v",
        $workingInstaller
    )

    $signature = Get-AuthenticodeSignature -LiteralPath $workingInstaller
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "PowerShell Authenticode verification returned status '$($signature.Status)': $($signature.StatusMessage)"
    }
    if ($null -eq $signature.SignerCertificate) {
        throw "The signed installer does not expose a signer certificate after verification."
    }
    if ($signature.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) {
        throw "The verified signer thumbprint does not match the selected certificate."
    }
    if ($null -eq $signature.TimeStamperCertificate) {
        throw "The signature is valid but no timestamp certificate was found. The installer will not be released."
    }

    $signedHash = (Get-FileHash -LiteralPath $workingInstaller -Algorithm SHA256).Hash.ToUpperInvariant()
    $workingChecksum = "$workingInstaller.sha256"
    "{0} *{1}" -f $signedHash, $sourceInstaller.Name |
        Set-Content -LiteralPath $workingChecksum -NoNewline -Encoding ascii

    if (-not (Test-Path -LiteralPath $resolvedOutputDirectory)) {
        New-Item -ItemType Directory -Path $resolvedOutputDirectory | Out-Null
    }
    $releaseInstaller = Join-Path $resolvedOutputDirectory $sourceInstaller.Name
    $releaseChecksum = "$releaseInstaller.sha256"
    Copy-Item -LiteralPath $workingInstaller -Destination $releaseInstaller
    Copy-Item -LiteralPath $workingChecksum -Destination $releaseChecksum

    $publishedHash = (Get-FileHash -LiteralPath $releaseInstaller -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($publishedHash -ne $signedHash) {
        throw "The release copy hash differs from the verified signed installer."
    }

    Write-Host ""
    Write-Host "Windows release signing completed successfully." -ForegroundColor Green
    Write-Host "  Signed installer:" $releaseInstaller
    Write-Host "  Signed SHA-256:" $signedHash
    Write-Host "  Checksum file:" $releaseChecksum
    Write-Host "  Signer:" $signature.SignerCertificate.Subject
    Write-Host "  Timestamp authority:" $signature.TimeStamperCertificate.Subject
    Write-Host ""
    Write-Host "Only the two files in the release output directory should be attached to the GitHub Release."

    [pscustomobject]@{
        Installer = $releaseInstaller
        Checksum = $releaseChecksum
        SHA256 = $signedHash
        Signer = $signature.SignerCertificate.Subject
        SignerThumbprint = $signature.SignerCertificate.Thumbprint
        TimestampAuthority = $signature.TimeStamperCertificate.Subject
    }
} finally {
    if ($temporaryRoot) {
        Remove-SafeTemporaryDirectory -Path $temporaryRoot
    }
}
