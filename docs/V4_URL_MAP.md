# V4.0 URL 路由规划

适用版本：`V4.0`

更新时间：2026-03-19

## 1. 公开页面路由

- `GET /` 首页（官网化聚合）
- `GET /about` 社团介绍
- `GET /team` 管理团队
- `GET /events` 活动列表
- `GET /events/<int:event_id>` 活动详情
- `GET /events/<int:event_id>/register` 活动报名页
- `POST /events/<int:event_id>/register` 提交报名
- `GET /events/<int:event_id>/register/success` 报名成功页
- `GET /contact` 联系页
- `GET /feedback` 网站反馈（保留）
- `POST /feedback` 网站反馈提交（保留）
- `GET /routes/<int:route_id>` 路线详情（保留）
- `GET /download/<int:route_id>` GPX 下载（保留）

## 2. 后台路由（新增）

- `GET /manage/content`
- `GET /manage/announcements`
- `GET /manage/announcements/new`
- `GET /manage/announcements/<int:id>/edit`
- `POST /manage/announcements/create`
- `POST /manage/announcements/<int:id>/update`
- `POST /manage/announcements/<int:id>/delete`
- `GET /manage/pages`
- `GET /manage/pages/<slug>/edit`
- `POST /manage/pages/<slug>/update`
- `GET /manage/homepage`
- `POST /manage/homepage/update`
- `GET /manage/event-registrations`
- `POST /manage/event-registrations/<int:id>/status`

## 3. API 路由（预留）

- `GET /api/v1/announcements`
- `GET /api/v1/pages/<slug>`
- `POST /api/v1/events/<int:event_id>/registrations`

注：V4.0 仅完成路由规划，不要求全部 API 实装。

## 4. 兼容与重定向策略

- 现有 `/activities` 与 `/activities/<id>` 在 V4 阶段保留
- 新前台“活动”优先使用 `/events*`，后续将 `/activities*` 做 301 到 `/events*`
- 旧管理路径不变，新增模块挂载在 `/manage/*`

## 5. 冲突审计结论

- 不覆盖现有 `routes_web.py` 的关键保留路由：`/`, `/feedback`, `/routes/<id>`, `/download/<id>`
- 不覆盖现有 `routes_admin.py` 已占用路径
- 新路由命名统一用 `events` 与 `event-registrations`，避免与已有 `activities` 混淆
