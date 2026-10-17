# Repository Guidelines

## Project Structure & Module Organization

This repository currently contains a condition-search research spike and planning documents, not a complete application. `scripts/phase0/verify_condition_search.py` performs read-only Kiwoom WebSocket checks. Its timestamped outputs and fixtures are under `scripts/phase0/output/`. `docs/guides/` contains user-facing guides, `docs/references/` records observed behavior, and `docs/plans/` describes the proposed application and its test requirements. Treat planned directories such as `apps/` and `packages/` as future work, not existing modules.

## Development & Verification Commands

- `python3 -m py_compile scripts/phase0/verify_condition_search.py` checks Python syntax and creates bytecode under `__pycache__/`.
- `~/.local/share/uv/tools/kwcli/bin/python scripts/phase0/verify_condition_search.py --help` shows the spike's options without making broker requests. The interpreter must have the `kiwoom` package installed.
- For an authorized demo-only live check, run `~/.local/share/uv/tools/kwcli/bin/python scripts/phase0/verify_condition_search.py --profiles kiwoom-demo --quick`. It requires interactive keyring access and writes timestamped output. The default profile list includes a real profile; always specify profiles explicitly.

There is currently no application build, configured linter, or automated test suite. Do not present the live spike as a unit test.

## Coding Style & Testing

Follow the existing Python style: four-space indentation, `snake_case` functions and variables, `UPPER_SNAKE_CASE` constants, type hints, and focused functions. Keep Markdown headings descriptive and link related documents with relative paths. For changes, run a syntax check and add automated tests when a test framework is introduced. The plan's testing section lists future cases for expression evaluation, WebSocket fixtures, retries, access control, and CSV safety; these are requirements, not tests already implemented.

## Security & Configuration

Keep App Keys, secrets, tokens, account numbers, and keyring passwords out of source, logs, fixtures, and pull requests. Review generated outputs before sharing. The spike is read-only; do not add order or real-time subscription calls to it. Never run live checks against a real profile without explicit authorization.

## Commits & Pull Requests

The repository has no commit history from which to infer conventions. Use an intent-first commit subject and relevant Lore trailers, such as `Tested:` and `Not-tested:`. Pull requests should explain the change, link relevant plans or issues, list verification and limitations, and include screenshots for UI changes.
