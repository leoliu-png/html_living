import type { Language } from "./content";

type HttpMethod = "GET" | "POST" | "PUT" | "DELETE" | "PATCH";

type Param = {
  name: string;
  in: "path" | "query" | "header" | "body";
  required: boolean;
  type: string;
  description: string;
  example?: string;
};

type Endpoint = {
  id: string;
  group: "pages" | "auth" | "system" | "assets" | "datasets" | "sharing" | "admin";
  method: HttpMethod;
  path: string;
  title: string;
  summary: string;
  description: string;
  auth: "required" | "none";
  params?: Param[];
  requestExample?: string;
  responseExample: string;
  curlExample: string;
};

const ENDPOINTS: Endpoint[] = [
  {
    id: "publish-page",
    group: "pages",
    method: "POST",
    path: "/api/pages",
    title: "发布页面",
    summary: "Create a new published page and return its public URL.",
    description:
      "提交一个 HTML 页面，保存到数据库并返回可访问的 URL。提交人邮箱由当前认证身份自动设置，不能通过请求体覆盖。owner + slug 唯一；省略 slug 时服务端自动生成 10 位。",
    auth: "required",
    params: [
      { name: "html", in: "body", required: true, type: "string", description: "页面完整 HTML", example: "<h1>Hello</h1>" },
      { name: "owner", in: "body", required: true, type: "string", description: "所有者/分组（小写字母、数字、连字符）", example: "adclarity" },
      { name: "description", in: "body", required: true, type: "string", description: "页面用途说明" },
      { name: "title", in: "body", required: false, type: "string", description: "页面标题（可选）" },
      { name: "slug", in: "body", required: false, type: "string", description: "URL slug，省略时自动生成 10 位" },
      { name: "data_sources", in: "body", required: false, type: "object", description: "模板数据源（key=SQL）" },
    ],
    requestExample: `{
  "html": "<h1>AdClarity 周报</h1><p>本周 Top 5 ...</p>",
  "owner": "adclarity",
  "description": "AdClarity 每周广告数据汇总",
  "title": "AdClarity 周报 W23"
}`,
    responseExample: `{
  "code": 0,
  "msg": "page published",
  "data": {
    "id": "183cbc20-0935-4ea4-ad67-74313bf89512",
    "owner": "adclarity",
    "slug": "e6viyb12di",
    "url": "http://127.0.0.1:8000/p/adclarity/e6viyb12di",
    "created_at": "2026-06-04T16:43:36+08:00"
  }
}`,
    curlExample: `curl -X POST http://127.0.0.1:8000/api/pages?token=$TOKEN \\
  -H "Content-Type: application/json" \\
  -d '{
    "html": "<h1>Hello</h1>",
    "owner": "adclarity",
    "description": "test"
  }'`,
  },
  {
    id: "list-pages",
    group: "pages",
    method: "GET",
    path: "/api/pages",
    title: "列出页面",
    summary: "List and search published pages, paginated.",
    description:
      "支持分页、scope 过滤、绑定身份筛选，以及跨 owner/slug/title/submitter/description 的模糊搜索。scope=all 返回全部；scope=mine 返回当前登录/Key 用户发布的页面。user_email/user_id 用于按真实归属筛选，submitter 仅用于历史兼容。",
    auth: "required",
    params: [
      { name: "page", in: "query", required: false, type: "int", description: "页码（默认 1）", example: "1" },
      { name: "page_size", in: "query", required: false, type: "int", description: "每页条数（1-100，默认 20）", example: "20" },
      { name: "q", in: "query", required: false, type: "string", description: "搜索关键字" },
      { name: "scope", in: "query", required: false, type: "string", description: "all / mine（默认 all；unassigned 仅保留旧接口兼容）", example: "mine" },
      { name: "user_email", in: "query", required: false, type: "string", description: "按绑定归属邮箱筛选", example: "alice@feedmob.com" },
      { name: "user_id", in: "query", required: false, type: "string", description: "按绑定 Google user id 筛选" },
    ],
    responseExample: `{
  "code": 0,
  "data": {
    "items": [ { "id": "...", "owner": "...", "slug": "...", "title": "...", ... } ],
    "pagination": { "page": 1, "page_size": 20, "total": 5, "total_pages": 1, "has_next": false, "has_prev": false }
  }
}`,
    curlExample: `curl "http://127.0.0.1:8000/api/pages?page=1&page_size=20&scope=mine&q=adclarity&token=$TOKEN"`,
  },
  {
    id: "page-stats",
    group: "pages",
    method: "GET",
    path: "/api/pages/stats",
    title: "页面统计",
    summary: "Aggregate stats: totals and top owners/submitters.",
    description: "返回总页面数、独立 owner 数、独立 submitter 数、最近创建时间，以及 Top 10 owner / submitter。",
    auth: "required",
    responseExample: `{
  "code": 0,
  "data": {
    "total_pages": 5,
    "total_owners": 3,
    "total_submitters": 4,
    "latest_created_at": "2026-06-04T16:58:28+08:00",
    "top_owners": [{ "owner": "adclarity", "count": 2 }],
    "top_submitters": [{ "submitter": "alice@feedmob.com", "count": 2 }]
  }
}`,
    curlExample: `curl "http://127.0.0.1:8000/api/pages/stats?token=$TOKEN"`,
  },
  {
    id: "get-page",
    group: "pages",
    method: "GET",
    path: "/api/pages/{owner}/{slug}",
    title: "页面详情",
    summary: "Get full metadata for a specific page by owner + slug.",
    description: "返回单页面的完整元数据。",
    auth: "required",
    params: [
      { name: "owner", in: "path", required: true, type: "string", description: "所有者", example: "adclarity" },
      { name: "slug", in: "path", required: true, type: "string", description: "页面 slug", example: "e6viyb12di" },
    ],
    responseExample: `{
  "code": 0,
  "data": {
    "id": "183cbc20-...",
    "owner": "adclarity",
    "slug": "e6viyb12di",
    "url": "http://127.0.0.1:8000/p/adclarity/e6viyb12di",
    "title": "AdClarity 周报 W23",
    "submitter": "alice@feedmob.com",
    "description": "...",
    "data_sources": null,
    "created_at": "...",
    "updated_at": "..."
  }
}`,
    curlExample: `curl "http://127.0.0.1:8000/api/pages/adclarity/e6viyb12di?token=$TOKEN"`,
  },
  {
    id: "update-page",
    group: "pages",
    method: "PUT",
    path: "/api/pages/{page_id}",
    title: "更新页面",
    summary: "Update an existing page's html/title/description/data_sources.",
    description:
      "按 page_id 更新页面字段。鉴权要求：调用方匹配页面绑定的 user_id/user_email，或为 admin。submitter 只作为历史兼容字段参与兜底匹配。至少传一个字段。",
    auth: "required",
    params: [
      { name: "page_id", in: "path", required: true, type: "string", description: "页面 UUID", example: "183cbc20-0935-4ea4-ad67-74313bf89512" },
      { name: "html", in: "body", required: false, type: "string", description: "新的 HTML" },
      { name: "title", in: "body", required: false, type: "string", description: "新标题" },
      { name: "description", in: "body", required: false, type: "string", description: "新描述" },
      { name: "data_sources", in: "body", required: false, type: "object", description: "新数据源映射" },
    ],
    requestExample: `{
  "title": "AdClarity 周报 W24",
  "description": "更新后的描述"
}`,
    responseExample: `{
  "code": 0,
  "msg": "page updated",
  "data": { "id": "...", "title": "AdClarity 周报 W24", "updated_at": "..." }
}`,
    curlExample: `curl -X PUT "http://127.0.0.1:8000/api/pages/183cbc20-...?token=$TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{ "title": "AdClarity 周报 W24" }'`,
  },
  {
    id: "delete-page",
    group: "pages",
    method: "DELETE",
    path: "/api/pages/{page_id}",
    title: "删除页面",
    summary: "Permanently delete a published page.",
    description: "按 page_id 删除。鉴权要求同更新：绑定用户或 admin。",
    auth: "required",
    params: [
      { name: "page_id", in: "path", required: true, type: "string", description: "页面 UUID" },
    ],
    responseExample: `{
  "code": 0,
  "msg": "page deleted",
  "data": { "id": "183cbc20-..." }
}`,
    curlExample: `curl -X DELETE "http://127.0.0.1:8000/api/pages/183cbc20-...?token=$TOKEN"`,
  },
  {
    id: "render-page",
    group: "pages",
    method: "GET",
    path: "/p/{owner}/{slug}",
    title: "访问已发布页面",
    summary: "Render the raw HTML of a published page (browser-facing).",
    description:
      "浏览器访问的页面 URL。支持登录态、管理员 token 或任意有效用户 API key 访问；访问已发布页面不限制为页面归属用户。返回 HTML 并附带 CSP 沙箱、X-Frame-Options 等安全头。",
    auth: "required",
    params: [
      { name: "owner", in: "path", required: true, type: "string", description: "所有者" },
      { name: "slug", in: "path", required: true, type: "string", description: "页面 slug" },
    ],
    responseExample: `<!doctype html>
<html><body>...页面内容...</body></html>`,
    curlExample: `curl "http://127.0.0.1:8000/p/adclarity/e6viyb12di?token=$TOKEN"

curl "http://127.0.0.1:8000/p/adclarity/e6viyb12di" \\
  -H "Authorization: Bearer $USER_API_KEY"`,
  },
  {
    id: "upload-asset",
    group: "assets",
    method: "POST",
    path: "/api/assets/upload",
    title: "上传图片到 R2",
    summary: "Upload an image file to Cloudflare R2 and return its public URL.",
    description:
      "支持 PNG/JPG/GIF/SVG/WebP/ICO/BMP，最大 50 MB。返回 full_url（绝对地址）和 url（相对路径）",
    auth: "required",
    params: [
      { name: "file", in: "body", required: true, type: "file", description: "图片文件 (multipart/form-data)" },
    ],
    responseExample: `{
  "url": "/uploads/<user-dir>/<uuid>.png",
  "full_url": "https://pub-xxx.r2.dev/uploads/<user-dir>/<uuid>.png",
  "filename": "logo.png",
  "size": 12345
}`,
    curlExample: `curl -X POST "http://127.0.0.1:8000/api/assets/upload?token=$TOKEN" \\
  -F "file=@/path/to/image.png"`,
  },
  {
    id: "upload-dataset",
    group: "datasets",
    method: "POST",
    path: "/api/pages/{page_id}/datasets",
    title: "上传数据文件",
    summary: "Attach a CSV/JSON data file to a page.",
    description:
      "multipart/form-data 上传 .csv / .tsv / .json / .ndjson，单文件最大 20 MB、20 万行。同一个 name 再次上传会覆盖旧文件（dashboard 刷新数据不用改 HTML）。鉴权与编辑页面一致：页面归属人或管理员。",
    auth: "required",
    params: [
      { name: "page_id", in: "path", required: true, type: "string", description: "页面 UUID" },
      { name: "file", in: "body", required: true, type: "file", description: "数据文件 (multipart/form-data)" },
      { name: "name", in: "body", required: false, type: "string", description: "页面内引用名，默认取文件名" },
      { name: "format", in: "body", required: false, type: "string", description: "csv | tsv | json | ndjson，默认按扩展名推断" },
    ],
    responseExample: `{
  "code": 0,
  "msg": "dataset saved",
  "data": {
    "id": "0f0c...",
    "name": "spend",
    "format": "csv",
    "row_count": 1240,
    "columns": ["campaign", "country", "spend", "installs"],
    "size_bytes": 82311,
    "data_url": "https://www.html.living/p/adclarity/e6viyb12di/data/spend"
  }
}`,
    curlExample: `curl -X POST "http://127.0.0.1:8000/api/pages/$PAGE_ID/datasets?token=$TOKEN" \\
  -F "file=@/path/to/spend.csv" \\
  -F "name=spend"`,
  },
  {
    id: "list-datasets",
    group: "datasets",
    method: "GET",
    path: "/api/pages/{page_id}/datasets",
    title: "数据文件列表",
    summary: "List the data files attached to a page.",
    description: "返回数据文件清单、页面数据端点和该页面的 data token。",
    auth: "required",
    params: [
      { name: "page_id", in: "path", required: true, type: "string", description: "页面 UUID" },
    ],
    responseExample: `{
  "code": 0,
  "data": {
    "items": [{ "name": "spend", "row_count": 1240, "columns": ["campaign", "country"] }],
    "data_endpoint": "https://www.html.living/p/adclarity/e6viyb12di/data",
    "data_token": "pTn...",
    "usage": "const rows = await PageData.load('spend')"
  }
}`,
    curlExample: `curl "http://127.0.0.1:8000/api/pages/$PAGE_ID/datasets?token=$TOKEN"`,
  },
  {
    id: "delete-dataset",
    group: "datasets",
    method: "DELETE",
    path: "/api/pages/{page_id}/datasets/{dataset_id}",
    title: "删除数据文件",
    summary: "Delete one data file from a page.",
    description: "删除数据库记录和 R2 对象。鉴权与编辑页面一致。",
    auth: "required",
    params: [
      { name: "page_id", in: "path", required: true, type: "string", description: "页面 UUID" },
      { name: "dataset_id", in: "path", required: true, type: "string", description: "数据文件 UUID" },
    ],
    responseExample: `{ "code": 0, "msg": "dataset deleted", "data": { "id": "0f0c..." } }`,
    curlExample: `curl -X DELETE "http://127.0.0.1:8000/api/pages/$PAGE_ID/datasets/$DATASET_ID?token=$TOKEN"`,
  },
  {
    id: "read-dataset",
    group: "datasets",
    method: "GET",
    path: "/p/{owner}/{slug}/data/{name}",
    title: "读取/过滤数据",
    summary: "Read a page dataset with server-side filtering, sorting, and paging.",
    description:
      "已发布页面的 JS 通过注入的 PageData 调用这个端点。页面运行在 CSP sandbox（opaque origin）里发不出会话 cookie，所以用页面级 data token（k 参数）鉴权；带登录会话或 API Key 时也可直接 curl 调试。响应带 Access-Control-Allow-Origin: *。",
    auth: "required",
    params: [
      { name: "owner", in: "path", required: true, type: "string", description: "页面 owner" },
      { name: "slug", in: "path", required: true, type: "string", description: "页面 slug" },
      { name: "name", in: "path", required: true, type: "string", description: "数据文件引用名" },
      { name: "k", in: "query", required: false, type: "string", description: "页面 data token（页面 JS 自动带上）" },
      { name: "where", in: "query", required: false, type: "string[]", description: "过滤：column:op:value，可重复。op: eq ne gt gte lt lte contains startswith endswith in nin empty notempty", example: "country:in:US,JP" },
      { name: "select", in: "query", required: false, type: "string", description: "只取部分列，逗号分隔" },
      { name: "sort", in: "query", required: false, type: "string", description: "排序列（数字列按数值排序）" },
      { name: "order", in: "query", required: false, type: "string", description: "asc | desc，默认 asc" },
      { name: "limit", in: "query", required: false, type: "integer", description: "默认 5000，最大 50000" },
      { name: "offset", in: "query", required: false, type: "integer", description: "偏移量，默认 0" },
      { name: "format", in: "query", required: false, type: "string", description: "json（带统计）| rows（纯数组）| csv" },
    ],
    responseExample: `{
  "name": "spend",
  "columns": ["campaign", "country", "spend"],
  "total": 1240,
  "matched": 86,
  "count": 20,
  "offset": 0,
  "limit": 20,
  "rows": [{ "campaign": "brand-search", "country": "US", "spend": "1200.50" }]
}`,
    curlExample: `curl "http://127.0.0.1:8000/p/adclarity/e6viyb12di/data/spend?token=$TOKEN" \\
  --get --data-urlencode "where=country:eq:US" --data-urlencode "sort=spend" \\
  --data-urlencode "order=desc" --data-urlencode "limit=20"`,
  },
  {
    id: "auth-me",
    group: "auth",
    method: "GET",
    path: "/auth/me",
    title: "当前用户",
    summary: "Get the current authenticated user (Google session).",
    description: "需要已通过 Google 登录。",
    auth: "none",
    responseExample: `{ "user": { "sub": "...", "email": "...", "name": "...", "hd": "feedmob.com" } }`,
    curlExample: `curl "http://127.0.0.1:8000/auth/me" -b "session=<cookie>"`,
  },
  {
    id: "health",
    group: "system",
    method: "GET",
    path: "/health",
    title: "健康检查",
    summary: "Health check endpoint (public).",
    description: "无需鉴权，用于探活。",
    auth: "none",
    responseExample: `{ "status": "ok" }`,
    curlExample: `curl "http://127.0.0.1:8000/health"`,
  },
];

const COPY = {
  zh: {
    eyebrow: "开发者参考",
    title: "API 文档",
    summary: "FeedMob 内部页面的所有 REST 接口。文档公开可读；写操作（POST/PUT/DELETE）需要 Bearer Token，请在自己的环境中调用。",
    baseUrl: "Base URL",
    auth: "鉴权",
    authRequired: "需要 Token",
    authNone: "公开",
    parameters: "请求参数",
    requestBody: "请求体",
    response: "响应示例",
    curl: "cURL",
    copy: "复制",
    copied: "已复制",
    tryIt: "试用",
    tryItRunning: "调用中…",
    groups: { pages: "页面", auth: "认证", system: "系统", assets: "资源", datasets: "数据文件", sharing: "分享与权限", admin: "管理" } as Record<string, string>,
    paramLocation: { path: "路径", query: "查询", body: "Body", header: "Header" } as Record<string, string>,
    noParams: "无参数",
    required: "必填",
    optional: "可选",
    searchPlaceholder: "搜索方法、路径、描述…",
    tokenNotice: "curl 示例中的 $TOKEN 是用户在控制台生成的 API Key。页面提交人由登录会话、用户 API Key 或受信任 MCP 转发的 Google 邮箱自动设置，不能在请求体里覆盖；管理员/内部 Token 仅供系统内部使用。",
  },
  en: {
    eyebrow: "Developer Reference",
    title: "API Documentation",
    summary: "All REST endpoints for FeedMob's internal page publishing. Docs are public; write operations (POST/PUT/DELETE) require a Bearer Token, call them from your own environment.",
    baseUrl: "Base URL",
    auth: "Auth",
    authRequired: "Token required",
    authNone: "Public",
    parameters: "Parameters",
    requestBody: "Request body",
    response: "Response",
    curl: "cURL",
    copy: "Copy",
    copied: "Copied",
    tryIt: "Try it",
    tryItRunning: "Calling…",
    groups: { pages: "Pages", auth: "Auth", system: "System", assets: "Assets", datasets: "Datasets", sharing: "Sharing", admin: "Admin" } as Record<string, string>,
    paramLocation: { path: "Path", query: "Query", body: "Body", header: "Header" } as Record<string, string>,
    noParams: "No parameters",
    required: "required",
    optional: "optional",
    searchPlaceholder: "Search method, path, description…",
    tokenNotice: "$TOKEN in curl examples is the user's console-generated API key. The submitter is set from the login session, user API key, or trusted MCP-forwarded Google email and cannot be overridden in the request body; admin/internal tokens are for system use only.",
  },
} satisfies Record<Language, Record<string, unknown>>;

export type { Endpoint, HttpMethod, Param };
export { ENDPOINTS, COPY };
