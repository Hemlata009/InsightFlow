# 2026-11-21 · Discussion 20: Setting aside 35%+ of SALES_003 is too much: recover safely

## Request
"It's not good that we keep more than 35% of the data aside. Handle it, use some tools, and ask me if you have questions."

## User decisions (asked and answered)
| Question | Decision |
|---|---|
| Date with no day ("Mar 2025") | **Business chooses** via the rule book: mean / median / mode day, a fixed day, first/last of month, copy from the row above/below ("insert up/down"), or a **plugin hook**. Default: first of month; completed rows are flagged |
| Two minus signs ("(20-)") | Read as **negative**, flag the row |
| Missing order number | **Temporary ID** `MISSING-ROW-<row>`, flag the row |
| Timestamps 1741132800 / 20250305 | Use **existing tools**: pandas (exact Unix/compact readers) + **dateparser** (github.com/scrapinghub/dateparser, BSD-3-Clause) for written dates |

## What was built
| # | Recovery | How | Tool |
|---|---|---|---|
| 1 | Written dates ("5th March 2025", "5 मार्च 2025") | strict dateparser fallback: dataset languages (`en`,`hi`), locale day/month order, all parts required, no relative words, range-checked | dateparser |
| 2 | Unix (s/ms/µs) and 20250305 dates | on by default, accepted only inside the business date range; Unix = UTC → business time zone | pandas |
| 3 | "10:00 IST" | locale `timezone_abbreviations` (en_IN: IST → Asia/Kolkata; US: EST/PST…) | zoneinfo/tzdata |
| 4 | Partial dates | `policies.partial_dates` (missing_day / missing_year strategies) + hook `resolve_partial_date` | pluggy |
| 5 | Two minus signs | negative + flag `double_minus_sign` | — |
| 6 | Missing ID | `missing_policy: placeholder` + flag | — |
| 7 | **Repair from formula** | one bad value among the formula's columns is recomputed from the others; accepted only if exactly ONE fix passes every check (ambiguous = stays aside); flagged; original text in the log | exact Decimal |
| 8 | Invalid value in a group column ("Mars") | treated as blank, filled from the group (same State), flagged | — |
| 9 | Group disagreement on an optional column | kept blank + flagged (required columns still set aside) | — |
| 10 | Excel formula saved without a result | simple arithmetic of same-sheet cells calculated (functions are not guessed) | own safe evaluator |
| 11 | Extra trailing cells | kept in column `_overflow`, row flagged; still validated | — |

## Results
| Dataset | Set aside before → after | Notes |
|---|---|---|
| SALES_003 chaos.csv | 31 (38%) → **11 (13.3%)** | 83/83 rows as expected; status completed_with_warnings |
| SALES_003 chaos.xlsx | 32 → **11 (13.1%)** | 84/84 |
| SALES_003 chunked | → **11** | 83/83, identical to in-memory |
| SALES_002 | 16 → **8** | 8 repaired from the formula, values = truth |
| SALES_001 | 160 → **40** | 120 repaired; -999 quantities repaired too (no returns there → only one fix fits) |

The 11 still set aside are rows whose truth can't be known: quantity 2.5 / 0 / over 1000, -999 where returns
are allowed (two fixes fit), 31 Feb, a 2024 and a 2035 date, a missing date with nothing to copy, product "?",
two missing numbers, a row with only 3 cells.

## Findings while building it
1. dateparser read "10:00 IST" as **Israel** time (13:30 in India) and, with a time zone set, shifted plain dates
   by 5½ h; it also filled a missing year with the current year. So: IST is mapped per locale, dateparser gets
   no time zone, and missing parts are detected before it runs.
2. dateparser was too eager (read "05/03/26" with two-digit years switched off, and zoned ISO times without a
   business time zone). Now it only sees written dates containing letters.
3. Hindi vowel signs aren't `\w` in Python's regex: the letter filter now accepts any single letter.
4. Our own Unix timestamps weren't converted from UTC; now they are (14:30 UTC = 20:00 IST).
5. Chunked mode read the overflow column as part of the header (every row set aside). Fixed; equal again.
6. A repaired row skipped the key-conflict check in memory (chunked caught it). Both now check repaired rows.
7. The same -999 is repairable in SALES_001 (returns not allowed) but ambiguous in SALES_002 (returns allowed):
   the answer keys now depend on the dataset's rules.

## Simple explanation
Instead of throwing a whole row away because of one bad cell, the machine now fixes what it can PROVE: if
quantity × price × (1 − discount) must equal sales, one wrong number can be worked out from the other three.
Every fix is marked so a person can see it. Where two answers are possible, or the truth simply isn't in the
file, the row still waits for a human. That's 11 rows instead of 31.
