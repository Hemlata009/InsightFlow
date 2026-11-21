import { useEffect, useState } from "react";
import { api, type LogEntry } from "../api.ts";
import { Pager } from "./DataTable.tsx";

const PAGE = 25;

type Props = { datasetId: string; version: string; row: number | null; onClearRow: () => void };

export default function ChangeLog({ datasetId, version, row, onClearRow }: Props) {
  const [stage, setStage] = useState("");
  const [rule, setRule] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ total: number; entries: LogEntry[] } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => setOffset(0), [stage, rule, row, version]);
  useEffect(() => {
    api
      .log(datasetId, { offset, limit: PAGE, stage, rule, row })
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e) => setError(e.message));
  }, [datasetId, offset, stage, rule, row, version]);

  if (error) return <div className="alert">{error}</div>;

  return (
    <div>
      <div className="row gap">
        <select value={stage} onChange={(e) => setStage(e.target.value)}>
          <option value="">All stages</option>
          <option value="normalize">normalize</option>
          <option value="clean">clean</option>
          <option value="validate">validate</option>
          <option value="plugin">plugin</option>
        </select>
        <input placeholder="Filter by rule / check (e.g. magnitude, derived)" value={rule} onChange={(e) => setRule(e.target.value)} />
        {row != null && (
          <span className="chip">
            row {row}{" "}
            <button className="link" onClick={onClearRow}>
              ✕
            </button>
          </span>
        )}
        <span className="muted small">{data?.total.toLocaleString() ?? "…"} entries</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>stage</th>
              <th>kind</th>
              <th>row</th>
              <th>column</th>
              <th>what</th>
              <th>before</th>
              <th>after / detail</th>
            </tr>
          </thead>
          <tbody>
            {data?.entries.map((e, i) => {
              const what = String(e.rule ?? e.check ?? e.flag ?? e.reason ?? "");
              const before = e.old ?? e.value ?? "";
              const after = e.new ?? e.detail ?? e.severity ?? "";
              return (
                <tr key={i}>
                  <td className="muted small">{String(e.seq ?? "")}</td>
                  <td>
                    <span className={`stage ${e.stage}`}>{e.stage}</span>
                  </td>
                  <td className="small">{String(e.kind ?? "")}</td>
                  <td>{e.source_row}</td>
                  <td>{String(e.column ?? "")}</td>
                  <td className="mono">{what}</td>
                  <td className="mono">{fmt(before)}</td>
                  <td className="mono">{fmt(after)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {data && <Pager total={data.total} offset={offset} page={PAGE} onChange={setOffset} />}
    </div>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "∅";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
