import { useEffect, useState } from "react";
import { api, type Dataset, type Finding, type ProfileResponse, type RunResult } from "../api.ts";
import DataTable from "../components/DataTable.tsx";
import ChangeLog from "../components/ChangeLog.tsx";

type View = "cleaned" | "quarantine" | "duplicates" | "log" | "health";

const STATUS_TEXT: Record<RunResult["status"], string> = {
  completed: "Completed",
  completed_with_warnings: "Completed with warnings",
  needs_review: "Needs review",
  failed: "Failed",
};

export default function RunPage({ dataset }: { dataset: Dataset }) {
  const [mode, setMode] = useState<"sample" | "upload">(dataset.samples.length ? "sample" : "upload");
  const [sample, setSample] = useState(dataset.samples.find((s) => s.includes("messy")) ?? dataset.samples[0] ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState<"" | "run" | "profile">("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<RunResult | null>(null);
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [readWarnings, setReadWarnings] = useState<string[]>([]);
  const [view, setView] = useState<View>("quarantine");
  const [traceRow, setTraceRow] = useState<number | null>(null);

  // Show the last run of this dataset, if any
  useEffect(() => {
    if (!dataset.has_run) return;
    api
      .latest(dataset.dataset_id)
      .then((d) => {
        setResult(d.metadata.result);
        setFindings(d.quality_report?.before?.findings ?? null);
      })
      .catch(() => undefined);
  }, [dataset]);

  const source = mode === "sample" ? { sample } : { file };
  const ready = mode === "sample" ? !!sample : !!file;

  async function go(kind: "run" | "profile") {
    setBusy(kind);
    setError("");
    try {
      if (kind === "run") {
        const r = await api.run(dataset.dataset_id, source);
        setResult(r);
        setTraceRow(null);
        if (r.status !== "failed") {
          const latest = await api.latest(dataset.dataset_id);
          setFindings(latest.quality_report?.before?.findings ?? null);
          setView(r.rows_quarantined ? "quarantine" : "cleaned");
        }
      } else {
        const p: ProfileResponse = await api.profile(dataset.dataset_id, source);
        if (!p.ok) setError(`[${p.error.code}] ${p.error.message}`);
        else {
          setFindings(p.report.findings);
          setReadWarnings(p.read_warnings);
          setView("health");
        }
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  const hasTables = result && result.status !== "failed";

  return (
    <div className="stack">
      <section className="card">
        <h2>1 · Choose a file</h2>
        <div className="row gap">
          <label className="radio">
            <input type="radio" checked={mode === "sample"} onChange={() => setMode("sample")} disabled={!dataset.samples.length} />
            Sample file
          </label>
          <select value={sample} onChange={(e) => setSample(e.target.value)} disabled={mode !== "sample"}>
            {dataset.samples.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <label className="radio">
            <input type="radio" checked={mode === "upload"} onChange={() => setMode("upload")} />
            Upload my own (.csv / .xlsx)
          </label>
          <input type="file" accept=".csv,.xlsx" disabled={mode !== "upload"} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
        {!dataset.samples.length && (
          <p className="muted small">
            No sample files for {dataset.dataset_id} yet. For SALES_001 run: <code>python -m scripts.fetch_superstore</code> then{" "}
            <code>python -m scripts.sample_data</code>.
          </p>
        )}
        <h2>2 · Go</h2>
        <div className="row gap">
          <button className="primary" disabled={!ready || !!busy} onClick={() => go("run")}>
            {busy === "run" ? "Running…" : "▶ Run full pipeline"}
          </button>
          <button disabled={!ready || !!busy} onClick={() => go("profile")}>
            {busy === "profile" ? "Checking…" : "Health check only (changes nothing)"}
          </button>
        </div>
        {error && <div className="alert error">{error}</div>}
      </section>

      {result && <Summary r={result} />}

      {(hasTables || findings) && (
        <section className="card">
          <nav className="subtabs">
            {hasTables && (
              <>
                <Sub v="quarantine" cur={view} set={setView} label={`Set aside (${result!.rows_quarantined})`} />
                <Sub v="cleaned" cur={view} set={setView} label={`Clean data (${result!.rows_output})`} />
                <Sub v="duplicates" cur={view} set={setView} label={`Duplicates removed (${result!.rows_duplicates_removed})`} />
                <Sub v="log" cur={view} set={setView} label="Change log" />
              </>
            )}
            {findings && <Sub v="health" cur={view} set={setView} label={`Health check (${findings.length})`} />}
          </nav>
          {hasTables && (view === "cleaned" || view === "quarantine" || view === "duplicates") && (
            <DataTable
              datasetId={dataset.dataset_id}
              kind={view}
              version={result!.run_id}
              onTraceRow={(row) => {
                setTraceRow(row);
                setView("log");
              }}
            />
          )}
          {hasTables && view === "log" && (
            <ChangeLog datasetId={dataset.dataset_id} version={result!.run_id} row={traceRow} onClearRow={() => setTraceRow(null)} />
          )}
          {view === "health" && findings && <Findings items={findings} readWarnings={readWarnings} />}
        </section>
      )}
    </div>
  );
}

function Sub({ v, cur, set, label }: { v: View; cur: View; set: (v: View) => void; label: string }) {
  return (
    <button className={cur === v ? "subtab active" : "subtab"} onClick={() => set(v)}>
      {label}
    </button>
  );
}

function Summary({ r }: { r: RunResult }) {
  const changes = Object.entries(r.transformations_applied).sort((a, b) => b[1] - a[1]);
  return (
    <section className="card">
      <div className="row gap between">
        <h2>Result</h2>
        <span className={`badge ${r.status}`}>{STATUS_TEXT[r.status]}</span>
      </div>
      {r.error && (
        <div className="alert error">
          [{r.error.code}] {r.error.message}
        </div>
      )}
      <div className="stats">
        <Stat label="Rows in" value={r.rows_input} />
        <Stat label="Clean rows out" value={r.rows_output} tone="good" />
        <Stat label="Set aside" value={r.rows_quarantined} tone={r.rows_quarantined ? "bad" : undefined} />
        <Stat label="Duplicates removed" value={r.rows_duplicates_removed} />
        <Stat label="Kept but flagged" value={r.rows_flagged} tone={r.rows_flagged ? "warn" : undefined} />
      </div>
      <div className="grid2">
        <div>
          <h3>What was changed</h3>
          {changes.length ? (
            <table className="compact">
              <tbody>
                {changes.map(([k, v]) => (
                  <tr key={k}>
                    <td className="mono">{k}</td>
                    <td className="num">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">Nothing needed changing.</p>
          )}
        </div>
        <div>
          <h3>Checks that failed</h3>
          {r.validation_errors.length ? (
            <ul className="list">
              {r.validation_errors.map((v) => (
                <li key={v} className="mono">
                  {v}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">All checks passed.</p>
          )}
          {r.warnings.length > 0 && (
            <>
              <h3>Warnings</h3>
              <ul className="list">
                {r.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
      {r.notes && r.notes.length > 0 && (
        <>
          <h3>Notes (information only, don't affect the status)</h3>
          <ul className="list muted">
            {r.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </>
      )}
      <p className="muted small">Run {r.run_id} · input {r.source_file}</p>
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "good" | "bad" | "warn" }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <div className="stat-value">{value.toLocaleString()}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function Findings({ items, readWarnings }: { items: Finding[]; readWarnings: string[] }) {
  const order = { error: 0, warning: 1, info: 2 };
  return (
    <div>
      {readWarnings.length > 0 && (
        <ul className="list">
          {readWarnings.map((w) => (
            <li key={w} className="muted">
              reader: {w}
            </li>
          ))}
        </ul>
      )}
      <table>
        <thead>
          <tr>
            <th>severity</th>
            <th>column</th>
            <th>finding (before any change)</th>
          </tr>
        </thead>
        <tbody>
          {[...items]
            .sort((a, b) => order[a.severity] - order[b.severity])
            .map((f, i) => (
              <tr key={i}>
                <td>
                  <span className={`sev ${f.severity}`}>{f.severity}</span>
                </td>
                <td>{f.column ?? "—"}</td>
                <td>{f.message}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}
