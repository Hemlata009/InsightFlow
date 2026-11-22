import { useEffect, useState } from "react";
import { api, type Dataset } from "../api.ts";
import MissingValues, { describeMissing } from "../components/MissingValues.tsx";

export default function RulesPage({ dataset }: { dataset: Dataset }) {
  const [cfg, setCfg] = useState<any>(null);
  const [saved, setSaved] = useState<Record<string, any>>({});
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);

  useEffect(() => {
    api.rules(dataset.dataset_id).then(setCfg).catch((e) => setError(e.message));
    api.choices(dataset.dataset_id).then((c) => setSaved(c.columns)).catch(() => setSaved({}));
  }, [dataset, version]);

  if (error) return <div className="alert error">{error}</div>;
  if (!cfg) return <p className="muted">Loading…</p>;

  const cols = Object.entries(cfg.columns) as [string, any][];
  const rules = Object.entries(cfg.rules) as [string, any][];
  const range = (c: any) => (c.min == null && c.max == null ? "" : `${c.min ?? "−∞"} … ${c.max ?? "+∞"}`);

  return (
    <div className="stack">
      <section className="card">
        <h2>Rule book for {cfg.dataset_id}</h2>
        <p className="muted small">
          The rule book in <code>configs/</code>: default.yaml → domains/{cfg.domain}.yaml → datasets/{cfg.dataset_id}.yaml → choices/{cfg.dataset_id}.yaml
          (missing-value choices saved below). Other rules: edit the YAML files. Changes are used from the next run.
        </p>
        <div className="stats">
          <Info label="Locale" value={`${cfg.locale_name} · ${cfg.locale.description}`} />
          <Info label="Currency" value={`${cfg.locale.currency_symbol} ${cfg.locale.currency_code}`} />
          <Info label="Dates" value={`${cfg.locale.date_order} (${cfg.locale.date_format})`} />
          <Info label="Date range" value={`${cfg.date_range.min} … ${cfg.date_range.max}`} />
          <Info label="Number style" value={cfg.locale.grouping} />
          <Info label="Short forms" value={Object.keys(cfg.locale.magnitudes).join(", ")} />
        </div>
      </section>

      <MissingValues datasetId={dataset.dataset_id} cfg={cfg} saved={saved} onSaved={() => setVersion((v) => v + 1)} />

      <section className="card">
        <h3>Columns</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>column</th>
                <th>type</th>
                <th>required</th>
                <th>if missing</th>
                <th>valid range</th>
                <th>allowed values</th>
                <th>other header names accepted</th>
              </tr>
            </thead>
            <tbody>
              {cols.map(([name, c]) => (
                <tr key={name} title={c.description}>
                  <td>
                    <b>{name}</b>
                    <div className="muted small">{c.description}</div>
                  </td>
                  <td>{c.type}</td>
                  <td>{c.required ? "yes" : "no"}</td>
                  <td>
                    {describeMissing(c)}
                    {name in saved && <span className="chip">your choice</span>}
                    {c.money && <div className="muted small">money{c.allow_estimates ? " · guesses allowed" : ""}</div>}
                  </td>
                  <td className="mono">{range(c)}</td>
                  <td>{c.allowed_values?.join(", ") ?? ""}</td>
                  <td className="muted small">{c.aliases.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card grid2">
        <div>
          <h3>Business rules</h3>
          <table className="compact">
            <tbody>
              {rules.map(([id, r]) => (
                <tr key={id}>
                  <td>
                    <b>{id}</b>
                    <div className="muted small">{r.description}</div>
                  </td>
                  <td>
                    <span className={`sev ${r.severity === "quarantine" ? "error" : "warning"}`}>{r.severity}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Business switches</h3>
          <p className="small">
            Returns allowed: <b>{cfg.business.returns_allowed ? "yes" : "no"}</b>
            {cfg.business.returns_column && (
              <span className="muted"> (enforced by {cfg.business.returns_column} min = {String(cfg.columns[cfg.business.returns_column]?.min ?? "none")})</span>
            )}
            <br />
            Losses (negative profit) allowed: <b>{cfg.business.negative_profit_allowed ? "yes" : "no"}</b>
            {cfg.business.profit_column && (
              <span className="muted"> (enforced by {cfg.business.profit_column} min = {String(cfg.columns[cfg.business.profit_column]?.min ?? "none")})</span>
            )}
            <br />
            <span className="muted">The rule book is refused if a switch and its limit disagree.</span>
          </p>
          <h3>Duplicates</h3>
          <p className="small">
            Exact copies: <b>{cfg.duplicates.exact}</b> · business key: <b>{cfg.duplicates.key.join(" + ")}</b> · same key, different values:{" "}
            <b>{cfg.duplicates.key_conflict}</b>
          </p>
        </div>
        <div>
          <h3>General policies</h3>
          <table className="compact">
            <tbody>
              {Object.entries(cfg.policies).map(([k, v]) => (
                <tr key={k}>
                  <td className="mono">{k}</td>
                  <td className="mono small">{Array.isArray(v) ? v.map((x) => JSON.stringify(x)).join(" ") : String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="info-value">{value}</div>
    </div>
  );
}
