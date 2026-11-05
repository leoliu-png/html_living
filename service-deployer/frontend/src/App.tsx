import { Book, Check, Copy, Download, Moon, PlugZap, Sun, Terminal } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiDocsView } from "./components/ApiDocsView";
import { ConsoleRoot } from "./components/ConsoleRoot";
import { PaperPlaneMotion } from "./components/PaperPlaneMotion";
import { copy, type Language } from "./content";

type Route = "home" | "console" | "api-docs";
type Theme = "light" | "dark";

const defaultOrigin = "https://www.html.living";

function getCurrentOrigin(): string {
  if (typeof window === "undefined") return defaultOrigin;
  return window.location.origin;
}

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function getRouteFromPath(): Route {
  if (typeof window === "undefined") return "home";
  if (["/console", "/registry"].includes(window.location.pathname)) return "console";
  if (window.location.pathname === "/api-docs") return "api-docs";
  return "home";
}

function FeedMobLogo() {
  return (
    <svg width="163" height="46.368" viewBox="0 0 161.65 46.368" aria-label="FeedMob">
      <defs>
        <clipPath id="feedmob-logo-clip">
          <rect width="161.65" height="46.368" fill="none" />
        </clipPath>
      </defs>
      <g clipPath="url(#feedmob-logo-clip)">
        <path d="M14.4,0H2.057A2.046,2.046,0,0,0,0,2.051v34.3A2.046,2.046,0,0,0,2.057,38.4h1.6a2.083,2.083,0,0,0,2.058-2.05V21.991h6.4a2.045,2.045,0,0,0,2.058-2.05V18.4a2.046,2.046,0,0,0-2.058-2.051h-6.4V5.64H14.4a2.045,2.045,0,0,0,2.058-2.05V2.051A2.046,2.046,0,0,0,14.4,0" transform="translate(0 7.969)" fill="#020303" />
        <path d="M14.4,32.76H5.658V21.991h7.2a2.045,2.045,0,0,0,2.057-2.05V18.4a2.045,2.045,0,0,0-2.057-2.051h-7.2V5.64H14.4a2.045,2.045,0,0,0,2.057-2.05V2.051A2.046,2.046,0,0,0,14.4,0H2.056A2.046,2.046,0,0,0,0,2.051v34.3A2.046,2.046,0,0,0,2.056,38.4H14.4a2.046,2.046,0,0,0,2.057-2.05V34.811A2.046,2.046,0,0,0,14.4,32.76" transform="translate(19.2 7.969)" fill="#020303" />
        <path d="M14.4,0H2.057A2.046,2.046,0,0,0,0,2.051v34.3A2.046,2.046,0,0,0,2.057,38.4H14.4a2.046,2.046,0,0,0,2.057-2.05V34.811A2.046,2.046,0,0,0,14.4,32.76H5.657V21.991h7.2a2.045,2.045,0,0,0,2.058-2.05V18.4a2.046,2.046,0,0,0-2.058-2.051h-7.2V5.64H14.4a2.045,2.045,0,0,0,2.057-2.05V2.051A2.046,2.046,0,0,0,14.4,0" transform="translate(39.771 7.969)" fill="#020303" />
        <path d="M7.91,38H2.064A2.049,2.049,0,0,1,0,35.971V2.03A2.049,2.049,0,0,1,2.064,0H7.91c3.392,0,5.958.953,7.625,2.834C17.171,4.678,18,7.481,18,11.164V26.837c0,3.683-.829,6.485-2.465,8.33C13.868,37.047,11.3,38,7.91,38ZM5.674,5.582V32.418H7.911c2.973,0,4.3-1.722,4.3-5.582V11.164c0-3.86-1.326-5.582-4.3-5.582Z" transform="translate(60.172 7.903)" fill="#020303" />
        <path d="M10.971,32.489,2.094,0H0V38.4H2.4V10.364L10.051,38.4h1.842l7.6-28.019V38.4h2.451V0H19.8Z" transform="translate(82.286 7.969)" fill="#020303" />
        <path d="M7.973,38a9.928,9.928,0,0,1-2.73-.4A6.089,6.089,0,0,1,2.61,36.012,8.369,8.369,0,0,1,.715,32.858,15.388,15.388,0,0,1,0,27.725V10.22C0,6.983.651,4.452,1.934,2.7A7.2,7.2,0,0,1,7.973,0,7.109,7.109,0,0,1,14.01,2.693C15.331,4.412,16,6.945,16,10.22V27.725a15.454,15.454,0,0,1-.714,5.132,8.4,8.4,0,0,1-1.9,3.155,6.078,6.078,0,0,1-2.63,1.587A10.11,10.11,0,0,1,7.973,38Zm0-35.508a4.645,4.645,0,0,0-4.1,1.772c-.972,1.292-1.465,3.3-1.465,5.956V27.725c0,2.7.491,4.719,1.459,6a4.728,4.728,0,0,0,4.1,1.781,4.961,4.961,0,0,0,4.162-1.789c.929-1.208,1.4-3.224,1.4-5.994V10.22c0-2.731-.472-4.731-1.4-5.945A4.879,4.879,0,0,0,7.973,2.492Z" transform="translate(108.172 7.903)" fill="#020303" />
        <path d="M6.03,38H0V0H6.03c2.722,0,4.775.865,6.1,2.572C13.371,4.259,14,6.8,14,10.109c0,3.279-.627,5.794-1.862,7.474a5.862,5.862,0,0,1-.927,1.005c-.163.137-.339.272-.522.4a6.343,6.343,0,0,1,1.443,1.367C13.371,22.042,14,24.578,14,27.891s-.627,5.847-1.862,7.529C10.808,37.132,8.754,38,6.03,38ZM2.37,20.22V35.508H6.03c2.014,0,3.461-.573,4.3-1.7.861-1.153,1.3-3.142,1.3-5.914s-.453-4.764-1.346-5.94A4.943,4.943,0,0,0,6.033,20.22Zm0-17.728V17.727H6.03A4.943,4.943,0,0,0,10.28,16c.9-1.179,1.349-3.161,1.349-5.891,0-2.768-.437-4.758-1.3-5.915-.842-1.129-2.289-1.7-4.3-1.7Z" transform="translate(130.172 7.903)" fill="#020303" />
        <path d="M8,15.993a8,8,0,1,1,8-8A8.005,8.005,0,0,1,8,15.993ZM4.163,6.684a.943.943,0,0,0-.955.928v.769a.956.956,0,0,0,.955.955H6.682v2.493a.944.944,0,0,0,.929.955h.769a.956.956,0,0,0,.954-.955V9.336h2.522a.944.944,0,0,0,.929-.955V7.612a.941.941,0,0,0-.929-.928H9.335V4.164a.945.945,0,0,0-.954-.957H7.612a.944.944,0,0,0-.929.957V6.684Z" transform="translate(145.657 0.001)" fill="#1B98BD" />
      </g>
    </svg>
  );
}

export function App() {
  const [language, setLanguage] = useState<Language>("zh");
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [route, setRoute] = useState<Route>(getRouteFromPath);
  const [copied, setCopied] = useState<"skill" | "mcp" | null>(null);
  const t = copy[language];
  const origin = getCurrentOrigin();
  const skillUrl = `${origin}/skill/page-publisher`;
  const mcpConfig = `{
  "mcpServers": {
    "page-publisher": {
      "type": "http",
      "url": "${origin}/mcp"
    }
  }
}`;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const syncTheme = (event: MediaQueryListEvent) => {
      setTheme(event.matches ? "dark" : "light");
    };
    const syncRoute = () => setRoute(getRouteFromPath());

    media.addEventListener("change", syncTheme);
    window.addEventListener("popstate", syncRoute);

    return () => {
      media.removeEventListener("change", syncTheme);
      window.removeEventListener("popstate", syncRoute);
    };
  }, []);

  const navigate = (nextRoute: Route) => {
    const nextPath =
      nextRoute === "console" ? "/console" : nextRoute === "api-docs" ? "/api-docs" : "/";
    window.history.pushState(null, "", nextPath);
    setRoute(nextRoute);
  };

  const copyText = async (target: "skill" | "mcp", value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(target);
      window.setTimeout(() => {
        setCopied((current) => (current === target ? null : current));
      }, 1500);
    } catch {
      // Clipboard access can be unavailable in some embedded browsers.
    }
  };

  return (
    <main className="page">
      <section className="shell">
        <header className="nav">
          <button className="brand brand-button" type="button" onClick={() => navigate("home")} aria-label={t.home}>
            <FeedMobLogo />
          </button>
          <div className="nav-actions">
            <div className="language-switch" aria-label="Language">
              <button
                className={language === "zh" ? "active" : ""}
                type="button"
                onClick={() => setLanguage("zh")}
              >
                中文
              </button>
              <button
                className={language === "en" ? "active" : ""}
                type="button"
                onClick={() => setLanguage("en")}
              >
                EN
              </button>
            </div>
            <button
              className="theme-toggle"
              type="button"
              aria-label={theme === "dark" ? t.lightTheme : t.darkTheme}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            {route === "console" ? (
              <button className="badge" type="button" onClick={() => navigate("home")}>{t.home}</button>
            ) : route === "api-docs" ? (
              <button className="badge" type="button" onClick={() => navigate("home")}>{t.home}</button>
            ) : (
              <>
                <button className="badge" type="button" onClick={() => navigate("api-docs")}>
                  <Book size={14} style={{ marginRight: 4, verticalAlign: "-2px" }} />
                  API
                </button>
                <button className="badge" type="button" onClick={() => navigate("console")}>{t.console}</button>
              </>
            )}
          </div>
        </header>

        {route === "console" ? (
          <ConsoleRoot language={language} />
        ) : route === "api-docs" ? (
          <ApiDocsView language={language} />
        ) : (
          <div className="content-grid">
          <section className="tile intro-tile">
            <div className="intro-copy">
              <p className="eyebrow">{t.internalTool}</p>
              <h1>{t.title}</h1>
              <p className="summary">
                {t.summary}
              </p>
            </div>
            <PaperPlaneMotion />
          </section>

          <section className="tile skill-tile">
            <article className="card skill-card">
              <div>
                <p className="eyebrow">{t.methodOne}</p>
                <div className="card-title">
                  <Download size={20} />
                  <h3>{t.installSkill}</h3>
                </div>
                <p>{t.skillDescription}</p>
              </div>

              <div className="command-panel">
                <div className="command-header">
                  <span>
                    <Terminal size={16} />
                    {t.skillUrlLabel}
                  </span>
                  <button type="button" onClick={() => copyText("skill", skillUrl)} aria-label={t.copySkillCommand}>
                    {copied === "skill" ? <Check size={16} /> : <Copy size={16} />}
                  </button>
                </div>
                <code>{skillUrl}</code>
              </div>

              <div className="skill-steps" aria-label={t.stepsLabel}>
                <div>
                  <span>01</span>
                  <strong>{t.install}</strong>
                </div>
                <div>
                  <span>02</span>
                  <strong>{t.invoke}</strong>
                </div>
                <div>
                  <span>03</span>
                  <strong>{t.publish}</strong>
                </div>
              </div>
            </article>
          </section>

          <section className="tile mcp-tile">
            <article className="card mcp-card">
              <p className="eyebrow">{t.methodTwo}</p>
              <div className="card-title">
                <PlugZap size={20} />
                <h3>{t.configureMcp}</h3>
              </div>
              <p>{t.mcpDescription}</p>
              <div className="mcp-config-panel">
                <button type="button" onClick={() => copyText("mcp", mcpConfig)} aria-label={t.copyMcpConfig}>
                  {copied === "mcp" ? <Check size={16} /> : <Copy size={16} />}
                </button>
                <pre>{mcpConfig}</pre>
              </div>
            </article>
          </section>
          </div>
        )}
      </section>
    </main>
  );
}
