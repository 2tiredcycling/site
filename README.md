# 2Tired Cycling Club GitHub Pages 静态站

这个仓库用于托管 `2tiredcycling.github.io` 的静态展示网站（根目录部署）。

## 本地预览

在仓库根目录运行：

```powershell
python -m http.server 8000
```

打开 `http://localhost:8000/`。

## 站点结构

- `index.html`：首页
- `about.html`：社团介绍
- `activities.html`：活动记录
- `guide.html`：新人指南
- `contact.html`：联系方式
- `assets/`：样式、脚本、图片
- `MAINTENANCE.md`：维护交接文档

## 更新内容

- 文案直接改对应 `.html` 文件。
- 图片放到 `assets/`（可自建子目录），并用相对路径引用，例如 `assets/images/ride-2026.jpg`。

## GitHub Pages（最简单分支方式）

1. 仓库 Settings -> Pages
2. Build and deployment 选择 `Deploy from a branch`
3. Branch 选择 `main`，文件夹选 `/ (root)`
4. 保存后等待发布

发布地址：`https://2tiredcycling.github.io/`
