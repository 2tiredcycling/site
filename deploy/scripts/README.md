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
