# Changelog

## [Unreleased]

## [v4.6.2]

### Changed

- Refined the management kit preorder list by hiding noisy IDs and moving low-frequency visibility/delete actions into a more menu.
- Unified the kit preorder edit page with the newer management edit layout, including clearer sections, compact image handling, and save-and-view actions.
- Improved the kit preorder registration management page by removing noisy IDs, tightening filters and status controls, and making status changes auto-submit.

## [v4.6.1]

### Changed

- Refined the management activities list with route names, registration counts, and lower-priority actions under a more menu.
- Improved the activity edit form with a shared activity date, per-route time fields, route enable states, compact registration settings, and collapsible uploaded media.
- Added default activity form behavior for route start time and registration deadline suggestions.

### Fixed

- Kept activity route time parsing compatible with legacy datetime-local form submissions while supporting the new shared-date time-only inputs.

## [v4.6.0]

### Added

- Added manual route statistic overrides so maintainers can preserve curated distance, elevation, and suggested-duration values across GPX recalculations.
- Added a database migration and startup compatibility column for route manual statistic override metadata.

### Changed

- Refined the route create/edit management form with clearer GPX file status, separated GPX recalculation controls, compact statistic display, and a collapsible manual-statistics panel.
- Updated route suggested-duration recalculation to use the currently selected difficulty when recalculating from the edit page.
- Split route maintenance controls into version maintenance and a separate danger zone, and changed supply/risk fields to support longer textarea content.

### Fixed

- Made route GPX recalculation work with legacy uploaded GPX filenames and refresh route statistics in place without jumping to the top of the page.

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
