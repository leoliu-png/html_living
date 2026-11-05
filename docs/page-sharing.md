# AI-2871: page sharing (P1)

Pages have `visibility: private | restricted | org`, `share_with: {users: [emails], groups: [slugs]}` and `listed: boolean`.
The authenticated account is the owner; the URL's `owner` namespace is not an identity.

## Behavior

- `private`: owner and administrators.
- `restricted`: owner, explicitly granted FeedMob accounts, members/managers of granted groups, and administrators.
- `org`: any authenticated FeedMob account. `listed=false` hides it from registry, regular lists, search and stats; the owner can still find it with `scope=mine`.
- Denied reads return 404. Anonymous HTML requests still go to login; unauthenticated API requests return 401.
- Admin token and configured administrators can view all pages; reads and all sharing changes are audited in `sharing_audit_log`. Unlisted pages are still omitted from discovery for administrators, but are accessible by direct URL/ID.
- Only owners and administrators can change sharing. Legacy unassigned org pages keep the existing claim workflow. An unassigned private page can only be managed by an administrator.
- New accounts default to org for compatibility. Each account can change its defaults. A publish call with no sharing fields inherits all account defaults; explicit sharing overrides them. Omitted `visibility` in a partial explicit configuration inherits the account's level; omitted grants become empty and omitted `listed` becomes true.
- User API keys and MCP OAuth use their associated user's permissions. MCP must forward identity only with the trusted backend credential; static MCP remains the audited admin principal.

## Interfaces

Console: visibility badges in lists; select a page and click Share. Sharing settings in the sidebar provides new-page defaults, group creation, and member/manager edits. The publish dialog starts with account defaults and lets the user choose sharing before publishing.

REST (all use the existing `code/msg/data` envelope and existing authentication):

| Method | Path | Body / result |
| --- | --- | --- |
| POST | `/api/pages` | Existing content fields plus optional sharing fields; returns effective sharing |
| PUT | `/api/pages/{id}` | Content and/or sharing fields |
| GET, PUT | `/api/pages/{id}/sharing` | Read/patch sharing (owner/admin only) |
| GET, POST | `/api/groups` | List / create `{slug,name,managers,members}` |
| PUT | `/api/groups/{slug}/members` | Replace `{managers,members}` (manager/admin only) |
| GET, PUT | `/api/me/sharing-defaults` | `{default_visibility,default_grants:{users,groups}}` |

Group slugs are unique; at least one manager is required. Managers are also members. Usernames must be FeedMob email addresses. Group membership is evaluated on every request; membership lists are only returned to managers/admins.

MCP: `publish_page` now accepts sharing; `update_page`, `get_page_sharing`, `set_page_sharing`, `list_groups`, `get_sharing_defaults`, `set_sharing_defaults` are added. `get_page_detail` and publish/update responses include effective sharing. `list_pages` supports `scope=mine`.

## Data and limitations

Non-public HTML and all page API/data responses use `Cache-Control: private, no-store` and `Vary: Cookie, Authorization`. This also covers denied responses.

The sandboxed HTML's `PageData` manifest contains a signed, viewer-bound credential, valid for one hour. It includes the page token revision. Each dataset request rechecks current account grants/group membership; sharing changes rotate the revision. Refresh the page after a credential expires. Raw legacy data tokens work only for org pages; they never authorize private or restricted data.

**Images remain public in P1.** Existing R2 image URLs are not protected by page permissions. Signed/proxied private assets, request-access notifications, Google Workspace group sync and external sharing links are not included.

**Legacy SQL `data_sources` templates are disabled by default.** They execute raw SQL using application database privileges, so a caller could query other pages and bypass visibility. Uploaded page datasets remain supported. `allow_legacy_sql_data_sources=true` restores the legacy behavior but reintroduces that bypass; do not enable it in a deployment requiring page confidentiality. Check and migrate existing SQL-template pages before production rollout.

## Rollout and validation

Back up PostgreSQL, install backend dependencies (including `python-multipart`), build frontend and MCP, then restart backend and MCP. Backend startup creates the additive grants/groups/defaults/audit tables and adds the two page columns with defaults `org/true`. Existing visibility is not overwritten by repeated startup. Deploy backend before the updated frontend/MCP. Run a local/staging smoke check before production deployment.

```powershell
cd service-deployer/backend
.\.venv\Scripts\python.exe -m pytest -q
# Optional real PostgreSQL migration verification, using a disposable schema rolled back after the test:
$env:SHARING_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/service_deployer'
.\.venv\Scripts\python.exe -m pytest -q tests/test_sharing_migration.py
cd ../mcp-node
npm test
cd ../frontend
npm run build
```

The permission matrix covers owner, user grant, group member, unrelated user, administrator, static admin token and user API keys across HTML, detail, list, search, stats and data. Further checks cover signed session access, forged identity headers, revoked grants/members, data token tampering, sharing revision rotation, account defaults, invalid grants/atomic rollback, unlisted discovery, legacy pages, SQL-template isolation, audit records and MCP forwarding.
