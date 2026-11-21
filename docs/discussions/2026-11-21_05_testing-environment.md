# 2026-11-21 · Discussion 05: Is a testing environment set up?

## Question
"Have you set up a testing environment?"

## Answer
Yes, a basic one, created in Step 0. It grows step by step:
- **Now:** pytest installed in `.venv`, configured in `pyproject.toml`, a `tests/` folder, and a smoke test
  (`tests/test_setup.py`, 14 passing).
- **Step 1:** practice data + answer key become shared test inputs.
- **Steps 3–9:** one test file per stage, one test per edge case from [../phase1-plan.md](../phase1-plan.md),
  written before the code (test-first).
- **Later, when needed:** shared fixtures (`tests/conftest.py`), coverage (`pytest-cov`), and automatic
  test runs on GitHub (CI) once the repo is pushed.

## Simple explanation
Like a test bench in a lab: the bench and the meter are ready. For each new circuit we build, we add its
own test before switching it on.

## Technical explanation
- Run: `.\.venv\Scripts\Activate.ps1` then `pytest` (or `pytest -v` for each test's name).
- `[tool.pytest.ini_options] testpaths = ["tests"]` in `pyproject.toml`.
- Editable install (`pip install -e ".[dev]"`) lets tests `import insightflow` from `src/`.

## Next steps
Step 1: practice sales data.
