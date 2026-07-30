# BODAQS Desktop And Hosted Demo Release Process

Status: draft  
Audience: BODAQS release/build operator  
Last updated: 2026-07-30

This note documents the current manual release process for:

- the bundled Windows BODAQS Desktop installer
- the hosted read-only BODAQS Workbench demo
- release notes and checksum generation

The current release model is bundle-first. Component versions are still tracked,
but public distribution is expected to be through the BODAQS Desktop installer
and, separately, the hosted demo site.

## Current Naming And Versioning

Use these names in user-facing release material:

- `BODAQS Desktop`: the Windows installer bundle.
- `BODAQS Import Manager`: the local desktop import/configuration app.
- `BODAQS Library Service`: the local or hosted HTTP API service.
- `BODAQS Workbench`: the browser-based library/analysis UI.

For the `0.2.0-beta` desktop release:

- BODAQS Desktop bundle: `0.2.0-beta`
- BODAQS Import Manager: `0.1.7-beta`
- BODAQS Library Service: `0.1.1-beta`
- BODAQS Workbench: `0.1.1-beta`

## Local Build Prerequisites

Builds are currently produced from the development workstation.

Expected local prerequisites:

- Windows PowerShell
- Python virtual environment at `.venv`
- Node/npm installed for the Workbench build
- Inno Setup 6 installed
- Demo library assets present in `demo-assets`

The build scripts use the live working tree, not only committed files. Uncommitted
changes are included in the build. This is convenient during active development,
but release candidates should still be reviewed with `git status --short`.

## Pre-Build Checks

From the repository root:

```powershell
git status --short
```

Run the Workbench build:

```powershell
cd C:\Users\benco\dev\BODAQS\application\cohort-workbench-prototype
npm run build
```

Run at least the web-app serving regression test:

```powershell
cd C:\Users\benco\dev\BODAQS\analysis
..\.venv\Scripts\python.exe -m pytest tests/test_library_api_adapter.py::test_library_api_service_serves_optional_web_app
```

That test confirms:

- the Library Service can serve the Workbench static app
- `index.html` and SPA fallback routes are served with no-cache headers
- hashed assets under `/assets/` remain long-cacheable

## Build The Desktop Installer

From the repository root:

```powershell
.\import-manager\build_import_manager.ps1 `
  -Target installer `
  -BundleVersion "0.2.0-beta" `
  -ImportManagerVersion "0.1.7-beta" `
  -LibraryServiceVersion "0.1.1-beta" `
  -WorkbenchVersion "0.1.1-beta"
```

Expected output:

```text
import-manager\dist\installer\windows\bodaqs-desktop-setup-0.2.0-beta.exe
```

The installer staging folder should include:

```text
import-manager\build\installer\windows\staging\manager
import-manager\build\installer\windows\staging\service
import-manager\build\installer\windows\staging\demo-assets
import-manager\build\installer\windows\staging\component_versions.json
```

Confirm component metadata:

```powershell
Get-Content import-manager\build\installer\windows\staging\component_versions.json
```

Confirm demo assets are present:

```powershell
Test-Path import-manager\build\installer\windows\staging\demo-assets\libraries\bodaqs-demo\library_definition.json
```

Generate the installer checksum:

```powershell
Get-FileHash import-manager\dist\installer\windows\bodaqs-desktop-setup-0.2.0-beta.exe -Algorithm SHA256
```

Record this checksum in the release notes.

## Desktop Installer Smoke Test

On a test machine, or after uninstalling the previous build:

1. Install `bodaqs-desktop-setup-0.2.0-beta.exe`.
2. Select the demo library install option if validating first-run/demo behavior.
3. Launch BODAQS Import Manager.
4. Click `Open BODAQS Workbench`.
5. Confirm the browser opens at `http://127.0.0.1:8765/`.
6. Confirm Library Browser data appears.
7. Confirm the Analysis Launcher shows implemented entries for:
   - Simple Suspension Analysis
   - Track Analysis and Lap Timing
8. Open both analysis views.
9. Stop the Workbench from Import Manager and confirm the browser reports the
   API as offline.

If the browser appears to show stale UI after installing a new build, check the
loaded script in DevTools:

```javascript
document.querySelector('script[type="module"]')?.src
```

The script should match the asset in the installed `index.html` at:

```text
C:\Program Files\BODAQS Desktop\service\web\index.html
```

The Library Service now serves the Workbench entry point with no-cache headers,
but a hard reload or fresh browser tab is still a useful diagnostic step.

## Draft Release Notes

Current release notes draft:

```text
import-manager\docs\BODAQS Desktop 0.2.0-beta Release Notes Draft.md
```

Release notes should include:

- release status and date
- component versions
- installer filename
- SHA-256 checksum
- headline changes since the previous release
- known limitations
- validation checklist

## Build Hosted Demo Artifacts

The hosted demo uses the same Workbench and Library Service source, but the demo
library is usually left unchanged unless explicitly refreshing demo data.

Current artifact layout:

```text
build\hosted-demo\<timestamp>\
  bodaqs-workbench-dist.zip
  bodaqs-library-service-source.zip
  bodaqs-demo-library-root.zip
  SHA256SUMS.txt
```

For the 2026-07-30 refresh, the generated folder was:

```text
build\hosted-demo\20260730-163631
```

The Workbench zip contains the built `dist` contents at zip root. The service
zip contains:

```text
analysis\bodaqs_analysis\...
analysis\templates\...
requirements-hosted-library-service.txt
```

When the hosted demo library is unchanged, copy forward the previous
`bodaqs-demo-library-root.zip` rather than regenerating it.

## Hosted Environment Overview

Current hosting shape:

- Provider: AWS Lightsail
- Instance platform: Amazon Linux 2023
- Public endpoint: `https://demo.bodaqs.net/`
- Static IPv4: `54.66.173.205`
- Public HTTP/HTTPS entry point: nginx
- Internal Library Service: `127.0.0.1:8765`
- Library mode: read-only
- Demo library path: `/opt/bodaqs/demo-library-root`
- Workbench static root: `/opt/bodaqs/workbench`
- Service source root: `/opt/bodaqs/app/analysis`
- Python virtual environment: `/opt/bodaqs/venv`
- systemd service: `bodaqs-library-api`

Public traffic should enter through nginx only. Do not expose port `8765`
through the Lightsail firewall.

## Lightsail Firewall

Recommended inbound rules:

- HTTP, TCP `80`, any IPv4/IPv6
- HTTPS, TCP `443`, any IPv4/IPv6
- SSH, TCP `22`, restricted to the current operator public IP where practical

To find the current operator public IP from Windows:

```powershell
Invoke-RestMethod https://checkip.amazonaws.com
```

If SSH/SCP times out before authentication, check that the Lightsail SSH rule
allows the current public IP as `/32`.

## Hosted Systemd Service

The Library Service is managed by systemd:

```bash
sudo systemctl status bodaqs-library-api --no-pager
sudo systemctl stop bodaqs-library-api
sudo systemctl start bodaqs-library-api
sudo systemctl restart bodaqs-library-api
sudo journalctl -u bodaqs-library-api -n 100 --no-pager
```

The service unit should be equivalent to:

```ini
[Unit]
Description=BODAQS Library API read-only demo
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/opt/bodaqs/app/analysis
Environment=PYTHONPATH=/opt/bodaqs/app/analysis
ExecStart=/opt/bodaqs/venv/bin/python -m bodaqs_analysis.library_api_service --libraries-root /opt/bodaqs/demo-library-root --web-root /opt/bodaqs/workbench --host 127.0.0.1 --port 8765 --read-only
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Hosted Nginx Shape

Nginx listens on public HTTP/HTTPS and proxies to the internal Library Service.

Important behavior:

- HTTP requests to `demo.bodaqs.net` redirect to HTTPS.
- HTTPS requests proxy to `http://127.0.0.1:8765`.
- Local curls to `http://127.0.0.1/...` may hit the default nginx server block
  rather than the `demo.bodaqs.net` block.
- Use the `Host: demo.bodaqs.net` header when testing the named nginx server
  locally.

Useful inspection command:

```bash
sudo nginx -T | grep -n "8765\|proxy_pass\|server_name\|root"
```

Expected proxy line:

```nginx
proxy_pass http://127.0.0.1:8765;
```

Reload nginx after changes:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## Hosted Upload

From Windows PowerShell, upload the Workbench and service zips:

```powershell
scp -i "$env:USERPROFILE\.ssh\LightsailDefaultKey-ap-southeast-2.pem" `
  C:\Users\benco\dev\BODAQS\build\hosted-demo\20260730-163631\bodaqs-workbench-dist.zip `
  C:\Users\benco\dev\BODAQS\build\hosted-demo\20260730-163631\bodaqs-library-service-source.zip `
  ec2-user@54.66.173.205:/home/ec2-user/
```

If refreshing the demo library too, also upload:

```text
bodaqs-demo-library-root.zip
```

SSH to the instance:

```powershell
ssh -i "$env:USERPROFILE\.ssh\LightsailDefaultKey-ap-southeast-2.pem" ec2-user@54.66.173.205
```

## Hosted Deploy

Stop the service:

```bash
sudo systemctl stop bodaqs-library-api
```

Deploy Workbench:

```bash
sudo rm -rf /opt/bodaqs/workbench/*
sudo unzip -o /home/ec2-user/bodaqs-workbench-dist.zip -d /opt/bodaqs/workbench
sudo chown -R ec2-user:ec2-user /opt/bodaqs/workbench
```

Deploy Library Service source:

```bash
rm -rf /home/ec2-user/bodaqs-service-update
mkdir -p /home/ec2-user/bodaqs-service-update
unzip -o /home/ec2-user/bodaqs-library-service-source.zip -d /home/ec2-user/bodaqs-service-update

sudo rm -rf /opt/bodaqs/app/analysis/bodaqs_analysis
sudo cp -R /home/ec2-user/bodaqs-service-update/analysis/bodaqs_analysis /opt/bodaqs/app/analysis/

if [ -d /home/ec2-user/bodaqs-service-update/analysis/templates ]; then
  sudo rm -rf /opt/bodaqs/app/analysis/templates
  sudo cp -R /home/ec2-user/bodaqs-service-update/analysis/templates /opt/bodaqs/app/analysis/
fi

sudo chown -R ec2-user:ec2-user /opt/bodaqs/app/analysis
```

If refreshing the demo library:

```bash
sudo rm -rf /opt/bodaqs/demo-library-root/*
sudo unzip -o /home/ec2-user/bodaqs-demo-library-root.zip -d /opt/bodaqs/demo-library-root
sudo chown -R ec2-user:ec2-user /opt/bodaqs/demo-library-root
```

Restart:

```bash
sudo systemctl start bodaqs-library-api
sudo systemctl status bodaqs-library-api --no-pager
```

## Hosted Smoke Tests

Test the service directly:

```bash
curl http://127.0.0.1:8765/api/v1/health
curl -i http://127.0.0.1:8765/ | head -30
```

Note: `curl -I http://127.0.0.1:8765/` may return `405 Method Not Allowed`
because the Workbench route handles `GET`, not `HEAD`.

Test nginx with the correct host:

```bash
curl -k https://127.0.0.1/api/v1/health -H "Host: demo.bodaqs.net"
curl -k -i https://127.0.0.1/ -H "Host: demo.bodaqs.net" | head -30
```

Test the public domain:

```bash
curl https://demo.bodaqs.net/api/v1/health
curl -i https://demo.bodaqs.net/ | head -30
```

The Workbench HTML response should include:

```text
Cache-Control: no-store, no-cache, must-revalidate, max-age=0
```

The body should reference the current built asset, for example:

```text
/assets/index-B-u5ti3e.js
```

In a browser, open:

```text
https://demo.bodaqs.net/
```

In DevTools Console:

```javascript
document.querySelector('script[type="module"]')?.src
fetch('/api/v1/analysis-views').then(r => r.json()).then(console.log)
```

The first command should show the current hashed bundle. The second should show
both implemented analysis views.

## Hosted Read-Only Expectations

The hosted demo should run with `--read-only`.

Expected behavior:

- browsing, filtering, maps, signals, metrics, GPS, and analysis should work
- study-set, track, filter, note, bookmark, video, and session writes should be
  disabled by API capability and rejected server-side
- hosted-only UI should avoid or disable local-file affordances where practical

Health should include:

```json
{"read_only": true}
```

Capabilities should report write features as `false`.

## Common Failure Modes

### SSH/SCP Times Out

Usually the Lightsail SSH firewall rule does not include the current public IP.
Update the SSH rule to the current IP as `/32`, or temporarily allow any IPv4
for deployment and lock it down afterward.

### `curl http://127.0.0.1/api/v1/health` Returns nginx 404

That curl is hitting nginx on port `80`, not the Library Service. If nginx has a
named server block for `demo.bodaqs.net`, local `127.0.0.1` requests may hit the
default static server.

Use:

```bash
curl -H "Host: demo.bodaqs.net" http://127.0.0.1/api/v1/health
```

or test the service directly:

```bash
curl http://127.0.0.1:8765/api/v1/health
```

### HTTP Returns 301 Moved Permanently

This is expected when nginx redirects HTTP to HTTPS. Test the HTTPS endpoint.

### Browser Shows Old UI After Deployment

Check the loaded script:

```javascript
document.querySelector('script[type="module"]')?.src
```

If it shows an old hashed asset, the browser has stale HTML. The Library Service
now prevents this by serving the Workbench entry point with no-cache headers.
Hard reload once, then verify the current script.

## Future Improvements

- Add a scripted hosted deploy command to reduce manual SSH steps.
- Add a build manifest with Workbench asset name, component versions, and git
  revision.
- Add a visible Workbench build/version diagnostic in the UI.
- Add hosted-demo health checks or uptime monitoring.
- Persist and display deployment history on the instance.
- Consider making nginx `127.0.0.1` local curls proxy to the app as well as the
  named `demo.bodaqs.net` server block.
