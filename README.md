# GPX 路线知识库 V3（Flask）

从 V2 的“路线下载平台”升级到“路线知识库 + 活动档案库”。

## V3 能力总览

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
- 路线详情：`/routes/<id>`
- 活动列表：`/activities`
- 活动详情：`/activities/<id>`
- 管理登录：`/manage/login`
- 管理后台：`/manage`
- API v1：`/api/v1/routes`
- 健康检查：`/health`
- 指标：`/metrics`

## 测试

```bash
python -m pytest -q
```
