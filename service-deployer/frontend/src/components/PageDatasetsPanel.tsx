import { useCallback, useEffect, useRef, useState } from "react";
import { Clipboard, Database, Loader2, Trash2, Upload } from "lucide-react";
import type { Language } from "../content";
import type { ConsoleApi } from "./ConsoleRoot";
import "./PageDatasetsPanel.css";

export type PageDataset = {
  id: string;
  page_id: string;
  name: string;
  filename: string;
  format: string;
  size_bytes: number;
  row_count: number;
  columns: string[];
  data_url: string;
  created_at: string;
  updated_at: string;
};

type DatasetListData = {
  items: PageDataset[];
  data_endpoint: string;
  data_token: string | null;
  usage: string;
};

const copy = {
  zh: {
    title: "数据文件",
    summary: "上传 CSV / JSON 数据文件，页面 HTML 里用 PageData 读取和过滤。",
    upload: "上传数据文件",
    uploading: "上传中...",
    empty: "还没有数据文件。上传 CSV / JSON 后，页面就能动态加载和过滤数据。",
    rows: "行",
    columns: "列",
    replaceHint: "同名文件会覆盖旧版本。",
    copySnippet: "复制引用代码",
    copyUrl: "复制数据地址",
    copied: "已复制",
    delete: "删除",
    deleting: "删除中...",
    deleteConfirm: "删除这个数据文件？",
    cancel: "取消",
    loadFailed: "数据文件加载失败",
    uploadFailed: "上传失败",
    allowed: "支持 .csv .tsv .json .ndjson，单个文件最大 20 MB",
  },
  en: {
    title: "Data files",
    summary: "Upload CSV / JSON files and read them from your page HTML with PageData.",
    upload: "Upload data file",
    uploading: "Uploading...",
    empty: "No data files yet. Upload a CSV / JSON file to load and filter data from the page.",
    rows: "rows",
    columns: "columns",
    replaceHint: "Uploading the same name replaces the previous version.",
    copySnippet: "Copy snippet",
    copyUrl: "Copy data URL",
    copied: "Copied",
    delete: "Delete",
    deleting: "Deleting...",
    deleteConfirm: "Delete this data file?",
    cancel: "Cancel",
    loadFailed: "Failed to load data files",
    uploadFailed: "Upload failed",
    allowed: "Accepts .csv .tsv .json .ndjson, up to 20 MB per file",
  },
} satisfies Record<Language, Record<string, string>>;

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function snippetFor(dataset: PageDataset) {
  const sample = dataset.columns[0] ?? "column";
  return [
    `const rows = await PageData.load(${JSON.stringify(dataset.name)});`,
    `const filtered = await PageData.query(${JSON.stringify(dataset.name)}, {`,
    `  where: { ${JSON.stringify(sample)}: "value" },`,
    `  sort: ${JSON.stringify(sample)},`,
    "  order: \"desc\",",
    "  limit: 100,",
    "});",
  ].join("\n");
}

type Props = {
  language: Language;
  api: ConsoleApi;
  pageId: string;
  canManage: boolean;
};

export function PageDatasetsPanel({ language, api, pageId, canManage }: Props) {
  const t = copy[language] as typeof copy.zh;
  const [datasets, setDatasets] = useState<PageDataset[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.fetchApi<DatasetListData>(`/api/pages/${pageId}/datasets`);
      setDatasets(data.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t.loadFailed);
    } finally {
      setIsLoading(false);
    }
  }, [api, pageId, t.loadFailed]);

  useEffect(() => {
    if (!canManage) {
      setDatasets([]);
      return;
    }
    void load();
  }, [canManage, load]);

  useEffect(() => {
    if (!notice) return;
    const id = window.setTimeout(() => setNotice(null), 2000);
    return () => window.clearTimeout(id);
  }, [notice]);

  const handleUpload = async (file: File) => {
    setIsUploading(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const suffix = api.token ? `?token=${encodeURIComponent(api.token)}` : "";
      const response = await fetch(`/api/pages/${pageId}/datasets${suffix}`, {
        method: "POST",
        body,
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(payload?.detail || payload?.msg || `HTTP ${response.status}`);
      }
      await load();
      setNotice(payload?.data?.name ? `${payload.data.name} · ${payload.data.row_count} ${t.rows}` : null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t.uploadFailed);
    } finally {
      setIsUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const handleDelete = async (datasetId: string) => {
    setDeletingId(datasetId);
    try {
      await api.fetchApi<{ id: string }>(`/api/pages/${pageId}/datasets/${datasetId}`, "DELETE");
      setDatasets((current) => current.filter((item) => item.id !== datasetId));
      setDeleteId(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  };

  const copyText = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setNotice(t.copied);
    } catch {
      setError("Clipboard unavailable");
    }
  };

  if (!canManage) return null;

  return (
    <div className="dataset-panel">
      <div className="dataset-header">
        <div>
          <strong><Database size={14} /> {t.title}</strong>
          <p>{t.summary}</p>
        </div>
        <button
          type="button"
          className="primary-btn"
          disabled={isUploading}
          onClick={() => fileInput.current?.click()}
        >
          {isUploading ? <Loader2 size={14} className="spin" /> : <Upload size={14} />}
          {isUploading ? t.uploading : t.upload}
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".csv,.tsv,.json,.ndjson,.jsonl"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void handleUpload(file);
          }}
        />
      </div>

      <p className="dataset-hint">{t.allowed} · {t.replaceHint}</p>
      {error && <p className="dataset-error">{error}</p>}
      {notice && <p className="dataset-notice">{notice}</p>}
      {isLoading && <p className="dataset-hint">…</p>}

      {!isLoading && datasets.length === 0 && <p className="dataset-empty">{t.empty}</p>}

      <ul className="dataset-list">
        {datasets.map((dataset) => (
          <li key={dataset.id}>
            <div className="dataset-row">
              <code>{dataset.name}</code>
              <span className="dataset-meta">
                {dataset.format.toUpperCase()} · {dataset.row_count} {t.rows} ·{" "}
                {dataset.columns.length} {t.columns} · {formatSize(dataset.size_bytes)}
              </span>
            </div>
            <div className="dataset-columns">{dataset.columns.join(", ")}</div>
            <div className="dataset-actions">
              <button type="button" onClick={() => void copyText(snippetFor(dataset))}>
                <Clipboard size={13} /> {t.copySnippet}
              </button>
              <button type="button" onClick={() => void copyText(dataset.data_url)}>
                <Clipboard size={13} /> {t.copyUrl}
              </button>
              {deleteId === dataset.id ? (
                <>
                  <button
                    type="button"
                    className="delete-btn danger"
                    disabled={deletingId === dataset.id}
                    onClick={() => void handleDelete(dataset.id)}
                  >
                    {deletingId === dataset.id ? t.deleting : t.deleteConfirm}
                  </button>
                  <button type="button" onClick={() => setDeleteId(null)}>{t.cancel}</button>
                </>
              ) : (
                <button type="button" className="delete-btn" onClick={() => setDeleteId(dataset.id)}>
                  <Trash2 size={13} /> {t.delete}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
