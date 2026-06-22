# v4.8 Page Permission Redesign Draft

## Goal

This document describes a proposed permission redesign for the v4.8 line.

The current admin permission system mixes administrator roles with several global permission flags. It works, but it is becoming hard to reason about as the management console gains more independent modules.

The v4.8 direction is to move toward page-scoped permissions:

- administrator types become presets;
- each management page or module gets a permission level;
- the dashboard renders each card or navigation entry according to the user's permission for that page;
- high-risk operations require the highest page permission level.

This is a design draft only. It does not change application code or database schema.

## Current State

The current `users` table stores:

- `role`
- `is_active`
- `perm_view_analytics`
- `perm_view_security`
- `perm_review`
- `perm_edit_content`
- `perm_manage_users`
- `perm_view_audit_logs`

Current roles are:

- `super_admin`
- `ops_admin`
- `content_admin`
- `viewer`

Current permission checks are mostly global. For example, `perm_edit_content` can allow broad content maintenance, while `perm_view_security` controls access to security pages.

This becomes less precise when different modules need different operation levels.

## Proposed Permission Levels

Each manageable page or module should have one of four permission levels.

### `none`

User has no permission for this page.

Expected behavior:

- hide navigation entry;
- hide dashboard card;
- direct URL access returns `403`;
- no related API operation is allowed.

Chinese display label:

- `无权限`

### `read`

User can view the page and inspect existing data.

Expected behavior:

- show navigation entry;
- allow list/detail/statistics views;
- allow reading registrations, feedback, audit rows, or traffic summaries when applicable;
- do not show create, edit, delete, status, import, rollback, or dangerous action buttons.

Chinese display label:

- `可读`

### `write`

User can perform normal maintenance.

Expected behavior:

- includes `read`;
- allow create, edit, save, upload, ordinary export, and ordinary status changes;
- allow soft deletion only if the module treats it as a normal maintenance action;
- do not allow high-risk operations such as rollback, hard delete, account permission changes, destructive cleanup, or recovery operations.

Chinese display label:

- `可修改`

### `admin`

User has full management permission for the page.

Expected behavior:

- includes `write`;
- allow dangerous operations such as:
  - rollback;
  - delete or deactivate;
  - restore from recycle bin;
  - force status changes;
  - account permission changes;
  - security-sensitive operations;
  - other actions shown in danger zones.

Chinese display label:

- `完全管理`

## Proposed Page Keys

The following page keys are proposed for v4.8.

| Key | Area | Current routes or pages | Notes |
| --- | --- | --- | --- |
| `overview` | Management overview | `/manage` | Special case. The page itself may be readable, but individual cards should follow each module's permission. |
| `routes` | Route management | `/manage/routes`, route create/edit/recycle | Route rollback and recycle operations should require `admin`. |
| `activities` | Activity management | `/manage/activities`, activity create/edit/registrations | Viewing registrations can be `read`; editing activities requires `write`; deletion requires `admin`. |
| `kit_preorders` | Kit preorder management | `/manage/kit-preorders` | Status updates may require `write`; deletion requires `admin`. |
| `announcements` | Announcement management | `/manage/announcements` | Publishing/offline can be `write`; deletion requires `admin`. |
| `feedback` | Site and route feedback | `/manage/site-feedback`, legacy route feedback | Reading feedback requires `read`; marking handled/reviewing requires `write`; deletion requires `admin`. |
| `analytics` | Traffic analytics | `/manage/analytics` | Usually `read` only; export, if added later, may require `write`. |
| `security` | Security monitor | `/manage/security` | Viewing requires `read`; future blocking/allow-list operations should require `admin`. |
| `accounts` | Admin account maintenance | `/manage/users` | Viewing users requires `read`; creating/editing users requires `write`; changing permissions or deactivating users requires `admin`. |
| `audit_logs` | Audit logs | `/manage/audit-logs` | Usually `read` only; deletion or retention changes should require `admin` if added. |

Open question:

- Whether `overview` needs its own stored permission or should be always available after login.

Recommended default:

- `overview` is accessible to every active admin account.
- Dashboard cards, shortcuts, and nav entries are filtered by each module's permission.

## Management Overview Permission Mapping

The management overview page (`/manage`) is a container page.

Recommended rule:

- every active admin account can open `/manage`;
- every visible card, number, shortcut, pending item, and recent activity block inside `/manage` must inherit the permission of its source module;
- if the user has less than `read` permission for the source module, hide the whole item;
- do not show zero, placeholder, or disabled cards for unreadable modules.

This means the overview page must not be used to bypass module permissions.

Examples:

| Overview item | Source page key | Required level | Behavior without permission |
| --- | --- | --- | --- |
| Route count or route shortcut | `routes` | `read` | Hide |
| Activity count or activity shortcut | `activities` | `read` | Hide |
| Kit preorder count or shortcut | `kit_preorders` | `read` | Hide |
| Announcement count or shortcut | `announcements` | `read` | Hide |
| Pending site feedback | `feedback` | `read` | Hide |
| Site feedback processing shortcut | `feedback` | `read` | Hide |
| 24h PV / UV / active users | `analytics` | `read` | Hide |
| Suspicious IP count | `security` | `read` | Hide |
| 429 count | `security` | `read` | Hide |
| Watchlist hit count | `security` | `read` | Hide |
| Recent route records | `routes` | `read` | Hide |
| Recent activity records | `activities` | `read` | Hide |
| Recent audit logs | `audit_logs` | `read` | Hide |
| Account maintenance shortcut | `accounts` | `read` | Hide |

Security-related numbers shown on the overview page are still security data.

For example:

- suspicious IP count;
- 429 count;
- watchlist hits;
- recent security summaries.

These items require `security >= read`. If the user does not have `security: read`, the overview page should hide the whole security item instead of showing `0`, a disabled card, or a vague placeholder.

Action buttons inside overview cards should follow the same level rules:

- read-only cards require `read`;
- create, edit, or process shortcuts require `write`;
- danger or recovery shortcuts require `admin`.

## Administrator Types as Presets

Administrator types should become permission presets rather than the primary source of truth.

Suggested presets:

### Super Admin

Purpose:

- full owner of the system.

Default page permissions:

- all page keys: `admin`

Notes:

- there should always be at least one active super admin.
- changing or deactivating the last active super admin must be blocked.

### Content Admin

Purpose:

- maintains public content and daily club operations.

Default page permissions:

- `overview`: read or implicit
- `routes`: write
- `activities`: write
- `kit_preorders`: write
- `announcements`: write
- `feedback`: write
- `analytics`: read
- `security`: none
- `accounts`: none
- `audit_logs`: none

### Operations Admin

Purpose:

- monitors traffic, security, feedback, and audit trails.

Default page permissions:

- `overview`: read or implicit
- `routes`: read
- `activities`: read
- `kit_preorders`: read
- `announcements`: read
- `feedback`: read
- `analytics`: read
- `security`: read
- `accounts`: none
- `audit_logs`: read

### Viewer

Purpose:

- read-only account for inspection or handoff.

Default page permissions:

- `overview`: read or implicit
- `routes`: read
- `activities`: read
- `kit_preorders`: read
- `announcements`: read
- `feedback`: read
- `analytics`: read
- `security`: none
- `accounts`: none
- `audit_logs`: none

## Compatibility Strategy

This change should be introduced gradually.

### Phase 1: Add a centralized permission helper

Create helpers such as:

- `get_page_permission(user, page_key) -> PermissionLevel`
- `can_read_page(user, page_key)`
- `can_write_page(user, page_key)`
- `can_admin_page(user, page_key)`

At first, these helpers can map from existing `role` and `perm_*` fields.

No database schema change is required in this phase.

### Phase 2: Update templates and route guards

Use page permission helpers for:

- navigation visibility;
- dashboard cards;
- action buttons;
- danger zones;
- route access guards;
- management API write operations.

Existing behavior should remain compatible during this phase.

### Phase 3: Add page permission storage

Potential storage options:

1. Add a JSON column on `users`, such as `page_permissions`.
2. Add a normalized table, such as `user_page_permissions`.

Recommended option:

- a normalized table is clearer and easier to query, but a JSON column is simpler for a small admin system.

Suggested normalized model:

```text
user_page_permissions
- id
- user_id
- page_key
- permission_level
- created_at
- updated_at
```

Unique constraint:

```text
(user_id, page_key)
```

### Phase 4: Migrate existing users

Migration should convert current fields to page permissions.

Suggested mapping:

- `super_admin`: every page -> `admin`
- `perm_edit_content`: routes / activities / kit_preorders / announcements -> `write`
- `perm_review`: feedback -> `write`
- `perm_view_analytics`: analytics -> `read`
- `perm_view_security`: security -> `read`
- `perm_manage_users`: accounts -> `admin`
- `perm_view_audit_logs`: audit_logs -> `read`

For users without a matching old permission:

- page permission should default to `none`, except `overview`.

### Phase 5: Deprecate old permission fields

Do not remove old fields immediately.

Recommended approach:

- keep old fields for one or more releases;
- stop writing new behavior against them;
- optionally mirror new page permissions back into old fields for compatibility during the transition;
- remove or ignore old fields only after the v4.8 line is stable.

## UI Design Direction

### Account list

The account list should show:

- username;
- administrator type;
- status badge;
- permission summary;
- created time;
- actions.

Avoid showing raw ID as the primary identifier.

### Account create/edit page

Suggested sections:

1. Basic information
   - username;
   - administrator type;
   - active status.

2. Page permissions
   - page/module name;
   - permission level selector: none / read / write / admin;
   - preset reset button.

3. Password
   - initial password for new user;
   - optional reset password for existing user.

4. Danger zone
   - deactivate account;
   - permission-sensitive actions.

### Permission selector behavior

For each page key, use a segmented control or compact select:

```text
无权限 | 可读 | 可修改 | 完全管理
```

For dangerous page areas, show a small hint:

- `完全管理会启用删除、回滚、恢复等危险操作。`

## UI Visibility Rules

Permission checks must affect both the visible UI and the backend route guards.

Recommended UI behavior:

### No `read` Permission

If a user has less than `read` permission for a page:

- hide the top navigation entry;
- hide dashboard cards for that module;
- hide shortcut entries for that module;
- hide related module summaries from the management overview;
- direct URL access must return `403`.

Do not show disabled entries for pages the user cannot read.

Reason:

- a user without read permission should not need to know that the page exists;
- hiding unreadable modules keeps the management console cleaner;
- backend guards remain responsible for real security.

### `read` Without `write`

If a user has `read` permission but not `write` permission:

- show list pages, detail pages, statistics, and read-only data;
- hide create buttons;
- hide edit buttons;
- hide save buttons;
- hide upload controls;
- hide ordinary status-change actions;
- backend write routes must return `403`.

Do not show disabled write buttons for pure permission reasons.

### `write` Without `admin`

If a user has `write` permission but not `admin` permission:

- show ordinary create, edit, save, upload, and normal status actions;
- hide danger zones;
- hide rollback actions;
- hide destructive delete or deactivate actions;
- hide restore or forced recovery actions;
- backend dangerous routes must return `403`.

### When Disabled Controls Are Acceptable

Disabled controls may be used only when the action is unavailable because of current object state, not because of user permission.

Examples:

- an ended batch cannot accept new signups;
- a route without a previous version cannot be rolled back;
- the current user cannot edit a specific self-protection field.

Pure permission failure should generally hide the control instead of disabling it.

## Route Guard Rules

Every management route should have a page key and a required level.

Examples:

| Route | Page key | Required level |
| --- | --- | --- |
| `GET /manage/routes` | `routes` | `read` |
| `GET /manage/routes/new` | `routes` | `write` |
| `POST /manage/routes` | `routes` | `write` |
| `POST /manage/routes/<id>/rollback` | `routes` | `admin` |
| `GET /manage/analytics` | `analytics` | `read` |
| `GET /manage/security` | `security` | `read` |
| `GET /manage/users` | `accounts` | `read` |
| `POST /manage/users/<id>` | `accounts` | `write` or `admin` depending on whether permissions change |
| `POST /manage/users/<id>/delete` | `accounts` | `admin` |

Open question:

- Whether ordinary account profile edits should exist separately from account permission management.

## Security and Safety Rules

The implementation should enforce these rules:

- A user cannot grant a permission level higher than their own level for that page.
- A user cannot deactivate themselves.
- A user cannot remove the last active super admin.
- A user without `accounts:admin` cannot change page permissions.
- UI hiding is not enough; backend route guards must enforce permissions.
- Dangerous operations must check `admin`, even if the button is hidden.

## Testing Plan

Tests should cover:

- page permission helper mapping from current legacy fields;
- navigation visibility by permission level;
- dashboard card visibility by permission level;
- read access allowed for `read`;
- write access blocked for `read`;
- dangerous operations blocked for `write` and allowed for `admin`;
- super admin keeps full access;
- last active super admin cannot be deactivated;
- account permission editing cannot exceed actor permissions.

## Versioning Impact

This is a v4.8-level change.

Reason:

- it changes backend authorization behavior;
- it likely introduces new database storage;
- it changes the account management workflow;
- it changes how management pages expose actions.

Suggested version:

- `v4.8.0` for the first implementation.

Patch releases after that can refine UI and migration details.

## Open Questions for Review

1. Should `overview` have its own stored permission, or should every active admin be able to open it?
2. Should soft delete count as `write` or `admin` for each module?
3. Should exports require `read` or `write`?
4. Should account password reset require `accounts:write` or `accounts:admin`?
5. Should `feedback` include both site feedback and route feedback, or should they become separate page keys?
6. Should `audit_logs` be read-only forever, or should retention/deletion controls be planned?
7. Should presets be editable templates, or fixed code-level defaults?
