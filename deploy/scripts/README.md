# V2 运维脚本

- `daily_backup.ps1`: 每日备份 `instance/app.db` 与 `uploads/gpx` 到 zip 文件。
- `monthly_restore_drill.ps1`: 对指定备份包做恢复演练，验证关键目录是否可恢复。

## 建议任务计划

1. 每日 03:00 执行：
`powershell -ExecutionPolicy Bypass -File deploy/scripts/daily_backup.ps1 -ProjectRoot C:\Work\CUHK\web-project -BackupDir backups`

2. 每月第一天 10:00 执行演练（替换成最近备份包）：
`powershell -ExecutionPolicy Bypass -File deploy/scripts/monthly_restore_drill.ps1 -ProjectRoot C:\Work\CUHK\web-project -BackupFile C:\Work\CUHK\web-project\backups\backup_YYYYMMDD_HHMMSS.zip`

## 监控建议

- 5xx：采集 Web 日志并统计状态码。
- 慢请求：Nginx 打开 `request_time`，阈值建议 1s。
- 磁盘容量：监控系统盘剩余空间低于 15% 告警。
- 应用指标：抓取 `/metrics`。

## 发版同步（V3.1.3+，Ubuntu 推荐）

新增脚本：`prepare_release.sh`（Ubuntu）  
用途：从上一个版本目录复制关键配置到新版本目录，减少人工漏拷。

### 1) 先检查计划（默认 dry-run）

```bash
chmod +x deploy/scripts/prepare_release.sh
./deploy/scripts/prepare_release.sh \
  --releases-root /opt/2tired/releases \
  --current v3.1.4
```

### 2) 确认后执行复制

```bash
./deploy/scripts/prepare_release.sh \
  --releases-root /opt/2tired/releases \
  --current v3.1.4 \
  --apply
```

### 3) 清单配置

默认清单文件：`deploy/scripts/release_copy_manifest.txt`  
按需维护每行一个相对路径，例如：

- `.env`
- `docker-compose.yml`
- `deploy/nginx.conf`
- `deploy/certs`
- `instance`
- `uploads`

脚本会在新版本目录写入 `deploy_sync_YYYYMMDD_HHMMSS.log`，用于审计和回滚排查。

### Windows 可选

如你在 Windows 环境准备发布目录，可用 `prepare_release.ps1`，参数含义与 Ubuntu 脚本一致。
