# AI-2871: page sharing (P1)

Pages have `visibility: private | restricted | org`, `share_with: {users: [emails], groups: [slugs]}` and `listed: boolean`.
The authenticated account is the owner; the URL's `owner` namespace is not an identity.

## Behavior

- `private`: owner and administrators.
- `restricted`: owner, explicitly granted FeedMob accounts, members/managers of granted groups, and administrators.
- `org`: any authenticated FeedMob account. `listed=false` hides it from registry, regular lists, search and stats; the owner can still find it with `scope=mine`.
- Denied reads return 404. Anonymous HTML requests still go to login; unauthenticated API requests return 401.
- Admin token and configured administrators can view all pages; reads and all sharing changes are audited in `sharing_audit_log`. Unlisted pages are still omitted from discovery for administrators, but are accessible by direct URL/ID.
- Only owners and administrators can change sharing. `share_with` lists in page detail and list responses are only returned to the owner and administrators; other viewers see `visibility` and `listed` with empty lists.
- Legacy unassigned org pages keep the existing claim workflow (explicit claim, or claim-by-update). Every claim writes a `page_claimed` audit row with the previous identity, so an administrator can trace and undo a wrong claim. An unassigned private page can only be managed by an administrator.
- New accounts default to org for compatibility. Each account can change its defaults. A publish call with no sharing fields inherits the defaults; explicit sharing overrides them. Omitted `visibility` in a partial explicit configuration inherits the default level; omitted grants become empty and omitted `listed` becomes true.
- Namespace defaults: an administrator, or a manager of the group whose slug equals an `owner` namespace, can set a default for that namespace (for example `ken-team` → group `ken-team`). Precedence for new pages: namespace default > account default > `org`. `GET /api/me/sharing-defaults?owner=<ns>` reports the effective default and its `source`.
- Deleting a group never leaves a dangling slug behind: a re-registered slug could otherwise inherit the old grants. Deleting with `force` removes the page grants and strips the slug from account and namespace defaults.
- Group slugs are first come, first served. Administrators can reassign the managers of any group through `PUT /api/groups/{slug}/members`.
- User API keys and MCP OAuth use their associated user's permissions. MCP must forward identity only with the trusted backend credential; static MCP remains the audited admin principal.

## Interfaces

Console: visibility badges in lists; select a page and click Share (general access, people and groups, registry toggle, copy link and a "who has access" list). Sharing settings in the sidebar provides account defaults, namespace defaults, group creation, and member/manager edits. The publish dialog starts with the effective default for the typed owner namespace and lets the user choose sharing before publishing. The admin section lists pages that still use legacy SQL templates. `/api-docs` renders the backend catalog (`/api-docs.json`), so sharing endpoints appear there.

REST (all use the existing `code/msg/data` envelope and existing authentication):

| Method | Path | Body / result |
| --- | --- | --- |
| POST | `/api/pages` | Existing content fields plus optional sharing fields; returns effective sharing |
| PUT | `/api/pages/{id}` | Content and/or sharing fields |
| GET, PUT | `/api/pages/{id}/sharing` | Read/patch sharing (owner/admin only) |
| GET, POST | `/api/groups` | List / create `{slug,name,managers,members}` |
| PUT | `/api/groups/{slug}/members` | Replace `{managers,members}` (manager/admin only) |
| PATCH | `/api/groups/{slug}/members` | Incremental `{add_members,add_managers,remove}`; applied atomically under a group lock, at least one manager must remain (422 otherwise) |
| PUT | `/api/groups/{slug}` | Rename `{name}` (manager/admin) |
| DELETE | `/api/groups/{slug}` | Delete (manager/admin). `409` while page grants or account/namespace defaults still reference the slug; `?force=true` removes those references, rotates the affected pages' data credentials and audits each page |
| GET | `/api/pages/{page_id}/audit` | Sharing history and admin reads of one page (owner/admin) |
| GET | `/api/admin/sharing-audit` | Admin: `sharing_audit_log` with `page_id`, `action`, `actor`, `limit` filters |
| GET, PUT | `/api/me/sharing-defaults` | `{default_visibility,default_grants:{users,groups}}`; `GET ?owner=` adds `source`/`owner` |
| GET | `/api/namespaces/sharing-defaults` | List namespace defaults |
| GET, PUT, DELETE | `/api/namespaces/{owner}/sharing-defaults` | Namespace default (admin or same-slug group manager) |
| GET | `/api/admin/legacy-sql-pages` | Admin: pages still using SQL `data_sources`, plus the current mode |

Group slugs are unique; at least one manager is required. Managers are also members. Usernames must be FeedMob email addresses. Group membership is evaluated on every request; membership lists are only returned to managers/admins.

MCP: `publish_page` now accepts sharing; `update_page`, `get_page_sharing`, `set_page_sharing`, `list_groups`, `create_group`, `update_group`, `add_group_members`, `remove_group_members`, `set_group_members` (replace), `delete_group` (`force`), `list_namespace_sharing_defaults`, `claim_page`, `get_page_audit`, `get_sharing_audit` (admin), `get_sharing_defaults` (optional `owner`), `set_sharing_defaults`, `set_namespace_sharing_defaults`, `clear_namespace_sharing_defaults` are added. `get_page_detail` and publish/update responses include effective sharing. `list_pages` supports `scope=mine`.

## Data and limitations

Non-public HTML and all page API/data responses use `Cache-Control: private, no-store` and `Vary: Cookie, Authorization`. This also covers denied responses.

The sandboxed HTML's `PageData` manifest contains a signed, viewer-bound credential, valid for one hour. Signed payloads are readable base64, so the credential carries an HMAC digest of the page token revision, never the raw page data token. Each dataset request rechecks current account grants/group membership; sharing changes rotate the revision. Refresh the page after a credential expires. Raw legacy data tokens work only for org pages; they never authorize private or restricted data.

**Images remain public in P1.** Existing R2 image URLs are not protected by page permissions. Signed/proxied private assets, request-access notifications, Google Workspace group sync and external sharing links are not included.

**Legacy SQL `data_sources` templates.** They used to run raw SQL with application database privileges, so a page could read private pages, API key hashes or data tokens. There are three modes:

| Mode | Setting | Behavior |
| --- | --- | --- |
| `disabled` (default) | nothing set | Existing SQL pages render a "Data source error" (500). New or updated non-empty `data_sources` are rejected with 422 |
| `sandbox` | `LEGACY_SQL_DATABASE_URL` | Each query runs in its own READ ONLY transaction, as a dedicated login role, with `statement_timeout` (`LEGACY_SQL_STATEMENT_TIMEOUT_MS`, default 5000) and `search_path=legacy_sql`. Unqualified `page_assets` resolves to the view `legacy_sql.page_assets`: org + listed pages only, without `data_token` |
| `unsafe` | `ALLOW_LEGACY_SQL_DATA_SOURCES=true` | Old behavior with application privileges. Bypasses page permissions; do not use where pages must stay confidential |

Sandbox privileges come from the login role itself, so `SET ROLE` or `set_config('role', …)` cannot climb back to the application role. Backend startup creates the `legacy_sql` schema and view. A DBA creates the role once:

```sql
CREATE ROLE html_living_legacy_sql LOGIN PASSWORD '<secret>';
GRANT CONNECT ON DATABASE service_deployer TO html_living_legacy_sql;
GRANT USAGE ON SCHEMA legacy_sql TO html_living_legacy_sql;
GRANT SELECT ON legacy_sql.page_assets TO html_living_legacy_sql;
-- Nothing on schema public.
```

```bash
LEGACY_SQL_DATABASE_URL=postgresql+psycopg://html_living_legacy_sql:<secret>@localhost:5432/service_deployer
```

Before rollout, an administrator checks `GET /api/admin/legacy-sql-pages`, or the console's Admin section. If it lists nothing, keep `disabled`. Otherwise either migrate those pages to uploaded datasets, or configure `sandbox`. With `sandbox`, a query that reads tables other than `page_assets` stops working; datasets are the replacement.

## Rollout and validation

Back up PostgreSQL, install backend dependencies (including `python-multipart`), build frontend and MCP, then restart backend and MCP. Backend startup creates the additive grants/groups/defaults/namespace-defaults/audit tables, adds the two page columns with defaults `org/true`, and creates the `legacy_sql` view. Then run the legacy SQL inventory above. Existing visibility is not overwritten by repeated startup. Deploy backend before the updated frontend/MCP. Run a local/staging smoke check before production deployment.

```powershell
cd service-deployer/backend
.\.venv\Scripts\python.exe -m pytest -q
# Optional real PostgreSQL migration verification, using a disposable schema rolled back after the test:
# A superuser URL is needed: the sandbox test creates and drops a throwaway login role.
$env:SHARING_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/service_deployer'
.\.venv\Scripts\python.exe -m pytest -q tests/test_sharing_migration.py tests/test_sharing_followups.py
cd ../mcp-node
npm test
cd ../frontend
npm run build
```

The permission matrix covers owner, user grant, group member, unrelated user, administrator, static admin token and user API keys across HTML, detail, list, search, stats and data. Further checks cover signed session access, forged identity headers, revoked grants/members, data token tampering, sharing revision rotation, the viewer credential not exposing the raw data token, grant-list privacy, account and namespace defaults, invalid grants/atomic rollback, unlisted discovery, legacy pages and claim auditing, SQL-template isolation (including the PostgreSQL sandbox against schema-qualified reads, role escalation, writes and timeouts), the legacy SQL inventory, audit records and MCP forwarding.
