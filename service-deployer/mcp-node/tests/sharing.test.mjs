import assert from "node:assert/strict";
import test from "node:test";
import axios from "axios";
import { z } from "zod";

process.env.PUBLISHER_URL = "http://publisher.test";
process.env.PUBLISHER_TOKEN = "test-transport-token";
const { registerTools } = await import("../dist/tools.js");
const tools = new Map();
let captured;
axios.defaults.adapter = async config => {
  captured = config;
  return { data: { code: 0, data: { id: "page", visibility: "private", listed: false } }, status: 200, statusText: "OK", headers: {}, config };
};
let actor = { sub: "alice", email: "alice@feedmob.com", name: "Alice", picture: "" };
registerTools({ tool: (name, description, schema, handler) => tools.set(name, { schema, handler }) }, () => actor);

async function call(name, payload = {}) {
  const tool = tools.get(name);
  return tool.handler(z.object(tool.schema).parse(payload));
}

test("publish forwards sharing and returns effective level with OAuth identity", async () => {
  const response = await call("publish_page", { html: "hello", owner: "alice", description: "test", visibility: "private", listed: false, share_with: { users: [], groups: [] } });
  assert.deepEqual(JSON.parse(captured.data).share_with, { users: [], groups: [] });
  assert.equal(JSON.parse(captured.data).visibility, "private");
  assert.equal(JSON.parse(captured.data).listed, false);
  assert.equal(captured.headers.get("X-User-Email"), "alice@feedmob.com");
  assert.equal(JSON.parse(response.content[0].text).data.visibility, "private");
});

test("omitted sharing leaves backend account defaults effective", async () => {
  await call("publish_page", { html: "hello", owner: "alice", description: "test" });
  assert.equal(Object.hasOwn(JSON.parse(captured.data), "visibility"), false);
});

test("update, sharing, defaults, groups and mine scope route to their REST endpoints", async () => {
  const cases = [
    ["update_page", { page_id: "a/b", visibility: "restricted", share_with: { users: ["bob@feedmob.com"], groups: ["team"] } }, "put", "/api/pages/a%2Fb"],
    ["get_page_sharing", { page_id: "a" }, "get", "/api/pages/a/sharing"],
    ["set_page_sharing", { page_id: "a", listed: false }, "put", "/api/pages/a/sharing"],
    ["list_groups", {}, "get", "/api/groups"],
    ["get_sharing_defaults", {}, "get", "/api/me/sharing-defaults"],
    ["set_sharing_defaults", { default_visibility: "private", default_grants: { users: [], groups: [] } }, "put", "/api/me/sharing-defaults"],
  ];
  for (const [name, body, method, path] of cases) {
    await call(name, body);
    assert.equal(captured.method, method);
    assert.equal(captured.url, `http://publisher.test${path}`);
    assert.equal(captured.headers.get("X-User-Id"), "alice");
    if (method === "put") assert.equal(Object.hasOwn(JSON.parse(captured.data), "page_id"), false);
  }
  await call("list_pages", { scope: "mine" });
  assert.equal(captured.params.scope, "mine");
});

test("static admin connection does not impersonate a user", async () => {
  actor = { sub: "static", email: "static@mcp.internal", name: "Static", picture: "" };
  await call("list_groups");
  assert.equal(captured.headers.get("X-User-Email"), undefined);
  actor = { sub: "alice", email: "alice@feedmob.com", name: "Alice", picture: "" };
});
