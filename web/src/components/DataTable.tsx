import { useEffect, useState } from "react";
import { api, type Table } from "../api.ts";

type Props = {
  datasetId: string;
  kind: "cleaned" | "quarantine" | "duplicates";
  version: string; // changes after every run -> reload
  onTraceRow?: (row: number) => void;
};

const PAGE = 25;

export default function DataTable({ datasetId, kind, version, onTraceRow }: Props) {
  const [data, setData] = useState<Table | null>(null);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  useEffect(() => setOffset(0), [query, kind, version]);
  useEffect(() => {
    api
      .table(datasetId, kind, offset, PAGE, query)
      .then((t) => {
        setData(t);
        setError("");
      })
      .catch((e) => setError(e.message));
  }, [datasetId, kind, offset, query, version]);

  if (error) return <div className="alert">{error}</div>;
  if (!data) return <p className="muted">Loading…</p>;

  const highlight = (col: string) => (col === "_reasons" || col === "duplicate_of" ? "reason" : "");

  return (
    <div>
      <form
        className="row gap"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(search);
        }}
      >
        <input placeholder="Search any column…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <button type="submit">Search</button>
        <span className="muted small">
          {data.total.toLocaleString()} row(s){query && ` matching “${query}”`}
          {onTraceRow && " · click a row number to trace every change made to it"}
        </span>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {data.columns.map((c) => (
                <th key={c} className={highlight(c)}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r, i) => (
              <tr key={i}>
                {data.columns.map((c) => (
                  <td key={c} className={highlight(c)}>
                    {c === "source_row" && onTraceRow ? (
                      <button className="link" onClick={() => onTraceRow(Number(r[c]))}>
                        {r[c]}
                      </button>
                    ) : r[c] === "" ? (
                      <span className="blank">blank</span>
                    ) : (
                      r[c]
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager total={data.total} offset={offset} page={PAGE} onChange={setOffset} />
    </div>
  );
}

export function Pager({ total, offset, page, onChange }: { total: number; offset: number; page: number; onChange: (o: number) => void }) {
  if (total <= page) return null;
  return (
    <div className="row gap pager">
      <button disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - page))}>
        ← Prev
      </button>
      <span className="muted small">
        {offset + 1}–{Math.min(offset + page, total)} of {total.toLocaleString()}
      </span>
      <button disabled={offset + page >= total} onClick={() => onChange(offset + page)}>
        Next →
      </button>
    </div>
  );
}
