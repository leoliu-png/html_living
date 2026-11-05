# 部署配置

## 文件清单

- `service-deployer.service` — 后端 systemd unit
- `service-deployer-mcp.service` — MCP 网关 systemd unit
- `Caddyfile` — Caddy 反代配置（节选自 `/etc/caddy/Caddyfile`）

## 密钥管理

两个 unit 都通过 `EnvironmentFile=` 加载敏感凭据，而非把密钥写进 unit 文件。
首次部署需要在服务器上创建：

```bash
sudo mkdir -p /etc/service-deployer
sudo chmod 700 /etc/service-deployer

# Backend 密钥
sudo tee /etc/service-deployer/backend.env > /dev/null <<'EOF'
R2_ACCOUNT_ID=<your-cloudflare-account-id>
R2_ACCESS_KEY_ID=<your-r2-access-key>
R2_SECRET_ACCESS_KEY=<your-r2-secret>
EOF
sudo chmod 600 /etc/service-deployer/backend.env

# MCP 密钥
sudo tee /etc/service-deployer/mcp.env > /dev/null <<'EOF'
PUBLISHER_TOKEN=<shared-with-backend-api_token>
GOOGLE_CLIENT_ID=<google-oauth-client-id>
GOOGLE_CLIENT_SECRET=<google-oauth-client-secret>
JWT_SECRET=<random-32+ chars, openssl rand -hex 32>
EOF
sudo chmod 600 /etc/service-deployer/mcp.env

# Backend 自己的 .env（DB/OAuth/session_secret/admin_emails）
# 路径：/srv/service-deployer/backend/.env
# 参考 backend/.env.example
```

## 安装/更新

```bash
# 复制 unit 文件
sudo cp deploy/service-deployer*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now service-deployer service-deployer-mcp

# 滚动重启
sudo systemctl restart service-deployer service-deployer-mcp
sudo systemctl status service-deployer service-deployer-mcp --no-pager
```

## 安全清单

- [ ] backend 监听 `127.0.0.1:30001`（已配置）
- [ ] mcp-node 监听 `127.0.0.1:30002`（通过 `HOST` 环境变量，需要代码层支持）
- [ ] ufw 启用，仅放行 22/80/443
- [ ] `/etc/service-deployer/*.env` 权限 600
- [ ] PostgreSQL 仅监听 `127.0.0.1`
- [ ] Caddy 处理 TLS（自动 Let's Encrypt）
- [ ] PostgreSQL 每日 `pg_dump` 异地备份
