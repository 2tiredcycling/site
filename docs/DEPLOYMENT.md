# Deployment Notes

## Environment

* Provider: Tencent Cloud Lighthouse
* OS: Ubuntu 22.04 LTS
* App version: v4.5.1
* Runtime: Python 3.10
* Web server: Nginx
* App server: Gunicorn
* Database: SQLite

## Server Paths

* Project directory: `/srv/2tired`
* Virtual environment: `/srv/2tired/.venv`
* Environment file: `/srv/2tired/.env`
* SQLite database: `/srv/2tired/instance/app.db`
* Uploads directory: `/srv/2tired/uploads/`
* Backups directory: `/srv/2tired/backups/`
* systemd service: `/etc/systemd/system/2tired.service`
* Nginx config: `/etc/nginx/sites-available/2tired`

## Deployment Steps

### 1. Install system packages

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git nginx python3-venv python3-pip curl unzip build-essential
```

### 2. Prepare project directory

```bash
sudo mkdir -p /srv/2tired
sudo chown -R ubuntu:ubuntu /srv/2tired
cd /srv/2tired
```

### 3. Clone repository and switch version

```bash
git clone <REPOSITORY_URL> .
git checkout v4.5.1
cat VERSION
```

### 4. Create virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

### 5. Configure environment variables

```bash
cp .env.example .env
nano .env
chmod 600 .env
```

Do not commit `.env`.

### 6. Create runtime directories

```bash
mkdir -p instance uploads/gpx uploads/media backups logs
```

### 7. Initialize database

For the current v4.5.x deployment, the app uses SQLAlchemy model initialization.

```bash
python - <<'PY'
from app import create_app

app = create_app()
print("app created")
PY
```

Then mark the Alembic state as the latest version:

```bash
alembic stamp head
```

`alembic stamp head` must operate on the same database that the Flask app uses.
Before stamping, confirm that `DATABASE_URL` in `.env` resolves to the intended database.
As of v4.5.1, Alembic loads the database URL from the same Flask configuration path used by the app, instead of relying only on the fixed `sqlalchemy.url` fallback in `alembic.ini`.
If `DATABASE_URL` is changed, verify the resolved database path before running `alembic stamp head`.

Check database tables:

```bash
python - <<'PY'
import sqlite3
from pathlib import Path

db = Path("instance/app.db")
print("db exists:", db.exists(), db)

if db.exists():
    con = sqlite3.connect(db)
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    for row in rows:
        print(row[0])
    con.close()
PY
```

### 8. Test Gunicorn locally

```bash
gunicorn -w 2 -b 127.0.0.1:8000 "app:create_app()"
```

In another terminal:

```bash
curl -I http://127.0.0.1:8000
```

### 9. systemd service

Service file:

```text
/etc/systemd/system/2tired.service
```

Example content:

```ini
[Unit]
Description=2Tired Flask App
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/srv/2tired
EnvironmentFile=/srv/2tired/.env
ExecStart=/srv/2tired/.venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 "app:create_app()"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl start 2tired
sudo systemctl enable 2tired
sudo systemctl status 2tired --no-pager
```

### 10. Nginx reverse proxy

Nginx config:

```text
/etc/nginx/sites-available/2tired
```

Example content:

```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;

    server_name _;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable config:

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/2tired /etc/nginx/sites-enabled/2tired
sudo nginx -t
sudo systemctl reload nginx
```

### 11. Service commands

Check service status:

```bash
sudo systemctl status 2tired --no-pager
sudo systemctl status nginx --no-pager
```

Restart app:

```bash
sudo systemctl restart 2tired
```

Reload Nginx:

```bash
sudo systemctl reload nginx
```

View app logs:

```bash
sudo journalctl -u 2tired -n 100 --no-pager
```

View Nginx logs:

```bash
sudo tail -n 100 /var/log/nginx/error.log
sudo tail -n 100 /var/log/nginx/access.log
```

## Current Deployment Notes

* Current deployment uses HTTP and server IP only.
* Domain and HTTPS are not configured yet.
* Do not expose port `8000` to the public internet.
* Public access should go through Nginx port `80`.
* HTTPS will be configured after domain registration, ICP filing, and domain resolution.

## Do Not Commit

Never commit the following files or directories:

```text
.env
instance/
uploads/
backups/
logs/
*.db
*.sqlite
*.sqlite3
.venv/
__pycache__/
*.pyc
```

## Known v4.5.1 Deployment Notes

* `alembic.ini` should be saved as UTF-8 without BOM.
* Alembic should read the database URL from Flask configuration so `alembic stamp head` targets the same database as the app.
* The current project contains both `db.create_all()` and Alembic migration files.
* In this deployment, database tables were initialized through the current SQLAlchemy models, then Alembic was marked with `alembic stamp head`.
* Future versions should clean up the database migration strategy.
