# V4.0 数据模型设计

适用版本：`V4.0`

更新时间：2026-03-19

## 1. 目标

在不破坏既有 `routes/activities` 业务的前提下，为官网内容管理与活动报名提供独立数据层。

## 2. 新增表

## 2.1 `site_pages`（静态页面）

用途：管理 `/about`、`/team`、`/contact` 等页面内容。

字段：
- `id` PK
- `slug` VARCHAR(64) UNIQUE NOT NULL
- `title` VARCHAR(128) NOT NULL
- `summary` VARCHAR(255) NOT NULL DEFAULT ''
- `content` TEXT NOT NULL DEFAULT ''
- `status` VARCHAR(16) NOT NULL DEFAULT `draft`（`draft/published/offline`）
- `published_at` DATETIME NULL
- `created_by` FK `users.id`
- `updated_by` FK `users.id`
- `created_at` DATETIME NOT NULL
- `updated_at` DATETIME NOT NULL

索引：
- `uq_site_pages_slug`
- `idx_site_pages_status_updated_at(status, updated_at)`

## 2.2 `announcements`（公告）

用途：首页公告区 + 公告列表数据源。

字段：
- `id` PK
- `title` VARCHAR(160) NOT NULL
- `content` TEXT NOT NULL DEFAULT ''
- `status` VARCHAR(16) NOT NULL DEFAULT `draft`（`draft/published/offline`）
- `is_pinned` BOOLEAN NOT NULL DEFAULT FALSE
- `sort_order` INTEGER NOT NULL DEFAULT 0
- `published_at` DATETIME NULL
- `created_by` FK `users.id`
- `updated_by` FK `users.id`
- `created_at` DATETIME NOT NULL
- `updated_at` DATETIME NOT NULL

索引：
- `idx_announcements_status_pinned_published(status, is_pinned, published_at)`
- `idx_announcements_updated_at(updated_at)`

## 2.3 `homepage_sections`（首页配置）

用途：首页模块开关与文案配置（hero、入口卡片、公告区显示等）。

字段：
- `id` PK
- `section_key` VARCHAR(64) UNIQUE NOT NULL（如 `hero`, `quick_links`, `latest_events`）
- `title` VARCHAR(160) NOT NULL DEFAULT ''
- `subtitle` VARCHAR(255) NOT NULL DEFAULT ''
- `payload_json` TEXT NOT NULL DEFAULT '{}'
- `is_enabled` BOOLEAN NOT NULL DEFAULT TRUE
- `sort_order` INTEGER NOT NULL DEFAULT 0
- `updated_by` FK `users.id`
- `created_at` DATETIME NOT NULL
- `updated_at` DATETIME NOT NULL

索引：
- `uq_homepage_sections_section_key`
- `idx_homepage_sections_enabled_sort(is_enabled, sort_order)`

## 2.4 `event_registrations`（活动报名）

用途：记录活动报名信息及处理状态。

字段：
- `id` PK
- `activity_id` FK `activities.id` NOT NULL
- `name` VARCHAR(64) NOT NULL
- `student_id` VARCHAR(32) NOT NULL DEFAULT ''
- `contact` VARCHAR(128) NOT NULL DEFAULT ''
- `notes` TEXT NOT NULL DEFAULT ''
- `status` VARCHAR(16) NOT NULL DEFAULT `pending`（`pending/confirmed/rejected/cancelled`）
- `review_note` VARCHAR(255) NOT NULL DEFAULT ''
- `reviewed_by` FK `users.id` NULL
- `reviewed_at` DATETIME NULL
- `source_ip` VARCHAR(64) NOT NULL DEFAULT ''
- `user_agent` VARCHAR(255) NOT NULL DEFAULT ''
- `created_at` DATETIME NOT NULL
- `updated_at` DATETIME NOT NULL

索引：
- `idx_event_registrations_activity_status(activity_id, status)`
- `idx_event_registrations_created_at(created_at)`
- `idx_event_registrations_student_id(student_id)`

唯一性建议：
- 同一活动同一学号可选唯一约束（V4.2 决定是否强制）

## 3. 状态机

- 内容类（`site_pages`, `announcements`）：`draft -> published -> offline`
- 报名类（`event_registrations`）：`pending -> confirmed/rejected`，允许 `cancelled`

## 4. 审计字段规范

新表统一保留：
- `created_at`, `updated_at`
- 业务需要时保留 `created_by`, `updated_by`
- 审核动作保留 `reviewed_by`, `reviewed_at`

## 5. 数据隔离策略

- GPX 核心路线数据不迁移、不重构
- 官网内容与报名数据独立表维护
- 首页只聚合读取，不在 `routes` / `activities` 混写官网字段
