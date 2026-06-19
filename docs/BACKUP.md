# Backup Policy

This document defines the backup format and minimum backup requirements for the 2Tired Cycling website.

## 1. Purpose

The website stores both code and runtime data. Code can be recovered from GitHub, but runtime data must be backed up separately.

Runtime data includes:

* SQLite database: `instance/app.db`
* Uploaded media files: `uploads/media/`
* Uploaded GPX files: `uploads/gpx/`
* Server environment file: `.env`

Before any update that may affect the running service, a manual backup should be created.

## 2. What Must Be Backed Up

The following paths should be included in a manual backup:

```text
instance/
uploads/
.env
```

Meaning:

```text
instance/      Runtime database and instance files
uploads/       Uploaded activity photos, media files, and GPX files
.env           Production environment variables
```

The following paths should not be treated as the main data backup target:

```text
app/
assets/
docs/
migrations/
tests/
```

These files are source code or documentation and should be managed through Git.

## 3. Backup Location

Manual backups should be stored under:

```text
backups/manual/
```

This directory is for server-side backup files only.

Backup files must not be committed to GitHub.

## 4. Backup File Naming Format

Use the following naming format:

```text
pre_update_YYYYMMDD_HHMMSS.tar.gz
```

Example:

```text
pre_update_20260619_153000.tar.gz
```

Rules:

* `pre_update` means the backup was created before a code update.
* `YYYYMMDD_HHMMSS` records the backup time.
* `.tar.gz` is used to preserve directory structure and reduce file size.

## 5. Manual Backup Command

Run the following commands on the server:

```bash
cd /srv/2tired
mkdir -p backups/manual
tar -czf backups/manual/pre_update_$(date +%Y%m%d_%H%M%S).tar.gz instance uploads .env
```

Explanation:

```text
cd /srv/2tired
    Enter the project directory.

mkdir -p backups/manual
    Create the manual backup directory if it does not exist.

tar -czf ...
    Create a compressed backup file containing instance, uploads, and .env.
```

## 6. Verify Backup File

After creating the backup, check that the file exists:

```bash
ls -lh backups/manual
```

A valid backup should appear as a `.tar.gz` file with a non-zero size.

Example:

```text
-rw-r--r-- 1 ubuntu ubuntu 2.5M Jun 19 15:30 pre_update_20260619_153000.tar.gz
```

## 7. When to Create a Backup

Create a manual backup before:

* Updating to a new Git tag or version
* Running database migration commands
* Changing upload-related logic
* Changing activity, media, GPX, or registration models
* Editing production `.env`
* Performing major server maintenance

A backup is optional before small text-only documentation changes.

## 8. Update Safety Rules

During code updates, do not delete or overwrite:

```text
.env
instance/
uploads/
backups/
logs/
```

Do not run destructive cleanup commands such as:

```bash
git clean -fdx
```

unless the command scope has been reviewed and it is confirmed that runtime data will not be affected.

## 9. Basic Restore Command

To inspect the contents of a backup:

```bash
tar -tzf backups/manual/pre_update_YYYYMMDD_HHMMSS.tar.gz
```

To restore a backup manually:

```bash
cd /srv/2tired
tar -xzf backups/manual/pre_update_YYYYMMDD_HHMMSS.tar.gz
sudo systemctl restart 2tired
```

Replace `pre_update_YYYYMMDD_HHMMSS.tar.gz` with the actual backup file name.

Before restoring, confirm that the target backup is the intended version.

## 10. Git Ignore Requirement

The backup directory should be ignored by Git.

The following rule should exist in `.gitignore`:

```gitignore
backups/
```

The production environment file should also be ignored:

```gitignore
.env
```

## 11. Recommended Update Flow

A safe update flow is:

```bash
cd /srv/2tired
mkdir -p backups/manual
tar -czf backups/manual/pre_update_$(date +%Y%m%d_%H%M%S).tar.gz instance uploads .env

git fetch --tags
git checkout vX.Y.Z

source .venv/bin/activate
pip install -r requirements.txt

python - <<'PY'
from app import create_app
app = create_app()
print("app created successfully")
PY

sudo systemctl restart 2tired
sudo systemctl status 2tired --no-pager
```

Replace `vX.Y.Z` with the target release tag.

## 12. Post-Update Checks

After each update, check:

* Home page loads normally
* Admin login works
* Existing activities still exist
* Uploaded media files are accessible
* GPX download works
* New activity creation works
* Nginx and 2Tired services are running

Commands:

```bash
sudo systemctl status 2tired --no-pager
sudo systemctl status nginx --no-pager
```

If static files or uploaded files were replaced with the same file names, Cloudflare cache may need to be purged.
