import { useEffect, useMemo, useRef, useState } from "react";
import { BarChart3, Check, Clipboard, Eye, FileStack, KeyRound, Loader2, Plus, Save, ShieldCheck, Tags, Trash2, UserCircle, UserRound, Users } from "lucide-react";
import type { Language } from "../content";
import { ConsoleView } from "./ConsoleView";
import { SharingSettings } from "./SharingControls";
import "./ConsoleView.css";

type ApiResponse<T> = {
  code: number;
  msg: string;
  data: T;
};

type ConsoleSection = "overview" | "pages" | "pending-pages" | "my-pages" | "api-keys" | "admin" | "sharing";

export type ConsoleUser = {
  sub: string;
  email: string;
  name?: string;
  picture?: string;
  hd?: string;
};

type MeResponse = {
  user: ConsoleUser;
  is_admin: boolean;
};

type ApiKeyRecord = {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  active: boolean;
};

type ApiKeyCreateData = {
  key: string;
  item: ApiKeyRecord;
};

type AdminSettingsData = {
  submitter_allowlist: string[];
};

const consoleCopy = {
  zh: {
    overview: "概览",
    allPages: "全部页面",
    pendingPages: "待认领",
    myPages: "我发布的",
    apiKeys: "API Keys",
    adminSettings: "Admin",
    signedIn: "当前用户",
    admin: "管理员",
    keyTitle: "个人 API Keys",
    keySummary: "为脚本和外部 API 调用生成个人密钥。登录后可随时重新查看完整 key。",
    keyName: "名称",
    keyPlaceholder: "例如：Reporting scripts",
    createKey: "生成 Key",
    creatingKey: "生成中...",
    active: "启用",
    revoked: "已撤销",
    created: "创建",
    lastUsed: "最近使用",
    neverUsed: "从未使用",
    revoke: "撤销",
    reveal: "回显",
    revealing: "读取中...",
    copied: "已复制",
    copy: "复制",
    newKeyNotice: "完整 key 如下。之后也可以在列表里点「回显」再次查看。",
    noKeys: "还没有 API key。",
    keyError: "API key 操作失败",
    adminTitle: "管理员设置",
    allowlistTitle: "历史提交人辅助名单",
    allowlistSummary: "每行一个 Google 邮箱。页面真实归属以绑定的 user_id / user_email 为准；这里仅保留给旧 submitter 数据识别和兼容使用。",
    allowlistPlaceholder: "alice@feedmob.com\nbob@feedmob.com",
    saveSettings: "保存设置",
    savingSettings: "保存中...",
    settingsSaved: "设置已保存",
    settingsError: "设置操作失败",
  },
  en: {
    overview: "Overview",
    allPages: "All Pages",
    pendingPages: "Pending claim",
    myPages: "My Published",
    apiKeys: "API Keys",
    adminSettings: "Admin",
    signedIn: "Signed in",
    admin: "Admin",
    keyTitle: "Personal API Keys",
    keySummary: "Generate personal keys for scripts and external API calls. You can reveal the full key again while signed in.",
    keyName: "Name",
    keyPlaceholder: "e.g. Reporting scripts",
    createKey: "Create key",
    creatingKey: "Creating...",
    active: "Active",
    revoked: "Revoked",
    created: "Created",
    lastUsed: "Last used",
    neverUsed: "Never used",
    revoke: "Revoke",
    reveal: "Reveal",
    revealing: "Revealing...",
    copied: "Copied",
    copy: "Copy",
    newKeyNotice: "Full key below. You can also reveal it later from the list.",
    noKeys: "No API keys yet.",
    keyError: "API key operation failed",
    adminTitle: "Admin Settings",
    allowlistTitle: "Legacy submitter helper",
    allowlistSummary: "One Google email per line. Page ownership is based on bound user_id / user_email; this list is only kept for legacy submitter compatibility.",
    allowlistPlaceholder: "alice@feedmob.com\nbob@feedmob.com",
    saveSettings: "Save settings",
    savingSettings: "Saving...",
    settingsSaved: "Settings saved",
    settingsError: "Settings operation failed",
  },
} satisfies Record<Language, Record<string, string>>;

function getToken(): string {
  return new URLSearchParams(window.location.search).get("token") ?? "";
}

async function fetchApi<T>(path: string, method: "GET" | "DELETE" = "GET"): Promise<T> {
  const token = getToken();
  const separator = path.includes("?") ? "&" : "?";
  const url = token ? `${path}${separator}token=${encodeURIComponent(token)}` : path;
  const response = await fetch(url, { method });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);

  const payload = (await response.json()) as ApiResponse<T>;
  if (payload.code !== 0) throw new Error(payload.msg || "Request failed");

  return payload.data;
}

async function sendJson<T>(path: string, body: unknown, method: "POST" | "PUT" = "POST"): Promise<T> {
  const token = getToken();
  const separator = path.includes("?") ? "&" : "?";
  const url = token ? `${path}${separator}token=${encodeURIComponent(token)}` : path;
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const j = await response.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  const payload = (await response.json()) as ApiResponse<T>;
  if (payload.code !== 0) throw new Error(payload.msg || "Request failed");
  return payload.data;
}

export type ConsoleApi = {
  token: string;
  fetchApi: <T>(path: string, method?: "GET" | "DELETE") => Promise<T>;
  sendJson: <T>(path: string, body: unknown, method?: "POST" | "PUT") => Promise<T>;
};

export function ConsoleRoot({ language }: { language: Language }) {
  const t = consoleCopy[language] as typeof consoleCopy.zh;
  const [section, setSection] = useState<ConsoleSection>("overview");
  const mainRef = useRef<HTMLDivElement>(null);
  useEffect(() => { mainRef.current?.scrollTo(0, 0); }, [section]);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [meError, setMeError] = useState<string | null>(null);
  const [apiKeys, setApiKeys] = useState<ApiKeyRecord[]>([]);
  const [keyName, setKeyName] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);
  const [revealedKeyId, setRevealedKeyId] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState(false);
  const [keyLoading, setKeyLoading] = useState(false);
  const [revealingKeyId, setRevealingKeyId] = useState<string | null>(null);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [allowlistText, setAllowlistText] = useState("");
  const [adminLoading, setAdminLoading] = useState(false);
  const [adminError, setAdminError] = useState<string | null>(null);
  const [adminSaved, setAdminSaved] = useState(false);
  const [settingsVersion, setSettingsVersion] = useState(0);

  const api: ConsoleApi = useMemo(
    () => ({ token: getToken(), fetchApi, sendJson }),
    [],
  );

  useEffect(() => {
    let isActive = true;
    async function loadMe() {
      try {
        const response = await fetch("/auth/me");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = (await response.json()) as MeResponse;
        if (!isActive) return;
        setMe(payload);
      } catch (reason) {
        if (!isActive) return;
        setMeError(reason instanceof Error ? reason.message : "Failed to load user");
      }
    }
    if (!api.token) {
      loadMe();
    }
    return () => {
      isActive = false;
    };
  }, [api.token]);

  useEffect(() => {
    let isActive = true;
    async function loadKeys() {
      if (section !== "api-keys" || api.token) return;
      setKeyLoading(true);
      setKeyError(null);
      try {
        const items = await api.fetchApi<ApiKeyRecord[]>("/api/keys");
        if (!isActive) return;
        setApiKeys(items);
      } catch (reason) {
        if (!isActive) return;
        setKeyError(reason instanceof Error ? reason.message : t.keyError);
      } finally {
        if (isActive) setKeyLoading(false);
      }
    }
    loadKeys();
    return () => {
      isActive = false;
    };
  }, [api, api.token, section, t.keyError]);

  useEffect(() => {
    let isActive = true;
    async function loadAdminSettings() {
      if (section !== "admin" || !(me?.is_admin || api.token)) return;
      setAdminLoading(true);
      setAdminError(null);
      setAdminSaved(false);
      try {
        const settings = await api.fetchApi<AdminSettingsData>("/api/admin/settings");
        if (!isActive) return;
        setAllowlistText(settings.submitter_allowlist.join("\n"));
      } catch (reason) {
        if (!isActive) return;
        setAdminError(reason instanceof Error ? reason.message : t.settingsError);
      } finally {
        if (isActive) setAdminLoading(false);
      }
    }
    loadAdminSettings();
    return () => {
      isActive = false;
    };
  }, [api, api.token, me?.is_admin, section, t.settingsError]);

  const createApiKey = async () => {
    setKeyLoading(true);
    setKeyError(null);
    setNewKey(null);
    setRevealedKeyId(null);
    try {
      const result = await api.sendJson<ApiKeyCreateData>("/api/keys", {
        name: keyName.trim() || "Default API key",
      });
      setApiKeys((current) => [result.item, ...current]);
      setNewKey(result.key);
      setRevealedKeyId(result.item.id);
      setCopiedKey(false);
      setKeyName("");
    } catch (reason) {
      setKeyError(reason instanceof Error ? reason.message : t.keyError);
    } finally {
      setKeyLoading(false);
    }
  };

  const revokeApiKey = async (keyId: string) => {
    setKeyLoading(true);
    setKeyError(null);
    try {
      const result = await api.fetchApi<ApiKeyRecord>(`/api/keys/${keyId}`, "DELETE");
      setApiKeys((current) => current.map((item) => (item.id === keyId ? result : item)));
      if (revealedKeyId === keyId) {
        setNewKey(null);
        setRevealedKeyId(null);
      }
    } catch (reason) {
      setKeyError(reason instanceof Error ? reason.message : t.keyError);
    } finally {
      setKeyLoading(false);
    }
  };

  const revealApiKey = async (keyId: string) => {
    setRevealingKeyId(keyId);
    setKeyError(null);
    try {
      const result = await api.fetchApi<ApiKeyCreateData>(`/api/keys/${keyId}/reveal`);
      setNewKey(result.key);
      setRevealedKeyId(result.item.id);
      setCopiedKey(false);
    } catch (reason) {
      setKeyError(reason instanceof Error ? reason.message : t.keyError);
    } finally {
      setRevealingKeyId(null);
    }
  };

  const copyNewKey = async () => {
    if (!newKey) return;
    await navigator.clipboard.writeText(newKey);
    setCopiedKey(true);
  };

  const parseAllowlistText = () => {
    const seen = new Set<string>();
    return allowlistText
      .split(/[\n,]+/)
      .map((item) => item.trim().toLowerCase())
      .filter((item) => {
        if (!item || seen.has(item)) return false;
        seen.add(item);
        return true;
      });
  };

  const saveAdminSettings = async () => {
    setAdminLoading(true);
    setAdminError(null);
    setAdminSaved(false);
    try {
      const result = await api.sendJson<AdminSettingsData>(
        "/api/admin/settings",
        { submitter_allowlist: parseAllowlistText() },
        "PUT",
      );
      setAllowlistText(result.submitter_allowlist.join("\n"));
      setAdminSaved(true);
      setSettingsVersion((current) => current + 1);
    } catch (reason) {
      setAdminError(reason instanceof Error ? reason.message : t.settingsError);
    } finally {
      setAdminLoading(false);
    }
  };

  const formatDate = (value: string | null) => {
    if (!value) return t.neverUsed;
    return new Intl.DateTimeFormat(undefined, {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  };

  return (
    <section className="console-view">
      <div className="console-layout">
        <aside className="console-sidebar">
          <div className="console-user-card">
            <div className="console-user-icon">
              {me?.user.picture ? (
                <img src={me.user.picture} alt="" />
              ) : (
                <UserCircle size={22} />
              )}
            </div>
            <div>
              <span>{t.signedIn}</span>
              <strong>{api.token ? "Admin token" : me?.user.email ?? meError ?? "-"}</strong>
            </div>
            {(me?.is_admin || api.token) && (
              <div className="admin-pill">
                <ShieldCheck size={12} />
                {t.admin}
              </div>
            )}
          </div>
          <nav className="console-nav" aria-label="Console Navigation">
            <button
              type="button"
              className={section === "overview" ? "active" : ""}
              onClick={() => setSection("overview")}
            >
              <BarChart3 size={16} />
              {t.overview}
            </button>
            <button
              type="button"
              className={section === "pages" ? "active" : ""}
              onClick={() => setSection("pages")}
            >
              <FileStack size={16} />
              {t.allPages}
            </button>
            <button
              type="button"
              className={section === "pending-pages" ? "active" : ""}
              onClick={() => setSection("pending-pages")}
            >
              <Tags size={16} />
              {t.pendingPages}
            </button>
            <button
              type="button"
              className={section === "my-pages" ? "active" : ""}
              onClick={() => setSection("my-pages")}
              disabled={Boolean(api.token)}
            >
              <UserRound size={16} />
              {t.myPages}
            </button>
            <button
              type="button"
              className={section === "api-keys" ? "active" : ""}
              onClick={() => setSection("api-keys")}
              disabled={Boolean(api.token)}
            >
              <KeyRound size={16} />
              {t.apiKeys}
            </button>
            {(me?.is_admin || api.token) && (
              <button
                type="button"
                className={section === "admin" ? "active" : ""}
                onClick={() => setSection("admin")}
              >
                <ShieldCheck size={16} />
                {t.adminSettings}
              </button>
            )}
            <button type="button" className={section === "sharing" ? "active" : ""} onClick={() => setSection("sharing")}>
              <Users size={16} />{language === "zh" ? "分享设置" : "Sharing settings"}
            </button>
          </nav>
        </aside>

        <div className="console-main" ref={mainRef}>
          {section === "sharing" ? <SharingSettings api={api} language={language} email={me?.user.email ?? ""} /> : section === "admin" ? (
            <section className="keys-view">
              <div className="console-header compact">
                <p className="eyebrow">{t.adminSettings}</p>
                <h1>{t.adminTitle}</h1>
              </div>

              <section className="console-panel keys-panel">
                {adminError && <div className="page-form-error">{adminError}</div>}
                {adminSaved && <div className="settings-success">{t.settingsSaved}</div>}
                <div className="admin-settings-block">
                  <label>
                    <span>{t.allowlistTitle}</span>
                    <textarea
                      value={allowlistText}
                      onChange={(event) => {
                        setAllowlistText(event.target.value);
                        setAdminSaved(false);
                      }}
                      placeholder={t.allowlistPlaceholder}
                      rows={10}
                    />
                  </label>
                  <p>{t.allowlistSummary}</p>
                  <button type="button" className="primary-btn" onClick={saveAdminSettings} disabled={adminLoading}>
                    {adminLoading ? <Loader2 size={14} className="spin" /> : <Save size={14} />}
                    {adminLoading ? t.savingSettings : t.saveSettings}
                  </button>
                </div>
              </section>
            </section>
          ) : section === "api-keys" ? (
            <section className="keys-view">
              <div className="console-header compact">
                <p className="eyebrow">{t.apiKeys}</p>
                <h1>{t.keyTitle}</h1>
                <p className="summary">{t.keySummary}</p>
              </div>

              <section className="console-panel keys-panel">
                {keyError && <div className="page-form-error">{keyError}</div>}
                {newKey && (
                  <div className="new-key-box">
                    <span>{t.newKeyNotice}</span>
                    <code>{newKey}</code>
                    <button type="button" className="ghost-btn" onClick={copyNewKey}>
                      {copiedKey ? <Check size={14} /> : <Clipboard size={14} />}
                      {copiedKey ? t.copied : t.copy}
                    </button>
                  </div>
                )}

                <div className="key-create-row">
                  <label>
                    <span>{t.keyName}</span>
                    <input
                      type="text"
                      value={keyName}
                      onChange={(event) => setKeyName(event.target.value)}
                      placeholder={t.keyPlaceholder}
                    />
                  </label>
                  <button type="button" className="primary-btn" onClick={createApiKey} disabled={keyLoading}>
                    {keyLoading ? <Loader2 size={14} className="spin" /> : <Plus size={14} />}
                    {keyLoading ? t.creatingKey : t.createKey}
                  </button>
                </div>

                <div className="key-list">
                  {keyLoading && apiKeys.length === 0 && <div className="inline-loading">{t.creatingKey}</div>}
                  {!keyLoading && apiKeys.length === 0 && (
                    <div className="console-empty">
                      <strong>{t.noKeys}</strong>
                    </div>
                  )}
                  {apiKeys.map((item) => (
                    <article key={item.id} className={`key-row ${item.active ? "" : "revoked"}`}>
                      <div>
                        <strong>{item.name}</strong>
                        <code>{item.key_prefix}...</code>
                      </div>
                      <div>
                        <span>{t.created}</span>
                        <strong>{formatDate(item.created_at)}</strong>
                      </div>
                      <div>
                        <span>{t.lastUsed}</span>
                        <strong>{formatDate(item.last_used_at)}</strong>
                      </div>
                      <span className={`status-pill ${item.active ? "" : "muted"}`}>
                        {item.active ? t.active : t.revoked}
                      </span>
                      <div className="key-row-actions">
                        <button
                          type="button"
                          className="ghost-btn"
                          onClick={() => revealApiKey(item.id)}
                          disabled={!item.active || keyLoading || revealingKeyId === item.id}
                        >
                          {revealingKeyId === item.id ? (
                            <Loader2 size={14} className="spin" />
                          ) : (
                            <Eye size={14} />
                          )}
                          {revealingKeyId === item.id ? t.revealing : t.reveal}
                        </button>
                        <button
                          type="button"
                          className="delete-btn"
                          onClick={() => revokeApiKey(item.id)}
                          disabled={!item.active || keyLoading}
                        >
                          <Trash2 size={14} />
                          {t.revoke}
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            </section>
          ) : (
            <ConsoleView
              key={`${section}-${settingsVersion}`}
              language={language}
              api={api}
              initialSection={section}
              currentUser={me?.user ?? null}
              isAdmin={Boolean(me?.is_admin || api.token)}
            />
          )}
        </div>
      </div>
    </section>
  );
}

// re-export so old call sites keep working
export { ConsoleView };
