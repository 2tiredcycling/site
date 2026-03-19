# V4.0 SEO 基线规范

适用版本：`V4.0`  
更新时间：2026-03-19

## 1. 目标

确保官网页面具备基础可索引能力，避免上线后“可访问但不可被正确识别”。

## 2. Title 规范

- 首页：`2Tired 骑行社 | 社团官网`
- 社团介绍：`社团介绍 | 2Tired 骑行社`
- 管理团队：`管理团队 | 2Tired 骑行社`
- 活动列表：`活动 | 2Tired 骑行社`
- 活动详情：`<活动标题> | 2Tired 骑行社`
- 路线详情：`<路线名> | 路线共享中心 | 2Tired 骑行社`

## 3. Description 规范

- 每个公开页面必须有 `<meta name="description">`
- 长度建议：80-160 字符
- 描述必须与页面主内容一致，不堆叠关键词

## 4. Sitemap 方案

- 新增 `GET /sitemap.xml`
- 包含：
  - `/`
  - `/about`
  - `/team`
  - `/events`
  - 已发布活动详情
  - 已发布静态页
- 排除：
  - `/manage/*`
  - 测试/临时路径

## 5. Robots 策略

- 保留并强化：
  - `Disallow: /manage/`
  - `Allow: /`
- 在 `robots.txt` 中追加 sitemap 地址

## 6. 404 页面要求

- 明确“页面不存在”
- 提供返回首页与主要入口
- 返回码保持 `404`

## 7. V4.0 验收清单

- 公共页面 `title + description` 覆盖率 100%
- `sitemap.xml` 可访问并返回 200
- `robots.txt` 可访问并包含 manage 屏蔽与 sitemap 声明
- 不新增软 404 页面

