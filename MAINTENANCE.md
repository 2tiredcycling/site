# MAINTENANCE

给后续接手同学：这是纯静态网站，不需要后端。

## 1) 改文字

直接编辑根目录页面文件：
- `index.html`
- `about.html`
- `activities.html`
- `guide.html`
- `contact.html`

## 2) 改图片

1. 把图片放到 `assets/`（建议 `assets/images/`）。
2. 在页面里使用相对路径，例如：`assets/images/xxx.jpg`。

## 3) 更新活动记录

打开 `activities.html`，在 `<ol class="activity-timeline-list">` 中复制一个活动条目并修改日期、人数、活动说明。建议最新活动放最上面。

## 4) 本地检查

```powershell
python -m http.server 8000
```

浏览器访问 `http://localhost:8000/`，检查导航链接和图片是否正常。

## 5) 发布

1. `git add .`
2. `git commit -m "update website content"`
3. `git push origin main`

GitHub Pages 使用 `main` 分支根目录发布。
