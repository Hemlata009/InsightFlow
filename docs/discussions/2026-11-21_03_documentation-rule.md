# 2026-11-21 · Discussion 03: Documentation rule and project setup

## Request
"All our discussions must be documented properly." The user asked for this as a global setting.

## Decision
- Added a mandatory rule to the global Claude settings (`~/.claude/CLAUDE.md`): every discussion is
  written to `docs/discussions/`, each decision gets a line in `docs/decisions.md`, and project docs are
  kept up to date and committed with the step they describe.
- Created the project folder `Desktop/InsightFlow` with git (branch `main`). Local commits only, no push yet.

## Simple explanation
Like a lab notebook: every test, setting and result is written down, so later you can see exactly why
each choice was made.

## Technical explanation
- `docs/discussions/YYYY-MM-DD_NN_<topic>.md`: full reasoning per discussion (works like an ADR).
- `docs/decisions.md`: index of decisions.
- `docs/progress.md`: current status and next step.
- `.gitignore` excludes virtual environments, caches, `.env` secrets and generated data outputs.

## Next steps
Milestone 1: choose the sales dataset (public Superstore-style, generated with deliberate data issues, or the user's own).
