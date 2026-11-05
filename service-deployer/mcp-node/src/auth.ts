import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import jwt from "jsonwebtoken";
import axios from "axios";

// ── types ────────────────────────────────────────────────────────────────────

export interface GoogleUser {
  sub: string;
  email: string;
  name: string;
  picture: string;
  hd?: string;
}

interface PkceSession {
  codeChallenge: string;   // client's code_challenge (for MCP /token endpoint)
  codeVerifier: string;    // server's code_verifier (for Google token exchange)
  redirectUri: string;
  state: string;
  exp: number;
}

interface AuthCode {
  user: GoogleUser;
  codeChallenge: string;
  exp: number;
}

// ── config ───────────────────────────────────────────────────────────────────

const GOOGLE_CLIENT_ID = process.env.GOOGLE_CLIENT_ID ?? "";
const GOOGLE_CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET ?? "";
const BASE_URL = (process.env.BASE_URL ?? "http://127.0.0.1:30002").replace(/\/+$/, "");
const ALLOWED_DOMAIN = process.env.ALLOWED_DOMAIN ?? "";
const JWT_SECRET = process.env.JWT_SECRET ?? crypto.randomBytes(32).toString("hex");

const ACCESS_TOKEN_EXPIRY = "90d";
const REFRESH_TOKEN_EXPIRY_MS = 90 * 24 * 3600 * 1000; // 90 days
const CODE_EXPIRY_MS = 10 * 60 * 1000; // 10 minutes
const STATIC_TOKEN = (process.env.MCP_STATIC_TOKEN ?? process.env.PUBLISHER_TOKEN ?? "").trim();

// ── in-memory stores ─────────────────────────────────────────────────────────

const pkceSessions = new Map<string, PkceSession>();
const authCodes = new Map<string, AuthCode>();

function cleanExpired(): void {
  const now = Date.now();
  let refreshChanged = false;
  for (const [key, s] of pkceSessions) {
    if (s.exp < now) pkceSessions.delete(key);
  }
  for (const [key, c] of authCodes) {
    if (c.exp < now) authCodes.delete(key);
  }
  for (const [key, r] of refreshTokens) {
    if (r.exp < now) {
      refreshTokens.delete(key);
      refreshChanged = true;
    }
  }
  if (refreshChanged) saveRefreshTokens();
}
setInterval(cleanExpired, 60_000);

// ── PKCE helpers ─────────────────────────────────────────────────────────────

export function generateCodeVerifier(): string {
  return crypto.randomBytes(64).toString("base64url");
}

export function generateCodeChallenge(verifier: string): string {
  return crypto.createHash("sha256").update(verifier).digest("base64url");
}

function generateTokenId(): string {
  return crypto.randomBytes(32).toString("base64url");
}

// ── Google OAuth URL ─────────────────────────────────────────────────────────

export function getGoogleAuthUrl(pkceState: string, codeChallenge: string): string {
  const params = new URLSearchParams({
    client_id: GOOGLE_CLIENT_ID,
    redirect_uri: `${BASE_URL}/mcp/auth/google/callback`,
    response_type: "code",
    scope: "openid email profile",
    state: pkceState,
    code_challenge: codeChallenge,
    code_challenge_method: "S256",
    access_type: "offline",
    prompt: "consent",
  });

  if (ALLOWED_DOMAIN) {
    params.set("hd", ALLOWED_DOMAIN);
  }

  return `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
}

// ── Google callback ──────────────────────────────────────────────────────────

export async function handleGoogleCallback(code: string, codeVerifier: string): Promise<GoogleUser> {
  if (!codeVerifier) {
    throw new Error("Missing code verifier — PKCE session may have expired or state mismatch");
  }
  const params: Record<string, string> = {
    client_id: GOOGLE_CLIENT_ID,
    client_secret: GOOGLE_CLIENT_SECRET,
    code,
    grant_type: "authorization_code",
    redirect_uri: `${BASE_URL}/mcp/auth/google/callback`,
    code_verifier: codeVerifier,
  };

  const tokenRes = await axios.post(
    "https://oauth2.googleapis.com/token",
    new URLSearchParams(params),
    { headers: { "Content-Type": "application/x-www-form-urlencoded" } }
  );

  const idToken: string = tokenRes.data.id_token;
  const decoded: any = jwt.decode(idToken);

  if (!decoded) {
    throw new Error("Failed to decode Google ID token");
  }

  if (ALLOWED_DOMAIN && decoded.hd !== ALLOWED_DOMAIN) {
    throw new Error(
      `Email domain not allowed. Required: @${ALLOWED_DOMAIN}, got: ${decoded.hd ?? "unknown"}`
    );
  }

  return {
    sub: decoded.sub,
    email: decoded.email ?? "",
    name: decoded.name ?? "",
    picture: decoded.picture ?? "",
    hd: decoded.hd,
  };
}

// ── PKCE session management ──────────────────────────────────────────────────

export function storePkceSession(
  state: string,
  codeChallenge: string,
  codeVerifier: string,
  redirectUri: string
): void {
  pkceSessions.set(state, {
    codeChallenge,
    codeVerifier,
    redirectUri,
    state,
    exp: Date.now() + CODE_EXPIRY_MS,
  });
}

export function getPkceSession(state: string): PkceSession | undefined {
  return pkceSessions.get(state);
}

export function deletePkceSession(state: string): void {
  pkceSessions.delete(state);
}

// ── authorization codes ──────────────────────────────────────────────────────

export function issueAuthorizationCode(
  user: GoogleUser,
  codeChallenge: string
): string {
  const code = generateTokenId();
  authCodes.set(code, { user, codeChallenge, exp: Date.now() + CODE_EXPIRY_MS });
  return code;
}

export function consumeAuthorizationCode(
  code: string,
  codeVerifier: string
): GoogleUser | null {
  const entry = authCodes.get(code);
  if (!entry || entry.exp < Date.now()) {
    return null;
  }

  const expectedChallenge = generateCodeChallenge(codeVerifier);
  if (!crypto.timingSafeEqual(
    Buffer.from(entry.codeChallenge),
    Buffer.from(expectedChallenge)
  )) {
    return null;
  }

  authCodes.delete(code);
  return entry.user;
}

// ── access tokens (JWT) ──────────────────────────────────────────────────────

export function issueAccessToken(user: GoogleUser): string {
  return jwt.sign(
    {
      sub: user.sub,
      email: user.email,
      name: user.name,
      picture: user.picture,
      hd: user.hd,
    },
    JWT_SECRET,
    { expiresIn: ACCESS_TOKEN_EXPIRY, algorithm: "HS256" }
  );
}

export function verifyStaticToken(token: string): GoogleUser | null {
  if (!STATIC_TOKEN || token !== STATIC_TOKEN) return null;
  return {
    sub: "static",
    email: "static@mcp.internal",
    name: "Static Token User",
    picture: "",
    hd: ALLOWED_DOMAIN || undefined,
  };
}

export function hasStaticToken(): boolean {
  return STATIC_TOKEN.length > 0;
}

export function getStaticTokenHint(): string {
  return STATIC_TOKEN.slice(0, 8) + "...";
}

export function verifyAccessToken(token: string): GoogleUser | null {
  try {
    const payload = jwt.verify(token, JWT_SECRET, { algorithms: ["HS256"] }) as any;
    return {
      sub: payload.sub,
      email: payload.email,
      name: payload.name,
      picture: payload.picture,
      hd: payload.hd,
    };
  } catch {
    return null;
  }
}

// ── refresh tokens ────────────────────────────────────────────────────────────

const DATA_DIR = path.resolve(process.env.DATA_DIR ?? path.join(process.cwd(), "data"));
const REFRESH_TOKENS_FILE = path.join(DATA_DIR, "refresh_tokens.json");

function loadRefreshTokens(): Map<string, { user: GoogleUser; exp: number }> {
  try {
    if (fs.existsSync(REFRESH_TOKENS_FILE)) {
      const raw = JSON.parse(fs.readFileSync(REFRESH_TOKENS_FILE, "utf-8"));
      const map = new Map<string, { user: GoogleUser; exp: number }>();
      for (const [key, val] of Object.entries(raw) as [string, { user: GoogleUser; exp: number }][]) {
        map.set(key, val);
      }
      return map;
    }
  } catch { /* corrupt file — start fresh */ }
  return new Map();
}

function saveRefreshTokens(): void {
  try {
    if (!fs.existsSync(DATA_DIR)) {
      fs.mkdirSync(DATA_DIR, { recursive: true });
    }
    const obj: Record<string, { user: GoogleUser; exp: number }> = {};
    for (const [key, val] of refreshTokens) {
      obj[key] = val;
    }
    fs.writeFileSync(REFRESH_TOKENS_FILE, JSON.stringify(obj, null, 2), { mode: 0o600 });
  } catch { /* fail silently — refresh tokens still work in-memory */ }
}

const refreshTokens = loadRefreshTokens();

export function issueRefreshToken(user: GoogleUser): string {
  const token = generateTokenId();
  refreshTokens.set(token, { user, exp: Date.now() + REFRESH_TOKEN_EXPIRY_MS });
  saveRefreshTokens();
  return token;
}

export function consumeRefreshToken(token: string): GoogleUser | null {
  const entry = refreshTokens.get(token);
  if (!entry || entry.exp < Date.now()) {
    if (entry) {
      refreshTokens.delete(token);
      saveRefreshTokens();
    }
    return null;
  }
  refreshTokens.delete(token);
  saveRefreshTokens();
  return entry.user;
}

// ── device authorization (RFC 8628) ──────────────────────────────────────────

const DEVICE_CODE_EXPIRY_MS = 10 * 60 * 1000; // 10 minutes

interface DeviceSession {
  deviceCode: string;
  userCode: string;
  codeChallenge: string;
  googleCodeVerifier?: string;
  user?: GoogleUser;
  exp: number;
  pollingInterval: number;
}

const deviceSessions = new Map<string, DeviceSession>();  // keyed by device_code

export function generateUserCode(): string {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const seg = (): string => {
    let s = "";
    for (let i = 0; i < 4; i++) s += chars[crypto.randomInt(chars.length)];
    return s;
  };
  return seg() + "-" + seg();
}

export function storeDeviceSession(
  deviceCode: string,
  userCode: string,
  codeChallenge: string
): void {
  deviceSessions.set(deviceCode, {
    deviceCode,
    userCode,
    codeChallenge,
    exp: Date.now() + DEVICE_CODE_EXPIRY_MS,
    pollingInterval: 5,
  });
}

export function setDeviceGoogleVerifier(userCode: string, googleCodeVerifier: string): boolean {
  const s = getDeviceSessionByUserCode(userCode);
  if (!s) return false;
  s.googleCodeVerifier = googleCodeVerifier;
  return true;
}

export function getDeviceSession(deviceCode: string): DeviceSession | undefined {
  const s = deviceSessions.get(deviceCode);
  if (s && s.exp < Date.now()) {
    deviceSessions.delete(deviceCode);
    return undefined;
  }
  return s;
}

export function getDeviceSessionByUserCode(userCode: string): DeviceSession | undefined {
  for (const s of deviceSessions.values()) {
    if (s.userCode === userCode && s.exp >= Date.now()) return s;
  }
  return undefined;
}

export function approveDeviceSession(userCode: string, user: GoogleUser): DeviceSession | null {
  const s = getDeviceSessionByUserCode(userCode);
  if (!s) return null;
  s.user = user;
  return s;
}

// Check if a device session exists and has its Google verifier (for callback dispatch)
export function getDeviceSessionByGoogleState(state: string): DeviceSession | undefined {
  const s = getDeviceSessionByUserCode(state);
  if (s && s.googleCodeVerifier) return s;
  return undefined;
}

export function consumeDeviceSession(deviceCode: string, codeVerifier: string): GoogleUser | null {
  const s = deviceSessions.get(deviceCode);
  if (!s || s.exp < Date.now()) return null;

  const expectedChallenge = generateCodeChallenge(codeVerifier);
  if (!crypto.timingSafeEqual(Buffer.from(s.codeChallenge), Buffer.from(expectedChallenge))) {
    return null;
  }

  if (!s.user) return null;

  deviceSessions.delete(deviceCode);
  return s.user;
}

// ── dynamic client registration ──────────────────────────────────────────────

const registeredClients = new Map<string, { redirectUris: string[]; clientName?: string }>();

export function registerClient(redirectUris: string[], clientName?: string): { clientId: string } {
  const clientId = crypto.randomBytes(16).toString("hex");
  registeredClients.set(clientId, { redirectUris, clientName });
  return { clientId };
}

export function getClient(clientId: string): { redirectUris: string[]; clientName?: string } | undefined {
  return registeredClients.get(clientId);
}

// ── OAuth metadata ───────────────────────────────────────────────────────────

export function getOAuthMetadata(): object {
  return {
    issuer: BASE_URL,
    authorization_endpoint: `${BASE_URL}/mcp/authorize`,
    token_endpoint: `${BASE_URL}/mcp/token`,
    registration_endpoint: `${BASE_URL}/mcp/register`,
    device_authorization_endpoint: `${BASE_URL}/mcp/device/authorize`,
    scopes_supported: ["openid", "email", "profile"],
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:device_code"],
    token_endpoint_auth_methods_supported: ["none"],
    code_challenge_methods_supported: ["S256"],
    revocation_endpoint: `${BASE_URL}/mcp/revoke`,
  };
}
