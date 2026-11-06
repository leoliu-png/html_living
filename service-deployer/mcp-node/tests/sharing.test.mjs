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
    ["set_namespace_sharing_defaults", { owner: "ken-team", default_visibility: "restricted", default_grants: { groups: ["ken-team"] } }, "put", "/api/namespaces/ken-team/sharing-defaults"],
    ["clear_namespace_sharing_defaults", { owner: "ken-team" }, "delete", "/api/namespaces/ken-team/sharing-defaults"],
    ["create_group", { slug: "ken-team", name: "Ken Team", managers: ["ken@feedmob.com"] }, "post", "/api/groups"],
    ["update_group", { slug: "ken-team", name: "Renamed" }, "put", "/api/groups/ken-team"],
    ["add_group_members", { slug: "ken-team", members: ["leo_liu@feedmob.com"] }, "patch", "/api/groups/ken-team/members"],
    ["remove_group_members", { slug: "ken-team", emails: ["amy@feedmob.com"] }, "patch", "/api/groups/ken-team/members"],
    ["set_group_members", { slug: "ken-team", managers: ["ken@feedmob.com"], members: [] }, "put", "/api/groups/ken-team/members"],
    ["delete_group", { slug: "ken-team" }, "delete", "/api/groups/ken-team"],
    ["list_namespace_sharing_defaults", {}, "get", "/api/namespaces/sharing-defaults"],
    ["claim_page", { page_id: "a" }, "post", "/api/pages/a/claim"],
    ["get_page_audit", { page_id: "a" }, "get", "/api/pages/a/audit"],
    ["get_sharing_audit", {}, "get", "/api/admin/sharing-audit"],
  ];
  for (const [name, body, method, path] of cases) {
    await call(name, body);
    assert.equal(captured.method, method);
    assert.equal(captured.url, `http://publisher.test${path}`);
    assert.equal(captured.headers.get("X-User-Id"), "alice");
    if (method === "put" || method === "patch") {
      assert.equal(Object.hasOwn(JSON.parse(captured.data), "page_id"), false);
      assert.equal(Object.hasOwn(JSON.parse(captured.data), "owner"), false);
    }
  }
  await call("get_sharing_defaults", { owner: "ken-team" });
  assert.equal(captured.params.owner, "ken-team");
  await call("list_pages", { scope: "mine" });
  assert.equal(captured.params.scope, "mine");
});

test("static admin connection does not impersonate a user", async () => {
  actor = { sub: "static", email: "static@mcp.internal", name: "Static", picture: "" };
  await call("list_groups");
  assert.equal(captured.headers.get("X-User-Email"), undefined);
  actor = { sub: "alice", email: "alice@feedmob.com", name: "Alice", picture: "" };
});

test("group member tools send incremental changes and the force flag", async () => {
  await call("add_group_members", { slug: "ken-team", members: ["leo_liu@feedmob.com"], managers: ["amy@feedmob.com"] });
  assert.deepEqual(JSON.parse(captured.data), { add_members: ["leo_liu@feedmob.com"], add_managers: ["amy@feedmob.com"] });
  await call("remove_group_members", { slug: "ken-team", emails: ["amy@feedmob.com"] });
  assert.deepEqual(JSON.parse(captured.data), { remove: ["amy@feedmob.com"] });
  await call("delete_group", { slug: "ken-team", force: true });
  assert.equal(captured.params.force, true);
  await call("delete_group", { slug: "ken-team" });
  assert.equal(captured.params, undefined);
  await call("get_sharing_audit", { action: "group_deleted", limit: 20 });
  assert.deepEqual(captured.params, { action: "group_deleted", limit: 20 });
  assert.equal(captured.headers.get("X-User-Email"), "alice@feedmob.com");
});

test("new group tools return the backend reason instead of a bare status code", async () => {
  const original = axios.defaults.adapter;
  axios.defaults.adapter = async config => {
    const error = new Error("Request failed with status code 409");
    error.response = { status: 409, data: { detail: "Group is still used by 2 page(s). Retry with force=true." }, headers: {}, config };
    throw error;
  };
  try {
    const response = await call("delete_group", { slug: "ken-team" });
    assert.equal(response.isError, true);
    assert.match(response.content[0].text, /409: Group is still used by 2 page\(s\)/);
  } finally {
    axios.defaults.adapter = original;
  }
});
