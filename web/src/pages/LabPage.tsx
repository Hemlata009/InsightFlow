import { useState } from "react";
import { api, type Dataset, type LabResult } from "../api.ts";

const PRESETS = {
  number: {
    "Indian style": ["₹1,23,456.00", "1,00,000", "12,34,567.50", "2.5 Cr", "1.2 L", "3 lakh", "15K"],
    "International": ["$1,234.56", "100,000", "2.5M", "3 bn", "1.5342K", "500 USD"],
    "Negatives & %": ["(1,401.97)", "-500", "₹-500", "5%", "12.5 %", "0.10"],
    "Should be refused": ["abc", "#VALUE!", "inf", "1.234,56", "12,3", "$500 in India", "1.2.3", "€40"],
  },
  date: {
    "Day/month order": ["05/03/2025", "03/05/2025", "25/03/2025", "12/12/2025"],
    "Other styles": ["2025-05-04", "13-Feb-25", "13-Feb-2025", "2025-03-30 10:15:00"],
    "Excel numbers": ["45746", "45658", "99999", "123"],
    "Should be refused": ["31/02/2025", "yesterday", "2025/13/01", "Feb 2025"],
  },
} as const;

type Kind = keyof typeof PRESETS;

export default function LabPage({ dataset }: { dataset: Dataset }) {
  const [kind, setKind] = useState<Kind>("number");
  const [text, setText] = useState<string>(PRESETS.number["Indian style"].join("\n"));
  const [ambiguous, setAmbiguous] = useState("use_locale");
  const [results, setResults] = useState<LabResult[] | null>(null);
  const [info, setInfo] = useState("");
  const [error, setError] = useState("");

  async function test(values = text) {
    setError("");
    try {
      const list = values.split("\n").map((v) => v.trim()).filter(Boolean);
      const r = await api.lab(kind, { dataset_id: dataset.dataset_id, values: list, ambiguous_dates: kind === "date" ? ambiguous : undefined });
      setResults(r.results);
      setInfo(
        kind === "date"
          ? `Locale ${r.locale}: dates read as ${r.date_order}; Excel numbers only accepted inside ${r.date_range?.join(" … ")}`
          : `Locale ${r.locale}: currency ${dataset.currency}`,
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function preset(values: readonly string[]) {
    const t = values.join("\n");
    setText(t);
    test(t);
  }

  return (
    <div className="stack">
      <section className="card">
        <h2>Try any value, see exactly how InsightFlow reads it</h2>
        <p className="muted small">
          Uses the same code as the pipeline, with the <b>{dataset.dataset_id}</b> rule book ({dataset.locale}). Switch the dataset at the top to compare
          India vs US. One value per line.
        </p>
        <div className="row gap">
          <button className={kind === "number" ? "subtab active" : "subtab"} onClick={() => { setKind("number"); setResults(null); setText(PRESETS.number["Indian style"].join("\n")); }}>
            Numbers & money
          </button>
          <button className={kind === "date" ? "subtab active" : "subtab"} onClick={() => { setKind("date"); setResults(null); setText(PRESETS.date["Day/month order"].join("\n")); }}>
            Dates
          </button>
          {kind === "date" && (
            <label className="row gap small">
              Unclear day/month:
              <select value={ambiguous} onChange={(e) => setAmbiguous(e.target.value)}>
                <option value="use_locale">read the locale way</option>
                <option value="quarantine">refuse (set aside)</option>
              </select>
            </label>
          )}
        </div>
        <div className="row gap wrap">
          {Object.entries(PRESETS[kind]).map(([name, values]) => (
            <button key={name} className="chip" onClick={() => preset(values)}>
              {name}
            </button>
          ))}
        </div>
        <div className="lab">
          <textarea rows={10} value={text} onChange={(e) => setText(e.target.value)} />
          <div>
            <button className="primary" onClick={() => test()}>
              Test these values
            </button>
            {info && <p className="muted small">{info}</p>}
          </div>
        </div>
        {error && <div className="alert error">{error}</div>}
      </section>

      {results && (
        <section className="card">
          <table>
            <thead>
              <tr>
                <th>you typed</th>
                <th>InsightFlow reads it as</th>
                <th>how / why not</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r, i) => (
                <tr key={i} className={r.ok ? "ok" : "fail"}>
                  <td className="mono">{r.input}</td>
                  <td className="mono">{r.ok ? (typeof r.value === "number" ? r.value.toLocaleString("en-US", { maximumFractionDigits: 10 }) : r.value) : "✗ not converted"}</td>
                  <td className="mono">{r.ok ? r.how : r.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
