# Changelog

## [Unreleased]

## [v4.5.1]

### Fixed

- Updated Alembic environment configuration to resolve the database URL from the Flask app configuration path, reducing the risk of stamping the wrong SQLite database during deployment.
- Documented the v4.5.x database initialization and Alembic stamping workflow.
- Saved `alembic.ini` without UTF-8 BOM.

## [v4.5.0]

### Added

- Added a batch-based cycling kit preorder module with public listing, preorder submission, lookup, cancellation, and success pages.
- Added admin management for preorder batches, gallery images, size-chart images, registrations, status updates, and Excel export.
- Added database models and migration for merch preorder batches, images, and registrations.
- Added frontend navigation entry for cycling kit preorder between activities and routes.
- Added V4.5 preorder design reference documentation.

### Changed

- Unified project version management around the root-level `VERSION` file.
- Prepared changelog-based maintenance workflow.

## [v4.4.0]

### Chore

- Baseline version corresponding to the existing Git tag `v4.4.0`.
