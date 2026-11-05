# service-deployer

页面发布服务（Page Publisher），部署在 `www.html.living`。提供 Web UI、REST API 和 MCP 接口，允许用户/AI Agent 通过 OAuth 鉴权发布 HTML 页面并上传图片到 Cloudflare R2。

## 架构

| 组件 | 技术栈 | 端口 | 路径 |
|---|---|---|---|
| `backend/` | FastAPI + PostgreSQL + uvicorn | 30001 (`127.0.0.1`) | REST API + 前端静态托管 |
| `frontend/` | Vite + TypeScript | — | 构建产物由 backend 直出 |
| `mcp-node/` | Node.js + TypeScript | 30002 (`127.0.0.1`) | MCP 网关（Google OAuth + PKCE） |
| `mcp/` | Python | — | 早期 MCP 实现（已被 mcp-node 替代） |
| `skill/` | — | — | page-publisher skill 文档 |

反代：Caddy 在 `www.html.living` 把 `/mcp*` 和 `/.well-known/*` 打到 30002，根路径打到 30001。两个后端服务**仅监听 127.0.0.1**，不对公网暴露，需经 Caddy 进入。

## 功能

页面分享权限（AI-2871）：支持仅自己、指定人员和群组、全公司三档；操作入口、API、迁移和 P1 限制见 [page-sharing.md](docs/page-sharing.md)。

### Web UI（`/`、`/console`）
Google OAuth 登录（仅放行 `allowed_domain`，目前 `feedmob.com`）后可在控制台浏览、发布、删除自己的页面。

### REST API
| 端点 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/api/pages` | GET/POST | session 或 Bearer | 列表/发布 |
| `/api/pages/{owner}/{slug}` | GET | session 或 Bearer | 详情 |
| `/api/pages/{page_id}` | DELETE | **本人 / `admin_emails` / 静态 token** | 见下文权限规则 |
| `/api/pages/{page_id}/datasets` | GET/POST | **本人 / `admin_emails` / 静态 token** | 页面数据文件列表 / 上传 CSV·JSON |
| `/api/pages/{page_id}/datasets/{dataset_id}` | DELETE | 同上 | 删除数据文件 |
| `/api/assets` | POST | session 或 Bearer | 上传图片到 R2 |
| `/p/{owner}/{slug}` | GET | session | 渲染已发布页面 |
| `/p/{owner}/{slug}/data/{name}` | GET | 页面 data token 或 session/API Key | 读取并过滤页面数据（见下文） |
| `/auth/login`, `/auth/callback`, `/auth/logout` | GET | — | Google OAuth 流程 |

### MCP 服务（`/mcp`）
Node.js 实现的 MCP 网关，支持 Google OAuth + PKCE 授权流，或用静态 Bearer token（`PUBLISHER_TOKEN`）调用。

| 工具 | 用途 |
|---|---|
| `publish_page` | 发布 HTML 页面（可附带图片，自动上传 R2 替换 URL） |
| `delete_page` | 删除页面（需归属/管理员） |
| `list_pages` | 搜索/浏览已发布页面 |
| `get_page_detail` | 获取单页完整元数据 |
| `get_page_stats` | 统计概览 |
| `upload_image` | 空工具，指引 AI 通过 REST `POST /mcp/upload` 上传本地图片到 R2 |
| `upload_dataset` | 给页面附加 CSV/JSON 数据文件（同名覆盖，用于刷新 dashboard 数据） |
| `list_datasets` | 列出页面的数据文件（含列名、行数） |
| `delete_dataset` | 删除页面的某个数据文件 |

### upload_image 工作流程

`upload_image` 本身不上传文件，但其工具描述会指引 AI 按以下流程操作：

```
1. AI 调用 curl POST https://www.html.living/mcp/upload
   -F "file=@本地图片.png;filename=图片.png"
   -H "Authorization: Bearer <token>"
   → 返回 { "full_url": "https://pub-xxx.r2.dev/uploads/.../xxx.png" }

2. AI 在 HTML 中使用返回的 URL:
   <img src="https://pub-xxx.r2.dev/uploads/.../xxx.png">

3. AI 调用 publish_page(html, owner, ...) 发布页面
```

这样本地图片不需要 base64 编码，直接通过 HTTP multipart 上传。

### publish_page 图片上传

`publish_page` 支持可选的 `images` 参数。流程：

1. HTML 中用文件名引用图片：`<img src="chart.png">`
2. 调用时传入 `images: [{filename: "chart.png", base64: "..."}]`
3. 工具自动上传每张图片到 R2，拿到公开 URL
4. 替换 HTML 中 `src="chart.png"` → `src="https://...r2.dev/xxx.png"`
5. 发布最终 HTML

`publish_page` 还支持可选的 `datasets` 参数（`[{filename, content|base64, name}]`），发布成功后逐个附加到新页面上，一次调用就能交付「dashboard + 数据」。

## 页面数据文件（dashboard 动态数据）

dashboard 类页面的数据不适合硬编码进 HTML：数据一变就得重新发布整页。所以页面可以携带数据文件：

1. 发布页面拿到 `data.id`
2. `POST /api/pages/{page_id}/datasets` 上传 `.csv` / `.tsv` / `.json` / `.ndjson`（单文件 ≤ 20 MB、≤ 20 万行），或在控制台页面详情里点「上传数据文件」
3. 页面 HTML 里用注入的 `PageData` 读取和过滤，**不需要**引入任何库

```html
<script>
  (async () => {
    const rows = await PageData.load("spend");                 // 全量（服务端解析好的行）
    const top = await PageData.query("spend", {                // 服务端过滤/排序/分页
      where: { country: "US", spend: { gte: 100 } },
      sort: "spend", order: "desc", limit: 20,
    });
    const visible = PageData.filter(rows, { campaign: { contains: "brand" } }); // 浏览器端过滤
    const options = PageData.unique(rows, "country");           // 下拉选项
  })();
</script>
```

底层 HTTP 端点是 `GET /p/{owner}/{slug}/data/{name}`，支持可重复的 `where=column:op:value`、`select`、`sort`、`order`、`limit`、`offset` 和 `format=json|rows|csv`。算子：`eq ne gt gte lt lte contains startswith endswith in nin empty notempty`。CSV 解析、过滤、排序都在服务端完成，页面只拿到需要的行。

同一个 `name` 再次上传会覆盖旧文件，所以刷新数据不用改 HTML、也不换 URL。

**为什么用 `k` 参数而不是 cookie**：发布页面带 `CSP: sandbox`（没有 `allow-same-origin`），origin 是 opaque，页面里的 `fetch` 发不出会话 cookie。所以渲染时给页面注入一个页面级随机 `data_token`，数据端点用它鉴权（只对该页面的数据有效），响应带 `Access-Control-Allow-Origin: *`。能看到页面的人本来就能看到这些数据，令牌不额外放大权限；管理数据文件仍然要页面归属人或管理员身份。

## 鉴权与权限模型

| 调用方 | 鉴权方式 | 删除权限 |
|---|---|---|
| Web 用户 | Google OAuth session cookie | 仅可删 `user_id`/`user_email` 匹配的页 |
| `admin_emails` 列表里的用户 | 同上 | 可删任意页 |
| 内部脚本 / MCP 转发 | `Authorization: Bearer <PUBLISHER_TOKEN>` | 可删任意页（信任服务端配置） |
| MCP OAuth 客户端 | 经 Google OAuth + PKCE 颁发的 JWT | 等同 Web 用户 |

`admin_emails` 在 `backend/.env` 里配置，逗号分隔，例如：
```
admin_emails=tony@feedmob.com,admin@feedmob.com
```

## 发布页面的隔离与安全

发布的页面通过 `/p/{owner}/{slug}` 渲染，因为内容是用户提交的 HTML，响应头会带：

- `Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups allow-modals` — 浏览器把页面当做不同 origin，禁止访问 `www.html.living` 域下其他服务的 cookie/storage
- `X-Frame-Options: SAMEORIGIN` — 防被外站 iframe 钓鱼
- `Referrer-Policy: no-referrer`、`X-Content-Type-Options: nosniff`

## 部署

生产部署在 `ubuntu@3.15.32.167:/srv/service-deployer/`，由 systemd 管理：

- `service-deployer.service` — 后端 API
- `service-deployer-mcp.service` — MCP 网关
- `service-deployer-backup.timer` — 每日 03:30 UTC 跑 `pg_dump`，14 天保留

unit 文件本身**不含任何密钥**，敏感凭据从 `/etc/service-deployer/*.env`（chmod 600 root）通过 `EnvironmentFile=` 加载。完整部署步骤、密钥文件结构、安全清单见 [`deploy/README.md`](deploy/README.md)。

防火墙：ufw 仅放行 22/80/443。

## 本地开发

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -e .
cp .env.example .env  # 填入凭据
uvicorn app.main:app --reload --port 30001

# Frontend
cd frontend
npm install
npm run dev

# MCP gateway
cd mcp-node
npm install
npm run build
node dist/index.js
```

## 环境变量

**Backend (`backend/.env`)**

| 变量 | 说明 |
|---|---|
| `database_url` | PostgreSQL 连接串 |
| `google_client_id` / `google_client_secret` | Google OAuth |
| `allowed_domain` | 限制登录的 Google Workspace 域（如 `feedmob.com`） |
| `session_secret` | Cookie session 签名密钥（`openssl rand -hex 32`） |
| `jwt_secret` | 与 MCP 共享的 JWT 签名密钥 |
| `admin_emails` | 逗号分隔的管理员邮箱列表，可删任意页 |
| `publisher_api_token` | 静态 Bearer token，给内部脚本/MCP 用 |

**Backend (systemd 环境)**

| 变量 | 说明 |
|---|---|
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | Cloudflare R2 凭据 |
| `R2_BUCKET_NAME` / `R2_PUBLIC_URL` | R2 bucket 名和公网域名 |
| `STATIC_DIR` | 前端构建产物路径 |

**MCP (`mcp-node/`，systemd 环境)**

| 变量 | 说明 |
|---|---|
| `HOST` / `PORT` | 监听地址（默认 `127.0.0.1:30002`） |
| `BASE_URL` | OAuth metadata 里的对外 URL |
| `PUBLISHER_URL` / `PUBLISHER_TOKEN` | 后端 API 地址与静态 token |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth |
| `ALLOWED_DOMAIN` | 限制登录域 |
| `JWT_SECRET` | 与 backend 共享的 JWT 密钥 |

## 相关

- 公网入口：https://www.html.living/
- MCP 入口：https://www.html.living/mcp
- Skill 文档：`skill/page-publisher.md`
- 部署细节：[`deploy/README.md`](deploy/README.md)
