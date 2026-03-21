# 2Tired 社团网站（Flask）

当前版本状态：
- 运行基线：`V3.3.x`（路线中心 + 活动档案 + 管理后台）
- 规划与数据基线：`V4.0.0`（官网化架构、数据模型、迁移兼容已落地）
- 前台架构基线：`V4.1.0`（官网首页 + 静态页 + 活动中心路由 + sitemap）

## 当前已上线能力（V3 基线）

### 用户侧
- 路线详情增强：里程、难度、建议用时、补给点、风险提示、GPX 预览
- 历史活动模块：活动列表/详情，活动与路线关联
- 路线反馈：评分、评论、路况更新、信息过期/路线变更标注
- 综合搜索：路线名/分类/活动名，热门路线与最新更新

### 管理侧
- RBAC：`admin/editor/reviewer/viewer`
- 审核流：`draft -> pending_review -> published -> offline`
- 反馈审核：待审核列表、通过/驳回
- 数据治理：路线版本管理、回滚、软删除+回收站恢复
- 批量导入报告：成功/失败明细下载
- 字段级审计：记录“谁改了什么”

### 平台与可靠性
- API v1 扩展：
  - `GET /api/v1/routes/{id}/preview`
  - `GET /api/v1/activities`
  - `GET /api/v1/activities/{id}`
  - `POST /api/v1/routes/{id}/feedback`
  - `POST /api/v1/admin/feedback/{id}/review`
  - `GET /api/v1/search?q=...`
- 文件安全：上传类型白名单与大小限制
- 列表接口分页 + 核心索引
- Alembic 迁移脚本：`migrations/`

## V4.0 已完成内容（v4.0.0）

- 范围冻结与 IA：官网 + GPX 模块边界清晰
- 数据模型基线：新增官网内容与活动报名相关模型
- 迁移基线：`20260319_0002_v4_content_and_registration.py`
- 兼容策略：`ensure_schema_compat()` 已覆盖 V4.0 新表字段兜底
- 文档交付：V4.0 任务单、权限矩阵、SEO/编码/测试计划等

V4.0 文档入口：
- `docs/V4_0_TASKLIST.md`
- `docs/V4_SCOPE.md`
- `docs/V4_IA.md`
- `docs/V4_URL_MAP.md`
- `docs/V4_DATA_MODEL.md`
- `docs/V4_PERMISSION_MATRIX.md`
- `docs/V4_ADMIN_CONTENT_DESIGN.md`
- `docs/V4_EVENT_REGISTRATION_FLOW.md`
- `docs/V4_SEO_BASELINE.md`
- `docs/V4_ENCODING_GUIDE.md`
- `docs/V4_TEST_PLAN.md`
- `docs/PRE_PUSH_CHECKLIST.md`

## V4.1 已完成内容（v4.1.0）

- 官网首页改版：导航入口、公告区、最新活动、最新路线、路线中心整合
- 新增静态页路由与模板：`/about`、`/team`、`/contact`
- 活动中心路由：`/events`、`/events/<id>`（保留 `/activities` 兼容）
- 基础 SEO 增强：
  - 页面 `meta description`
  - `GET /sitemap.xml`
  - `robots.txt` 增加 `Sitemap` 声明
- 测试补充：站点地图、静态页、events 别名路由

## 目录结构

```text
web-project/
  app/
    routes_web.py
    routes_api_v1.py
    routes_admin.py
    models.py
    querying.py
    services.py
  migrations/
    env.py
    versions/
  tests/
  uploads/gpx/
  instance/
  config.py
  run.py
```

## 本地启动

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

## 默认入口

- 用户页：`/`
- 社团介绍：`/about`
- 管理团队：`/team`
- 联系我们：`/contact`
- 活动中心：`/events`
- 路线详情：`/routes/<id>`
- 活动列表：`/activities`
- 活动详情：`/activities/<id>`
- 管理登录：`/manage/login`
- 管理后台：`/manage`
- API v1：`/api/v1/routes`
- 健康检查：`/health`
- 指标：`/metrics`
- 站点地图：`/sitemap.xml`

## 测试

```bash
python -m pytest -q
```

## 版本说明

- 已打标签：`v4.0.0`、`v4.0.1`
- 当前阶段：`V4.2.x`（官网样式统一与视觉优化）
- 下一阶段：`V4.3`（新增界面：加入社团申请、未来活动、活动报名）
