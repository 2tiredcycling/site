# Changelog

## [Unreleased]

## [v4.5.4]

### Changed

- Refined the management routes page filter layout so advanced filters expand below the basic controls without shifting the toolbar.
- Improved the management routes table by hiding noisy route IDs, adding difficulty display, and moving low-frequency actions into a floating "more" menu.
- Moved the route recycle bin to a dedicated management page with a compact entry from the routes list.
- Marked route bulk import as temporarily unavailable in the UI while keeping the backend endpoint available.

## [v4.5.3]

### Changed

- Reworked the management dashboard into clearer core data, pending work, recent activity, and shortcut sections.
- Added a lightweight permission-aware top navigation across management pages.
- Gave management pages a fixed admin color system independent from the public site theme choices.
- Unified management status displays into colored badge labels for faster scanning.
- Refined the dashboard header, shortcut cards, pending-work cards, and recent audit log previews for clearer scanning.
- Updated tests to read the expected management version from the standalone `VERSION` file.

## [v4.5.2]

### Fixed

- Hid cycling kit style descriptions from the public preorder overview cards.
- Displayed the current app version on the management dashboard.
- Added backup policy documentation for safer server updates.

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
