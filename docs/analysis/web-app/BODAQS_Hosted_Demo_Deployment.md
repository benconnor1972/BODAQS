# BODAQS Hosted Demo Deployment

Status: draft  
Audience: hosted read-only demo deployment

This note describes the lightweight hosted-demo deployment shape for the BODAQS
Workbench and Library API. The intended first target is a small AWS Lightsail
Linux instance running a read-only demo library.

For the current full build, release, and hosted-demo update runbook, see:

```text
docs/analysis/release-notes/BODAQS_Desktop_And_Hosted_Demo_Release_Process.md
```

## Deployment Shape

- Nginx listens publicly on ports `80` and `443`.
- Nginx proxies requests to the Library API on `127.0.0.1:8765`.
- The Library API runs in `--read-only` mode.
- The Library API serves both `/api/v1/*` routes and the built Workbench static
  app via `--web-root`.
- The processed demo library is stored on the instance filesystem.

The Library API port should not be exposed directly through the Lightsail
firewall. Public traffic should enter through Nginx only.

## Build Artifacts

The local deployment bundle currently consists of:

- `bodaqs-workbench-dist.zip`: built Workbench static files.
- `bodaqs-library-service-source.zip`: Python source for the Library API service.
- `bodaqs-demo-library-root.zip`: processed read-only demo library root.
- `SHA256SUMS.txt`: checksums for the three archives.

Example generated bundle folder:

```text
C:\Users\benco\dev\BODAQS\build\hosted-demo\<timestamp>
```

## Runtime Dependencies

Use the hosted runtime requirements file rather than the full development
requirements:

```text
requirements-hosted-library-service.txt
```

This avoids installing notebook, desktop UI, and import-manager dependencies on
the hosted demo instance.

## Suggested Instance Layout

```text
/opt/bodaqs/app
/opt/bodaqs/venv
/opt/bodaqs/workbench
/opt/bodaqs/demo-library-root
/var/cache/bodaqs-library-api
/var/log/bodaqs
```

## Upload

Upload the generated archives to the Lightsail instance, for example to
`/home/ec2-user`. For large demo libraries, `scp` using the downloaded Lightsail
SSH key is usually more reliable than browser upload.

Example from PowerShell:

```powershell
scp -i C:\path\to\LightsailDefaultKey-ap-southeast-2.pem `
  C:\Users\benco\dev\BODAQS\build\hosted-demo\20260723-110228\*.zip `
  ec2-user@54.66.173.205:/home/ec2-user/
```

## Install On Instance

```bash
sudo dnf update -y
sudo dnf install -y python3.12 python3.12-pip unzip nginx

sudo mkdir -p /opt/bodaqs/app /opt/bodaqs/workbench /opt/bodaqs/demo-library-root
sudo mkdir -p /var/cache/bodaqs-library-api /var/log/bodaqs
sudo chown -R ec2-user:ec2-user /opt/bodaqs /var/cache/bodaqs-library-api /var/log/bodaqs

unzip -o ~/bodaqs-workbench-dist.zip -d /opt/bodaqs/workbench
unzip -o ~/bodaqs-library-service-source.zip -d /opt/bodaqs/app
unzip -o ~/bodaqs-demo-library-root.zip -d /opt/bodaqs/demo-library-root

python3.12 -m venv /opt/bodaqs/venv
/opt/bodaqs/venv/bin/python -m pip install --upgrade pip setuptools wheel
/opt/bodaqs/venv/bin/python -m pip install -r /opt/bodaqs/app/requirements-hosted-library-service.txt
```

## Systemd Service

```bash
sudo tee /etc/systemd/system/bodaqs-library-api.service > /dev/null <<'EOF'
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
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now bodaqs-library-api
sudo systemctl status bodaqs-library-api --no-pager
```

## Nginx

```bash
sudo tee /etc/nginx/conf.d/bodaqs-demo.conf > /dev/null <<'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name demo.bodaqs.net;

    client_max_body_size 10m;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

## Smoke Tests

Run these on the instance:

```bash
curl http://127.0.0.1:8765/api/v1/health
curl http://127.0.0.1/api/v1/health
curl http://127.0.0.1/api/v1/capabilities
```

The health response should include:

```json
{"read_only": true}
```

The capabilities response should include `"read_only": true` and write features
should be `false`.

From a local browser, before DNS is ready:

```text
http://54.66.173.205/
```

After DNS is ready:

```text
http://demo.bodaqs.net/
```

## TLS

Once `demo.bodaqs.net` resolves to the Lightsail static IP, install a Let's
Encrypt certificate with Certbot. This gives the demo HTTPS without a paid
certificate.

Typical Amazon Linux 2023 path:

```bash
sudo dnf install -y certbot python3-certbot-nginx
sudo certbot --nginx -d demo.bodaqs.net
sudo certbot renew --dry-run
```

If the `python3-certbot-nginx` package is unavailable from the configured repos,
install Certbot using Snap or Python tooling instead, then run the same
`certbot --nginx` command.

## Read-Only Policy

The hosted demo should run with `--read-only`. In this mode, mutating Library API
routes return `403 read_only_mode`, including writes to study sets, filters,
bookmarks, tracks, notes, session descriptions, session deletion, and persisted
trackpoint-match queries.

Read/query routes remain available so the Workbench can browse, inspect, and run
analysis against the demo library.

## Future Hardening

- Add a repeatable deployment script once the manual Lightsail path is proven.
- Add a build script that regenerates all three deployment archives and checksums.
- Add deeper read-only UI affordances for bookmark/note/edit controls in hosted
  mode.
- Add HTTP security headers in Nginx once HTTPS is enabled.
- Add access logs and basic health monitoring for the read-only service.
