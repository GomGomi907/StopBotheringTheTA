# Repository Guidelines

This repository is intended for a web-crawling toolchain. Keep the layout predictable so crawlers, parsers, and tests remain easy to maintain.

## Project Structure & Module Organization
- `src/`: crawler logic; split into `fetchers/` (HTTP, throttling), `parsers/` (HTML/JSON), and `pipelines/` (storage/export). Provide an `__main__.py` so `python -m src` runs the entrypoint.
- `tests/`: pytest suites mirroring the module tree; fixtures in `tests/fixtures/` for sample pages/responses.
- `scripts/`: one-off maintenance tasks (data refresh, cleanup); keep idempotent.
- `docs/`: protocol notes, endpoint schemas, and architecture sketches.
- `data/`: sample outputs (CSV/JSON) and recorded responses; exclude secrets and large dumps.

## Build, Test, and Development Commands
- Create venv: `python -m venv .venv` then `.\.venv\Scripts\activate`.
- Install deps: `pip install -r requirements.txt` (pin versions).
- Run locally: `python -m src` or `python -m crawler.cli` once the entry module is defined.
- Format/lint: `ruff check src tests` and `black src tests` (add to pre-commit once configured).
- Tests: `pytest` or `pytest -k keyword` for focused runs; add `--cov=src --cov-report=term-missing` for coverage.

## Coding Style & Naming Conventions
- Python 3.11+ assumed; 4-space indentation; prefer f-strings and explicit imports.
- Modules/files: lower_snake_case; classes: PascalCase; functions/variables: snake_case.
- Type-hint public APIs; document rate limits and selectors near fetchers.

## Testing Guidelines
- Mirror modules in `tests/` with `test_<module>.py`; one behavior per test.
- Use fixtures for recorded responses; avoid live network calls in CI by faking I/O.
- Target ≥80% branch coverage on new/changed code; add regression tests with bug fixes.

## Commit & Pull Request Guidelines
- Commit messages: imperative mood; short summary plus optional body with rationale and test plan.
- PRs: include what/why, linked issue, manual/automated test evidence, and screenshots/logs when parser output changes.
- Keep diffs small and cohesive; update docs/tests alongside code changes.

## Security & Configuration
- Store secrets in `.env` and keep out of VCS; load via `python-dotenv` or equivalent.
- Respect robots.txt and site usage policies; throttle requests (sleep/backoff) and log request IDs.
- Validate outputs against schemas before writing; avoid writing partial files on failure.
