---
name: page-publisher
description: Publish HTML pages through the FeedMob Service Deployer REST API. Covers user API token auth, page publishing, asset upload, listing, ownership, and curl invocation patterns.
---

# Page Publisher

Publish HTML pages to the FeedMob Service Deployer. Every page gets a stable public URL.

This Skill is documentation for an AI agent. Reading this file does not authenticate the user and does not grant publishing access. Ask the user for their Service Deployer API token when you need to call protected API endpoints.

## Base URL

Use the same origin that served this Skill:

`{{BASE_URL}}`

Published pages are available at:

`{{BASE_URL}}/p/{owner}/{slug}`

## API reference (curl-friendly)

Human docs UI (browser):

`{{BASE_URL}}/api-docs`

Agents and curl can hit the **same path** and get readable docs by default:

```bash
# Default curl Accept is */* → returns markdown catalog
curl -sS "{{BASE_URL}}/api-docs"

# Explicit formats
curl -sS "{{BASE_URL}}/api-docs?format=json"
curl -sS "{{BASE_URL}}/api-docs.json"
curl -sS "{{BASE_URL}}/api-docs.md"
```

Browsers still get the SPA because they send `Accept: text/html`.

## Authentication

Protected API calls require a user API token:

```http
Authorization: Bearer <user_api_token>
```

The user creates this token in the Service Deployer console. Do not invent a token. Do not ask the user for their Google email to fill `submitter`; the backend derives submitter ownership from the authenticated API token.

The `submitter`, `user_email`, and `user_id` fields are server-controlled. Never include them in request bodies.

## Publish a page

Endpoint:

```http
POST /api/pages
Content-Type: application/json
Authorization: Bearer <user_api_token>
```

Body:

| Field | Required | Description |
|---|---|---|
| `html` | yes | Full HTML document or fragment |
| `owner` | yes | Owner/group name. Use lowercase letters, numbers, and hyphens |
| `description` | yes | Short human-readable purpose of the page |
| `title` | no | Page title |
| `slug` | no | URL slug. Server generates one when omitted |
| `data_sources` | no | Object of named SQL/data source strings |

Example:

```bash
curl -s -X POST "{{BASE_URL}}/api/pages" \
  -H "Authorization: Bearer <user_api_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "html": "<!doctype html><html><body><h1>Weekly Report</h1></body></html>",
    "owner": "adclarity",
    "description": "AdClarity weekly report",
    "title": "AdClarity Weekly Report"
  }'
```

Successful response includes `data.url`. Return that URL to the user.

## Upload an image

For local image files, upload first, then use the returned `full_url` in the HTML.

Endpoint:

```http
POST /api/assets/upload
Content-Type: multipart/form-data
Authorization: Bearer <user_api_token>
```

Example:

```bash
curl -s -X POST "{{BASE_URL}}/api/assets/upload" \
  -H "Authorization: Bearer <user_api_token>" \
  -F "file=@/path/to/image.png;filename=image.png"
```

Response contains:

```json
{
  "full_url": "https://pub-xxx.r2.dev/uploads/.../image.png"
}
```

Use `full_url`, not the relative `url`, inside the page HTML.

## Attach a data file (dashboards)

When the page is a dashboard driven by CSV/JSON data, do not inline the whole
dataset into the HTML. Upload the data file to the page and read it at runtime,
so the data can be refreshed later without touching the HTML.

Endpoint (page must already exist, use the `data.id` returned by publish):

```http
POST /api/pages/{page_id}/datasets
Content-Type: multipart/form-data
Authorization: Bearer <user_api_token>
```

```bash
curl -s -X POST "{{BASE_URL}}/api/pages/<page_id>/datasets" \
  -H "Authorization: Bearer <user_api_token>" \
  -F "file=@/path/to/spend.csv" \
  -F "name=spend"
```

Accepts `.csv`, `.tsv`, `.json`, `.ndjson` (max 20 MB, 200,000 rows). Uploading
the same `name` again replaces the previous version. The response reports the
detected `columns` and `row_count` — use those exact column names in the HTML.

### Reading the data from the page

Pages that own datasets get a `PageData` helper injected automatically. It needs
no library and no token handling:

```html
<script>
  (async () => {
    // Whole file (server-parsed rows, cached in the page)
    const rows = await PageData.load("spend");

    // Server-side filtering / sorting / paging
    const top = await PageData.query("spend", {
      where: { country: "US", spend: { gte: 100 } },
      sort: "spend",
      order: "desc",
      limit: 20,
    });
    console.log(top.matched, top.rows);

    // Client-side filtering for interactive controls
    const visible = PageData.filter(rows, { campaign: { contains: "brand" } });
    const countries = PageData.unique(rows, "country");
  })();
</script>
```

`PageData` API:

| Call | Result |
| --- | --- |
| `PageData.list()` | Dataset manifest: `name`, `columns`, `row_count`, `format` |
| `PageData.load(name, { parseNumbers })` | All rows (auto-paged, cached) |
| `PageData.query(name, options)` | `{ rows, columns, total, matched, count, offset, limit }` |
| `PageData.filter(rows, where)` | Same filter semantics, applied in the browser |
| `PageData.sort(rows, column, order)` | Numeric-aware sort |
| `PageData.unique(rows, column)` | Distinct values, handy for filter dropdowns |
| `PageData.url(name, options)` | Raw data URL, e.g. to feed into a CSV download link |

Filter operators (both server- and client-side): `eq`, `ne`, `gt`, `gte`, `lt`,
`lte`, `contains`, `startswith`, `endswith`, `in`, `nin`, `empty`, `notempty`.
Write them as `{ column: value }` (eq), `{ column: { gte: 100 } }`, or
`{ column: ["ios", "android"] }` (in).

Raw HTTP shape, if the page needs a plain `fetch` or a CSV download:

```
GET /p/{owner}/{slug}/data/{name}?k=<page_data_token>
    &where=country:eq:US&where=spend:gte:100
    &select=campaign,spend&sort=spend&order=desc&limit=20&offset=0
    &format=json|rows|csv
```

The token is injected into the page for you (`PageData` adds `k` automatically);
an authenticated session or API key also works for manual curl checks.

## List pages

Endpoint:

```http
GET /api/pages?page=1&page_size=20&scope=all&q=<query>
Authorization: Bearer <user_api_token>
```

Query parameters:

| Parameter | Description |
|---|---|
| `page` | Page number, default `1` |
| `page_size` | Results per page, default `20`, max `100` |
| `q` | Optional search keyword across owner, slug, title, submitter, description |
| `scope` | `all`, `mine`, or `unassigned` |

Scopes:

- `all`: all published pages visible to the console/API user.
- `mine`: pages owned by the current API token user.
- `unassigned`: legacy pages without a bound user identity and whose submitter is outside the admin allowlist.

## Update a page

Endpoint:

```http
PUT /api/pages/{page_id}
Content-Type: application/json
Authorization: Bearer <user_api_token>
```

Body may include any of:

| Field | Description |
|---|---|
| `html` | New HTML |
| `title` | New title |
| `description` | New description |
| `data_sources` | New data source object |

Ownership rules:

- A user can update their own pages.
- Admin can update any page.
- Any signed-in/API-token user can update an unassigned legacy page; updating it claims it to that user.

## Delete a page

Endpoint:

```http
DELETE /api/pages/{page_id}
Authorization: Bearer <user_api_token>
```

Ownership rules match update. Unassigned legacy pages can be deleted by any signed-in/API-token user.

## Get page detail

Endpoint:

```http
GET /api/pages/{owner}/{slug}
Authorization: Bearer <user_api_token>
```

## Page stats

Endpoint:

```http
GET /api/pages/stats
Authorization: Bearer <user_api_token>
```

Returns total pages, top owners, and top submitters.

## Agent workflow

1. If the user asks you to publish a page, ask for their Service Deployer API token unless they already provided one in the current context.
2. Upload local image assets first with `/api/assets/upload`.
3. Replace local image references in the HTML with returned `full_url` values.
4. Call `POST /api/pages` with `html`, `owner`, `description`, and optional `title`/`slug`.
5. For a data-driven dashboard, upload the CSV/JSON with `POST /api/pages/{page_id}/datasets` and read it in the HTML through `PageData` instead of inlining the rows.
6. Return the published URL from `data.url`.

## Pitfalls

- Do not use `submitter` in request bodies.
- Do not claim that reading this Skill logs the user in.
- Do not use MCP endpoints unless the user explicitly asks for MCP integration.
- Do not use the old command `npx skills add feedmob/page-publisher`; that package/repository is not published.
- For images, use the response `full_url` field in HTML.
- Do not inline large datasets into the HTML; upload them as data files and query them with `PageData`.
- Dataset column names come from the uploaded file's header — read them from the upload response instead of guessing.
- Keep generated HTML reasonably compact. Large embedded base64 images should be uploaded as files instead.

## More API documentation

The interactive API documentation is available at:

`{{BASE_URL}}/api-docs`
