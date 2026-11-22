import { useState } from "react";
import { api } from "../api.ts";

// Missing-value choices per column. Saved into the rule book (configs/choices/<ID>.yaml, layer 4);
// the server checks the WHOLE rule book before saving, so an invalid choice is refused with a reason.

export const POLICY_TEXT: Record<string, string> = {
  quarantine: "Set the row aside",
  keep_and_flag: "Leave blank (NA) and mark",
  fill_value: "Fill with a fixed value (0, a word, any value)",
  impute: "Fill with the mean / median / mode",
  fill_down: "Copy from the row above (fill down)",
  fill_up: "Copy from the row below (fill up)",
  fill_from_group: "Copy from rows of the same group",
  derive: "Work it out from the formula",
  placeholder: "Temporary label (e.g. MISSING-ROW-49)",
};

const ESTIMATING = ["impute", "fill_down", "fill_up"];
const NUMERIC = ["integer", "float"];

/** One line in plain words: what happens to a blank cell in this column. */
export function describeMissing(c: any): string {
  const p = c.missing_policy;
  const group = c.group_by?.length ? ` with the same ${c.group_by.join(" + ")}` : "";
  const limit = c.fill_limit ? `, at most ${c.fill_limit} row(s) away` : "";
  switch (p) {
    case "fill_value":
      return `Fill with ${JSON.stringify(c.fill_value)}`;
    case "impute":
      return `Fill with the ${c.impute_method}${c.impute_method === "mean" ? ` (refused if skew > ${c.max_skew_for_mean})` : ""}`;
    case "fill_down":
      return `Copy from the row above${group}${limit}`;
    case "fill_up":
      return `Copy from the row below${group}${limit}`;
    case "fill_from_group":
      return `Copy from rows${group} (only if they agree)`;
    case "derive":
      return `Work out = ${c.derive_expression}`;
    case "placeholder":
      return `Temporary label ${c.placeholder}`;
    default:
      return POLICY_TEXT[p] ?? p;
  }
}

export default function MissingValues({
  datasetId,
  cfg,
  saved,
  onSaved,
}: {
  datasetId: string;
  cfg: any;
  saved: Record<string, any>;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const cols = Object.entries(cfg.columns) as [string, any][];
  return (
    <section className="card">
      <h3>Missing values: what to do with blank cells</h3>
      <p className="muted small">
        Pick a choice per column. It is saved into the rule book (<code>configs/choices/{datasetId}.yaml</code>, the last layer) and used from the next
        run. Every guessed value (mean/median/mode, fill down/up) is written in the change log and marked for review. Money columns are only guessed if
        you allow it (business rule 9).
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>column</th>
              <th>if a cell is blank</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {cols.map(([name, c]) => (
              <Row
                key={name}
                name={name}
                c={c}
                cfg={cfg}
                datasetId={datasetId}
                isSaved={name in saved}
                open={open === name}
                setOpen={(v) => setOpen(v ? name : null)}
                onSaved={onSaved}
              />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Row(props: {
  name: string;
  c: any;
  cfg: any;
  datasetId: string;
  isSaved: boolean;
  open: boolean;
  setOpen: (v: boolean) => void;
  onSaved: () => void;
}) {
  const { name, c, cfg, datasetId, isSaved, open, setOpen, onSaved } = props;
  return (
    <>
      <tr>
        <td>
          <b>{name}</b>
          <div className="muted small">
            {c.type}
            {c.money ? " · money" : ""}
            {c.nullable ? "" : " · may not stay blank"}
          </div>
        </td>
        <td>
          {describeMissing(c)} {isSaved && <span className="chip">your choice</span>}
        </td>
        <td className="num">
          <button onClick={() => setOpen(!open)}>{open ? "Close" : "Change"}</button>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={3}>
            <Editor name={name} c={c} cfg={cfg} datasetId={datasetId} isSaved={isSaved} done={() => { setOpen(false); onSaved(); }} />
          </td>
        </tr>
      )}
    </>
  );
}

function Editor({ name, c, cfg, datasetId, isSaved, done }: { name: string; c: any; cfg: any; datasetId: string; isSaved: boolean; done: () => void }) {
  const numeric = NUMERIC.includes(c.type);
  const policies = Object.keys(POLICY_TEXT).filter((p) => p !== "derive" || c.derive_expression);
  const others = Object.keys(cfg.columns).filter((x) => x !== name);
  const [policy, setPolicy] = useState<string>(c.missing_policy);
  const [value, setValue] = useState<string>(c.fill_value == null ? "" : String(c.fill_value));
  const [method, setMethod] = useState<string>(c.impute_method ?? (numeric ? "median" : "mode"));
  const [groups, setGroups] = useState<string[]>(c.group_by ?? []);
  const [limit, setLimit] = useState<string>(c.fill_limit ? String(c.fill_limit) : "");
  const [label, setLabel] = useState<string>(c.placeholder ?? "MISSING-ROW-{row}");
  const [allow, setAllow] = useState<boolean>(!!c.allow_estimates);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function settings(): Record<string, unknown> {
    const s: Record<string, unknown> = { missing_policy: policy };
    if (policy === "fill_value") s.fill_value = numeric && value.trim() !== "" && !isNaN(Number(value)) ? Number(value) : value;
    if (policy === "impute") s.impute_method = method;
    if (policy === "fill_down" || policy === "fill_up") {
      s.group_by = groups;
      s.fill_limit = limit ? Number(limit) : null;
    }
    if (policy === "fill_from_group") s.group_by = groups;
    if (policy === "placeholder") s.placeholder = label;
    if (c.money) s.allow_estimates = ESTIMATING.includes(policy) ? allow : false;
    return s;
  }

  async function save(remove = false) {
    setBusy(true);
    setError("");
    try {
      await api.saveChoice(datasetId, name, remove ? null : settings());
      done();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const toggle = (g: string) => setGroups(groups.includes(g) ? groups.filter((x) => x !== g) : [...groups, g]);

  return (
    <div className="choice-form stack">
      <label>
        Choice{" "}
        <select value={policy} onChange={(e) => setPolicy(e.target.value)}>
          {policies.map((p) => (
            <option key={p} value={p}>
              {POLICY_TEXT[p]}
            </option>
          ))}
        </select>
      </label>

      {policy === "fill_value" && (
        <label>
          Value{" "}
          <input value={value} onChange={(e) => setValue(e.target.value)} placeholder={numeric ? "e.g. 0" : "e.g. Unknown"} />
          {c.allowed_values && <span className="muted small"> allowed: {c.allowed_values.join(", ")}</span>}
        </label>
      )}

      {policy === "impute" && (
        <label>
          Method{" "}
          <select value={method} onChange={(e) => setMethod(e.target.value)}>
            {numeric && <option value="median">median (middle value; safe with extremes)</option>}
            {numeric && <option value="mean">mean (average; refused on skewed data)</option>}
            <option value="mode">mode (most common value)</option>
          </select>
        </label>
      )}

      {["fill_down", "fill_up", "fill_from_group"].includes(policy) && (
        <div>
          <div className="small">
            {policy === "fill_from_group" ? "Group by (required):" : "Only copy within the same (optional):"}
          </div>
          <div className="row wrap gap">
            {others.map((g) => (
              <label key={g} className="small">
                <input type="checkbox" checked={groups.includes(g)} onChange={() => toggle(g)} /> {g}
              </label>
            ))}
          </div>
        </div>
      )}

      {(policy === "fill_down" || policy === "fill_up") && (
        <label>
          At most{" "}
          <input type="number" min={1} value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="no limit" style={{ width: "7em" }} /> rows away
        </label>
      )}

      {policy === "placeholder" && (
        <label>
          Label <input value={label} onChange={(e) => setLabel(e.target.value)} /> <span className="muted small">{"{row}"} = row number in the file</span>
        </label>
      )}

      {c.money && ESTIMATING.includes(policy) && (
        <label className="small">
          <input type="checkbox" checked={allow} onChange={(e) => setAllow(e.target.checked)} /> Yes, guessing money amounts is OK for this column
          (business rule 9 refuses it otherwise)
        </label>
      )}

      {error && <div className="alert error">{error}</div>}
      <div className="row gap">
        <button className="primary" disabled={busy} onClick={() => save()}>
          Save to rule book
        </button>
        {isSaved && (
          <button disabled={busy} onClick={() => save(true)}>
            Back to the original rule
          </button>
        )}
      </div>
    </div>
  );
}
