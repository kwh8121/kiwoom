# Task 5 Report

## Outcome

Implemented the Kiwoom response parser, return-code classifier, and outgoing request allowlist for the worker package. Added a single secret-safe phase0 `CNSRREQ` fixture and test coverage for code normalization, signed rate parsing, error extraction/classification, and allowlist enforcement.

## Fixture inspection

- Source inspected: `scripts/phase0/output/20261017-135943/fixtures.json`
- Copied only: `kiwoom-real-vibe` -> `1`
- Selected message keys: `cont_yn`, `data`, `next_key`, `return_code`, `seq`, `trnm`
- Selected row keys: `10`, `11`, `12`, `13`, `16`, `17`, `18`, `25`, `302`, `9001`
- Secret-safety check: key-name scans for `token`, `secret`, `appkey`, `account`, `acct`, `password`, `pwd` returned zero hits in the selected message. No profile-level data or unrelated fixture entries were copied.
- Preserved observed behavior: includes `A0010F0` and 8-digit signed change-rate strings such as `00000686`.

## RED -> GREEN

### RED

Command:

```bash
UV_CACHE_DIR=/tmp/uv-cache-task4 uv run pytest tests/test_parse.py tests/test_errors.py tests/test_allowlist.py -v
```

Observed failure:

```text
ModuleNotFoundError: No module named 'kiwoom_worker.kiwoom'
```

Collection stopped with 3 import errors across the new parse/errors/allowlist test files.

### GREEN

Targeted tests:

```bash
UV_CACHE_DIR=/tmp/uv-cache-task4 uv run pytest tests/test_parse.py tests/test_errors.py tests/test_allowlist.py -v
```

Result: `22 passed`

Full worker tests:

```bash
UV_CACHE_DIR=/tmp/uv-cache-task4 uv run pytest -v
```

Result: `47 passed`

Lint:

```bash
UV_CACHE_DIR=/tmp/uv-cache-task4 uv run ruff check
```

Result: `All checks passed!`

## Changed files

- `apps/worker/src/kiwoom_worker/kiwoom/__init__.py`
- `apps/worker/src/kiwoom_worker/kiwoom/allowlist.py`
- `apps/worker/src/kiwoom_worker/kiwoom/errors.py`
- `apps/worker/src/kiwoom_worker/kiwoom/parse.py`
- `apps/worker/tests/fixtures/phase0_cnsrreq_seq1.json`
- `apps/worker/tests/test_allowlist.py`
- `apps/worker/tests/test_errors.py`
- `apps/worker/tests/test_parse.py`

## Simplifications made

- Kept code normalization strict to the approved `A/J/Q` prefixes and six-character alphanumeric bodies.
- Limited request enforcement to the Task 5 rules only: allowlisted `trnm`, `search_type == "0"`, and `stex_tp == "K"`.
- Scoped return-code resolution to top-level integer parsing plus the required embedded-code fallbacks (`[dddd:` and `CODE=dddd`).
- Copied a single response message fixture instead of introducing a larger phase0 capture dependency.

## Remaining risks

- Task 7 sequencing behavior for bare `{"trnm":"CNSRREQ"}` messages is intentionally not implemented here.
- Empty-result success handling and retry orchestration are still deferred to later tasks.
- The parser currently trusts the documented field map (`9001`, `302`, `10`, `12`) and does not add extra row-shape recovery beyond type checks.
