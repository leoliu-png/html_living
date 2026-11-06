import { useEffect, useId, useState } from "react";
import { Globe, Lock, Share2, Users, X } from "lucide-react";
import type { ConsoleApi } from "./ConsoleRoot";
import type { Language } from "../content";
import "./SharingControls.css";

export type Sharing = {
  visibility: "private" | "restricted" | "org";
  share_with: { users: string[]; groups: string[] };
  listed: boolean;
};
type NamespaceDefault = {
  owner: string;
  default_visibility: Sharing["visibility"];
  default_grants: Sharing["share_with"];
  updated_by?: string | null;
  can_manage: boolean;
};
type Group = {
  slug: string;
  name: string;
  members: string[];
  managers: string[];
  can_manage: boolean;
};
const labels = {
  zh: {
    private: "仅自己",
    restricted: "指定人员和群组",
    org: "FeedMob 全体员工",
  },
  en: {
    private: "Private",
    restricted: "Selected people & groups",
    org: "Everyone at FeedMob",
  },
};
const empty: Sharing = {
  visibility: "org",
  share_with: { users: [], groups: [] },
  listed: true,
};
const split = (text: string) => [
  ...new Set(
    text
      .split(/[\s,;]+/)
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  ),
];

export function VisibilityBadge({
  visibility = "org",
  language,
}: {
  visibility?: Sharing["visibility"];
  language: Language;
}) {
  const Icon =
    visibility === "private"
      ? Lock
      : visibility === "restricted"
        ? Users
        : Globe;
  return (
    <span className={`sharing-badge ${visibility}`}>
      <Icon size={12} />
      {labels[language][visibility]}
    </span>
  );
}

export function SharingFields({
  value,
  onChange,
  api,
  language,
  showListed = true,
}: {
  value: Sharing;
  onChange: (value: Sharing) => void;
  api: ConsoleApi;
  language: Language;
  showListed?: boolean;
}) {
  const zh = language === "zh";
  const id = useId();
  const [groups, setGroups] = useState<Group[]>([]);
  const [people, setPeople] = useState<string[]>([]);
  const [directoryError, setDirectoryError] = useState("");
  const [email, setEmail] = useState("");
  const [inputError, setInputError] = useState("");
  useEffect(() => {
    let active = true;
    Promise.all([
      api.fetchApi<{ items: Group[] }>("/api/groups"),
      api.fetchApi<{ identity_filters: { user_email: string }[] }>(
        "/api/pages?page_size=1",
      ),
    ])
      .then(([g, p]) => {
        if (active) {
          setGroups(g.items);
          setPeople(p.identity_filters.map((v) => v.user_email));
        }
      })
      .catch((error) => {
        if (active) setDirectoryError(String(error));
      });
    return () => {
      active = false;
    };
  }, [api]);
  function addEmail() {
    const emails = split(email);
    if (
      !emails.length ||
      emails.some((v) => !/^[^\s@]+@feedmob\.com$/.test(v))
    ) {
      setInputError(
        zh
          ? "请输入有效的 @feedmob.com 邮箱"
          : "Enter a valid @feedmob.com email",
      );
      return;
    }
    onChange({
      ...value,
      share_with: {
        ...value.share_with,
        users: [...new Set([...value.share_with.users, ...emails])],
      },
    });
    setEmail("");
    setInputError("");
  }
  return (
    <div className="sharing-fields">
      <label>
        {zh ? "常规访问权限" : "General access"}
        <select
          value={value.visibility}
          onChange={(e) =>
            onChange({
              ...value,
              visibility: e.target.value as Sharing["visibility"],
            })
          }
        >
          {Object.entries(labels[language]).map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {value.visibility === "restricted" && (
        <>
          <label>
            {zh ? "添加人员" : "Add people"}
            <div className="sharing-input-row">
              <input
                value={email}
                list={id}
                placeholder="name@feedmob.com"
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addEmail();
                  }
                }}
              />
              <button type="button" onClick={addEmail}>
                {zh ? "添加" : "Add"}
              </button>
            </div>
            <datalist id={id}>
              {people.map((p) => (
                <option key={p} value={p} />
              ))}
            </datalist>
          </label>
          {inputError && (
            <p role="alert" className="page-form-error">
              {inputError}
            </p>
          )}
          <div className="sharing-grants">
            {value.share_with.users.map((user) => (
              <span key={user}>
                {user}
                <button
                  type="button"
                  aria-label={`Remove ${user}`}
                  onClick={() =>
                    onChange({
                      ...value,
                      share_with: {
                        ...value.share_with,
                        users: value.share_with.users.filter((u) => u !== user),
                      },
                    })
                  }
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
          <fieldset>
            <legend>{zh ? "群组" : "Groups"}</legend>
            {groups.length === 0 && (
              <p>
                {zh
                  ? "暂无群组，可在分享设置中创建。"
                  : "No groups. Create one in Sharing settings."}
              </p>
            )}
            {groups.map((group) => (
              <label key={group.slug} className="sharing-checkbox">
                <input
                  type="checkbox"
                  checked={value.share_with.groups.includes(group.slug)}
                  onChange={(e) =>
                    onChange({
                      ...value,
                      share_with: {
                        ...value.share_with,
                        groups: e.target.checked
                          ? [...value.share_with.groups, group.slug]
                          : value.share_with.groups.filter(
                              (g) => g !== group.slug,
                            ),
                      },
                    })
                  }
                />
                {group.name} <small>{group.slug}</small>
              </label>
            ))}
          </fieldset>
          <p>
            {zh
              ? "仅页面所有者及以上人员和群组可访问。未选择对象时仅自己可见。"
              : "Only the owner and selected accounts or group members can access this page. An empty selection gives access only to the owner."}
          </p>
        </>
      )}
      {directoryError && (
        <p role="alert" className="page-form-error">
          {directoryError}
        </p>
      )}
      {showListed && value.visibility === "org" && (
        <label className="sharing-checkbox">
          <input
            type="checkbox"
            checked={value.listed}
            onChange={(e) => onChange({ ...value, listed: e.target.checked })}
          />
          {zh ? "在页面目录和搜索中展示" : "Show in registry and search"}
        </label>
      )}
      <p className="sharing-note">
        {zh
          ? "管理员可以访问并记录审计。图片链接目前仍是公开的，请勿上传需要保密的图片。"
          : "Administrator reads are audited. Image URLs remain public; avoid uploading confidential images."}
      </p>
    </div>
  );
}

/** "Who has access" list, reflecting the unsaved choice in the dialog. */
function AccessSummary({
  value,
  owner,
  language,
}: {
  value: Sharing;
  owner?: string | null;
  language: Language;
}) {
  const zh = language === "zh";
  const rows: { key: string; who: string; role: string }[] = [
    {
      key: "owner",
      who: owner || (zh ? "未认领页面" : "Unassigned page"),
      role: zh ? "所有者" : "Owner",
    },
  ];
  if (value.visibility === "org") {
    rows.push({
      key: "org",
      who: zh ? "所有 FeedMob 登录账号" : "Everyone signed in at FeedMob",
      role: value.listed
        ? zh ? "查看 · 出现在目录" : "Viewer · listed"
        : zh ? "查看 · 仅凭链接" : "Viewer · link only",
    });
  } else if (value.visibility === "restricted") {
    for (const user of value.share_with.users) {
      rows.push({ key: `u:${user}`, who: user, role: zh ? "查看" : "Viewer" });
    }
    for (const group of value.share_with.groups) {
      rows.push({
        key: `g:${group}`,
        who: `${zh ? "群组" : "Group"} ${group}`,
        role: zh ? "查看（全部成员）" : "Viewer (all members)",
      });
    }
  }
  rows.push({
    key: "admins",
    who: zh ? "管理员" : "Administrators",
    role: zh ? "可访问 · 记录审计" : "Access is audited",
  });
  return (
    <section className="sharing-access" aria-label={zh ? "谁有权限" : "Who has access"}>
      <h3>{zh ? "谁有权限" : "Who has access"}</h3>
      <ul>
        {rows.map((row) => (
          <li key={row.key}>
            <span>{row.who}</span>
            <small>{row.role}</small>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ShareDialog({
  page,
  api,
  language,
  onClose,
  onSaved,
}: {
  page: { id: string; title: string; url: string; user_email?: string | null };
  api: ConsoleApi;
  language: Language;
  onClose: () => void;
  onSaved: () => void;
}) {
  const zh = language === "zh";
  const [value, setValue] = useState<Sharing>(empty);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let active = true;
    api
      .fetchApi<Sharing>(`/api/pages/${page.id}/sharing`)
      .then((v) => {
        if (active) {
          setValue(v);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
    };
  }, [api, page.id]);
  async function save() {
    setLoading(true);
    setError("");
    try {
      await api.sendJson(`/api/pages/${page.id}/sharing`, value, "PUT");
      onSaved();
      onClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className="page-form-backdrop">
      <section
        className="page-form-modal sharing-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={zh ? "分享页面" : "Share page"}
      >
        <div className="sharing-heading">
          <h2>
            <Share2 size={20} /> {zh ? "分享" : "Share"} · {page.title}
          </h2>
          <button type="button" aria-label="Close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <p>
          {zh ? "所有者" : "Owner"}:{" "}
          {page.user_email ||
            (zh
              ? "未认领（仅管理员可设置分享）"
              : "Unassigned (admin-managed)")}
        </p>
        {error && (
          <p className="page-form-error" role="alert">
            {error}
          </p>
        )}
        {!loading && (
          <SharingFields
            value={value}
            onChange={setValue}
            api={api}
            language={language}
          />
        )}
        {!loading && (
          <AccessSummary
            value={value}
            owner={page.user_email}
            language={language}
          />
        )}
        <footer className="sharing-actions">
          <button
            type="button"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(page.url);
                setCopied(true);
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            {copied
              ? zh
                ? "已复制"
                : "Copied"
              : zh
                ? "复制链接"
                : "Copy link"}
          </button>
          <button
            type="button"
            className="primary-btn"
            disabled={loading}
            onClick={save}
          >
            {loading ? "…" : zh ? "保存" : "Save"}
          </button>
        </footer>
      </section>
    </div>
  );
}

export function SharingSettings({
  api,
  language,
  email,
}: {
  api: ConsoleApi;
  language: Language;
  email: string;
}) {
  const zh = language === "zh";
  const [value, setValue] = useState<Sharing>(empty);
  const [groups, setGroups] = useState<Group[]>([]);
  const [editing, setEditing] = useState<Group | null>(null);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [members, setMembers] = useState("");
  const [managers, setManagers] = useState(email);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [namespaces, setNamespaces] = useState<NamespaceDefault[]>([]);
  const [nsOwner, setNsOwner] = useState("");
  const [nsValue, setNsValue] = useState<Sharing>(empty);
  const reloadGroups = async () =>
    setGroups((await api.fetchApi<{ items: Group[] }>("/api/groups")).items);
  const reloadNamespaces = async () =>
    setNamespaces(
      (
        await api.fetchApi<{ items: NamespaceDefault[] }>(
          "/api/namespaces/sharing-defaults",
        )
      ).items,
    );
  useEffect(() => {
    let active = true;
    Promise.all([
      api.fetchApi<{
        default_visibility: Sharing["visibility"];
        default_grants: Sharing["share_with"];
      }>("/api/me/sharing-defaults"),
      api.fetchApi<{ items: Group[] }>("/api/groups"),
      api.fetchApi<{ items: NamespaceDefault[] }>(
        "/api/namespaces/sharing-defaults",
      ),
    ])
      .then(([d, g, n]) => {
        if (active) {
          setNamespaces(n.items);
          setValue({
            ...empty,
            visibility: d.default_visibility,
            share_with: d.default_grants,
          });
          setGroups(g.items);
        }
      })
      .catch((e) => {
        if (active) setError(String(e));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [api]);
  async function saveDefaults() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api.sendJson(
        "/api/me/sharing-defaults",
        {
          default_visibility: value.visibility,
          default_grants: value.share_with,
        },
        "PUT",
      );
      setMessage(zh ? "默认设置已保存" : "Defaults saved");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function saveNamespace() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const owner = nsOwner.trim().toLowerCase();
      await api.sendJson(
        `/api/namespaces/${encodeURIComponent(owner)}/sharing-defaults`,
        {
          default_visibility: nsValue.visibility,
          default_grants: nsValue.share_with,
        },
        "PUT",
      );
      await reloadNamespaces();
      setNsOwner("");
      setNsValue(empty);
      setMessage(zh ? "命名空间默认值已保存" : "Namespace default saved");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function removeNamespace(owner: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api.fetchApi(
        `/api/namespaces/${encodeURIComponent(owner)}/sharing-defaults`,
        "DELETE",
      );
      await reloadNamespaces();
      setMessage(zh ? "命名空间默认值已移除" : "Namespace default removed");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function saveGroup() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const body = { members: split(members), managers: split(managers) };
      if (editing && name.trim() && name.trim() !== editing.name) {
        await api.sendJson(`/api/groups/${editing.slug}`, { name: name.trim() }, "PUT");
      }
      await api.sendJson(
        editing ? `/api/groups/${editing.slug}/members` : "/api/groups",
        editing ? body : { ...body, slug, name },
        editing ? "PUT" : "POST",
      );
      await reloadGroups();
      setEditing(null);
      setSlug("");
      setName("");
      setMembers("");
      setManagers(email);
      setMessage(zh ? "群组已保存" : "Group saved");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function deleteGroup(group: Group) {
    const ask = zh
      ? `确定删除群组 ${group.name}（${group.slug}）吗？此操作不可撤销。`
      : `Delete group ${group.name} (${group.slug})? This cannot be undone.`;
    if (!window.confirm(ask)) return;
    setBusy(true);
    setError("");
    setMessage("");
    const path = `/api/groups/${encodeURIComponent(group.slug)}`;
    try {
      try {
        await api.fetchApi(path, "DELETE");
      } catch (e) {
        const reason = e instanceof Error ? e.message : String(e);
        if (!reason.includes("still used")) throw e;
        const force = zh
          ? `${reason}\n\n继续删除会同时移除这些页面和默认值里对该群组的授权，相关页面会立即失去这部分访问权限。仍要删除吗？`
          : `${reason}\n\nDeleting anyway removes this group's access from those pages and defaults immediately. Delete anyway?`;
        if (!window.confirm(force)) return;
        await api.fetchApi(`${path}?force=true`, "DELETE");
      }
      await reloadGroups();
      setEditing(null);
      setSlug("");
      setName("");
      setMembers("");
      setManagers(email);
      setMessage(zh ? "群组已删除" : "Group deleted");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="sharing-settings">
      <header className="console-header">
        <h1>{zh ? "分享设置" : "Sharing settings"}</h1>
        <p>
          {zh
            ? "为新页面设置默认权限，并管理分享群组。"
            : "Choose defaults for new pages and manage sharing groups."}
        </p>
      </header>
      {error && (
        <p className="page-form-error" role="alert">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      <section className="console-panel">
        <h2>{zh ? "新页面默认权限" : "New page defaults"}</h2>
        <fieldset disabled={busy} className="sharing-loading-fields">
          <SharingFields
            key={groups.map((g) => g.slug).join(",")}
            value={value}
            onChange={setValue}
            api={api}
            language={language}
            showListed={false}
          />
        </fieldset>
        <button
          type="button"
          className="primary-btn"
          disabled={busy}
          onClick={saveDefaults}
        >
          {zh ? "保存默认设置" : "Save defaults"}
        </button>
      </section>
      <section className="console-panel">
        <h2>{zh ? "命名空间默认权限" : "Namespace defaults"}</h2>
        <p>
          {zh
            ? "发布到某个 owner 命名空间（例如 ken-team）的新页面优先使用这里的默认值，其次才是个人默认值。只有管理员或同名群组的经理可以设置。"
            : "New pages under an owner namespace (for example ken-team) use this default before the publisher's own. Only administrators or managers of the group with the same slug can set it."}
        </p>
        {namespaces.map((n) => (
          <div key={n.owner} className="sharing-group-row">
            <span>
              <strong>{n.owner}</strong>{" "}
              <VisibilityBadge visibility={n.default_visibility} language={language} />{" "}
              {[...n.default_grants.users, ...n.default_grants.groups].join(", ")}
            </span>
            {n.can_manage && (
              <span className="sharing-actions">
                <button
                  type="button"
                  onClick={() => {
                    setNsOwner(n.owner);
                    setNsValue({
                      ...empty,
                      visibility: n.default_visibility,
                      share_with: n.default_grants,
                    });
                  }}
                >
                  {zh ? "编辑" : "Edit"}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => removeNamespace(n.owner)}
                >
                  {zh ? "移除" : "Remove"}
                </button>
              </span>
            )}
          </div>
        ))}
        <div className="sharing-fields">
          <label>
            {zh ? "命名空间（owner）" : "Namespace (owner)"}
            <input
              value={nsOwner}
              onChange={(e) => setNsOwner(e.target.value)}
              placeholder="ken-team"
            />
          </label>
          <fieldset disabled={busy} className="sharing-loading-fields">
            <SharingFields
              key={`ns:${groups.map((g) => g.slug).join(",")}`}
              value={nsValue}
              onChange={setNsValue}
              api={api}
              language={language}
              showListed={false}
            />
          </fieldset>
          <button
            type="button"
            className="primary-btn"
            disabled={busy || !nsOwner.trim()}
            onClick={saveNamespace}
          >
            {zh ? "保存命名空间默认值" : "Save namespace default"}
          </button>
        </div>
      </section>
      <section className="console-panel">
        <h2>{zh ? "分享群组" : "Sharing groups"}</h2>
        <p>
          {zh
            ? "成员变更对该群组的所有页面立即生效。经理始终也是成员。"
            : "Membership changes apply immediately to all shared pages. Managers are also members."}
        </p>
        {groups.map((g) => (
          <div key={g.slug} className="sharing-group-row">
            <span>
              <strong>{g.name}</strong> · {g.slug}
            </span>
            {g.can_manage && (
              <button
                type="button"
                onClick={() => {
                  setEditing(g);
                  setSlug(g.slug);
                  setName(g.name);
                  setMembers(g.members.join("\n"));
                  setManagers(g.managers.join("\n"));
                }}
              >
                {zh ? "编辑群组" : "Edit group"}
              </button>
            )}
          </div>
        ))}
        <div className="sharing-fields">
          <h3>
            {editing
              ? zh
                ? "编辑群组"
                : "Edit group"
              : zh
                ? "创建群组"
                : "Create group"}
          </h3>
          <label>
            Slug
            <input
              value={slug}
              disabled={!!editing}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="ken-team"
            />
          </label>
          <label>
            {zh ? "名称" : "Name"}
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            {zh ? "成员邮箱（每行一个）" : "Members (one email per line)"}
            <textarea
              value={members}
              rows={4}
              onChange={(e) => setMembers(e.target.value)}
            />
          </label>
          <label>
            {zh ? "经理邮箱（至少一人）" : "Managers (at least one)"}
            <textarea
              value={managers}
              rows={2}
              onChange={(e) => setManagers(e.target.value)}
            />
          </label>
          <div className="sharing-actions">
            <button
              type="button"
              className="primary-btn"
              disabled={
                busy || (!editing && (!slug || !name)) || !managers.trim()
              }
              onClick={saveGroup}
            >
              {zh ? "保存群组" : "Save group"}
            </button>
            {editing && (
              <button
                type="button"
                className="danger-btn"
                disabled={busy}
                onClick={() => deleteGroup(editing)}
              >
                {zh ? "删除群组" : "Delete group"}
              </button>
            )}
            {editing && (
              <button
                type="button"
                onClick={() => {
                  setEditing(null);
                  setSlug("");
                  setName("");
                  setMembers("");
                  setManagers(email);
                }}
              >
                {zh ? "取消" : "Cancel"}
              </button>
            )}
          </div>
        </div>
      </section>
    </section>
  );
}

type LegacySqlPage = {
  id: string;
  owner: string;
  slug: string;
  title?: string | null;
  url: string;
  visibility: Sharing["visibility"];
  user_email?: string | null;
  data_source_names: string[];
};

/** Admin-only inventory of pages that still depend on legacy SQL templates. */
export function LegacySqlInventory({
  api,
  language,
}: {
  api: ConsoleApi;
  language: Language;
}) {
  const zh = language === "zh";
  const [data, setData] = useState<{
    mode: "disabled" | "sandbox" | "unsafe";
    items: LegacySqlPage[];
  } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api
      .fetchApi<{ mode: "disabled" | "sandbox" | "unsafe"; items: LegacySqlPage[] }>(
        "/api/admin/legacy-sql-pages",
      )
      .then((value) => active && setData(value))
      .catch((e) => active && setError(String(e)));
    return () => {
      active = false;
    };
  }, [api]);
  const modeText = {
    disabled: zh
      ? "已禁用：这些页面会显示数据源错误，需迁移为数据文件或配置沙箱角色。"
      : "Disabled: these pages show a data source error until migrated to datasets or a sandbox role is configured.",
    sandbox: zh
      ? "沙箱模式：查询以只读低权限角色执行，只能看到 org 且已列出的页面。"
      : "Sandbox: queries run read-only as a low-privilege role that only sees listed org pages.",
    unsafe: zh
      ? "不安全模式：查询使用应用数据库权限，可绕过页面权限。"
      : "Unsafe: queries use application privileges and can bypass page permissions.",
  };
  return (
    <section className="console-panel keys-panel">
      <h2>{zh ? "旧 SQL 模板页面" : "Legacy SQL template pages"}</h2>
      {error && (
        <p className="page-form-error" role="alert">
          {error}
        </p>
      )}
      {data && (
        <>
          <p>{modeText[data.mode]}</p>
          {data.items.length === 0 ? (
            <p>{zh ? "没有页面使用旧 SQL 模板。" : "No page uses legacy SQL templates."}</p>
          ) : (
            <ul className="sharing-access">
              {data.items.map((item) => (
                <li key={item.id}>
                  <span>
                    <a href={item.url} target="_blank" rel="noreferrer">
                      {item.owner}/{item.slug}
                    </a>{" "}
                    {item.title} · {item.data_source_names.join(", ")}
                  </span>
                  <small>{item.user_email || (zh ? "未认领" : "unassigned")}</small>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
