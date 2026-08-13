# Windows Certum Release Signing

This procedure signs the final BODAQS Windows installer after a `Desktop-v*`
GitHub Actions release-candidate build has passed. It deliberately keeps the
Certum Open Source Code Signing certificate and SimplySign authentication on
the release approver's Windows PC, rather than in GitHub Actions.

## Prerequisites

- An issued and activated Certum Open Source Code Signing in Cloud certificate.
- SimplySign Desktop installed, signed in, and configured for the certificate.
- The Windows SDK `signtool.exe` available on the release PC.
- The certificate SHA-1 thumbprint from SimplySign Desktop or the Windows
  certificate store.

The certificate must be used only for the BODAQS project's free, open-source
software releases. Do not store a SimplySign token, PIN, certificate private
key, or any signing credential in this repository or GitHub Actions.

## Sign a tagged release candidate

1. Push a `Desktop-v<version>` tag and wait for the `Desktop CI` run to pass.
2. Download its `windows-x64-<version>-certum-signing-candidate` artifact.
3. Check the downloaded installer against its adjacent `.exe.sha256` file:

   ```powershell
   Get-FileHash -Algorithm SHA256 .\BODAQS-Import-Manager-<version>-Setup.exe
   ```

4. Open SimplySign Desktop and ensure the Certum signing certificate is
   available. If the certificate requires a PIN, provide it only in the
   SimplySign prompt.
5. Sign the final installer. Replace the placeholder thumbprint and filename:

   ```powershell
   signtool sign /sha1 "CERTIFICATE_SHA1_THUMBPRINT" /fd SHA256 `
     /tr http://time.certum.pl /td SHA256 /v `
     ".\BODAQS-Import-Manager-<version>-Setup.exe"
   ```

6. Verify the completed Authenticode signature:

   ```powershell
   signtool verify /pa /all /v `
     ".\BODAQS-Import-Manager-<version>-Setup.exe"
   ```

7. Create a fresh checksum for the signed installer and retain it with the
   release files:

   ```powershell
   Get-FileHash -Algorithm SHA256 .\BODAQS-Import-Manager-<version>-Setup.exe |
     ForEach-Object { "{0} *{1}" -f $_.Hash, $_.Path.Split('\')[-1] } |
     Set-Content -NoNewline -Encoding ascii `
       .\BODAQS-Import-Manager-<version>-Setup.exe.sha256
   ```

8. Create the GitHub Release for the same tag and attach the signed Windows
   installer and its new checksum, both signed/notarized macOS DMGs, and the
   Linux archive with its Sigstore bundle.

The Windows GitHub Actions artifact is a release candidate, not a public
release download. Do not attach it to a GitHub Release until it has been signed
and verified.
