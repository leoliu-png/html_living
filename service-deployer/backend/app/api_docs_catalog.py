from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_CATALOG_PATH = Path(__file__).resolve().parent / "data" / "api_docs.json"


@lru_cache(maxsize=1)
def load_api_docs_catalog() -> dict[str, Any]:
    with _CATALOG_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("API docs catalog must be a JSON object.")
    endpoints = payload.get("endpoints")
    if not isinstance(endpoints, list):
        raise ValueError("API docs catalog must include an endpoints list.")
    return {
        "version": int(payload.get("version") or 1),
        "endpoints": endpoints,
    }


def api_docs_markdown() -> str:
    catalog = load_api_docs_catalog()
    lines = [
        "# Service Deployer API",
        "",
        f"Catalog version: {catalog['version']}",
        "",
        "Machine-readable JSON: `/api-docs.json`",
        "",
    ]
    for endpoint in catalog["endpoints"]:
        method = endpoint.get("method", "")
        path = endpoint.get("path", "")
        title = endpoint.get("title") or endpoint.get("summary") or endpoint.get("id")
        lines.extend(
            [
                f"## {method} {path}",
                "",
                f"**{title}**",
                "",
                str(endpoint.get("summary") or ""),
                "",
            ]
        )
        description = endpoint.get("description")
        if description:
            lines.extend([str(description), ""])
        auth = endpoint.get("auth")
        if auth:
            lines.append(f"- Auth: `{auth}`")
        params = endpoint.get("params") or []
        if params:
            lines.append("- Parameters:")
            for param in params:
                required = "required" if param.get("required") else "optional"
                location = param.get("in", "body")
                name = param.get("name", "")
                ptype = param.get("type", "string")
                desc = param.get("description") or ""
                lines.append(f"  - `{name}` ({location}, {ptype}, {required}) — {desc}")
        curl_example = endpoint.get("curlExample")
        if curl_example:
            lines.extend(["", "```bash", str(curl_example), "```"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"
