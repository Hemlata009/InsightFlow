// Thin client for the local InsightFlow API (see src/insightflow/api/app.py).

export type Dataset = {
  dataset_id: string;
  domain: string;
  locale: string;
  currency: string;
  date_order: string;
  description: string;
  samples: string[];
  has_run: boolean;
};

export type RunResult = {
  dataset_id: string;
  run_id: string;
  status: "completed" | "completed_with_warnings" | "needs_review" | "failed";
  source_file: string;
  rows_input: number;
  rows_output: number;
  rows_quarantined: number;
  rows_duplicates_removed: number;
  rows_flagged: number;
  transformations_applied: Record<string, number>;
  validation_errors: string[];
  warnings: string[];
  error: { code: string; message: string } | null;
  output_paths: Record<string, string>;
};

export type Finding = { severity: "error" | "warning" | "info"; column: string | null; message: string };

export type ProfileResponse =
  | { ok: true; read_warnings: string[]; report: { rows: number; column_count: number; findings: Finding[] } }
  | { ok: false; error: { code: string; message: string } };

export type Table = { total: number; offset: number; columns: string[]; rows: Record<string, string>[] };
export type LogEntry = Record<string, unknown> & { stage: string; source_row: number };
export type LabResult = { input: string; ok: boolean; value?: number | string | null; how?: string | null; reason?: string | null };

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body?.detail ?? `${r.status} ${r.statusText}`);
  return body as T;
}

export type Source = { sample?: string; file?: File | null };

function form(datasetId: string, src: Source): FormData {
  const f = new FormData();
  f.append("dataset_id", datasetId);
  if (src.file) f.append("file", src.file);
  else if (src.sample) f.append("sample", src.sample);
  return f;
}

export const api = {
  datasets: () => req<Dataset[]>("/api/datasets"),
  rules: (id: string) => req<any>(`/api/datasets/${id}/rules`),
  profile: (id: string, src: Source) => req<ProfileResponse>("/api/profile", { method: "POST", body: form(id, src) }),
  run: (id: string, src: Source) => req<RunResult>("/api/run", { method: "POST", body: form(id, src) }),
  latest: (id: string) => req<{ metadata: { result: RunResult }; quality_report: any }>(`/api/runs/${id}/latest`),
  table: (id: string, kind: string, offset: number, limit: number, search: string) =>
    req<Table>(`/api/runs/${id}/table/${kind}?offset=${offset}&limit=${limit}&search=${encodeURIComponent(search)}`),
  log: (id: string, p: { offset: number; limit: number; stage: string; rule: string; row?: number | null }) =>
    req<{ total: number; entries: LogEntry[] }>(
      `/api/runs/${id}/log?offset=${p.offset}&limit=${p.limit}&stage=${p.stage}&rule=${encodeURIComponent(p.rule)}` +
        (p.row != null ? `&row=${p.row}` : ""),
    ),
  lab: (kind: "number" | "date", body: { dataset_id: string; values: string[]; ambiguous_dates?: string }) =>
    req<{ locale: string; date_order?: string; date_range?: string[]; results: LabResult[] }>(`/api/lab/${kind}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};
