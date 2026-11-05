import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import axios from "axios";
import FormData from "form-data";
import type { GoogleUser } from "./auth.js";

const PUBLISHER_URL = (process.env.PUBLISHER_URL ?? "http://127.0.0.1:30001").replace(/\/+$/, "");
const PUBLISHER_TOKEN=process.env.PUBLISHER_TOKEN ?? "";
const R2_PUBLIC_URL = (process.env.R2_PUBLIC_URL ?? "https://www.html.living").replace(/\/+$/, "");
const sharingFields = {
  visibility: z.enum(["private", "restricted", "org"]).optional().describe("Page access; omitted sharing uses account defaults"),
  share_with: z.object({ users: z.array(z.string()).default([]), groups: z.array(z.string()).default([]) }).optional(),
  listed: z.boolean().optional().describe("Show an org page in registry, search and lists"),
};

function authHeaders(): Record<string, string> {
  if (!PUBLISHER_TOKEN) return {};
  return { Authorization: `Bearer ${PUBLISHER_TOKEN}` };
}

function appendUserHeaders(headers: Record<string, string>, user: GoogleUser | null): void {
  if (!user || user.sub === "static") return;
  headers["X-User-Id"] = user.sub;
  headers["X-User-Email"] = user.email;
  headers["X-User-Name"] = user.name;
}

function publisherHeaders(user: GoogleUser | null): Record<string, string> {
  const headers = authHeaders();
  appendUserHeaders(headers, user);
  return headers;
}

// Upload a buffer to R2 via backend /api/assets/upload, return full_url
async function uploadToR2(
  buffer: Buffer,
  filename: string,
  user: GoogleUser | null
): Promise<{ url: string; full_url: string; filename: string; size: number }> {
  const form = new FormData();
  form.append("file", buffer, { filename });

  const headers: Record<string, string> = {
    ...authHeaders(),
    ...form.getHeaders(),
  };
  appendUserHeaders(headers, user);

  const r = await axios.post(`${PUBLISHER_URL}/api/assets/upload`, form, {
    headers,
    timeout: 300_000,
    maxContentLength: 55 * 1024 * 1024,
    maxBodyLength: 55 * 1024 * 1024,
  });

  const result = r.data;
  const fullUrl = result.full_url || `${R2_PUBLIC_URL}${result.url}`;
  return { url: result.url, full_url: fullUrl, filename: result.filename, size: result.size };
}

// Upload a dataset (CSV/JSON text) to a page via backend /api/pages/{id}/datasets
async function uploadDataset(
  pageId: string,
  filename: string,
  content: Buffer,
  name: string | undefined,
  user: GoogleUser | null
): Promise<Record<string, unknown>> {
  const form = new FormData();
  form.append("file", content, { filename });
  if (name) form.append("name", name);

  const headers: Record<string, string> = {
    ...authHeaders(),
    ...form.getHeaders(),
  };
  appendUserHeaders(headers, user);

  const r = await axios.post(`${PUBLISHER_URL}/api/pages/${encodeURIComponent(pageId)}/datasets`, form, {
    headers,
    timeout: 300_000,
    maxContentLength: 25 * 1024 * 1024,
    maxBodyLength: 25 * 1024 * 1024,
  });
  return r.data;
}

export function registerTools(server: McpServer, getUser: () => GoogleUser | null): void {
  const result = (data: unknown) => ({ content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }] });
  server.tool("update_page", "Update a page's content or sharing. Owner/admin only.", {
    page_id: z.string().min(1), ...sharingFields,
    html: z.string().min(1).optional(), title: z.string().max(200).optional(),
    description: z.string().min(1).optional(), data_sources: z.record(z.string()).optional(),
  }, async ({ page_id, ...body }) => result((await axios.put(
    `${PUBLISHER_URL}/api/pages/${encodeURIComponent(page_id)}`, body,
    { headers: publisherHeaders(getUser()), timeout: 30_000 }
  )).data));
  server.tool("get_page_sharing", "Read page sharing settings. Owner/admin only.", { page_id: z.string().min(1) },
    async ({ page_id }) => result((await axios.get(`${PUBLISHER_URL}/api/pages/${encodeURIComponent(page_id)}/sharing`,
      { headers: publisherHeaders(getUser()), timeout: 30_000 })).data));
  server.tool("set_page_sharing", "Change page sharing; changes revoke old page data credentials.",
    { page_id: z.string().min(1), ...sharingFields }, async ({ page_id, ...body }) => result((await axios.put(
      `${PUBLISHER_URL}/api/pages/${encodeURIComponent(page_id)}/sharing`, body,
      { headers: publisherHeaders(getUser()), timeout: 30_000 })).data));
  server.tool("list_groups", "List html.living sharing groups.", {}, async () => result((await axios.get(
    `${PUBLISHER_URL}/api/groups`, { headers: publisherHeaders(getUser()), timeout: 30_000 })).data));
  server.tool("get_sharing_defaults", "Read your new-page sharing defaults.", {}, async () => result((await axios.get(
    `${PUBLISHER_URL}/api/me/sharing-defaults`, { headers: publisherHeaders(getUser()), timeout: 30_000 })).data));
  server.tool("set_sharing_defaults", "Set your new-page sharing defaults.", {
    default_visibility: z.enum(["private", "restricted", "org"]),
    default_grants: z.object({ users: z.array(z.string()), groups: z.array(z.string()) }),
  }, async (body) => result((await axios.put(`${PUBLISHER_URL}/api/me/sharing-defaults`, body,
    { headers: publisherHeaders(getUser()), timeout: 30_000 })).data));
  server.tool(
    "publish_page",
    "Publish an HTML page. If the HTML contains images, pass them via the `images` parameter — " +
    "each image is uploaded to R2 and its filename is replaced with the R2 URL in the HTML. " +
    "Example: HTML has <img src=\"chart.png\">, pass images=[{filename:\"chart.png\", base64:\"...\"}].",
    {
      ...sharingFields,
      html: z.string().min(1).describe("Full HTML content. Reference images by filename, e.g. <img src=\"photo.png\">"),
      owner: z.string().min(1).max(96).describe("Owner/group name (lowercase letters, numbers, hyphens)"),
      description: z.string().min(1).describe("Short description of the page"),
      slug: z.string().max(96).optional().describe("URL slug — auto-generated if omitted"),
      title: z.string().max(200).optional().describe("Page title"),
      images: z.array(z.object({
        filename: z.string().min(1).describe("Image filename referenced in HTML, e.g. chart.png"),
        base64: z.string().min(1).describe("Base64-encoded image content (raw, no data: prefix)"),
      })).max(20).optional().describe("Images to upload to R2. Each filename is replaced with its R2 URL in the HTML."),
      datasets: z.array(z.object({
        filename: z.string().min(1).describe("Data file name with extension: .csv, .tsv, .json, .ndjson"),
        content: z.string().min(1).optional().describe("Raw file text (CSV rows or JSON)"),
        base64: z.string().min(1).optional().describe("Base64-encoded file content, as an alternative to `content`"),
        name: z.string().max(64).optional().describe("Reference name used in the page, e.g. 'sales'"),
      })).max(10).optional().describe(
        "Data files attached to the page. The page HTML reads them with the injected PageData helper: "
        + "`const rows = await PageData.load('sales')` or "
        + "`await PageData.query('sales', { where: { country: 'US' }, sort: 'spend', order: 'desc', limit: 20 })`."
      ),
    },
    async (args) => {
      let html = args.html;
      const uploaded: Array<{ filename: string; r2_url: string; size: number }> = [];

      // Upload images to R2 and replace filenames in HTML
      if (args.images && args.images.length > 0) {
        for (const img of args.images) {
          const buffer = Buffer.from(img.base64, "base64");
          if (buffer.length > 50 * 1024 * 1024) {
            return {
              content: [{ type: "text", text: JSON.stringify({ error: "image_too_large", filename: img.filename, max_mb: 50 }) }],
            };
          }

          const result = await uploadToR2(buffer, img.filename, getUser());
          uploaded.push({ filename: img.filename, r2_url: result.full_url, size: result.size });

          // Replace all occurrences of the filename in src attributes
          const escaped = img.filename.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          html = html.replace(new RegExp(`src=["']${escaped}["']`, "g"), `src="${result.full_url}"`);
        }
      }

      // Publish the final HTML
      const body: Record<string, unknown> = {
        html,
        owner: args.owner,
        description: args.description,
      };
      if (args.slug) body.slug = args.slug;
      if (args.title) body.title = args.title;
      if (args.visibility !== undefined) body.visibility = args.visibility;
      if (args.share_with !== undefined) body.share_with = args.share_with;
      if (args.listed !== undefined) body.listed = args.listed;

      const user = getUser();
      const headers = publisherHeaders(user);

      const r = await axios.post(`${PUBLISHER_URL}/api/pages`, body, {
        headers,
        timeout: 30_000,
      });

      // Attach data files once the page exists, so the HTML can query them at runtime.
      const attached: Array<Record<string, unknown>> = [];
      const pageId = r.data?.data?.id;
      if (args.datasets && args.datasets.length > 0) {
        if (!pageId) {
          return {
            content: [{ type: "text", text: JSON.stringify({ ...r.data, datasets_error: "missing_page_id" }, null, 2) }],
          };
        }
        for (const dataset of args.datasets) {
          if (!dataset.content && !dataset.base64) {
            attached.push({ filename: dataset.filename, error: "missing_content" });
            continue;
          }
          const buffer = dataset.base64
            ? Buffer.from(dataset.base64, "base64")
            : Buffer.from(dataset.content as string, "utf-8");
          if (buffer.length > 20 * 1024 * 1024) {
            attached.push({ filename: dataset.filename, error: "dataset_too_large", max_mb: 20 });
            continue;
          }
          const result = await uploadDataset(pageId, dataset.filename, buffer, dataset.name, user);
          attached.push((result as { data?: Record<string, unknown> }).data ?? result);
        }
      }

      return {
        content: [{
          type: "text",
          text: JSON.stringify({
            ...r.data,
            images_uploaded: uploaded.length > 0 ? uploaded : undefined,
            datasets_attached: attached.length > 0 ? attached : undefined,
          }, null, 2),
        }],
      };
    }
  );

  server.tool(
    "upload_image",
    "Upload a local image file to R2 storage and get back a public URL for use in HTML pages. "
    + "This tool does NOT accept file content directly. Instead, you MUST use the REST API endpoint to upload:\n\n"
    + "POST https://www.html.living/mcp/upload\n"
    + "Content-Type: multipart/form-data\n"
    + "Authorization: Bearer <your_token>\n"
    + "Body: file=@<local_file_path>;filename=<filename>\n\n"
    + "Example using curl:\n"
    + "curl -s -X POST https://www.html.living/mcp/upload \\\n"
    + "  -F \"file=@/path/to/image.png;filename=image.png\" \\\n"
    + "  -H \"Authorization: Bearer <token>\"\n\n"
    + "The response contains: { \"full_url\": \"https://...r2.dev/uploads/.../xxx.png\" }\n\n"
    + "Use the returned full_url in your HTML: <img src=\"https://...r2.dev/uploads/.../xxx.png\">\n\n"
    + "Then call publish_page with the HTML containing the image URL.",
    {},
    async () => {
      return {
        content: [{
          type: "text",
          text: JSON.stringify({
            message: "To upload an image, use the REST API endpoint directly:",
            endpoint: "POST https://www.html.living/mcp/upload",
            content_type: "multipart/form-data",
            auth_header: "Authorization: Bearer <your_token>",
            form_field: "file=@<local_path>;filename=<filename>",
            response: "{ full_url: \"https://pub-xxx.r2.dev/uploads/.../xxx.png\" }",
            next_step: "Use the full_url in your HTML, then call publish_page.",
          }, null, 2),
        }],
      };
    }
  );

  server.tool(
    "upload_dataset",
    "Attach a CSV/JSON data file to an already published page so its HTML can load and filter "
    + "the data at runtime. Inside the page, the injected `PageData` helper is available:\n"
    + "  const rows = await PageData.load('sales');\n"
    + "  const top = await PageData.query('sales', { where: { country: 'US', spend: { gte: 100 } }, "
    + "sort: 'spend', order: 'desc', limit: 20 });\n"
    + "Uploading the same `name` again replaces the previous file, so a dashboard can be refreshed "
    + "without editing its HTML.",
    {
      page_id: z.string().min(1).describe("The UUID of the target page (from publish_page or list_pages)"),
      filename: z.string().min(1).describe("File name with extension: .csv, .tsv, .json, .ndjson"),
      content: z.string().min(1).optional().describe("Raw file text (CSV rows or JSON). Use this for text data."),
      base64: z.string().min(1).optional().describe("Base64-encoded file content, as an alternative to `content`"),
      name: z.string().max(64).optional().describe("Reference name used in the page, e.g. 'sales'. Defaults to the file stem."),
    },
    async (args) => {
      if (!args.content && !args.base64) {
        return {
          content: [{ type: "text", text: JSON.stringify({ error: "missing_content", hint: "Provide `content` or `base64`." }) }],
        };
      }
      const buffer = args.base64
        ? Buffer.from(args.base64, "base64")
        : Buffer.from(args.content as string, "utf-8");
      if (buffer.length > 20 * 1024 * 1024) {
        return {
          content: [{ type: "text", text: JSON.stringify({ error: "dataset_too_large", max_mb: 20 }) }],
        };
      }
      const data = await uploadDataset(args.page_id, args.filename, buffer, args.name, getUser());
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "list_datasets",
    "List the data files attached to a page, including their reference name, columns, and row count.",
    {
      page_id: z.string().min(1).describe("The UUID of the page"),
    },
    async (args) => {
      const r = await axios.get(
        `${PUBLISHER_URL}/api/pages/${encodeURIComponent(args.page_id)}/datasets`,
        { headers: publisherHeaders(getUser()), timeout: 30_000 }
      );
      return { content: [{ type: "text", text: JSON.stringify(r.data, null, 2) }] };
    }
  );

  server.tool(
    "delete_dataset",
    "Delete a data file from a page.",
    {
      page_id: z.string().min(1).describe("The UUID of the page"),
      dataset_id: z.string().min(1).describe("The UUID of the dataset to delete"),
    },
    async (args) => {
      const r = await axios.delete(
        `${PUBLISHER_URL}/api/pages/${encodeURIComponent(args.page_id)}`
        + `/datasets/${encodeURIComponent(args.dataset_id)}`,
        { headers: publisherHeaders(getUser()), timeout: 30_000 }
      );
      return { content: [{ type: "text", text: JSON.stringify(r.data, null, 2) }] };
    }
  );

  server.tool(
    "list_pages",
    "List and search published pages.",
    {
      page: z.number().int().min(1).default(1).describe("Page number (1-based)"),
      page_size: z.number().int().min(1).max(100).default(20).describe("Results per page (1-100)"),
      q: z.string().max(100).optional().describe("Search keyword (matches owner, slug, title, submitter, description)"),
      scope: z.enum(["all", "mine", "unassigned"]).optional(),
    },
    async (args) => {
      const params: Record<string, string | number> = {
        page: args.page,
        page_size: args.page_size,
      };
      if (args.q) params.q = args.q;
      if (args.scope) params.scope = args.scope;

      const r = await axios.get(`${PUBLISHER_URL}/api/pages`, {
        params,
        headers: publisherHeaders(getUser()),
        timeout: 30_000,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(r.data, null, 2) }],
      };
    }
  );

  server.tool(
    "get_page_stats",
    "Return page statistics: total pages, top owners, top submitters.",
    {},
    async () => {
      const r = await axios.get(`${PUBLISHER_URL}/api/pages/stats`, {
        headers: publisherHeaders(getUser()),
        timeout: 30_000,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(r.data, null, 2) }],
      };
    }
  );

  server.tool(
    "get_page_detail",
    "Get full metadata for a specific page.",
    {
      owner: z.string().min(1).describe("Owner/group name"),
      slug: z.string().min(1).describe("Page slug"),
    },
    async (args) => {
      const r = await axios.get(
        `${PUBLISHER_URL}/api/pages/${encodeURIComponent(args.owner)}/${encodeURIComponent(args.slug)}`,
        { headers: publisherHeaders(getUser()), timeout: 30_000 }
      );
      return {
        content: [{ type: "text", text: JSON.stringify(r.data, null, 2) }],
      };
    }
  );

  server.tool(
    "delete_page",
    "Delete a published page by its ID.",
    {
      page_id: z.string().min(1).describe("The UUID of the page to delete"),
    },
    async (args) => {
      const r = await axios.delete(
        `${PUBLISHER_URL}/api/pages/${encodeURIComponent(args.page_id)}`,
        { headers: publisherHeaders(getUser()), timeout: 30_000 }
      );
      return {
        content: [{ type: "text", text: JSON.stringify(r.data, null, 2) }],
      };
    }
  );
}
