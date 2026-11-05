import { readFileSync } from "node:fs";
import { join } from "node:path";
import crypto from "node:crypto";
import { AsyncLocalStorage } from "node:async_hooks";
import process from "node:process";
import express from "express";
import type { Request, Response, NextFunction } from "express";
import axios from "axios";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { registerTools } from "./tools.js";
import {
  getOAuthMetadata,
  getGoogleAuthUrl,
  handleGoogleCallback,
  storePkceSession,
  getPkceSession,
  deletePkceSession,
  issueAuthorizationCode,
  consumeAuthorizationCode,
  issueAccessToken,
  verifyAccessToken,
  generateCodeVerifier,
  generateCodeChallenge,
  registerClient,
  verifyStaticToken,
  hasStaticToken,
  getStaticTokenHint,
  issueRefreshToken,
  consumeRefreshToken,
  generateUserCode,
  storeDeviceSession,
  setDeviceGoogleVerifier,
  getDeviceSession,
  getDeviceSessionByUserCode,
  getDeviceSessionByGoogleState,
  approveDeviceSession,
  consumeDeviceSession,
  type GoogleUser,
} from "./auth.js";

// ── per-request user context ─────────────────────────────────────────────────

const userContext = new AsyncLocalStorage<GoogleUser>();

export function getCurrentUser(): GoogleUser | null {
  return userContext.getStore() ?? null;
}

// ── constants ────────────────────────────────────────────────────────────────

const PORT = parseInt(process.env.PORT ?? "30002", 10);
const HOST = process.env.HOST ?? "127.0.0.1"; // H1: 默认仅监听本地，由 Caddy 反代
const BASE_URL = (process.env.BASE_URL ?? `http://127.0.0.1:${PORT}`).replace(/\/+$/, "");

// ── Per-request MCP server factory (stateless) ─────────────────────────────────
// Each request gets its own McpServer + transport to avoid "already initialized"
// errors from the global singleton pattern.

function createMcpServer(): McpServer {
  const server = new McpServer({
    name: "service-deployer",
    version: "1.0.0",
  });
  registerTools(server, getCurrentUser);
  return server;
}

// ── Express app ──────────────────────────────────────────────────────────────

const app = express();

app.use(express.json({ limit: "50mb" }));
app.use(express.urlencoded({ extended: true, limit: "50mb" }));

// ── OAuth metadata ───────────────────────────────────────────────────────────

app.get("/.well-known/oauth-authorization-server", (_req: Request, res: Response) => {
  res.json(getOAuthMetadata());
});

// ── health ───────────────────────────────────────────────────────────────────

app.get("/health", (_req: Request, res: Response) => {
  res.json({ status: "ok", service: "service-deployer-mcp", oauth: true });
});


// ── Skill endpoint (public documentation) ────────────────────────────────────

const SKILL_DIR = process.env.SKILL_DIR ?? "/srv/service-deployer/skill";

function isValidSkillName(name: string): boolean {
  return /^[a-zA-Z0-9_-]+$/.test(name);
}

function firstHeaderValue(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value;
}

function requestOrigin(req: Request): string {
  const forwardedProto = firstHeaderValue(req.headers["x-forwarded-proto"]);
  const forwardedHost = firstHeaderValue(req.headers["x-forwarded-host"]);
  const proto = (forwardedProto ?? req.protocol ?? "http").split(",")[0]?.trim() || "http";
  const host = (forwardedHost ?? req.headers.host ?? `${HOST}:${PORT}`).split(",")[0]?.trim();
  return `${proto}://${host}`.replace(/\/+$/, "");
}

function renderSkillMarkdown(content: string, req: Request): string {
  return content.replaceAll("{{BASE_URL}}", requestOrigin(req));
}

function serveSkillMd(name: string, req: Request, res: Response): void {
  if (!isValidSkillName(name)) {
    res.status(400).json({ error: "invalid_name", description: "Skill name must be alphanumeric with hyphens/underscores" });
    return;
  }
  const filePath = join(SKILL_DIR, `${name}.md`);
  try {
    const content = readFileSync(filePath, "utf-8");
    res.type("text/markdown; charset=utf-8").send(renderSkillMarkdown(content, req));
  } catch (err: any) {
    if (err.code === "ENOENT") {
      res.status(404).json({ error: "not_found", description: `Skill '${name}' not found` });
    } else {
      console.error("Skill md read error:", err);
      res.status(500).json({ error: "internal_error" });
    }
  }
}

function serveSkillZip(name: string, res: Response): void {
  if (!isValidSkillName(name)) {
    res.status(400).json({ error: "invalid_name", description: "Skill name must be alphanumeric with hyphens/underscores" });
    return;
  }
  const filePath = join(SKILL_DIR, `${name}.zip`);
  try {
    const buf = readFileSync(filePath);
    res.type("application/zip");
    res.setHeader("Content-Disposition", `attachment; filename="${name}.zip"`);
    res.send(buf);
  } catch (err: any) {
    if (err.code === "ENOENT") {
      res.status(404).json({ error: "not_found", description: `Skill zip '${name}' not found` });
    } else {
      console.error("Skill zip read error:", err);
      res.status(500).json({ error: "internal_error" });
    }
  }
}

// GET /skill/:name — markdown content
app.get("/skill/:name", (req: Request, res: Response) => {
  const name = req.params.name as string;
  serveSkillMd(name, req, res);
});

// GET /skill/zip/:name — zip download (full skill package)
app.get("/skill/zip/:name", (req: Request, res: Response) => {
  const name = req.params.name as string;
  serveSkillZip(name, res);
});

// ── Dynamic client registration ──────────────────────────────────────────────

app.post("/mcp/register", (req: Request, res: Response) => {
  const redirectUris: string[] = req.body.redirect_uris ?? [];
  const clientName: string | undefined = req.body.client_name;

  if (!Array.isArray(redirectUris) || redirectUris.length === 0) {
    res.status(400).json({ error: "invalid_client_metadata", error_description: "redirect_uris is required" });
    return;
  }

  const { clientId } = registerClient(redirectUris, clientName);

  res.status(201).json({
    client_id: clientId,
    redirect_uris: redirectUris,
    client_name: clientName,
    grant_types: ["authorization_code"],
    token_endpoint_auth_method: "none",
  });
});

// ── Device Authorization (RFC 8628) ──────────────────────────────────────────

app.post("/mcp/device/authorize", (req: Request, res: Response) => {
  const codeChallenge: string = req.body.code_challenge ?? "";
  if (!codeChallenge) {
    res.status(400).json({ error: "invalid_request", error_description: "Missing code_challenge" });
    return;
  }

  const deviceCode = crypto.randomUUID();
  const userCode = generateUserCode();

  storeDeviceSession(deviceCode, userCode, codeChallenge);

  res.json({
    device_code: deviceCode,
    user_code: userCode,
    verification_uri: `${BASE_URL}/mcp/device`,
    verification_uri_complete: `${BASE_URL}/mcp/device?code=${userCode}`,
    expires_in: 600,
    interval: 5,
  });
});

// Device verification page (browser-based)
app.get("/mcp/device", (req: Request, res: Response) => {
  const prefilled = (req.query.code as string) ?? "";
  res.type("html").send(`<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Device Verification</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 420px; margin: 80px auto; padding: 24px; background: #f8fafc; }
  .card { background: #fff; border-radius: 12px; padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  h1 { font-size: 20px; margin-bottom: 8px; }
  p { color: #64748b; font-size: 14px; margin-bottom: 20px; }
  input { width: 100%; padding: 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 20px; font-family: monospace; text-align: center; letter-spacing: 2px; text-transform: uppercase; }
  input:focus { outline: none; border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,.1); }
  button { width: 100%; padding: 12px; background: #6366f1; color: #fff; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; margin-top: 12px; }
  button:hover { background: #4f46e5; }
  .error { color: #ef4444; font-size: 13px; margin-top: 8px; display: none; }
</style>
</head>
<body>
<div class="card">
  <h1>Enter verification code</h1>
  <p>Paste or type the code shown in your terminal.</p>
  <form method="post" action="/mcp/device">
    <input type="text" name="code" placeholder="XXXX-XXXX" maxlength="9" value="${prefilled.replace(/"/g, "&quot;")}" required autofocus autocomplete="off">
    <button type="submit">Verify</button>
    <div class="error" id="error"></div>
  </form>
</div>
</body>
</html>`);
});

app.post("/mcp/device", (req: Request, res: Response) => {
  const userCode = (req.body.code as string ?? "").trim().toUpperCase();
  if (!userCode) {
    res.redirect(302, "/mcp/device");
    return;
  }

  const session = getDeviceSessionByUserCode(userCode);
  if (!session) {
    res.type("html").send(`<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Invalid Code</title></head>
<body style="font-family:sans-serif;text-align:center;margin-top:80px">
<h1 style="color:#ef4444">Invalid or expired code</h1>
<p>Please restart the authorization flow in your terminal.</p>
</body></html>`);
    return;
  }

  // Generate server-side PKCE for the Google OAuth leg
  const googleCodeVerifier = generateCodeVerifier();
  const googleCodeChallenge = generateCodeChallenge(googleCodeVerifier);
  setDeviceGoogleVerifier(userCode, googleCodeVerifier);

  // Use getGoogleAuthUrl with userCode as state
  const googleUrl = getGoogleAuthUrl(userCode, googleCodeChallenge);
  res.redirect(302, googleUrl);
});

// ── OAuth authorize ──────────────────────────────────────────────────────────

app.get("/mcp/authorize", (req: Request, res: Response) => {
  const redirectUri = (req.query.redirect_uri as string) ?? "";
  const clientCodeChallenge = (req.query.code_challenge as string) ?? "";
  const state = (req.query.state as string) ?? "";

  if (!clientCodeChallenge) {
    res.status(400).json({ error: "invalid_request", error_description: "Missing code_challenge" });
    return;
  }

  // Generate PKCE state for CSRF protection
  const pkceState = Array.isArray(state) ? state[0] : state || crypto.randomUUID();

  // Generate server-side PKCE pair for the Google OAuth leg
  const serverCodeVerifier = generateCodeVerifier();
  const serverCodeChallenge = generateCodeChallenge(serverCodeVerifier);

  storePkceSession(pkceState, clientCodeChallenge, serverCodeVerifier, redirectUri);

  const googleUrl = getGoogleAuthUrl(pkceState, serverCodeChallenge);
  res.redirect(302, googleUrl);
});

// ── Google OAuth callback ────────────────────────────────────────────────────

app.get("/mcp/auth/google/callback", async (req: Request, res: Response) => {
  const code = req.query.code as string | undefined;
  const error = req.query.error as string | undefined;
  const state = req.query.state as string | undefined;

  if (error) {
    res.status(400).json({ error: "access_denied", error_description: error });
    return;
  }

  if (!code) {
    res.status(400).json({ error: "invalid_request", error_description: "Missing authorization code" });
    return;
  }

  try {
    // First check: PKCE session (standard authorization code flow)
    const pkceSession = state ? getPkceSession(state) : undefined;

    // Second check: device session (device authorization flow)
    const deviceSession = (!pkceSession && state) ? getDeviceSessionByGoogleState(state) : undefined;

    if (!pkceSession && !deviceSession) {
      console.error("Google callback: no session found for state", String(state).slice(0, 20));
      res.status(400).json({ error: "invalid_request", error_description: "Session expired or not found. Please restart the authorization flow." });
      return;
    }

    const serverCodeVerifier = pkceSession?.codeVerifier ?? deviceSession!.googleCodeVerifier!;
    const googleUser = await handleGoogleCallback(code, serverCodeVerifier);

    if (pkceSession) {
      const codeChallenge = pkceSession.codeChallenge;
      const redirectUri = pkceSession.redirectUri;
      deletePkceSession(state!);

      // Standard MCP flow:
      const authCode = issueAuthorizationCode(googleUser, codeChallenge);

      if (redirectUri) {
        const redirectUrl = new URL(redirectUri);
        redirectUrl.searchParams.set("code", authCode);
        if (state) redirectUrl.searchParams.set("state", state);
        res.redirect(302, redirectUrl.toString());
      } else {
        res.json({
          code: authCode,
          state,
          message: "Copy this authorization code and paste it in your MCP client.",
        });
      }
    } else {
      // Device flow: approve the device session
      approveDeviceSession(state!, googleUser);

      res.type("html").send(`<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Device Connected</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 500px; margin: 80px auto; padding: 20px; text-align: center; }
  .icon { color: #22c55e; font-size: 48px; margin-bottom: 0; }
</style>
</head>
<body>
  <p class="icon">&#10003;</p>
  <h1>Device Connected</h1>
  <p>Your MCP client is now authorized. You can close this window.</p>
</body>
</html>`);
    }
  } catch (err: any) {
    console.error("Google callback error:", err);
    res.status(500).json({
      error: "server_error",
      error_description: err.message ?? "Authentication failed",
    });
  }
});

// ── Token endpoint ───────────────────────────────────────────────────────────

app.post("/mcp/token", (req: Request, res: Response) => {
  const grantType = req.body.grant_type;

  // ── authorization_code ──────────────────────────────────────────────────
  if (grantType === "authorization_code") {
    const code = req.body.code;
    const codeVerifier = req.body.code_verifier;

    if (!code || !codeVerifier) {
      res.status(400).json({ error: "invalid_request" });
      return;
    }

    const user = consumeAuthorizationCode(code, codeVerifier);
    if (!user) {
      res.status(400).json({ error: "invalid_grant", error_description: "Invalid or expired authorization code" });
      return;
    }

    const accessToken = issueAccessToken(user);
    const refreshToken = issueRefreshToken(user);

    res.json({
      access_token: accessToken,
      token_type: "Bearer",
      expires_in: 86400, // 24 hours
      refresh_token: refreshToken,
    });
    return;
  }

  // ── refresh_token ───────────────────────────────────────────────────────
  if (grantType === "refresh_token") {
    const refreshToken = req.body.refresh_token;

    if (!refreshToken) {
      res.status(400).json({ error: "invalid_request", error_description: "Missing refresh_token" });
      return;
    }

    const user = consumeRefreshToken(refreshToken);
    if (!user) {
      res.status(400).json({ error: "invalid_grant", error_description: "Invalid or expired refresh token" });
      return;
    }

    const accessToken = issueAccessToken(user);
    const newRefreshToken = issueRefreshToken(user);

    res.json({
      access_token: accessToken,
      token_type: "Bearer",
      expires_in: 86400,
      refresh_token: newRefreshToken,
    });
    return;
  }

  // ── device_code ──────────────────────────────────────────────────────────
  if (grantType === "urn:ietf:params:oauth:grant-type:device_code") {
    const deviceCode = req.body.device_code;
    const codeVerifier = req.body.code_verifier;

    if (!deviceCode) {
      res.status(400).json({ error: "invalid_request", error_description: "Missing device_code" });
      return;
    }

    const ds = getDeviceSession(deviceCode);
    if (!ds) {
      res.status(400).json({ error: "invalid_grant", error_description: "Invalid or expired device_code" });
      return;
    }

    if (!ds.user) {
      res.status(400).json({ error: "authorization_pending" });
      return;
    }

    // Verify PKCE
    const user = consumeDeviceSession(deviceCode, codeVerifier ?? "");
    if (!user) {
      res.status(400).json({ error: "invalid_grant", error_description: "PKCE verification failed" });
      return;
    }

    const accessToken = issueAccessToken(user);
    const refreshToken = issueRefreshToken(user);

    res.json({
      access_token: accessToken,
      token_type: "Bearer",
      expires_in: 86400,
      refresh_token: refreshToken,
    });
    return;
  }

  res.status(400).json({ error: "unsupported_grant_type" });
});

// ── Revoke endpoint ──────────────────────────────────────────────────────────

app.post("/mcp/revoke", (_req: Request, res: Response) => {
  // JWTs are self-contained and cannot be revoked server-side without a blocklist.
  // This endpoint exists for spec compliance.
  res.json({ active: false });
});

// ── Auth middleware for MCP endpoint ──────────────────────────────────────────

function extractBearerToken(req: Request): string | null {
  const auth = req.headers.authorization ?? "";
  if (auth.startsWith("Bearer ")) {
    return auth.slice(7);
  }
  return null;
}

function mcpAuthMiddleware(req: Request, res: Response, next: NextFunction): void {
  const token = extractBearerToken(req);
  if (!token) {
    res
      .status(401)
      .setHeader("WWW-Authenticate", "Bearer")
      .json({ error: "invalid_token", error_description: "Missing Authorization header" });
    return;
  }

  // Try static token first (bypasses OAuth entirely)
  let user = verifyStaticToken(token);
  if (user) {
    console.error("AUTH: static token used"); // H6: 不再打印 token hint
    userContext.run(user, () => next());
    return;
  }

  // Try JWT access token
  user = verifyAccessToken(token);
  if (!user) {
    res
      .status(401)
      .setHeader("WWW-Authenticate", "Bearer")
      .json({ error: "invalid_token", error_description: "Invalid or expired access token" });
    return;
  }

  userContext.run(user, () => next());
}

// ── Direct upload proxy (bypasses JSON-RPC + base64, streams multipart to Python) ─

const PUBLISHER_URL = (process.env.PUBLISHER_URL ?? "http://127.0.0.1:30001").replace(/\/+$/, "");
const PUBLISHER_TOKEN = process.env.PUBLISHER_TOKEN ?? "";
const R2_PUBLIC_URL = (process.env.R2_PUBLIC_URL ?? "https://www.html.living").replace(/\/+$/, "");

app.post("/mcp/upload", mcpAuthMiddleware, async (req: Request, res: Response) => {
  try {
    const user = getCurrentUser();
    const headers: Record<string, string> = {
      Authorization: `Bearer ${PUBLISHER_TOKEN}`,
      "Content-Type": req.headers["content-type"] ?? "multipart/form-data",
    };
    if (user && user.sub !== "static") {
      headers["X-User-Id"] = user.sub;
      headers["X-User-Email"] = user.email;
      headers["X-User-Name"] = user.name;
    }

    const r = await axios.post(`${PUBLISHER_URL}/api/assets/upload`, req, {
      headers,
      timeout: 300_000,
      maxContentLength: 55 * 1024 * 1024,
      maxBodyLength: 55 * 1024 * 1024,
    });

    const result = r.data;
    result.full_url = result.full_url || `${R2_PUBLIC_URL}${result.url}`;
    res.json(result);
  } catch (err: any) {
    console.error("Direct upload error:", err.message);
    if (!res.headersSent) {
      res.status(500).json({ error: "upload_failed", message: err.message });
    }
  }
});

// ── MCP endpoint ─────────────────────────────────────────────────────────────
// Stateless: each request gets a fresh McpServer + transport.

// POST — JSON-RPC requests
app.post("/mcp", mcpAuthMiddleware, async (req: Request, res: Response) => {
  try {
    const server = createMcpServer();
    const transport = new StreamableHTTPServerTransport();
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (err) {
    console.error("MCP POST error:", err);
    if (!res.headersSent) {
      res.status(500).json({ error: "internal_error" });
    }
  }
});

// GET — SSE streaming
app.get("/mcp", mcpAuthMiddleware, async (req: Request, res: Response) => {
  try {
    const server = createMcpServer();
    const transport = new StreamableHTTPServerTransport();
    await server.connect(transport);
    await transport.handleRequest(req, res);
  } catch (err) {
    console.error("MCP GET error:", err);
    if (!res.headersSent) {
      res.status(500).json({ error: "internal_error" });
    }
  }
});

// DELETE — session cleanup
app.delete("/mcp", mcpAuthMiddleware, async (req: Request, res: Response) => {
  try {
    const server = createMcpServer();
    const transport = new StreamableHTTPServerTransport();
    await server.connect(transport);
    await transport.handleRequest(req, res);
  } catch (err) {
    console.error("MCP DELETE error:", err);
    if (!res.headersSent) {
      res.status(500).json({ error: "internal_error" });
    }
  }
});

// ── Global error handler ─────────────────────────────────────────────────────

app.use((err: any, _req: Request, res: Response, _next: NextFunction) => {
  console.error("UNHANDLED ERROR:", err?.stack ?? err);
  if (!res.headersSent) {
    res.status(500).json({ error: "internal_error", message: err?.message ?? String(err) });
  }
});

// ── start ────────────────────────────────────────────────────────────────────

app.listen(PORT, HOST, () => {
  console.log(`MCP Server running on http://${HOST}:${PORT}`);
  console.log(`OAuth metadata: ${BASE_URL}/.well-known/oauth-authorization-server`);
});
