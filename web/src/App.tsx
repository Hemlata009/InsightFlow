import { useEffect, useState } from "react";
import { api, type Dataset } from "./api.ts";
import RunPage from "./pages/RunPage.tsx";
import LabPage from "./pages/LabPage.tsx";
import RulesPage from "./pages/RulesPage.tsx";

const TABS = [
  { id: "run", label: "Run pipeline" },
  { id: "lab", label: "Edge-case lab" },
  { id: "rules", label: "Rule book" },
] as const;
type Tab = (typeof TABS)[number]["id"];

export default function App() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [tab, setTab] = useState<Tab>("run");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .datasets()
      .then((d) => {
        setDatasets(d);
        setDatasetId(d.find((x) => x.samples.length)?.dataset_id ?? d[0]?.dataset_id ?? "");
      })
      .catch((e) => setError(`Cannot reach the InsightFlow API: ${e.message}. Is it running?`));
  }, []);

  const ds = datasets.find((d) => d.dataset_id === datasetId);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">◆</span> InsightFlow <span className="muted">Explorer · Phase 1</span>
        </div>
        <label className="dataset-picker">
          Dataset
          <select value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
            {datasets.map((d) => (
              <option key={d.dataset_id} value={d.dataset_id}>
                {d.dataset_id} · {d.locale} · {d.currency}
              </option>
            ))}
          </select>
        </label>
      </header>

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "tab active" : "tab"} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      <main>
        {error && <div className="alert error">{error}</div>}
        {ds && <p className="muted small">{ds.description} · dates read as {ds.date_order}</p>}
        {ds && tab === "run" && <RunPage key={ds.dataset_id} dataset={ds} />}
        {ds && tab === "lab" && <LabPage key={ds.dataset_id} dataset={ds} />}
        {ds && tab === "rules" && <RulesPage key={ds.dataset_id} dataset={ds} />}
      </main>
    </div>
  );
}
