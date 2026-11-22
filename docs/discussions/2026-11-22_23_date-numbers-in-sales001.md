# 2026-11-22 · Discussion 23: Date numbers refused in SALES_001 (UI test by the user)

## What the user saw
In the Edge-case lab with SALES_001, `45746`, `45746.75`, `99999`, `1741132800` and `20250305` were all refused
with "outside_date_range_or_not_a_date". The user pointed out (correctly) that they are valid date codes:
30 Mar 2025, 30 Mar 2025 18:00, 13 Oct 2173, 5 Mar 2025 00:00 UTC, 5 Mar 2025.

## Why they were refused
SALES_001 (Superstore) covers **2014-01-01 … 2017-12-31**. Plain numbers are only accepted as dates when they
land inside the dataset's business range: otherwise an order number or price (e.g. 45746) could silently become
a date. In SALES_002 (2025–2026) the same 2025 numbers ARE accepted.

## What was wrong (and fixed)
1. The reason was vague. Now it says what the number would mean and why it's refused, e.g.
   `excel_serial_outside_date_range (=2025-03-30 outside 2014-01-01..2017-12-31)`,
   `unix_timestamp_outside_date_range (=2025-03-05 00:00 UTC …)`, `compact_date_outside_date_range (…)`,
   or `number_is_not_a_date`.
2. The lab couldn't show the reading. New checkbox "only accept dates inside this dataset's date range"
   (on by default); untick it to see how any value would be read. The pipeline itself still applies the range.

## Decision
Keep the safety rule (date numbers only inside the business range); explain refusals precisely; let the lab explore.

## Simple explanation
A number like 45746 can be a date, but it can also be an order number or a price. So we only treat it as a date
when the date makes sense for this data. For the US data (2014–2017), 2025 doesn't fit, so it's refused, but now
the message tells you "this would be 30 March 2025, which is outside 2014–2017".

## Technical
`dates._refusal_reasons(..., cfg)` → `_explain_number()` (compact / Unix / Excel interpretation + range);
API `LabRequest.ignore_date_range` widens the range to 1900–2199 for the lab only; UI checkbox in LabPage.
Tests: 3 new (US reasons with values, SALES_002 acceptance, API ignore_date_range). 464 passing.
