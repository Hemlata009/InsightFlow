# The rule book: complete guide

The rule book is the set of YAML text files in `configs/` that tells InsightFlow what correct data looks like and
what to do with incorrect data. **The program contains no business rules of its own:** change a file, and the next
run follows the new rule. Loader: `src/insightflow/config.py` (`load_dataset_config("<ID>")`).

## 1. Files and layers
```
configs/default.yaml           Layer 1  general policies for ANY data (53 lines)
configs/domains/sales.yaml     Layer 2  the sales columns, business rules, duplicate key (158 lines)
configs/datasets/SALES_00x.yaml Layer 3 one dataset: country style, date range, allowed values, overrides
configs/choices/SALES_00x.yaml  Layer 4 missing-value choices saved from the web page (only if you saved some)
configs/locales.yaml           country styles: en_IN (India), en_US (USA), de_DE (Germany/Europe)
```
**Layer 4 (choices):** written by the web page (Rule book tab → "Missing values"), safe to edit by hand. It may
only contain missing-value settings per column (`missing_policy`, `fill_value`, `impute_method`,
`max_skew_for_mean`, `group_by`, `fill_limit`, `placeholder`, `allow_estimates`); anything else is refused. A choice
is saved only if the WHOLE rule book is still valid with it (e.g. a fixed value must be an allowed value and inside
the limits). The run's `config_sha256` includes this file. The test suite ignores it
(`INSIGHTFLOW_IGNORE_CHOICES=1`, set in `tests/conftest.py`), so saved choices never break the frozen baseline.
Later layers win: dataset > domain > default. Inside a section only the keys you write are replaced (deep merge);
lists are replaced as a whole. Example: SALES_002 sets `Quantity: {min: -1000}`; the domain's `max: 1000` stays.

## 2. Layer 1: `default.yaml` sections
### `policies` (how values are read and handled)
| Key | Default | Meaning |
|---|---|---|
| `null_markers` | "", NA, N/A, n/a, NULL, null, None, -, --, ?, nan, NaN | texts that mean "empty" |
| `strip_whitespace`, `collapse_inner_spaces` | true | `" north "` → `north`; `Desk   Organizer` → `Desk Organizer` |
| `categorical_case` | match_known | `NORTH` → `North` (the allowed or most common spelling) |
| `ambiguous_dates` | use_locale | 01/02/2025 read the country's way; `quarantine` = refuse instead |
| `extra_date_formats` | %Y-%m-%d, %d-%b-%y, %d-%b-%Y | other date styles accepted |
| `excel_serial_dates`, `unix_timestamps`, `compact_dates` | true | 45746 / 1741132800 / 20250305, only inside `date_range` |
| `two_digit_years` | true | 05/03/26 → 2026 |
| `dateparser_fallback` | true | "5th March 2025", Hindi dates |
| `timezone` | null (SALES_002/003: Asia/Kolkata) | business time zone for times with +05:30 / Z / IST |
| `partial_dates` | missing_day: first_of_month · missing_year: mode_year · fixed_day: 1 · fixed_year: null | how to complete "Mar 2025" / "05/03" (see §6) |
| `percent_strings`, `accounting_negatives`, `magnitude_suffixes` | true | 10% · (1,000) · 15K / 1.2 L / 3 Cr |
| `invalid_value_action` | quarantine | bad values are set aside, never deleted (only option) |
| `max_quarantine_share` | 0.20 | above 20% set aside → status `needs_review` |
| `header_rows` | 1 | 2 = join a two-row header |
| `max_file_mb`, `large_files`, `chunk_rows`, `duckdb_memory_mb`, `max_chunked_file_mb` | 50 · auto · 20000 · 128 · 5000 | big-file (chunked) mode |
### `duplicates`
`exact: drop` (identical rows after cleaning: keep first, save the rest in duplicates_removed.csv) or `flag`;
`key` (set by the domain); `key_conflict: flag` (same key, different values) or `quarantine`.
### `currency`
`foreign_amounts: refuse|convert`, `reporting_currency: null|USD…`, `rate_date_column`, `max_rate_age_days: 7`.

## 3. Layer 2: `domains/sales.yaml`
### Columns (the data dictionary)
| Column | Type | Required | If missing | Other settings |
|---|---|---|---|---|
| Order_ID | text | yes | **placeholder** `MISSING-ROW-{row}` (BR-10) | |
| Order_Date | date | yes | **fill from same order** (BR-4), else set aside | inside `date_range` |
| Customer_ID | text | yes (may be blank) | **fill from same order** (BR-3), else keep + flag | |
| Product | text | yes | set aside | spelling standardized |
| Category | text | yes (may be blank) | keep + flag | allowed values per dataset |
| Region | text | yes (may be blank) | **fill from same State** (BR-2), else keep + flag | allowed values per dataset |
| Quantity | whole number | yes | set aside | 1…1000 (−1000…1000 where returns allowed), never 0; repair formula |
| Unit_Price | decimal, money | yes | derive = Sales / (Quantity × (1 − Discount)) | ≥ 0.01 |
| Sales | decimal, money | yes | derive = Quantity × Unit_Price × (1 − Discount) | |
| Discount | decimal | yes | derive = 1 − Sales / (Quantity × Unit_Price) | 0…0.8 (fraction) |
| Profit | decimal, money | yes | keep + flag | negative = a real loss |
| Sub_Category, Segment, State | text | optional | keep | Segment has allowed values per dataset |

Each column can also have `aliases` (other header names accepted: `Qty`, `Sales Amount`, `Unit Price (INR)`…),
`normalize_case`, `money`, `derive_expression` / `derive_round`, `group_by`, `placeholder`, `impute_method`, `description`.

### Missing-value choices (pick one per column with `missing_policy`)
| Choice | YAML | Example |
|---|---|---|
| Set the row aside | `quarantine` | a sale with no product |
| Keep blank (NA) and mark | `keep_and_flag` | unknown sub-category |
| A fixed value: 0, a word, any value you write | `fill_value` + `fill_value: 0` / `"Unknown"` | Discount blank → 0 |
| Work it out from a formula | `derive` + `derive_expression` | Sales = Quantity × Unit_Price × (1 − Discount) |
| Copy from rows of the same group | `fill_from_group` + `group_by` | Region from the same State |
| Mean / median / mode | `impute` + `impute_method` | typical value (mean refused on skewed data) |
| Fill down (value from the row above) | `fill_down` (+ optional `group_by`, `fill_limit`) | report exports where a value is written once |
| Fill up (value from the row below) | `fill_up` (+ optional `group_by`, `fill_limit`) | totals written on the last row of a block |
| Temporary label | `placeholder` | `MISSING-ROW-49` |
| Your own logic | a plugin (`after_normalize` / `after_clean` hook) | anything else |

A fixed value is checked when saved: it must be one of the allowed values and inside min/max (numbers).
Rules: fill down/up follow the ORIGINAL file order; with `group_by` they never copy across groups; `fill_limit: 3`
= at most 3 rows away. Every guessed value (mean/median/mode, fill down/up) is logged with where it came from and
**marked** `estimated_value`. **Money columns (BR-9):** guessing (`impute`, `fill_down`, `fill_up`) is refused unless
the column says `allow_estimates: true`; a fixed value (e.g. 0) is allowed. Big-file (chunked) mode can't use
impute / fill down / fill up yet: those columns fall back to keep + mark, with a warning.

```yaml
columns:
  Sub_Category: {missing_policy: fill_down, group_by: [Order_ID], fill_limit: 5}
  Discount:     {missing_policy: fill_value, fill_value: 0}
  Profit:       {missing_policy: impute, impute_method: median, allow_estimates: true}
```

### Business rules (`rules:`)
| Rule | Kind | Severity | Check |
|---|---|---|---|
| sales_formula | formula | flag | Sales ≈ Quantity × Unit_Price × (1 − Discount) within 0.01 or 0.1% |
| return_sign_consistency | same_sign | set aside | Quantity and Sales both negative or both positive |
| quantity_not_zero | not_equal | set aside | Quantity ≠ 0 |
| order_date_in_range | date_range | set aside | Order_Date inside the dataset's date range |
Rule kinds available: `formula`, `same_sign`, `not_equal`, `date_range`. Severity: `quarantine` (set aside) or `flag`.

### Duplicates key
`key: [Order_ID, Product]`: one product appears once per order.

## 4. Layer 3: the datasets
| | SALES_001 (US Superstore) | SALES_002 (India) | SALES_003 (chaos) |
|---|---|---|---|
| Country style | en_US | en_IN | en_IN |
| Date range | 2014-01-01 … 2017-12-31 | 2025-01-01 … 2026-06-30 | same as 002 |
| Time zone | — | Asia/Kolkata | Asia/Kolkata |
| Regions | Central, East, South, West | North, South, East, West, Central | same as 002 |
| Categories | Furniture, Office Supplies, Technology | Electronics, Furniture, Office Supplies | same as 002 |
| Returns | not allowed (Quantity min 1) | allowed (min −1000) | allowed |

## 5. Country styles (`locales.yaml`)
| | en_IN | en_US | de_DE |
|---|---|---|---|
| Currency | ₹ INR | $ USD | € EUR |
| Dates | DD/MM/YYYY | MM/DD/YYYY | DD.MM.YYYY |
| Numbers | 1,00,000.00 | 100,000.00 | 100.000,00 |
| Short forms | K, L/Lakh/Lac, Cr/Crore | K, M/Mn, B/Bn | K, Tsd, Mio, Mrd |
| Languages for written dates | English, Hindi | English | German, English |
| Time-zone abbreviations | IST → India | EST/EDT, CST/CDT, MST/MDT, PST/PDT | CET/CEST |

## 6. Business rules BR-1 … BR-15 (summary; full list in data-dictionary.md)
BR-1 repeats removed (copy kept) · BR-2 Region from State · BR-3 Customer from order · BR-4 Date from order ·
BR-5 disagreement → never copy · BR-6 > 20% → needs review · BR-7 country date order · BR-8 foreign currency refused ·
BR-9 no averages for money · BR-10 temporary Order ID (user) · BR-11 two minus signs = negative (user) ·
BR-12 partial dates per policy (user) · BR-13 proven formula repair · BR-14 invalid group value replaced ·
BR-15 disagreeing customers kept blank.

Partial-date strategies (`policies.partial_dates`): missing day → `first_of_month` | `last_of_month` | `fixed_day` |
`median_day` | `mean_day` | `mode_day` | `previous_row` | `next_row` | `plugin` | `quarantine`; missing year →
`mode_year` | `previous_row` | `next_row` | `fixed_year` | `plugin` | `quarantine`.

## 7. Safety: mistakes in the rule book are refused at load time
Unknown key (typo) · wrong type name · min > max · ranges on text columns · empty allowed list · a rule or duplicate key
using an unknown column · a business switch disagreeing with its column limit · guessing money without `allow_estimates` · a formula with anything but columns, numbers and + − × ÷ ( ) · a formula referring to itself ·
`derive` without a formula · `fill_from_group` without `group_by` · mean/median on text · not-nullable + keep_and_flag ·
unknown locale / time zone · bad plugin name · currency conversion without a date column · two columns claiming one alias.

## 8. How to change a rule (examples)
```yaml
# configs/datasets/SALES_002.yaml
policies:
  partial_dates: {missing_day: median_day}     # complete "Mar 2025" with the typical day of March
  max_quarantine_share: 0.10                   # stricter "needs review" limit
columns:
  Discount: {max: 0.5}                         # discounts above 50% are wrong for this business
  Region: {allowed_values: [North, South, East, West, Central, North-East]}
currency: {reporting_currency: USD, rate_date_column: Order_Date}   # add Sales_USD, Profit_USD…
plugins: [plugins.sales_sanity]                # switch on the example add-on
```
New data area (e.g. HR): add `configs/domains/hr.yaml` + `configs/datasets/HR_001.yaml`; no engine code changes.

## 9. Business switches (fixed 2026-11-22)
`business.returns_allowed` / `negative_profit_allowed` each name their column (`returns_column: Quantity`,
`profit_column: Profit`); the loader **refuses** a rule book where a switch and that column's `min` disagree:
returns allowed ⇔ Quantity min below 0; losses allowed ⇔ Profit min empty or below 0. Example error:
`business.returns_allowed is false but Quantity min is -1000: they disagree; set Quantity min of 0 or more (e.g. 1),
or change the switch`. (Before this fix the switches were documentation only.)

## 10. Where to see it
Web explorer → **Rule book** tab: the merged result for each dataset, the **Missing values** editor (change /
save / back to the original rule), the business switches and the limits that enforce them. **Run** tab →
"What was marked for review" (counts by reason, e.g. `estimated_value`). Plain-language version of the sales rules:
`docs/data-dictionary.md`.
