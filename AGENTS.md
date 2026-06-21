# AGENTS.md

## Project line

This repository contains both a Flask dynamic site and a root-level static site.

The Flask dynamic site is the current main line of the project.

The root-level static site should be preserved as a fallback and possible future direction. It must not be deleted or broken during cleanup or refactoring tasks. The static site can remain inactive or lightly maintained unless the user explicitly asks to work on it.

Future mini-program support, if needed, should reuse the existing backend models, services, and API routes where possible instead of rewriting the backend from scratch.

## Repository structure

The repository currently includes these important parts:

* `app/`: Flask dynamic site application.
* `assets/`: static-site assets and fallback static resources.
* `deploy/`: deployment configuration and related files.
* `docs/`: project documentation and handoff materials.
* `instance/`: local/runtime instance data.
* `migrations/`: Alembic database migration files.
* `tests/`: automated tests.
* `uploads/`: uploaded files, route files, media, or runtime assets.
* Root-level HTML files: static fallback site pages.
* `run.py`: Flask startup entry.
* `config.py`: project configuration.
* `requirements.txt`: Python dependencies.
* `.env`: local private environment configuration.
* `.env.example`: public environment variable template.
* `.venv/`: local Python virtual environment.
* `AGENTS.md`: agent instruction and maintenance rules.
* `Dockerfile` and `docker-compose.yml`: container/deployment files.
* `VERSION`: single source of truth for the project version.
* `CHANGELOG.md`: human-readable release and maintenance history.

## Agent instruction file protection

Do not delete or modify `AGENTS.md` unless the user explicitly asks to update it.

For normal coding, cleanup, versioning, testing, deployment, or documentation tasks, treat `AGENTS.md` as read-only.

If a task appears to require changing `AGENTS.md`, first stop, explain why the change may be needed, and wait for explicit user approval.

## Deletion and cleanup rules

Do not delete the following directories:

* `.git/`
* `.github/`
* `app/`
* `assets/`
* `deploy/`
* `docs/`
* `instance/`
* `migrations/`
* `tests/`
* `uploads/`

Do not delete the following files:

* `AGENTS.md`
* `.env.example`
* `.gitignore`
* `alembic.ini`
* `config.py`
* `docker-compose.yml`
* `Dockerfile`
* `requirements.txt`
* `run.py`
* `VERSION`
* `CHANGELOG.md`

The following items require explicit confirmation before deletion:

* `.venv/`
* `.env`
* `about.html`
* `activities.html`
* `contact.html`
* `guide.html`
* `index.html`
* `MAINTENANCE.md`
* `README.md`


The following items can be cleaned:

* root-level `.vscode/`
* root-level `tmp_test/`
* root-level `tmp_regression/`
* root-level `tmp_restore_drill/`
* any `pytest-cache-files-*/` directory at any level
* any `__pycache__/` directory at any level
* any `.pytest_cache/` directory at any level
* any `*.pyc` file at any level
* any `*.db-journal` file under `instance/`

The following items can be cleaned only after confirmation:

* `server-sync/`
* `backups/`

Before deleting, moving, or heavily rewriting project files, list the proposed changes and wait for user approval. Moreover, being ignored by `.gitignore` does not automatically mean the item can be deleted. Deletion and cleanup must follow the rules in this file.

## Local files, secrets, and runtime data

Do not expose or copy real secrets from `.env` into tracked files, documentation, examples, logs, or commit messages.

Use `.env.example` as the public configuration template.

If environment variables, upload paths, database paths, deployment paths, or configuration names change, update `.env.example`.

Deleting `.env` requires explicit confirmation.

Do not assume local runtime files are disposable. In particular, do not delete `instance/` or `uploads/` without explicit user approval.

## Versioning

The project version must be maintained in a standalone `VERSION` file.

The initial value of `VERSION` should follow the existing GitHub tag format:

```text
v4.4.0
```

The `VERSION` file should be the source of truth for the project version.

Do not use `.env` as the project version source.

If application code needs `APP_VERSION`, it should read from the standalone `VERSION` file or from a single centralized version-loading helper.

The project uses the existing `vX.Y.Z` version format. Git tags and the `VERSION` file must match exactly.

Examples:

```text
v4.4.0
v4.4.1
v4.5.0
v5.0.0
```

Do not switch to non-prefixed versions such as `4.4.1` unless the user explicitly requests it.

Version bumps are required when there are:

* feature changes;
* bug fixes;
* user-visible behavior changes;
* backend behavior changes;
* API changes;
* database schema changes;
* deployment behavior changes;
* configuration behavior changes.

Use semantic versioning with the `v` prefix:

* `MAJOR`: incompatible or breaking changes, for example `v5.0.0`.
* `MINOR`: new features or meaningful behavior changes, for example `v4.5.0`.
* `PATCH`: bug fixes, small improvements, environment fixes, cleanup, or documentation changes, for example `v4.4.1`.

If a change does not require a version bump, explicitly state that no version bump was needed.

If `VERSION` does not exist yet, create it before enforcing the version bump workflow.

## Changelog

Maintain `CHANGELOG.md`.

Every version bump must update `CHANGELOG.md`.

If `CHANGELOG.md` does not exist yet, create it before enforcing the version bump workflow.

The initial changelog should establish `v4.4.0` as the current baseline if no earlier changelog exists.

Use clear categories such as:

- `Added`
- `Changed`
- `Fixed`
- `Removed`
- `Security`
- `Docs`
- `Tests`
- `Chore`

Changelog entries should summarize meaningful project changes for maintainers. Do not use the changelog as a replacement for detailed commit history.

## Required checks

For Python code changes, run relevant pytest tests.

On Windows, prefer the virtual environment Python executable when available:

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m compileall -q app tests
```

If the virtual environment is unavailable, use the active Python interpreter:

```powershell
python -m pytest
python -m compileall -q app tests
```

`compileall` may generate `__pycache__/` directories. These cache directories can be cleaned after the check.

For static-site-only changes, Flask pytest is not required unless shared assets, deployment behavior, Python code, or Flask-rendered pages are affected.

If the change affects local startup, configuration, database paths, upload paths, or deployment behavior, verify that the Flask dynamic site can start locally.

For Flask startup checks, do not leave a long-running process behind. Start the server, request the homepage, confirm `GET / -> 200`, and then stop the server process.

If tests or startup checks cannot be run, clearly state:

1. which checks were not run;
2. why they were not run;
3. what risk remains.

## Maintenance requirements by change type

When configuration variables, environment variables, paths, upload directories, database URLs, or deployment behavior change, update:

* `.env.example`
* `README.md` if setup instructions are affected
* relevant files under `docs/` or `deploy/` if needed

When Python dependencies change, update:

* `requirements.txt`

When database models change, update or create migrations under:

* `migrations/`

Do not edit existing migration history unless explicitly instructed.

When application behavior changes, update or add tests under:

* `tests/`

When setup, deployment, maintenance workflow, or handoff instructions change, check whether these files need updates:

* `README.md`
* `MAINTENANCE.md`
* `docs/`
* `deploy/`

## Remote push and tag policy

Before pushing commits to the remote GitHub repository, review the pending changes against the versioning rules above and ask the user whether the push should include a version bump. Do not rely only on the user's initial wording. If the user asks to push without mentioning versioning, explicitly state whether the pending changes appear to require a version bump. If a version bump appears appropriate, recommend the smallest suitable version increment and ask for confirmation before changing `VERSION`, updating `CHANGELOG.md`, creating a tag, or pushing.

If the user confirms that a version bump is needed, complete all of the following before pushing:

1. update the standalone `VERSION` file;
2. update `CHANGELOG.md`;
3. commit the version and changelog updates;
4. create a Git tag that exactly matches the value in `VERSION`;
5. push both the branch and the tag to the remote GitHub repository.

The Git tag and the `VERSION` file must stay consistent.

Use the existing tag style. Existing tags use the `vX.Y.Z` format, for example:

```text
v4.4.0
```

Continue using tags such as:

```text
v4.4.1
v4.5.0
v5.0.0
```

Do not create non-prefixed tags such as `4.4.1` unless the user explicitly requests it.

Do not create or push a version tag unless the corresponding `VERSION` and `CHANGELOG.md` updates are already committed.

If the user confirms that no version bump is needed for the push, do not create a new tag unless explicitly instructed. In that case, report that the push was made without a version bump or new tag.

## Change policy

Prefer small, reversible changes.

Do not mix unrelated cleanup, feature work, dependency changes, and documentation rewrites in one change.

Do not rewrite business logic during cleanup tasks.

Do not introduce a new frontend framework, mini-program, backend framework, database system, or deployment platform unless explicitly requested.

Do not remove tests, migrations, documentation, deployment files, static fallback pages, or uploaded/runtime assets during cleanup.

Preserve both the Flask dynamic site and the static fallback site unless the user explicitly changes this policy.

## Deployment metadata

Do not store deployment timestamps in the `VERSION` file.

The `VERSION` file must contain only the project version, such as `v4.4.0`.

Deployment-specific metadata, such as `APP_DEPLOYED_AT`, should be provided through environment variables, deployment scripts, or deployment-specific metadata files.

`APP_DEPLOYED_AT` may remain in `.env` for local or server-specific deployment metadata.

If `APP_DEPLOYED_AT` is documented in `.env.example`, it should be optional and shown as a commented example, not as a required fixed value.

Use ISO 8601 format with timezone for deployment timestamps, for example:

```text
2026-03-17T18:30:00+08:00
```

## Completion report

After each task, report:

1. files changed;
2. why they changed;
3. tests or checks run;
4. whether `VERSION` was updated;
5. whether `CHANGELOG.md` was updated;
6. whether `.env.example` was updated;
7. whether `README.md`, `MAINTENANCE.md`, `docs/`, or `deploy/` were updated;
8. whether a remote GitHub push was requested or performed;
9. whether a Git tag was created and pushed, and whether it matches `VERSION`;
10. any remaining risks or follow-up tasks.

For small tasks, items that are not relevant may be reported as `not involved`.
