# Windows Certum Release Signing

This procedure signs the final BODAQS Windows installer after a `Desktop-v*`
GitHub Actions release-candidate build has passed. It deliberately keeps the
Certum Open Source Code Signing certificate and SimplySign authentication on
the release approver's Windows PC rather than in GitHub Actions.

The preferred workflow uses
[`sign_windows_release.ps1`](../sign_windows_release.ps1). The script validates
the unsigned candidate, signs and timestamps a temporary copy, verifies the
result, and creates a clean directory containing the two files that may be
published. The downloaded GitHub candidate is never modified.

## Security boundary

The script may locate the public certificate and ask Windows to use its private
key, but it does not and must not handle:

- a SimplySign mobile token or one-time password;
- a card PIN;
- a private key or exported signing credential; or
- unattended GitHub release publication.

SimplySign Desktop presents any required authentication or approval prompt
directly to the release approver. Never store a token, PIN, private key, or
other signing credential in this repository, a shell script, a terminal
transcript, or GitHub Actions.

The Certum Open Source Code Signing certificate must be used only for eligible
BODAQS free and open-source software releases.

## Prerequisites

- An issued, activated, and unexpired Certum Open Source Code Signing in Cloud
  certificate.
- The current 64-bit SimplySign Desktop installed on the release PC.
- The SimplySign mobile application available for login or approval.
- The 64-bit Windows SDK `signtool.exe` installed.
- The certificate SHA-1 thumbprint. The thumbprint identifies the public
  certificate and is not a private signing credential.
- A successful tagged `Desktop CI` workflow run.

Use PowerShell 5.1 or newer on Windows. Run the commands from the BODAQS
repository root.

## 1. Download the release candidate

From the successful `Desktop CI` run for `Desktop-v<version>`, download:

```text
windows-x64-<version>-certum-signing-candidate
```

GitHub normally downloads the artifact as a ZIP. It contains the unsigned
`bodaqs-desktop-setup-<version>.exe` and its GitHub-generated `.exe.sha256`
file. The signing script accepts the ZIP directly; manual extraction is not
required.

Do not rename or edit either file before validation.

## 2. Connect SimplySign

1. Start SimplySign Desktop.
2. Generate a fresh login token in the SimplySign mobile application when
   required.
3. Use **Connect to SimplySign** from the Desktop system-tray menu.
4. Confirm that the expected virtual card and code-signing certificate appear
   under **Manage certificates → Certificate list**.

The certificate must be exposed in the current user's Windows Personal
certificate store with its private key available. This can be checked with:

```powershell
$Thumbprint = "CERTIFICATE_SHA1_THUMBPRINT" -replace "\s", ""
Get-Item "Cert:\CurrentUser\My\$Thumbprint" |
  Format-List Subject, Issuer, NotAfter, Thumbprint, HasPrivateKey
```

`HasPrivateKey` must be `True`. If it is false, reconnect SimplySign Desktop
with a fresh mobile token before proceeding.

## 3. Run a non-signing preflight

Preflight checks the ZIP structure, original checksum, SignTool installation,
certificate validity, Code Signing EKU, and private-key availability. It does
not sign or create release output.

```powershell
.\import-manager\sign_windows_release.ps1 `
  -CandidatePath "$env:USERPROFILE\Downloads\windows-x64-<version>-certum-signing-candidate.zip" `
  -CertificateThumbprint "CERTIFICATE_SHA1_THUMBPRINT" `
  -PreflightOnly
```

If the artifact has already been extracted, `-CandidatePath` may instead name
the extracted directory or the unsigned installer itself. When an installer is
provided directly, its adjacent `.exe.sha256` file is still required.

Do not continue unless the script reports:

```text
BODAQS Windows release-signing preflight passed.
```

Inspect the printed installer path, checksum, certificate subject, issuer,
expiry, thumbprint, timestamp service, and intended output directory.

## 4. Sign the release candidate

Run the same command without `-PreflightOnly`:

```powershell
.\import-manager\sign_windows_release.ps1 `
  -CandidatePath "$env:USERPROFILE\Downloads\windows-x64-<version>-certum-signing-candidate.zip" `
  -CertificateThumbprint "CERTIFICATE_SHA1_THUMBPRINT"
```

The script deliberately requests confirmation before using the certificate.
Confirm only after checking both the installer and certificate displayed in
the prompt. Complete any PIN or approval request only in the SimplySign user
interface.

The script then:

1. extracts the candidate into an isolated temporary directory when needed;
2. verifies the original SHA-256 checksum;
3. confirms that the source candidate is unsigned;
4. validates the selected certificate and Code Signing EKU;
5. signs a temporary copy using a SHA-256 Authenticode signature;
6. obtains an RFC 3161 SHA-256 timestamp from `http://time.certum.pl`;
7. verifies the signature, selected signer, certificate chain, and timestamp;
8. generates a new SHA-256 checksum for the signed installer; and
9. copies only the signed installer and new checksum to the release output
   directory.

By default the output is a sibling of the ZIP or directory with `-signed`
appended to its name. To choose a different empty or nonexistent directory:

```powershell
.\import-manager\sign_windows_release.ps1 `
  -CandidatePath "C:\Release\windows-x64-<version>-certum-signing-candidate.zip" `
  -CertificateThumbprint "CERTIFICATE_SHA1_THUMBPRINT" `
  -OutputDirectory "C:\Release\windows-x64-<version>-signed"
```

The script refuses to write into a nonempty output directory. It does not
delete or overwrite an earlier release result.

## 5. Inspect and test the result

A successful run finishes with:

```text
Windows release signing completed successfully.
```

The output directory must contain exactly:

```text
bodaqs-desktop-setup-<version>.exe
bodaqs-desktop-setup-<version>.exe.sha256
```

Before publication:

1. Run the installer on a clean supported Windows machine or VM.
2. Open the installer's **Properties → Digital Signatures** page.
3. Confirm the expected Certum signer and a valid countersignature/timestamp.
4. Re-run verification independently if desired:

   ```powershell
   signtool verify /pa /all /tw /v `
     ".\bodaqs-desktop-setup-<version>.exe"
   ```

5. Check the published checksum:

   ```powershell
   Get-FileHash -Algorithm SHA256 `
     ".\bodaqs-desktop-setup-<version>.exe"
   Get-Content ".\bodaqs-desktop-setup-<version>.exe.sha256"
   ```

The calculated and recorded hashes must match.

## 6. Publish deliberately

Create or edit the GitHub Release for the same `Desktop-v<version>` tag. Attach:

- the signed Windows installer and new checksum from the script's output;
- `BODAQS-Import-Manager-<version>-macos-arm64.dmg` and
  `BODAQS-Import-Manager-<version>-macos-x64.dmg`; and
- the Linux archive and its Sigstore verification bundle.

Do not attach the original Windows candidate ZIP, unsigned installer, or old
checksum to the public release. Signing and publishing remain separate actions;
the script does not upload release assets.

## Troubleshooting

### Private key unavailable

If preflight says that the certificate is visible but its private key is
unavailable, or SignTool reports `After Private Key filter, 0 certs were left`:

1. disconnect and restart SimplySign Desktop;
2. connect again with a fresh mobile token;
3. confirm the virtual card and certificate are listed;
4. rerun `-PreflightOnly` so the certificate object is refreshed; and
5. repair or update the current 64-bit SimplySign Desktop installation if
   `HasPrivateKey` remains false.

Do not delete or reinstall the certificate itself as a first response.

### SignTool not found

Install the Windows SDK signing tools or supply the exact executable:

```powershell
.\import-manager\sign_windows_release.ps1 `
  -CandidatePath "C:\Release\candidate.zip" `
  -CertificateThumbprint "CERTIFICATE_SHA1_THUMBPRINT" `
  -SignToolPath "C:\Program Files (x86)\Windows Kits\10\bin\<sdk-version>\x64\signtool.exe"
```

### Timestamp failure

Do not publish an installer without a verified timestamp. Check internet,
firewall, and proxy access to `http://time.certum.pl`, reconnect SimplySign if
needed, and rerun from the original candidate. The script never promotes a
failed working copy into the release output directory.

### Existing output directory is nonempty

Select a new `-OutputDirectory` or deliberately archive the previous result.
The script does not remove prior release files automatically.

## Scope of the current signature

This procedure signs the outer Inno Setup installer, matching the present
GitHub candidate workflow. It does not retrospectively sign every executable
embedded inside the installer. Signing all installed component executables
would require signing the staged binaries before compiling Inno Setup and then
signing the finished installer as a separate final step.

Authenticode signing identifies the publisher and protects installer integrity,
but a newly used certificate may still encounter Microsoft SmartScreen
reputation warnings while reputation develops.
