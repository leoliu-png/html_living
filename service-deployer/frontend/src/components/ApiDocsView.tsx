import { useEffect, useMemo, useState } from "react";
import { Book, Check, Clipboard, Search, X } from "lucide-react";
import type { Language } from "../content";
import { COPY, ENDPOINTS, type Endpoint, type HttpMethod, type Param } from "../apiDocs";
import "./ApiDocsView.css";

const METHOD_COLOR: Record<HttpMethod, string> = {
  GET: "method-get",
  POST: "method-post",
  PUT: "method-put",
  DELETE: "method-delete",
  PATCH: "method-patch",
};

type Props = {
  language: Language;
};

export function ApiDocsView({ language }: Props) {
  const t = COPY[language] as typeof COPY.zh;
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<string | null>(ENDPOINTS[0]?.id ?? null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return ENDPOINTS;
    return ENDPOINTS.filter((ep) => {
      return (
        ep.method.toLowerCase().includes(q) ||
        ep.path.toLowerCase().includes(q) ||
        ep.title.toLowerCase().includes(q) ||
        ep.summary.toLowerCase().includes(q)
      );
    });
  }, [query]);

  const grouped = useMemo(() => {
    const map = new Map<string, Endpoint[]>();
    for (const ep of filtered) {
      const list = map.get(ep.group) ?? [];
      list.push(ep);
      map.set(ep.group, list);
    }
    return Array.from(map.entries());
  }, [filtered]);

  useEffect(() => {
    if (!activeId && filtered[0]) {
      setActiveId(filtered[0].id);
    }
  }, [filtered, activeId]);

  const replaceToken = (curl: string) => curl.replace(/\$TOKEN/g, "<your-token>");
  const buildFullCurl = (ep: Endpoint) => replaceToken(ep.curlExample);

  const handleCopy = async (ep: Endpoint) => {
    try {
      await navigator.clipboard.writeText(buildFullCurl(ep));
      setCopiedId(ep.id);
      window.setTimeout(() => setCopiedId((current) => (current === ep.id ? null : current)), 1500);
    } catch {
      // ignore
    }
  };

  const activeEndpoint = ENDPOINTS.find((ep) => ep.id === activeId);

  return (
    <div className="api-docs">
      <aside className="api-docs-sidebar">
        <div className="api-docs-search">
          <Search size={14} />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.searchPlaceholder}
          />
          {query && (
            <button type="button" onClick={() => setQuery("")} aria-label="Clear search">
              <X size={14} />
            </button>
          )}
        </div>

        <nav className="api-docs-nav">
          {grouped.map(([group, eps]) => (
            <section key={group} className="api-docs-group">
              <h4>{(t.groups as Record<string, string>)[group] ?? group}</h4>
              {eps.map((ep) => (
                <button
                  key={ep.id}
                  type="button"
                  className={`api-docs-nav-item ${activeId === ep.id ? "active" : ""}`}
                  onClick={() => setActiveId(ep.id)}
                >
                  <span className={`api-docs-method-tag ${METHOD_COLOR[ep.method]}`}>{ep.method}</span>
                  <span className="api-docs-nav-path">{ep.path}</span>
                </button>
              ))}
            </section>
          ))}
          {filtered.length === 0 && <div className="api-docs-empty">No matches.</div>}
        </nav>
      </aside>

      <main className="api-docs-main">
        <header className="api-docs-header">
          <p className="eyebrow">{t.eyebrow}</p>
          <h2>{t.title}</h2>
          <p className="api-docs-summary">{t.summary}</p>
          <div className="api-docs-notice">
            <Book size={14} />
            <span>{t.tokenNotice}</span>
          </div>
        </header>

        {activeEndpoint && (
          <article className="api-docs-endpoint" key={activeEndpoint.id}>
            <div className="api-docs-endpoint-head">
              <span className={`api-docs-method ${METHOD_COLOR[activeEndpoint.method]}`}>
                {activeEndpoint.method}
              </span>
              <code className="api-docs-path">{activeEndpoint.path}</code>
              <span className={`api-docs-auth ${activeEndpoint.auth}`}>
                {activeEndpoint.auth === "required" ? `🔒 ${t.authRequired}` : `🌐 ${t.authNone}`}
              </span>
            </div>

            <h3 className="api-docs-endpoint-title">{activeEndpoint.title}</h3>
            <p className="api-docs-endpoint-summary">{activeEndpoint.summary}</p>
            <p className="api-docs-endpoint-desc">{activeEndpoint.description}</p>

            {activeEndpoint.params && activeEndpoint.params.length > 0 && (
              <section className="api-docs-section">
                <h4>{t.parameters}</h4>
                <div className="api-docs-params">
                  {groupParams(activeEndpoint.params).map(({ location, params }) => (
                    <div key={location} className="api-docs-params-group">
                      <div className="api-docs-params-label">
                        {(t.paramLocation as Record<string, string>)[location] ?? location}
                      </div>
                      {params.map((p) => (
                        <div key={`${location}-${p.name}`} className="api-docs-param">
                          <div className="api-docs-param-name">
                            <code>{p.name}</code>
                            <span className={`api-docs-required ${p.required ? "yes" : "no"}`}>
                              {p.required ? t.required : t.optional}
                            </span>
                          </div>
                          <div className="api-docs-param-type">{p.type}</div>
                          <div className="api-docs-param-desc">
                            {p.description}
                            {p.example && (
                              <span className="api-docs-param-example">
                                e.g. <code>{p.example}</code>
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </section>
            )}

            {activeEndpoint.requestExample && (
              <section className="api-docs-section">
                <h4>{t.requestBody}</h4>
                <pre className="api-docs-codeblock">{activeEndpoint.requestExample}</pre>
              </section>
            )}

            <section className="api-docs-section">
              <h4>{t.response}</h4>
              <pre className="api-docs-codeblock">{activeEndpoint.responseExample}</pre>
            </section>

            <section className="api-docs-section">
              <h4>{t.curl}</h4>
              <div className="api-docs-curl">
                <pre className="api-docs-codeblock">{buildFullCurl(activeEndpoint)}</pre>
                <div className="api-docs-curl-actions">
                  <button type="button" onClick={() => handleCopy(activeEndpoint)}>
                    {copiedId === activeEndpoint.id ? <Check size={14} /> : <Clipboard size={14} />}
                    {copiedId === activeEndpoint.id ? t.copied : t.copy}
                  </button>
                </div>
              </div>
            </section>
          </article>
        )}
      </main>
    </div>
  );
}

function groupParams(params: Param[]): Array<{ location: string; params: Param[] }> {
  const map = new Map<string, Param[]>();
  for (const p of params) {
    const list = map.get(p.in) ?? [];
    list.push(p);
    map.set(p.in, list);
  }
  return Array.from(map.entries()).map(([location, params]) => ({ location, params }));
}
