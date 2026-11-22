# 2026-11-22 · Discussion 25: Where the hooks are used, and why

## Question
"Where did you use the concept of hooks, and why?"

## Answer
5 hook points (pluggy): `after_ingest`, `after_normalize`, `resolve_partial_date`, `after_clean`, `extra_checks`,
called in that order in `pipeline/phase1.py` (and `normalization/partial_dates.py` for partial dates). Why: keep
the engine generic, let the business plug in its own rules (e.g. partial-date choices), safely (no row changes,
every change logged, plugin fingerprinted). Details: [../tools-and-hooks.md](../tools-and-hooks.md).

## Gaps found while answering (fixed)
1. `resolve_partial_date` had **no test**: added (normal and chunked mode).
2. **Chunked mode skipped plugins** (only a warning): a dataset using the partial-date plugin would have set
   those rows aside for big files. Now plugins run in chunked mode piece by piece, the pre-passes see the same
   plugin output, and a test proves chunked = in-memory with plugins. Metadata records plugins in chunked mode too.

## Simple explanation
A hook is a plug socket in the cleaning line. The main machine stays the same for every business; each business
plugs in its own small rule. We checked the sockets while answering, and found one socket that was never tested
and one machine (big-file mode) that had no sockets at all. Both are fixed now.

## Technical
`run_chunked(..., pm=)`; per piece: after_ingest (original text kept for quarantine), after_normalize,
`resolve_partial_dates(norm, cfg, pm, contexts)`, after_clean, `run_checks`; `_plugged()` applies after_ingest in
both pre-passes, after_normalize in the group pre-pass. 467 tests passing.
