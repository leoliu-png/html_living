import { useEffect, useState } from "react";
import { Loader2, Pencil, Plus, Save, Share2, ShieldCheck, Trash2, X } from "lucide-react";
import type { Language } from "../content";
import type { ConsoleApi, ConsoleUser } from "./ConsoleRoot";
import { PageDatasetsPanel } from "./PageDatasetsPanel";
import { ShareDialog, SharingFields, VisibilityBadge } from "./SharingControls";
import type { Sharing } from "./SharingControls";
import "./ConsoleView.css";

type PageRecord = {
  visibility: Sharing["visibility"];
  id: string;
  owner: string;
  slug: string;
  url: string;
  title: string;
  submitter: string;
  description: string;
  submit_ip: string;
  submit_device: string;
  submit_user_agent: string;
  html?: string;
  data_sources: Record<string, string> | null;
  user_id?: string | null;
  user_email?: string | null;
  is_unassigned: boolean;
  created_at: string;
  updated_at: string;
};

type IdentityFilter = {
  user_id?: string | null;
  user_email?: string | null;
  count: number;
};

type CountByOwner = { owner: string; count: number };
type CountBySubmitter = { submitter: string; count: number };

type PageStats = {
  total_pages: number;
  total_owners: number;
  total_submitters: number;
  latest_created_at: string | null;
  top_owners: CountByOwner[];
  top_submitters: CountBySubmitter[];
};

type Pagination = {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
};

type PageListData = {
  items: PageRecord[];
  pagination: Pagination;
  legacy_submitters?: string[] | null;
  identity_filters?: IdentityFilter[] | null;
};

type ConsoleSection = "overview" | "pages" | "pending-pages" | "my-pages";
type PageScope = "all" | "mine" | "unassigned";
type TimeRange = "all" | "24h" | "7d" | "30d";

const copy = {
  zh: {
    eyebrow: "后台界面",
    title: "发布信息控制台",
    summary: "用于查看页面发布记录、提交信息和发布后的访问地址。",
    recentPages: "最近页面",
    overview: "概览",
    allPages: "全部页面",
    myPages: "我发布的",
    pendingPages: "待认领",
    scopeFilters: "页面分类",
    identityFilters: "归属筛选",
    identityAll: "全部归属",
    timeFilters: "时间筛选",
    timeAll: "全部时间",
    time24h: "近 24 小时",
    time7d: "近 7 天",
    time30d: "近 30 天",
    unboundIdentity: "未绑定",
    pendingClaim: "待认领",
    identityEmail: "归属邮箱",
    identityUserId: "User ID",
    total: "总发布",
    owners: "负责人",
    submitters: "提交人",
    latest: "最近创建",
    recent: "最近发布",
    detail: "发布详情",
    statusLive: "已发布",
    owner: "负责人",
    slug: "Slug",
    submitter: "提交人",
    device: "设备",
    ip: "IP",
    updated: "更新时间",
    created: "创建时间",
    pageUrl: "页面地址",
    openPage: "打开页面",
    loading: "正在加载发布记录",
    emptyTitle: "暂无发布记录",
    emptySummary: "发布页面后，这里会显示提交人、访问地址和更新时间。",
    errorTitle: "加载失败",
    topOwners: "主要负责人",
    topSubmitters: "主要提交人",
    noSelection: "先从左侧列表选择一个页面",
    searchPlaceholder: "搜索 owner、slug、title、submitter、description",
    previousPage: "上一页",
    nextPage: "下一页",
    pageInfo: "第 {page} / {totalPages} 页",
    totalItems: "共 {total} 条",
    noSearchResults: "没有匹配结果",
    tryAnotherKeyword: "试试别的关键词，或者清空搜索条件。",
    dataSources: "数据源",
    delete: "删除",
    deleteConfirm: "确定要永久删除此页面？",
    deleteCancel: "取消",
    deleting: "删除中...",
    deleteSuccess: "页面已成功删除",
    deleteFailed: "删除失败",
    manageRestricted: "只有归属用户或管理员可以编辑、删除此页面。",
    claim: "认领",
    claiming: "认领中...",
    claimSuccess: "页面已认领",
    claimFailed: "认领失败",
    newPage: "新建页面",
    edit: "编辑",
    cancel: "取消",
    save: "保存",
    saving: "保存中...",
    create: "发布",
    creating: "发布中...",
    createSuccess: "页面已发布",
    saveSuccess: "页面已更新",
    saveFailed: "保存失败",
    formTitleCreate: "发布新页面",
    formTitleEdit: "编辑页面",
    fieldOwner: "Owner",
    fieldSlug: "Slug（可选）",
    fieldTitle: "Title",
    fieldDescription: "Description",
    fieldHtml: "HTML 内容",
    slugHint: "留空将自动生成 10 位 slug",
  },
  en: {
    eyebrow: "Console",
    title: "Publishing Console",
    summary: "Review page publishing records, submission details, and live page URLs.",
    recentPages: "Recent pages",
    overview: "Overview",
    allPages: "All Pages",
    myPages: "My Published",
    pendingPages: "Pending claim",
    scopeFilters: "Page scope",
    identityFilters: "Owner filters",
    identityAll: "All identities",
    timeFilters: "Time filters",
    timeAll: "All time",
    time24h: "Last 24 hours",
    time7d: "Last 7 days",
    time30d: "Last 30 days",
    unboundIdentity: "Unbound",
    pendingClaim: "Pending claim",
    identityEmail: "Owner email",
    identityUserId: "User ID",
    total: "Total",
    owners: "Owners",
    submitters: "Submitters",
    latest: "Latest created",
    recent: "Recent publishes",
    detail: "Publish detail",
    statusLive: "Live",
    owner: "Owner",
    slug: "Slug",
    submitter: "Submitter",
    device: "Device",
    ip: "IP",
    updated: "Updated",
    created: "Created",
    pageUrl: "Page URL",
    openPage: "Open page",
    loading: "Loading publishing records",
    emptyTitle: "No publishing records yet",
    emptySummary: "Published pages will appear here with submitter, live URL, and update time.",
    errorTitle: "Failed to load",
    topOwners: "Top owners",
    topSubmitters: "Top submitters",
    noSelection: "Select a page from the left list first",
    searchPlaceholder: "Search owner, slug, title, submitter, or description",
    previousPage: "Previous",
    nextPage: "Next",
    pageInfo: "Page {page} / {totalPages}",
    totalItems: "{total} items",
    noSearchResults: "No matching results",
    tryAnotherKeyword: "Try a different keyword or clear the search.",
    dataSources: "Data sources",
    delete: "Delete",
    deleteConfirm: "Delete this page permanently?",
    deleteCancel: "Cancel",
    deleting: "Deleting...",
    deleteSuccess: "Page deleted successfully",
    deleteFailed: "Delete failed",
    manageRestricted: "Only the bound owner or an admin can edit or delete this page.",
    claim: "Claim",
    claiming: "Claiming...",
    claimSuccess: "Page claimed",
    claimFailed: "Claim failed",
    newPage: "New page",
    edit: "Edit",
    cancel: "Cancel",
    save: "Save",
    saving: "Saving...",
    create: "Publish",
    creating: "Publishing...",
    createSuccess: "Page published",
    saveSuccess: "Page updated",
    saveFailed: "Save failed",
    formTitleCreate: "Publish new page",
    formTitleEdit: "Edit page",
    fieldOwner: "Owner",
    fieldSlug: "Slug (optional)",
    fieldTitle: "Title",
    fieldDescription: "Description",
    fieldHtml: "HTML content",
    slugHint: "Leave blank to auto-generate a 10-char slug",
  },
} satisfies Record<Language, Record<string, string>>;

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

type Props = {
  language: Language;
  api: ConsoleApi;
  initialSection: ConsoleSection;
  currentUser: ConsoleUser | null;
  isAdmin: boolean;
};

type FormMode =
  | { kind: "closed" }
  | { kind: "create" }
  | { kind: "edit"; page: PageRecord };

type FormState = {
  sharing?: Sharing;
  owner: string;
  slug: string;
  title: string;
  description: string;
  html: string;
};

const EMPTY_FORM: FormState = {
  owner: "",
  slug: "",
  title: "",
  description: "",
  html: "<!doctype html>\n<html><body><h1>Hello</h1></body></html>",
};

function getIdentityFilters(data: PageListData) {
  return Array.isArray(data.identity_filters) ? data.identity_filters : [];
}

function identityFilterKey(filter: IdentityFilter) {
  const userEmail = filter.user_email?.trim() ?? "";
  const userId = filter.user_id?.trim() ?? "";
  return `${userEmail}::${userId}`;
}

function formatIdentityFilter(filter: IdentityFilter, fallback: string) {
  return filter.user_email || filter.user_id || fallback;
}

function pageIdentityLabel(page: PageRecord, pendingLabel: string) {
  return page.is_unassigned ? pendingLabel : page.user_email || "-";
}

export function ConsoleView({ language, api, initialSection, currentUser, isAdmin }: Props) {
  const t = copy[language] as typeof copy.zh;
  const [pages, setPages] = useState<PageRecord[]>([]);
  const [stats, setStats] = useState<PageStats | null>(null);
  const [pagination, setPagination] = useState<Pagination | null>(null);
  const [selectedPage, setSelectedPage] = useState<PageRecord | null>(null);
  const [sharingPage, setSharingPage] = useState<PageRecord | null>(null);
  const [section, setSection] = useState<ConsoleSection>(initialSection);
  const [pageScopeOverride, setPageScopeOverride] = useState<PageScope>("all");
  const [identityFilter, setIdentityFilter] = useState("");
  const [identityFilters, setIdentityFilters] = useState<IdentityFilter[]>([]);
  const [timeRange, setTimeRange] = useState<TimeRange>("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [isBootLoading, setIsBootLoading] = useState(true);
  const [isListLoading, setIsListLoading] = useState(false);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isClaiming, setIsClaiming] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [form, setForm] = useState<FormMode>({ kind: "closed" });
  const [formState, setFormState] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [formSubmitting, setFormSubmitting] = useState(false);

  useEffect(() => {
    setSection(initialSection);
    setPageScopeOverride(initialSection === "pending-pages" ? "unassigned" : "all");
    setIdentityFilter("");
    setTimeRange("all");
    setPage(1);
    setQuery("");
    setSelectedPage(null);
  }, [initialSection]);

  const pageScope: PageScope = section === "my-pages"
    ? "mine"
    : section === "pending-pages"
      ? "unassigned"
      : pageScopeOverride;
  const sectionTitle = section === "my-pages"
    ? t.myPages
    : pageScope === "unassigned"
      ? t.pendingPages
      : t.allPages;
  const buildPagesPath = (nextPage: number) => {
    const search = new URLSearchParams({
      page: String(nextPage),
      page_size: "20",
      scope: pageScope,
    });
    if (query.trim()) search.set("q", query.trim());
    if (section === "pages" && pageScope === "all" && identityFilter) {
      const [userEmail, userId] = identityFilter.split("::");
      if (userEmail) search.set("user_email", userEmail);
      if (userId) search.set("user_id", userId);
    }
    if (section === "pages" && timeRange !== "all") {
      search.set("created_range", timeRange);
    }
    return `/api/pages?${search.toString()}`;
  };

  useEffect(() => {
    let isActive = true;

    async function loadInitial() {
      setIsBootLoading(true);
      setError(null);

      try {
        const [nextStats, nextPages] = await Promise.all([
          api.fetchApi<PageStats>("/api/pages/stats"),
          api.fetchApi<PageListData>(buildPagesPath(1)),
        ]);
        if (!isActive) return;

        setStats(nextStats);
        setPages(nextPages.items);
        setPagination(nextPages.pagination);
        setIdentityFilters(getIdentityFilters(nextPages));
        setSelectedPage(nextPages.items[0] ?? null);
      } catch (reason) {
        if (!isActive) return;
        setError(reason instanceof Error ? reason.message : "Request failed");
      } finally {
        if (isActive) setIsBootLoading(false);
      }
    }

    async function loadPages() {
      if (isBootLoading) return;
      setIsListLoading(true);

      try {
        const nextPages = await api.fetchApi<PageListData>(buildPagesPath(page));
        if (!isActive) return;

        setPages(nextPages.items);
        setPagination(nextPages.pagination);
        setIdentityFilters(getIdentityFilters(nextPages));
        setSelectedPage((current) => {
          if (!current) return nextPages.items[0] ?? null;
          return nextPages.items.find((item) => item.id === current.id) ?? nextPages.items[0] ?? null;
        });
      } catch (reason) {
        if (!isActive) return;
        setError(reason instanceof Error ? reason.message : "Request failed");
      } finally {
        if (isActive) setIsListLoading(false);
      }
    }

    if (isBootLoading) {
      loadInitial();
    } else {
      loadPages();
    }

    return () => {
      isActive = false;
    };
  }, [page, query, isBootLoading, api, pageScope, section, identityFilter, timeRange]);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 2200);
    return () => window.clearTimeout(id);
  }, [toast]);

  const loadDetail = async (pageRecord: PageRecord) => {
    setSelectedPage(pageRecord);
    setSection(initialSection === "overview" ? "pages" : initialSection);
    setIsDetailLoading(true);

    try {
      const detail = await api.fetchApi<PageRecord>(`/api/pages/${pageRecord.owner}/${pageRecord.slug}`);
      setSelectedPage(detail);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Request failed");
    } finally {
      setIsDetailLoading(false);
    }
  };

  const handleDelete = async (pageId: string) => {
    setIsDeleting(true);
    try {
      await api.fetchApi<{ id: string }>(`/api/pages/${pageId}`, "DELETE");
      setPages((current) => current.filter((p) => p.id !== pageId));
      setSelectedPage((current) => (current?.id === pageId ? null : current));
      setDeleteConfirmId(null);
      setToast(t.deleteSuccess);
      if (pagination) {
        setPagination({ ...pagination, total: Math.max(0, pagination.total - 1) });
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t.deleteFailed);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleClaim = async (pageId: string) => {
    setIsClaiming(true);
    try {
      const claimed = await api.sendJson<PageRecord>(`/api/pages/${pageId}/claim`, {}, "POST");
      setToast(t.claimSuccess);
      setSelectedPage(claimed);
      await reloadAfterMutation();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t.claimFailed);
    } finally {
      setIsClaiming(false);
    }
  };

  const openCreate = async () => {
    setFormError(null);
    try {
      const defaults = await api.fetchApi<{ default_visibility: Sharing["visibility"]; default_grants: Sharing["share_with"] }>("/api/me/sharing-defaults");
      setFormState({ ...EMPTY_FORM, sharing: { visibility: defaults.default_visibility, share_with: defaults.default_grants, listed: true } });
      setForm({ kind: "create" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Request failed");
    }
  };

  const openEdit = (pageRecord: PageRecord) => {
    setFormState({
      owner: pageRecord.owner,
      slug: pageRecord.slug,
      title: pageRecord.title ?? "",
      description: pageRecord.description,
      html: pageRecord.html ?? "",
    });
    setFormError(null);
    setForm({ kind: "edit", page: pageRecord });
  };

  const closeForm = () => {
    if (formSubmitting) return;
    setForm({ kind: "closed" });
    setFormError(null);
  };

  const validateForm = (state: FormState): string | null => {
    if (!state.owner.trim()) return t.fieldOwner + " required";
    if (!state.title.trim()) return t.fieldTitle + " required";
    if (!state.description.trim()) return t.fieldDescription + " required";
    if (!state.html.trim()) return t.fieldHtml + " required";
    return null;
  };

  const handleSubmit = async () => {
    const err = validateForm(formState);
    if (err) {
      setFormError(err);
      return;
    }
    setFormError(null);
    setFormSubmitting(true);
    try {
      if (form.kind === "create") {
        const created = await api.sendJson<Pick<PageRecord, "id" | "owner" | "slug">>(
          "/api/pages",
          {
            html: formState.html,
            owner: formState.owner.trim(),
            description: formState.description.trim(),
            title: formState.title.trim(),
            slug: formState.slug.trim() || undefined,
            ...formState.sharing,
          },
          "POST",
        );
        setToast(t.createSuccess);
        setForm({ kind: "closed" });
        await reloadAfterMutation();
        const detail = await api.fetchApi<PageRecord>(`/api/pages/${created.owner}/${created.slug}`);
        setSelectedPage(detail);
      } else if (form.kind === "edit") {
        await api.sendJson<PageRecord>(
          `/api/pages/${form.page.id}`,
          {
            html: formState.html,
            title: formState.title.trim(),
            description: formState.description.trim(),
          },
          "PUT",
        );
        setToast(t.saveSuccess);
        setForm({ kind: "closed" });
        await reloadAfterMutation();
        // try refresh detail if selected
        if (selectedPage?.id === form.page.id) {
          try {
            const detail = await api.fetchApi<PageRecord>(
              `/api/pages/${formState.owner.trim()}/${formState.slug.trim() || form.page.slug}`,
            );
            setSelectedPage(detail);
          } catch {
            // ignore
          }
        }
      }
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : t.saveFailed);
    } finally {
      setFormSubmitting(false);
    }
  };

  const reloadAfterMutation = async () => {
    setPage(1);
    try {
      const [nextStats, nextPages] = await Promise.all([
        api.fetchApi<PageStats>("/api/pages/stats"),
        api.fetchApi<PageListData>(buildPagesPath(1)),
      ]);
      setStats(nextStats);
      setPages(nextPages.items);
      setPagination(nextPages.pagination);
      setIdentityFilters(getIdentityFilters(nextPages));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Request failed");
    }
  };

  const latestCreatedAt = stats?.latest_created_at ? formatDate(stats.latest_created_at) : "-";
  const hasNoPagesAtAll = !isBootLoading && !error && !query.trim() && !identityFilter && timeRange === "all" && pages.length === 0;
  const hasNoSearchResults = !isBootLoading && !error && (!!query.trim() || !!identityFilter || timeRange !== "all") && pages.length === 0;
  const isPageListSection = section === "pages" || section === "pending-pages" || section === "my-pages";
  const pageInfo = t.pageInfo
    .replace("{page}", String(pagination?.page ?? 1))
    .replace("{totalPages}", String(pagination?.total_pages ?? 1));
  const totalItems = t.totalItems.replace("{total}", String(pagination?.total ?? 0));
  const canManagePage = (pageRecord: PageRecord | null) => {
    if (!pageRecord) return false;
    if (isAdmin) return true;
    if (pageRecord.is_unassigned) return true;
    const actorEmail = currentUser?.email?.toLowerCase();
    const actorId = currentUser?.sub;
    if (actorId && pageRecord.user_id && actorId === pageRecord.user_id) return true;
    if (actorEmail && pageRecord.user_email && actorEmail === pageRecord.user_email.toLowerCase()) return true;
    return false;
  };
  const canClaimPage = (pageRecord: PageRecord | null) => {
    return Boolean(
      pageRecord?.is_unassigned
      && currentUser?.email?.toLowerCase().endsWith("@feedmob.com")
    );
  };

  return (
    <>
      {toast && <div className="console-toast">{toast}</div>}

      {isBootLoading && <div className="console-empty"><strong>{t.loading}</strong></div>}
      {!isBootLoading && error && (
        <div className="console-empty">
          <strong>{t.errorTitle}</strong>
          <p>{error}</p>
        </div>
      )}
      {hasNoPagesAtAll && form.kind === "closed" && (
        <div className="console-empty">
          <strong>{t.emptyTitle}</strong>
          <p>{t.emptySummary}</p>
          <button type="button" className="primary-btn" onClick={openCreate}>
            <Plus size={16} /> {t.newPage}
          </button>
        </div>
      )}

      {!isBootLoading && !error && !hasNoPagesAtAll && section === "overview" && (
        <>
          <div className="console-header">
            <p className="eyebrow">{t.eyebrow}</p>
            <h1>{t.title}</h1>
            <p className="summary">{t.summary}</p>
            <div className="console-toolbar">
              <button type="button" className="primary-btn" onClick={openCreate}>
                <Plus size={16} /> {t.newPage}
              </button>
            </div>
          </div>
          <div className="metric-grid">
            <div><span>{t.total}</span><strong>{stats?.total_pages ?? 0}</strong></div>
            <div><span>{t.owners}</span><strong>{stats?.total_owners ?? 0}</strong></div>
            <div><span>{t.submitters}</span><strong>{stats?.total_submitters ?? 0}</strong></div>
            <div><span>{t.latest}</span><strong>{latestCreatedAt}</strong></div>
          </div>
          <div className="console-grid">
            <section className="console-panel overview-panel">
              <h2>{t.topOwners}</h2>
              <div className="publish-list compact-list">
                {(stats?.top_owners ?? []).map((item) => (
                  <article key={item.owner} className="summary-row">
                    <strong>{item.owner}</strong>
                    <span>{item.count}</span>
                  </article>
                ))}
              </div>
            </section>
            <section className="console-panel overview-panel">
              <h2>{t.topSubmitters}</h2>
              <div className="publish-list compact-list">
                {(stats?.top_submitters ?? []).map((item) => (
                  <article key={item.submitter} className="summary-row">
                    <strong>{item.submitter}</strong>
                    <span>{item.count}</span>
                  </article>
                ))}
              </div>
            </section>
            <section className="console-panel overview-panel">
              <h2>{t.recentPages}</h2>
              <div className="publish-list recent-pages-list">
                {pages.map((p) => (
                  <button
                    key={p.id}
                    className={`publish-row ${selectedPage?.id === p.id ? "active" : ""}`}
                    type="button"
                    onClick={() => loadDetail(p)}
                  >
                    <div>
                      <strong>{p.title}<VisibilityBadge visibility={p.visibility} language={language} /></strong>
                      <span>{p.owner}/{p.slug}</span>
                    </div>
                    <span className="status-pill">{t.statusLive}</span>
                  </button>
                ))}
              </div>
            </section>
          </div>
        </>
      )}

      {!isBootLoading && !error && !hasNoPagesAtAll && isPageListSection && (
        <>
          <div className="console-header compact">
            <p className="eyebrow">{t.eyebrow}</p>
            <h1>{sectionTitle}</h1>
            <div className="console-toolbar">
              <button type="button" className="primary-btn" onClick={openCreate}>
                <Plus size={16} /> {t.newPage}
              </button>
            </div>
          </div>
          <div className="console-grid pages-grid">
            <section className="console-panel">
              <div className="list-toolbar">
                {section === "pages" && (
                  <div className="submitter-filter-block">
                    <span>{t.scopeFilters}</span>
                    <div className="submitter-filter-tabs" role="group" aria-label={t.scopeFilters}>
                      {([
                        ["all", t.allPages],
                        ["unassigned", t.pendingPages],
                      ] as const).map(([value, label]) => (
                        <button
                          key={value}
                          type="button"
                          className={pageScope === value ? "active" : ""}
                          onClick={() => {
                            setPageScopeOverride(value);
                            setIdentityFilter("");
                            setPage(1);
                          }}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {section === "pages" && pageScope === "all" && identityFilters.length > 0 && (
                  <div className="submitter-filter-block">
                    <span>{t.identityFilters}</span>
                    <div className="submitter-filter-tabs" role="group" aria-label={t.identityFilters}>
                      <button
                        type="button"
                        className={identityFilter === "" ? "active" : ""}
                        onClick={() => {
                          setIdentityFilter("");
                          setPage(1);
                        }}
                      >
                        {t.identityAll}
                      </button>
                      {identityFilters.map((filter) => {
                        const key = identityFilterKey(filter);
                        return (
                        <button
                          key={key}
                          type="button"
                          className={identityFilter === key ? "active" : ""}
                          onClick={() => {
                            setIdentityFilter((current) => current === key ? "" : key);
                            setPage(1);
                          }}
                        >
                          {formatIdentityFilter(filter, t.unboundIdentity)}
                          <span className="filter-count">{filter.count}</span>
                        </button>
                        );
                      })}
                    </div>
                  </div>
                )}
                {section === "pages" && (
                  <div className="submitter-filter-block">
                    <span>{t.timeFilters}</span>
                    <div className="submitter-filter-tabs" role="group" aria-label={t.timeFilters}>
                      {([
                        ["all", t.timeAll],
                        ["24h", t.time24h],
                        ["7d", t.time7d],
                        ["30d", t.time30d],
                      ] as const).map(([value, label]) => (
                        <button
                          key={value}
                          type="button"
                          className={timeRange === value ? "active" : ""}
                          onClick={() => {
                            setTimeRange(value);
                            setPage(1);
                          }}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <input
                  type="search"
                  value={query}
                  onChange={(event) => {
                    setPage(1);
                    setQuery(event.target.value);
                  }}
                  placeholder={t.searchPlaceholder}
                />
                <div className="pagination-meta">
                  <span>{pageInfo}</span>
                  <span>{totalItems}</span>
                </div>
              </div>
              <div className="table-list">
                {isListLoading && <div className="inline-loading">{t.loading}</div>}
                {hasNoSearchResults && (
                  <div className="console-empty search-empty">
                    <strong>{t.noSearchResults}</strong>
                    <p>{t.tryAnotherKeyword}</p>
                  </div>
                )}
                {pages.map((p) => (
                  <button
                    key={p.id}
                    className={`table-row ${p.is_unassigned ? "unassigned" : ""} ${selectedPage?.id === p.id ? "active" : ""}`}
                    type="button"
                    onClick={() => loadDetail(p)}
                  >
                    <strong>{p.title}<VisibilityBadge visibility={p.visibility} language={language} /></strong>
                    <span>{p.owner}</span>
                    <span>{pageIdentityLabel(p, t.pendingClaim)}</span>
                    <span>{formatDate(p.updated_at)}</span>
                  </button>
                ))}
              </div>
              <div className="pagination-actions">
                <button type="button" disabled={!pagination?.has_prev} onClick={() => setPage((current) => Math.max(1, current - 1))}>
                  {t.previousPage}
                </button>
                <button type="button" disabled={!pagination?.has_next} onClick={() => setPage((current) => current + 1)}>
                  {t.nextPage}
                </button>
              </div>
            </section>
            <section className="console-panel detail-panel">
              {isDetailLoading && <div className="inline-loading">{t.loading}</div>}
              {selectedPage ? (
                <>
                  <div className="sharing-actions"><VisibilityBadge visibility={selectedPage.visibility} language={language} />
                    {(isAdmin || selectedPage.user_email?.toLowerCase() === currentUser?.email.toLowerCase() || (selectedPage.user_id && selectedPage.user_id === currentUser?.sub)) &&
                      <button type="button" className="primary-btn" onClick={() => setSharingPage(selectedPage)}><Share2 size={14} />{language === "zh" ? "分享" : "Share"}</button>}
                  </div>
                  <dl>
                    <div><dt>{t.owner}</dt><dd>{selectedPage.owner}</dd></div>
                    <div><dt>{t.slug}</dt><dd>{selectedPage.slug}</dd></div>
                    <div>
                      <dt>{t.submitter}</dt>
                      <dd>{selectedPage.submitter}</dd>
                    </div>
                    <div>
                      <dt>{t.identityEmail}</dt>
                      <dd>{pageIdentityLabel(selectedPage, t.pendingClaim)}</dd>
                    </div>
                    <div><dt>{t.identityUserId}</dt><dd>{selectedPage.user_id || "-"}</dd></div>
                    <div><dt>{t.device}</dt><dd>{selectedPage.submit_device || "-"}</dd></div>
                    <div><dt>{t.ip}</dt><dd>{selectedPage.submit_ip || "-"}</dd></div>
                    <div><dt>{t.created}</dt><dd>{formatDate(selectedPage.created_at)}</dd></div>
                    <div><dt>{t.updated}</dt><dd>{formatDate(selectedPage.updated_at)}</dd></div>
                    {selectedPage.data_sources && Object.keys(selectedPage.data_sources).length > 0 && (
                      <div>
                        <dt>{t.dataSources}</dt>
                        <dd>
                          <ul style={{ margin: 0, paddingLeft: "1rem" }}>
                            {Object.entries(selectedPage.data_sources).map(([key, query]) => (
                              <li key={key}>
                                <strong>{key}</strong>: {query}
                              </li>
                            ))}
                          </ul>
                        </dd>
                      </div>
                    )}
                  </dl>
                  <PageDatasetsPanel
                    language={language}
                    api={api}
                    pageId={selectedPage.id}
                    canManage={canManagePage(selectedPage)}
                  />
                  <div className="console-empty">
                    <strong>{selectedPage.title}</strong>
                    <p>{selectedPage.description || selectedPage.submit_user_agent}</p>
                    <a href={selectedPage.url} target="_blank" rel="noreferrer">{t.openPage}</a>
                    {canManagePage(selectedPage) ? (
                      <div className="action-row">
                        {canClaimPage(selectedPage) && (
                          <button
                            type="button"
                            className="claim-btn"
                            disabled={isClaiming}
                            onClick={() => handleClaim(selectedPage.id)}
                          >
                            <ShieldCheck size={14} /> {isClaiming ? t.claiming : t.claim}
                          </button>
                        )}
                        <button type="button" className="primary-btn" onClick={() => openEdit(selectedPage)}>
                          <Pencil size={14} /> {t.edit}
                        </button>
                        {deleteConfirmId === selectedPage.id ? (
                          <div className="delete-confirm">
                            <span>{t.deleteConfirm}</span>
                            <div className="delete-actions">
                              <button type="button" className="delete-btn danger" disabled={isDeleting} onClick={() => handleDelete(selectedPage.id)}>
                                {isDeleting ? t.deleting : t.delete}
                              </button>
                              <button type="button" disabled={isDeleting} onClick={() => setDeleteConfirmId(null)}>
                                {t.deleteCancel}
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button type="button" className="delete-btn" onClick={() => setDeleteConfirmId(selectedPage.id)}>
                            <Trash2 size={14} /> {t.delete}
                          </button>
                        )}
                      </div>
                    ) : (
                      <p className="permission-note">{t.manageRestricted}</p>
                    )}
                  </div>
                </>
              ) : (
                <div className="console-empty">
                  <strong>{t.detail}</strong>
                  <p>{t.noSelection}</p>
                </div>
              )}
            </section>
          </div>
        </>
      )}

      {sharingPage && <ShareDialog page={sharingPage} api={api} language={language} onClose={() => setSharingPage(null)} onSaved={async () => {
        await reloadAfterMutation();
        await loadDetail(sharingPage);
      }} />}
      {form.kind !== "closed" && (
        <PageFormModal
          api={api}
          language={language}
          mode={form.kind}
          state={formState}
          onChange={setFormState}
          error={formError}
          submitting={formSubmitting}
          onCancel={closeForm}
          onSubmit={handleSubmit}
        />
      )}
    </>
  );
}

type ModalProps = {
  api: ConsoleApi;
  language: Language;
  mode: "create" | "edit";
  state: FormState;
  onChange: (next: FormState) => void;
  error: string | null;
  submitting: boolean;
  onCancel: () => void;
  onSubmit: () => void;
};

function PageFormModal({ api, language, mode, state, onChange, error, submitting, onCancel, onSubmit }: ModalProps) {
  const t = copy[language] as typeof copy.zh;

  const update = (patch: Partial<FormState>) => onChange({ ...state, ...patch });

  return (
    <div className="page-form-backdrop" onClick={onCancel}>
      <div className="page-form-modal" onClick={(e) => e.stopPropagation()}>
        <header className="page-form-header">
          <h2>{mode === "create" ? t.formTitleCreate : t.formTitleEdit}</h2>
          <button type="button" onClick={onCancel} disabled={submitting} aria-label="Close">
            <X size={18} />
          </button>
        </header>

        <div className="page-form-body">
          {error && <div className="page-form-error">{error}</div>}

          <div className="page-form-row">
            <label>{t.fieldOwner}</label>
            <input
              type="text"
              value={state.owner}
              onChange={(e) => update({ owner: e.target.value })}
              disabled={mode === "edit"}
              required
            />
          </div>

          {mode === "create" && (
            <div className="page-form-row">
              <label>
                {t.fieldSlug} <span className="hint">— {t.slugHint}</span>
              </label>
              <input
                type="text"
                value={state.slug}
                onChange={(e) => update({ slug: e.target.value })}
              />
            </div>
          )}

          <div className="page-form-row">
            <label>{t.fieldTitle}</label>
            <input
              type="text"
              value={state.title}
              onChange={(e) => update({ title: e.target.value })}
              required
            />
          </div>

          <div className="page-form-row">
            <label>{t.fieldDescription}</label>
            <textarea
              rows={2}
              value={state.description}
              onChange={(e) => update({ description: e.target.value })}
              required
            />
          </div>

          <div className="page-form-row">
            <label>{t.fieldHtml}</label>
            <textarea
              rows={10}
              value={state.html}
              onChange={(e) => update({ html: e.target.value })}
              className="code-input"
              required
            />
          </div>
          {mode === "create" && state.sharing && <SharingFields api={api} language={language} value={state.sharing} onChange={sharing => update({ sharing })} />}
        </div>

        <footer className="page-form-footer">
          <button type="button" className="ghost-btn" onClick={onCancel} disabled={submitting}>
            {t.cancel}
          </button>
          <button type="button" className="primary-btn" onClick={onSubmit} disabled={submitting}>
            {submitting ? (
              <>
                <Loader2 size={14} className="spin" /> {mode === "create" ? t.creating : t.saving}
              </>
            ) : (
              <>
                {mode === "create" ? <Plus size={14} /> : <Save size={14} />}{" "}
                {mode === "create" ? t.create : t.save}
              </>
            )}
          </button>
        </footer>
      </div>
    </div>
  );
}
