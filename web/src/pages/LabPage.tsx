import { useState } from "react";
import { api, type Dataset, type LabResult } from "../api.ts";

const PRESETS = {
  number: {
    "Indian style": ["₹1,23,456.00", "1,00,000", "12,34,567.50", "2.5 Cr", "1.2 L", "3 lakh", "15K"],
    "International": ["$1,234.56", "100,000", "2.5M", "3 bn", "1.5342K", "500 USD"],
    "Negatives & %": ["(1,401.97)", "-500", "₹-500", "5%", "12.5 %", "0.10"],
    "Signs & forms": ["500-", "−500", "Rs. 1,500", "Rs.200", "1,00,000 INR", "(500-)", "-(500)"],
    "Currency clash": ["$500", "US$500", "C$500", "€40", "£40", "AUD 40", "¥500"],
    "Should be refused": ["abc", "#VALUE!", "inf", "1.234,56", "12,3", "1.2.3", "12345678901234567"],
  },
  date: {
    "Day/month order": ["05/03/2025", "03/05/2025", "25/03/2025", "12/12/2025", "05/03/26"],
    "Other styles": ["2025-05-04", "13-Feb-25", "13-Feb-2025", "2025-03-30 10:15:00", "2025-03-05T23:59"],
    "Time zones": ["2025-03-05T20:00:00Z", "2025-03-05T20:00:00+05:30", "2025-03-05 20:00:00 +0000", "2025-03-05 10:00 IST"],
    "Excel & Unix": ["45746", "45746.75", "99999", "1741132800", "20250305"],
    "Incomplete": ["05/03", "5 Mar", "Feb 2025", "03/2025"],
    "Should be refused": ["31/02/2025", "29/02/2025", "yesterday", "2025/13/01"],
  },
} as const;

type Kind = keyof typeof PRESETS;

export default function LabPage({ dataset }: { dataset: Dataset }) {
  const [kind, setKind] = useState<Kind>("number");
  const [text, setText] = useState<string>(PRESETS.number["Indian style"].join("\n"));
  const [ambiguous, setAmbiguous] = useState("use_locale");
  const [inRange, setInRange] = useState(true);
  const [results, setResults] = useState<LabResult[] | null>(null);
  const [info, setInfo] = useState("");
  const [error, setError] = useState("");

  async function test(values = text) {
    setError("");
    try {
      const list = values.split("\n").map((v) => v.trim()).filter(Boolean);
      const r = await api.lab(kind, {
        dataset_id: dataset.dataset_id,
        values: list,
        ambiguous_dates: kind === "date" ? ambiguous : undefined,
        ignore_date_range: kind === "date" ? !inRange : undefined,
      });
      setResults(r.results);
      setInfo(
        kind === "date"
          ? inRange
            ? `Locale ${r.locale}: dates read as ${r.date_order}. Date numbers (Excel, Unix, 20250305) are only accepted inside this dataset's range ${r.date_range?.join(" … ")}; untick the box to see how any value would be read.`
            : `Locale ${r.locale}: dates read as ${r.date_order}. Showing how values WOULD be read, ignoring the dataset's date range (the pipeline still applies it).`
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
          {kind === "date" && (
            <label className="row gap small">
              <input type="checkbox" checked={inRange} onChange={(e) => setInRange(e.target.checked)} />
              only accept dates inside this dataset's date range
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
