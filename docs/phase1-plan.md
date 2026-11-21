# Phase 1 Plan: Data Intake & Quality Engine (lean version)

Agreed 2026-11-21. Based on the full proposal in
[reference/phase1-proposal.md](reference/phase1-proposal.md), trimmed to build fewer pieces first.

## Principles
1. Raw files are never modified (store a SHA-256 hash in metadata).
2. Profile before changing anything.
3. Normalization (standard representation) is separate from cleaning (policy decisions).
4. Never guess ambiguous values. Flag them and send them to quarantine with a reason.
5. Quarantine, never delete.
6. Idempotent: re-running gives the same output.
7. Every change is logged: rule, column, row, old value, new value, reason.
8. Domain-agnostic core; domain rules live in `configs/*.yaml`.
9. Third-party libraries are wrapped behind InsightFlow functions.
10. Every run returns a structured result with a status:
    `completed | completed_with_warnings | needs_review | failed`.

## Defaults
- Locale: **India**: INR (₹), day-first dates (DD/MM/YYYY), lakh/crore grouping and magnitudes.
  US/international is available as a config option.
- Formats: CSV and Excel (.xlsx).
- Practice data: SALES_001 real Superstore (en_US) + SALES_002 generated India (en_IN), both with answer keys. See [datasets.md](datasets.md).

## Steps

| Step | Module | Deliverable | Status |
|---|---|---|---|
| 0 | setup | venv, pyproject, folders, smoke test | ✅ done |
| 1 | `data/sample` | SALES_001 (Superstore) + SALES_002 (India) with planted issues + answer keys | ✅ done |
| 2 | `configs/` | Layered rule book + validated loader (`insightflow.config`) | ✅ done |
| 3 | `ingestion` | Safe CSV/Excel reader + file metadata + repeat-upload registry | ✅ done |
| 4 | `profiling` | Column-level health report before changes (patterns, ranges, duplicates) | ✅ done |
| 5 | `normalization` | Column names, null markers, numbers/magnitudes, dates, booleans, IDs | ✅ done |
| 6 | `cleaning` | Missing values (quarantine/flag/fill/derive), duplicates, key conflicts → quarantine | ✅ done |
| 7 | `validation` | Pandera schema from config + business rules (quarantine / flag) | ✅ done |
| 8 | `audit` | cleaning_log, quality_report, metadata, result object | ⏳ next |
| 9 | `pipeline` | End-to-end run + idempotency test | |

## Edge-case test backlog (each becomes a pytest test)

### Step 3: Ingestion
- [x] Wrong extension / file signature mismatch
- [x] Corrupt file; password-protected Excel → fail with a clear message
- [x] Empty file / empty worksheet
- [x] Multiple Excel sheets (select by config)
- [x] Header not in the first row
- [x] Duplicate or blank column names
- [x] CSV encoding (UTF-8, UTF-8-BOM, cp1252)
- [x] Comma / semicolon / tab delimiters
- [x] Same file uploaded again (hash match)

### Step 5: Normalization
- [x] Column names: whitespace, casing, map to canonical names
- [x] Null markers: NA, N/A, NULL, -, empty string
- [x] Indian vs international grouping: 1,00,000 vs 100,000
- [x] Decimal separators: 1.234,56 vs 1,234.56 (per locale config)
- [x] Magnitudes: K, M, B, L, Lakh, Cr, Crore
- [x] Accounting negatives: (1,000)
- [x] Percentages: 10% vs 0.10
- [x] Currency symbols/codes stripped and recorded; `$` ambiguity flagged
- [x] NaN, Infinity, malformed numbers → flagged
- [x] Dates: DMY vs MDY ambiguity resolved by config, otherwise flagged
- [x] ISO and local date formats mixed
- [x] Excel serial dates
- [x] Invalid dates; dates outside the business range (Step 7 rule `order_date_in_range`)
- [x] Booleans: Yes/No, Y/N, 1/0
- [x] IDs keep leading zeros (read as text)
- [x] Mixed types in one column

### Step 6: Cleaning
- [x] Meaningful missing (zero vs unknown) per column policy
- [x] No fill across group boundaries
- [x] Duplicates found only after normalization
- [x] Repeated Order_ID that are valid line items (configurable key)
- [x] Imputation is logged, and skipped for skewed columns by default

### Step 7: Validation & business rules
- [x] Required / optional / extra / missing columns
- [x] Negative sales = return (if allowed by config)
- [x] Negative profit = legitimate loss
- [x] Quantity zero/negative per returns policy
- [x] Sales ≈ Quantity × Unit_Price × (1 − Discount) consistency check
- [x] Conflicting rules detected

### Step 9: Pipeline
- [ ] Re-run is idempotent
- [ ] Original values and source row numbers are kept
- [ ] Log records which rule changed which value and why

## Deferred (not in Phase 1 v1)
JSON/JSONL/Parquet · nested JSON · currency conversion · timezones/DST · Unix timestamps ·
large-file chunking · hook registry · Frictionless · dateparser · PyJanitor · moneyparse ·
ydata-profiling · Great Expectations · DuckDB · Babel
