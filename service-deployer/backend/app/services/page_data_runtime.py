"""Client runtime injected into published pages that own datasets.

Gives dashboard HTML a tiny `PageData` helper so it can load an attached
CSV/JSON file and filter it — either server-side (`PageData.query`) or in the
browser (`PageData.filter`) — without bundling any third-party library.
"""

from __future__ import annotations

import json
from typing import Any

RUNTIME_JS = r"""
(function () {
  var el = document.getElementById("page-data-manifest");
  if (!el) return;
  var manifest;
  try {
    manifest = JSON.parse(el.textContent || "{}");
  } catch (err) {
    console.error("[PageData] invalid manifest", err);
    return;
  }

  var endpoint = manifest.endpoint || "";
  var token = manifest.token || "";
  var datasets = manifest.datasets || [];
  var cache = {};
  var MAX_PAGE = 50000;

  function byName(name) {
    for (var i = 0; i < datasets.length; i += 1) {
      if (datasets[i].name === name) return datasets[i];
    }
    return null;
  }

  function encodeWhere(where) {
    var out = [];
    if (!where) return out;
    if (Array.isArray(where)) return where.slice();
    Object.keys(where).forEach(function (column) {
      var condition = where[column];
      if (condition === null || condition === undefined) return;
      if (typeof condition === "object" && !Array.isArray(condition)) {
        Object.keys(condition).forEach(function (op) {
          var value = condition[op];
          if (value === null || value === undefined) return;
          out.push(column + ":" + op + ":" + (Array.isArray(value) ? value.join(",") : value));
        });
        return;
      }
      if (Array.isArray(condition)) {
        out.push(column + ":in:" + condition.join(","));
        return;
      }
      out.push(column + ":eq:" + condition);
    });
    return out;
  }

  function buildUrl(name, options) {
    var opts = options || {};
    var params = new URLSearchParams();
    if (token) params.set("k", token);
    encodeWhere(opts.where).forEach(function (expression) {
      params.append("where", expression);
    });
    if (opts.select) {
      params.set("select", Array.isArray(opts.select) ? opts.select.join(",") : opts.select);
    }
    if (opts.sort) params.set("sort", opts.sort);
    if (opts.order) params.set("order", opts.order);
    if (opts.limit !== undefined && opts.limit !== null) params.set("limit", String(opts.limit));
    if (opts.offset) params.set("offset", String(opts.offset));
    if (opts.format) params.set("format", opts.format);
    return endpoint + "/" + encodeURIComponent(name) + "?" + params.toString();
  }

  function request(name, options) {
    return fetch(buildUrl(name, options), { credentials: "omit" }).then(function (response) {
      if (!response.ok) {
        return response.text().then(function (text) {
          throw new Error("PageData " + response.status + ": " + text);
        });
      }
      return response.json();
    });
  }

  function query(name, options) {
    return request(name, options);
  }

  function load(name, options) {
    var opts = options || {};
    if (!opts.fresh && cache[name] && !opts.where && !opts.select && !opts.sort) {
      return Promise.resolve(cache[name]);
    }
    var rows = [];
    function fetchFrom(offset) {
      var pageOptions = Object.assign({}, opts, { limit: MAX_PAGE, offset: offset });
      delete pageOptions.fresh;
      return request(name, pageOptions).then(function (payload) {
        rows = rows.concat(payload.rows || []);
        var seen = offset + (payload.count || 0);
        if ((payload.count || 0) >= MAX_PAGE && seen < (payload.matched || 0)) {
          return fetchFrom(seen);
        }
        return rows;
      });
    }
    return fetchFrom(0).then(function (allRows) {
      var result = opts.parseNumbers ? allRows.map(coerceRow) : allRows;
      if (!opts.where && !opts.select && !opts.sort) cache[name] = result;
      return result;
    });
  }

  function coerceRow(row) {
    var out = {};
    Object.keys(row).forEach(function (key) {
      out[key] = toNumber(row[key], row[key]);
    });
    return out;
  }

  function toNumber(value, fallback) {
    if (typeof value === "number") return value;
    if (typeof value !== "string") return fallback;
    var text = value.trim().replace(/,/g, "");
    if (text === "" || isNaN(Number(text))) return fallback;
    return Number(text);
  }

  function cellText(value) {
    return value === null || value === undefined ? "" : String(value);
  }

  function compare(cell, value, op) {
    var left = toNumber(cell, null);
    var right = toNumber(value, null);
    if (left !== null && right !== null) {
      if (op === "gt") return left > right;
      if (op === "gte") return left >= right;
      if (op === "lt") return left < right;
      return left <= right;
    }
    var text = cellText(cell);
    var other = cellText(value);
    if (op === "gt") return text > other;
    if (op === "gte") return text >= other;
    if (op === "lt") return text < other;
    return text <= other;
  }

  function matches(row, expression) {
    var parts = String(expression).split(":");
    var column = parts.shift();
    var op = parts.length > 1 ? parts.shift() : "eq";
    var value = parts.join(":");
    var cell = row[column];
    var text = cellText(cell).toLowerCase();
    var needle = String(value).toLowerCase();
    if (op === "empty") return text.trim() === "";
    if (op === "notempty") return text.trim() !== "";
    if (op === "eq" || op === "ne") {
      var left = toNumber(cell, null);
      var right = toNumber(value, null);
      var equal = left !== null && right !== null ? left === right : text === needle;
      return op === "eq" ? equal : !equal;
    }
    if (op === "contains") return text.indexOf(needle) !== -1;
    if (op === "startswith") return text.indexOf(needle) === 0;
    if (op === "endswith") return text.lastIndexOf(needle) === text.length - needle.length;
    if (op === "in" || op === "nin") {
      var options = needle.split(",").map(function (item) { return item.trim(); });
      var found = options.indexOf(text) !== -1;
      return op === "in" ? found : !found;
    }
    return compare(cell, value, op);
  }

  function filter(rows, where) {
    var expressions = encodeWhere(where);
    if (!expressions.length) return rows.slice();
    return rows.filter(function (row) {
      return expressions.every(function (expression) { return matches(row, expression); });
    });
  }

  function sortRows(rows, column, order) {
    var direction = order === "desc" ? -1 : 1;
    return rows.slice().sort(function (a, b) {
      var left = toNumber(a[column], null);
      var right = toNumber(b[column], null);
      if (left !== null && right !== null) return (left - right) * direction;
      var leftText = cellText(a[column]).toLowerCase();
      var rightText = cellText(b[column]).toLowerCase();
      if (leftText === rightText) return 0;
      return (leftText < rightText ? -1 : 1) * direction;
    });
  }

  function unique(rows, column) {
    var seen = [];
    rows.forEach(function (row) {
      var value = cellText(row[column]);
      if (value !== "" && seen.indexOf(value) === -1) seen.push(value);
    });
    return seen;
  }

  window.PageData = {
    endpoint: endpoint,
    datasets: datasets,
    list: function () { return datasets.slice(); },
    describe: byName,
    url: buildUrl,
    load: load,
    query: query,
    filter: filter,
    sort: sortRows,
    unique: unique,
    toNumber: function (value) { return toNumber(value, null); },
    clearCache: function () { cache = {}; },
  };

  window.dispatchEvent(new CustomEvent("pagedata:ready", { detail: window.PageData }));
})();
"""


def build_page_data_runtime(*, endpoint: str, token: str, datasets: list[dict[str, Any]]) -> str:
    manifest = json.dumps(
        {"endpoint": endpoint, "token": token, "datasets": datasets},
        ensure_ascii=False,
        default=str,
    ).replace("</", "<\\/")
    return (
        '\n<script id="page-data-manifest" type="application/json">'
        f"{manifest}"
        "</script>\n<script>"
        f"{RUNTIME_JS}"
        "</script>\n"
    )


def inject_page_data_runtime(html: str, snippet: str) -> str:
    """Insert the runtime as early as possible so page scripts can use it."""

    lower_html = html.lower()
    head_index = lower_html.find("<head")
    if head_index != -1:
        close_index = lower_html.find(">", head_index)
        if close_index != -1:
            cut = close_index + 1
            return f"{html[:cut]}{snippet}{html[cut:]}"
    body_index = lower_html.find("<body")
    if body_index != -1:
        close_index = lower_html.find(">", body_index)
        if close_index != -1:
            cut = close_index + 1
            return f"{html[:cut]}{snippet}{html[cut:]}"
    return f"{snippet}{html}"
