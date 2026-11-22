# Phase 1: complete summary (everything that was done)

Phase 1 = **Data Intake & Quality Engine**. Built 2026-11-21 → 2026-11-22. Final tag `phase1-v1.4`.
42 commits · 5 version tags · 464 tests · ~10,200 lines (engine 4,489 · harness 511 · scripts 1,249 · web UI 881 ·
tests 3,079) · 23 discussion notes · 59 logged decisions.

## 1. Project foundation
| # | What | Where |
|---|---|---|
| 1 | Vision, mission, outcomes, tools, skills, 9-phase roadmap | `docs/project-overview.md` |
| 2 | Decision: sales first, but a domain-agnostic core + per-domain config | discussion 01 |
| 3 | Lean Phase 1 plan (10 steps) instead of a 35-file design | `docs/phase1-plan.md`, discussion 04 |
| 4 | Every discussion documented; decision log; progress page | `docs/discussions/`, `docs/decisions.md`, `docs/progress.md` |
| 5 | Git repo, local commit per step; GitHub repo (Actions disabled; now **public**) | github.com/Hemlata009/InsightFlow |
| 6 | Python 3.14 virtual environment, pinned requirements, `pyproject.toml` (extras `dev`, `api`) | `requirements.txt` |

## 2. Local harness (protects this ~6 GB-RAM PC)
| # | Feature |
|---|---|
| 1 | `harness check`: free RAM / CPU / disk → OK / WARN / STOP, shows the biggest programs |
| 2 | `harness test` / `run`: refuses to start below 400 MB free; watchdog stops a task over 1.5 GB, or when the PC stays under 250 MB for 5 s and the task is ≥ 200 MB; timeouts; Ctrl+C stops everything |
| 3 | Full test run = 3 groups in fresh processes (lower peak memory) |
| 4 | Run history in SQLite (`harness history`), `harness status`, `harness ui`, `--cwd` |
| 5 | Survives Windows memory errors (WinError 1455), console-proof output (₹, →) |

## 3. Sample data (test material with known answers)
| Dataset | What | Size |
|---|---|---|
| SALES_001 | Real Tableau Superstore (US, USD, MDY), downloaded + checksum, not in git | 9,994 → 10,074 messy rows |
| SALES_002 | Generated India data (INR, DMY, lakh/crore), stories: Diwali boost, March-2026 North Electronics drop, returns | 1,005 → 1,013 |
| SALES_003 | "Chaos" file: one problem per row, 78 cases, CSV + Excel | 83 / 84 rows |
| Each | truth file + messy CSV + messy Excel + answer key (row, problem, expected value/action) | |

## 4. Rule book (configuration, no code changes needed)
Layers: `configs/default.yaml` → `domains/sales.yaml` → `datasets/<ID>.yaml` + `locales.yaml` (en_IN, en_US, de_DE),
validated by Pydantic (typos and contradictions are refused). Business rules BR-1…BR-15 in `docs/data-dictionary.md`
(set by InsightFlow because none were given yet; BR-10, BR-11 and BR-12 decided by the user).

## 5. The engine, stage by stage
| Stage | What it does |
|---|---|
| **Ingestion** | CSV/TSV/TXT, Excel, JSON, JSON Lines (nested), Parquet, XML (safe), fixed-width; detects encoding (UTF-8/BOM/UTF-16/cp1252), separator, header row, two-row headers, sheet (skips hidden), merged cells; refuses broken, locked, empty, mislabelled or too-big files with clear codes; keeps the original row number; repeated-upload detection; never changes the original file |
| **Profiling** | health report before any change: patterns, blanks, ranges, allowed values, duplicates, spelling variants, Excel-formula risk |
| **Normalization** | numbers (₹/$/€, Rs., 1,00,000 / 100,000 / 1.234,56, K/L/Cr/M/B, (500), 500-, −, %, precision guard), dates (locale order, ISO, month names, Excel serials, Unix, compact, 2-digit years, time zones + daylight saving, IST per locale, written/Hindi dates via dateparser), date vs datetime, text tidy and spelling standardization, headers to canonical names, null markers |
| **Cleaning** | missing-value policies (set aside / keep+flag / fill / derive by formula / fill from same order or state / impute / placeholder), duplicates after cleaning (incl. hidden), key conflicts, incomplete-date strategies (+ plugin hook) |
| **Repair** | proven fixes from the sales formula (one bad value, only one possible fix); invalid group values replaced; ambiguous rows stay set aside |
| **Validation** | Pandera schema + config rules (formula, sign consistency, not-zero, date range); severities set aside / flag |
| **Audit & output** | cleaned CSV (Excel-friendly), set-aside rows with original text + reasons, removed duplicates, quality report, standard change log (seq, run, kind, rule, row, column, old, new), metadata (hashes, versions, plugins), raw copy; statuses completed / with warnings / needs review / failed; notes vs warnings; schema-drift detection; row trace command |

## 6. Extra capabilities
| # | Capability | Tool |
|---|---|---|
| 1 | Files bigger than free RAM: chunked mode, identical results (600k rows in 82 s, peak 446 MB) | DuckDB |
| 2 | Currency conversion at the row's date (opt-in) + reporting-currency columns | CurrencyConverter (ECB rates) |
| 3 | Exact money maths (Decimal, half-up), KPI helpers ready for Phase 2 | Python decimal |
| 4 | Add-on steps (plugins) with row-safety rules + provenance | pluggy |
| 5 | Excel formulas without results: simple arithmetic calculated | own safe evaluator |
| 6 | Web explorer: Run pipeline · Edge-case lab · Rule book (local API) | React + FastAPI |

## 7. Quality evidence
| Check | Result |
|---|---|
| Automated tests | **464 passing** (harness 20 · edge cases 150 · others 294) |
| Truth check (cleaned output vs truth) | 6/6 PASS on SALES_001 and SALES_002 |
| Chaos check (row by row) | CSV 83/83 · Excel 84/84 · chunked 83/83 · 13% set aside |
| Frozen baseline | results + SHA-256 of outputs reproduced exactly |
| Chunked = in-memory | proven on all datasets |
| Static check | ruff clean |

## 8. Problems found and fixed during Phase 1 (selection)
Generator rounding of 4-decimal values · invisible non-breaking spaces in real data · UTF-16 files rejected ·
European-number trap (1.234) · (500-) cancelling to +500 · ₹ garbled in Excel output · NumPy 2 repr broke Decimal ·
round(2.675) = 2.67 · Excel serials with time · chunked spelling differences · chunked fill differences ·
typo values blocking group fills · dateparser reading IST as Israel and guessing years · UTC timestamps not converted ·
overflow column read as header in chunked mode · harness crash under memory pressure · slow repair (397 s → 82 s).

## 9. Not done / open
| # | Item | Needs |
|---|---|---|
| 1 | Test with one real business file | the user's file |
| 2 | Approval of business rules BR-1…15 | the user |
| 3 | Explorer doesn't show repairs/flags/settings well yet | small UI work |
| 4 | Excel formula *functions* (SUM, VLOOKUP…) and very large Excel files | optional (GPL/LibreOffice or save as CSV) |
| 5 | Repository visibility (now public) | the user's choice |
