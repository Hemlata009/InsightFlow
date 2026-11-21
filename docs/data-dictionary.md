# Data Dictionary & Business Rules: Sales domain

The machine-readable source of truth is `configs/`. This page explains it in plain words.
If they ever disagree, **the config files win**.

## How the rule book is layered
```
configs/default.yaml           Layer 1: generic policies for ANY dataset
configs/domains/sales.yaml     Layer 2: sales columns + business rules
configs/datasets/<ID>.yaml     Layer 3: one dataset's locale, date range, allowed values, overrides
configs/locales.yaml           Number/date/currency conventions (en_IN, en_US)
```
Later layers override earlier ones. Loaded and validated by `insightflow.config.load_dataset_config("<ID>")`.
A typo or contradiction (e.g. min > max, a rule using an unknown column) is rejected at load time.

## Columns
| Column | Type | Required | If missing | Valid values | Meaning |
|---|---|---|---|---|---|
| Order_ID | text | yes | quarantine | any | Order identifier; repeats across lines of one order |
| Order_Date | date | yes | quarantine | inside dataset `date_range` | Date of the order |
| Customer_ID | text | yes | keep + flag | any (kept as text) | Customer identifier |
| Product | text | yes | quarantine | any | Product name |
| Category | text | yes | keep + flag | per dataset list | Product category |
| Region | text | yes | keep + flag | per dataset list | Sales region |
| Quantity | integer | yes | quarantine | 1…1000 (−1000…1000 if returns allowed), never 0 | Units; negative = return |
| Unit_Price | decimal | yes | derive | ≥ 0.01 | Price of one unit before discount |
| Sales | decimal | yes | derive | any | Revenue after discount; negative = return |
| Discount | decimal | yes | derive | 0 … 0.8 (fraction) | 0.2 = 20%; "20%" text → 0.2 |
| Profit | decimal | yes | keep + flag | any | Negative = a real loss |
| Sub_Category | text | no | keep | any | Optional |
| Segment | text | no | keep | per dataset list | Optional customer segment |
| State | text | no | keep | any | Optional |

**If-missing policies:** `quarantine` = set the row aside with a reason; `keep + flag` = keep the row, mark
the cell as missing in the report; `derive` = calculate with the column's `derive_expression` from the config
(e.g. Discount = `1 - Sales / (Quantity * Unit_Price)`) when the other values exist, otherwise quarantine.

**Spelling:** text columns with `normalize_case: true` (Product, Category, Region, Sub_Category, Segment, State)
are matched to the allowed value, or to the most common spelling (`" north "` → `North`).

## Business rules (decided 2026-11-21, change in config if the business says otherwise)
| # | Question | Decision |
|---|---|---|
| 1 | What is one row? | One **order line**: one product in one order |
| 2 | What uniquely identifies a row? | `Order_ID + Product`. Same key with different values → flag for review |
| 3 | What is a duplicate? | All values identical **after** cleaning text/numbers → keep the first, log the rest |
| 4 | Negative sales? | A **return**, only if the dataset allows returns (SALES_002 yes, SALES_001 no) |
| 5 | Return consistency | Quantity and Sales must both be negative or both positive, else quarantine |
| 6 | Quantity zero? | Invalid → quarantine |
| 7 | Discount: % or amount? | **Fraction** of the price (0–0.8). Above 0.8, or 150%, → quarantine |
| 8 | Negative profit? | Valid (a loss) |
| 9 | Sales formula | Sales ≈ Quantity × Unit_Price × (1 − Discount) within ₹/$0.01 or 0.1% → otherwise flag |
| 10 | Dates outside range? | Quarantine (e.g. a 2035 date) |
| 11 | Ambiguous dates (01/02/2026)? | Read with the dataset locale (DMY for India, MDY for US); never guess |
| 12 | Currency conversion? | **Off by default.** Opt-in: `currency.foreign_amounts: convert` (at the row's date, ECB rates) and/or `currency.reporting_currency: USD` (adds `Sales_USD` etc.). Bare `$` in a non-dollar dataset is always refused |
| 13 | Too many bad rows? | If more than 20% are quarantined → run status `needs_review` |

## Locales
| | en_IN (SALES_002) | en_US (SALES_001) |
|---|---|---|
| Currency | ₹ INR | $ USD |
| Date order | DD/MM/YYYY | MM/DD/YYYY |
| Grouping | 1,00,000 (lakh) | 100,000 |
| Short forms | K, L/Lakh/Lac, Cr/Crore | K, M/Mn, B/Bn |

## Header aliases
Messy headers are matched after normalizing (lower-case; non-letters/digits → `_`):
`" order_id"`, `"ORDER DATE"`, `"Qty"`, `"Sales Amount"`, `"Unit Price (INR)"`, `"Product Name"`,
`"Sub-Category"` … all map to canonical names. The full lists are in `configs/domains/sales.yaml`.

## Optional policies (added 2026-11-21, off unless set)
| Setting | Where | Meaning |
|---|---|---|
| `policies.timezone` | dataset | Business time zone; times like `…Z` / `…+05:30` are converted to it before taking the date (SALES_002: Asia/Kolkata) |
| `policies.unix_timestamps` | any layer | Read 10/13/16-digit numbers as Unix time (s/ms/µs) |
| `policies.compact_dates` | any layer | Read `20250305` as a date |
| `policies.two_digit_years` | any layer (on) | `05/03/26` → 2026 |
| `missing_policy: fill_from_group` + `group_by` | column | Copy the value the other rows of the same group agree on (e.g. the same order) |
| `missing_policy: impute` + `impute_method` | column | median / mean / mode; mean refused when \|skew\| > `max_skew_for_mean` |
| locale `de_DE` | dataset | € EUR, `1.234,56`, DD.MM.YYYY, K/Tsd/Mio/Mrd |

## Large files, plugins, currency (added 2026-11-21)
| Setting | Meaning |
|---|---|
| `policies.large_files` | `auto` (default): files too big for RAM are processed in pieces with DuckDB · `always` · `never` |
| `policies.chunk_rows` / `duckdb_memory_mb` / `max_chunked_file_mb` | 20,000 rows · 128 MB · 5,000 MB |
| `currency.foreign_amounts` | `refuse` (default) / `convert` |
| `currency.reporting_currency` + `rate_date_column` | e.g. `USD` + `Order_Date` |
| column `money: true` | Unit_Price, Sales, Profit (amounts that can be converted) |
| `plugins: [plugins.sales_sanity]` | add-on modules in `plugins/` (pluggy) |
