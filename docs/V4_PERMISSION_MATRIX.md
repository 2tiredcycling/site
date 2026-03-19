# V4.0 权限矩阵（页面级 + 操作级）

适用版本：`V4.0`

更新时间：2026-03-19

## 1. 角色基线

- `super_admin`：全部权限
- `ops_admin`：安全/统计/审计优先，默认不编辑内容
- `content_admin`：内容与活动运营优先
- `viewer`：只读

## 2. 页面级权限

| 页面 | super_admin | ops_admin | content_admin | viewer |
|---|---|---|---|---|
| `/manage/content` | Y | N | Y | N |
| `/manage/announcements` | Y | N | Y | N |
| `/manage/pages` | Y | N | Y | N |
| `/manage/homepage` | Y | N | Y | N |
| `/manage/event-registrations` | Y | Y* | Y* | N |

注：`*` 取决于是否开启审核权限。

## 3. 操作级权限

| 操作 | 建议权限位 |
|---|---|
| 公告创建/编辑/发布/下线 | `perm_edit_content` |
| 静态页编辑与发布 | `perm_edit_content` |
| 首页配置更新 | `perm_edit_content` |
| 活动报名状态变更 | `perm_review` |
| 活动报名导出（后续） | `perm_review` |
| 管理员账号管理 | `perm_manage_users` |

## 4. 守卫策略

- 页面守卫：先校验页面访问权限，不满足则 `403`
- 操作守卫：POST 动作再次校验权限位
- 超级管理员兜底：始终允许

## 5. 最小权限原则

- 内容编辑与审核分离，避免一人全链路不可追踪
- 账号管理仅 super_admin 或显式授权用户
- 安全与统计权限与内容权限解耦
