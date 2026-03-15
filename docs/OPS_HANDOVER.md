# 2tiredcycling.org 运维交接文档（V3.1）

更新时间：2026-03-15  
当前状态：已上线（公网可访问），校园网个别环境可能受 DNS 缓存影响延迟生效

## 1. 基本信息

- 项目名称：2TiredCycling 社团网站
- 生产域名：`2tiredcycling.org`
- 域名注册商：NameSilo
- 域名到期日：2027-03-14
- 生产服务器公网 IP：`43.129.217.167`
- 部署架构：Docker（`gpx-nginx` + `gpx-web` + `gpx-postgres`）
- 当前 Web 入口容器：`gpx-nginx`（对外监听 `80/443`）

## 2. DNS 配置（NameSilo）

当前生效记录：

- `A` 记录：`@` -> `43.129.217.167`
- `A` 记录：`www` -> `43.129.217.167`
- `TXT` 记录：`_domainconnect` -> `www.namesilo.com/domainconnect`（保留，不影响访问）

说明：

- 不要把服务器 IP 填到 NameServer 页面。
- NameServer 维持默认（dnsowl）即可。

## 3. HTTPS 证书

- 证书签发：Let's Encrypt（certbot Docker）
- 证书路径（容器内挂载）：
  - `/etc/nginx/certs/letsencrypt/live/2tiredcycling.org/fullchain.pem`
  - `/etc/nginx/certs/letsencrypt/live/2tiredcycling.org/privkey.pem`
- 当前证书到期：2026-06-13（后续会自动续期）

## 4. Nginx 关键配置

配置文件（宿主机）：

- `/root/web-project/deploy/nginx.conf`

挂载关系：

- `/root/web-project/deploy/nginx.conf` -> `/etc/nginx/conf.d/default.conf`
- `/root/web-project/deploy/certs` -> `/etc/nginx/certs`

关键点：

- 80 端口跳转到 HTTPS
- `server_name` 必须包含：
  - `2tiredcycling.org`
  - `www.2tiredcycling.org`

## 5. 证书自动续期（必须保留）

当前 `crontab` 推荐任务（每天 03:00）：

```bash
0 3 * * * /bin/bash -lc 'docker stop gpx-nginx; docker run --rm -v /root/web-project/deploy/certs/letsencrypt:/etc/letsencrypt certbot/certbot renew --quiet; docker start gpx-nginx'
```

查看定时任务：

```bash
crontab -l
```

手动演练续期（建议每月一次）：

```bash
docker stop gpx-nginx
docker run --rm -v /root/web-project/deploy/certs/letsencrypt:/etc/letsencrypt certbot/certbot renew --dry-run
docker start gpx-nginx
```

## 6. 常用运维命令

查看容器状态：

```bash
docker ps
```

重载 Nginx：

```bash
docker exec -it gpx-nginx nginx -t
docker exec -it gpx-nginx nginx -s reload
```

服务器本机验证站点：

```bash
curl -I https://2tiredcycling.org
curl -I https://www.2tiredcycling.org
```

## 7. 故障排查速查

### 7.1 浏览器报 `ERR_SSL_UNRECOGNIZED_NAME_ALERT`

优先检查：

1. `server_name` 是否包含根域名和 `www`
2. 证书路径是否正确挂载
3. Nginx 是否已 reload
4. DNS 是否仍解析到旧 IP（如 `91.195.240.123`）

### 7.2 外网能打开，校园网打不开

通常是校园 DNS 缓存未刷新：

1. 先用权威 DNS 验证是否已正确解析：
   - `nslookup 2tiredcycling.org 1.1.1.1`
2. 若权威解析正确，等待校园 DNS 刷新（常见几小时到 24 小时）
3. 临时让用户使用公共 DNS 或手机流量访问

### 7.3 Windows 本机排查

```powershell
ipconfig /flushdns
nslookup 2tiredcycling.org
curl.exe -Iv https://2tiredcycling.org
```

## 8. 账号与资产（交接时补全）

请在交接时补全并更新：

- 域名平台账号负责人：
- 云服务器负责人：
- 续费付款方式负责人：
- 2FA 管理人：
- 报销/发票归档位置：

## 9. 变更记录

- 2026-03-15：购买域名 `2tiredcycling.org`
- 2026-03-15：DNS 切换到 `43.129.217.167`
- 2026-03-15：Nginx 绑定根域名与 `www`
- 2026-03-15：签发并启用 HTTPS 证书
- 2026-03-15：配置证书自动续期 cron
