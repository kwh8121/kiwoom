# 키움 조건검색식 조합 웹앱 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. The execution method is fixed by the human partner: Codex CLI runs this plan Subagent-driven (see "Execution" below). Do not switch to superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 키움 HTS에 저장된 조건검색식의 결과 종목 집합을 AND·OR·EXCLUDE로 조합해 실행·저장·비교·CSV로 내보내는 개인용 웹앱과, 키움 조회를 전담하는 Python 워커를 만든다.

**Architecture:** 브라우저 → Next.js(Vercel) → Supabase(Auth·PostgreSQL, RLS) ← Python 워커(고정 IP 호스트) → 키움 REST API WebSocket. 웹은 키움을 호출하지 않고 `public` 스키마의 RPC로 작업을 큐에 넣는다. 워커는 전용 DB 역할 `kiwoom_worker`로 `worker` 스키마 함수만 호출해 작업을 선점하고 결과를 원자적으로 확정한다. 표현식 규칙은 `packages/contracts/`의 공용 케이스 파일로 TS 검증기와 Python 평가기가 같은 결과를 내는지 고정한다.

**Tech Stack:**
- 웹: Next.js 16(App Router, `src/`, `proxy.ts`), React 19, TypeScript, Tailwind CSS 4, shadcn CLI 4.x, `@supabase/ssr` 0.12, `@supabase/supabase-js` 2.x, zod 4, Vitest 5, Playwright 1.64
- 워커: uv로 관리하는 Python 3.13(`requires-python >=3.12`), `websockets` 17, `httpx` 0.28, `psycopg[binary]` 3.3, pytest 9, pytest-asyncio 1.4, ruff
- DB: Supabase CLI 2.121(로컬 Docker), pgTAP(`supabase test db`)
- 배포: Vercel(웹), Supabase Cloud, systemd(워커)

**Spec:** [`docs/plans/kiwoom-conditions-plan.md`](../../plans/kiwoom-conditions-plan.md), [`docs/references/kiwoom-condition-search-verification.md`](../../references/kiwoom-condition-search-verification.md)

**Spec deltas (이 계획에서 확정한 사항, 스펙에도 반영):**
- 워커는 Python으로 작성한다(D2 결정). 스펙의 공용 `packages/core`는 쓰지 않는다. 웹은 `apps/web/src/lib/strategy/`에서 검증·미리보기를, 워커는 `apps/worker/src/kiwoom_worker/core/`에서 검증·평가를 맡는다. 둘의 동작은 `packages/contracts/cases/*.json`으로 맞춘다.
- 워커는 Supabase service role 키를 쓰지 않는다. 전용 역할 `kiwoom_worker`로 Postgres에 직접 연결하고, `worker` 스키마의 `SECURITY DEFINER` 함수만 실행할 수 있다.
- 목록 동기화는 `runs.kind = 'sync'` 작업으로 처리한다. 참고 문서 30개 목록을 seed로 넣는 기능은 만들지 않는다(조건식은 동기화로만 생긴다).

## Global Constraints

- 키움 호출은 워커에서만 한다. `apps/web`에는 키움 URL이나 키움 클라이언트 코드가 없어야 한다.
- 워커 허용 API: `au10001`, `au10002`, `ka10171`, `ka10172`. 허용 `trnm`: `LOGIN`, `PING`(되돌려 보내기만), `CNSRLST`, `CNSRREQ`. `CNSRREQ`의 `search_type`은 항상 `"0"`, `stex_tp`는 항상 `"K"`. 주문 API, `ka10173`, `CNSRCLR`는 구현하지 않는다.
- 연결마다 `LOGIN → CNSRLST → CNSRREQ…` 순서를 지킨다. `CNSRREQ`는 한 번에 하나만 보내고, 요청 간격 기본값은 `0.25`초(설정값)다.
- `{"trnm":"CNSRREQ"}`처럼 `trnm`만 있는 메시지는 기록하고 건너뛴다. 응답은 `trnm`과 `seq`로 대응시킨다. `seq`가 없는 오류 응답은 대기 중인 요청의 오류로 본다.
- 0건 응답은 `return_code=0`, `cont_yn=N`, `data: null`(또는 `[]`)이다. 실패를 0건으로 기록하지 않는다.
- 호출 제한 코드 `105110`, `1700`, `1701`, `1702`: 1초 이상 기다린 뒤 지수 백오프로 재시도한다(최대 3회).
- 표현식 규칙: `and`/`or` 자식 2개 이상, `exclude.subtract` 1개 이상, 최대 깊이 `5`(루트가 깊이 1), 리프(`condition` 노드) 최대 `10`개, `schemaVersion: 1`, `exchange: "K"`. 단독 NOT은 지원하지 않는다.
- 종목코드: 정규화 코드는 `^[0-9A-Z]{6}$`이고 원본(`raw_code`, 예: `A0010F0`)을 보존한다. 접두어 `A`→`stock`, `J`→`elw`, `Q`→`etn`. 정렬은 문자열 오름차순이다.
- `succeeded`는 모든 리프 스냅샷이 완전할 때만 설정한다.
- 비밀정보(앱키·시크릿·토큰·계좌번호·DB 비밀번호)는 DB, 로그, fixture, 저장소에 넣지 않는다. `broker_profiles`에는 `alias`와 `mode`만 저장한다.
- Supabase Auth 공개 가입은 끈다. 사용자 소유 테이블은 모두 RLS를 켠다.
- CSV: UTF-8 BOM을 붙인다. 텍스트 셀이 `=`, `+`, `-`, `@`, 탭, CR로 시작하면 앞에 `'`를 붙인다. `raw_code` 열을 포함한다.
- 결과 화면에는 다음 문구를 고정 표시한다: `추출된 종목은 조건 조합의 결과일 뿐, 매수 추천이나 검증된 신호가 아닙니다.`
- 시각은 KST(`Asia/Seoul`)로 표시한다. 장 구분은 `pre`(09:00 전), `regular`(09:00 이상 15:30 미만), `post`(15:30 이상), `weekend`(토·일)이다. 수집 구간이 `15`초를 넘으면 경고를 표시한다.
- 커밋 메시지는 의도를 먼저 쓰는 제목에 `Tested:`·`Not-tested:` 트레일러를 붙인다(AGENTS.md). 실전 프로필로 실제 호출하는 검증은 사용자가 명시적으로 허락했을 때만 한다.

## Review Focus

- HTS에서 조건식이 바뀌고 동기화되어 기존 전략이 비활성 조건식을 참조하게 된 경우, 실행 요청은 큐에 들어가지 않고 `CONDITION_INACTIVE`와 "목록이 바뀌었으니 전략을 다시 저장하세요" 안내로 막혀야 한다. → Task 2 `request_run` 테스트, Task 13 `mapRpcError` 테스트
- 음수 숫자 셀과 수식 주입 방어가 충돌하는 경우: 등락률 `-2.52`는 CSV에 `-2.52` 그대로 나가야 하고, `=`로 시작하는 종목명만 `'`가 붙어야 한다. → Task 14 CSV 테스트
- 리스를 잃은 워커가 결과를 확정하려는 경우: `complete_search_run`은 `false`를 반환하고 아무것도 쓰지 않아야 한다. 워커는 그 실행을 실패 처리하지 않고 다음 작업으로 넘어가야 한다. → Task 3 pgTAP, Task 9 `test_lease_lost_*`
- 0건 성공 실행: "성공 · 0건"으로 표시하고, CSV는 헤더만 있고, 직전 결과의 종목은 모두 이탈로 보여야 한다. → Task 3 빈 결과 확정 테스트, Task 14 CSV·이탈 테스트
- 어떤 워커도 처리하지 않는 별칭의 프로필로 실행을 요청한 경우: 작업이 조용히 큐에 머물지 않고 화면에 "이 프로필을 처리하는 워커가 없습니다"가 표시되어야 한다. → Task 12 `workerStatus` 테스트

---

## Execution

사용자가 정한 실행 방식: **Codex CLI가 `superpowers:subagent-driven-development`로 실행한다.** Codex 세션이 컨트롤러가 되어 작업마다 새 구현 하위 에이전트를 띄운다. 작업이 끝날 때마다 별도 검토 하위 에이전트가 스펙 준수와 품질을 검토하고, 마지막에 브랜치 전체를 검토한다.

### 실행 전 준비 (사용자)

| # | 항목 | 확인 방법 |
| --- | --- | --- |
| 1 | 기준 커밋: 저장소에 커밋이 없으므로 `master`에 기존 `docs/`, `scripts/`, `AGENTS.md`, `.gitignore`를 커밋한다(`.serena/`, `.omx/`는 `.gitignore`에 추가). Codex는 작업 브랜치를 만들기 위해 이 커밋이 필요하다. | `git log --oneline -1`에 커밋이 보임 |
| 2 | Codex 멀티 에이전트: `~/.codex/config.toml`의 `[features] multi_agent = true` | 이미 설정됨(2026-10-17 확인) |
| 3 | Superpowers 플러그인: 현재 `superpowers@openai-api-curated`, `superpowers@openai-curated`, `superpowers@superpowers-dev` 세 곳이 모두 켜져 있다. 같은 스킬이 중복으로 보이지 않도록 **하나만 남긴다.** | Codex에서 `/plugins` |
| 4 | 하위 에이전트 모델 기본값: `~/.codex/config.toml`에 `[agents] default_subagent_model = "<spawn 허용 목록의 중간 등급 모델>"`, `default_subagent_reasoning_effort = "medium"`. 모델을 명시하지 않고 띄운 하위 에이전트가 가장 비싼 모델을 물려받지 않게 하는 안전장치다. | 설정 파일 확인 |
| 5 | 샌드박스 사전 점검: Codex 세션 안에서 `docker ps`, `pnpm --version`, `uv --version`이 되는지, `pnpm db:start`로 로컬 Supabase가 뜨는지 확인한다. 샌드박스가 Docker 소켓이나 홈 디렉터리 캐시(`~/.cache/uv`, pnpm store) 접근을 막으면, 승인하거나 권한을 조정한다. | 명령 출력 |

### 시작 지시문 (Codex에 입력)

```text
Use superpowers:subagent-driven-development to execute
docs/superpowers/plans/2026-10-17-kiwoom-conditions-mvp.md.
Spec: docs/plans/kiwoom-conditions-plan.md. Follow AGENTS.md.
Work on a new branch feat/kiwoom-mvp in a worktree (superpowers:using-git-worktrees); never implement on master.
Scope: Tasks 1–15 and Task 16 Step 1 only. Stop before any step listed under "Stop points" in the plan.
```

### 실행 규칙

- **작업 공간:** `superpowers:using-git-worktrees`로 `feat/kiwoom-mvp` 브랜치 워크트리를 만든다. `master`에서 직접 구현하지 않는다. 진행 기록(ledger)은 skill이 만드는 `.superpowers/sdd/<plan>/progress.md`에 남긴다(`.superpowers/`는 Task 1에서 `.gitignore`에 추가).
- **순서:** Task 1 → 16 순서로 하나씩 실행한다. 구현 하위 에이전트를 동시에 여러 개 띄우지 않는다. Part 간 의존이 있어 순서를 바꾸지 않는다(B는 A의 DB 함수, C는 A의 타입과 B의 fixture 워커를 쓴다).
- **하위 에이전트 띄우기:** Codex에서는 `spawn_agent`에 `fork_turns: "none"`을 주고, `model`과 `reasoning_effort`를 **항상 명시**한다. 모델 이름은 현재 spawn 허용 목록에서 고른다. 수정 라운드 1~3은 `followup_task`로 같은 구현 에이전트를 이어서 쓴다.
- **모델 등급** (이름이 아니라 등급. 계획이 시그니처·테스트 중심이라 구현 에이전트는 중간 등급이 최저선):

  | Task | 구현 에이전트 | 작업 검토 에이전트 | 이유 |
  | --- | --- | --- | --- |
  | 1, 4, 5, 6, 10, 11, 12, 13, 14 | 중간 | 중간 | 경계가 분명한 단위 작업 |
  | 2 | 중간 | 최상위 | `security definer` 함수의 소유권 검사 |
  | 3 | 최상위 | 최상위 | 선점·리스·원자적 확정, 동시성 |
  | 7 | 최상위 | 최상위 | WebSocket 프로토콜(bare 메시지, seq 대응, 호출 제한) |
  | 8, 9 | 중간 | 최상위 | 실패 분류와 재시도 판단, 리스 상실 처리 |
  | 15 | 중간 | 중간 | 통합 확인 |
  | 최종 브랜치 검토 | — | 최상위 | |
  | 수정 라운드 4~5 | 막힌 에이전트보다 한 등급 위 | 중간 | |

- **검토 에이전트에 줄 제약:** 이 계획의 Global Constraints 전체를 그대로 붙인다. Task 3·7·9 검토에는 Task 3의 `p_payload` 형식과 Task 8의 실패 코드 표도 붙인다.
- **판단(Ruling):** 계획과 스펙이 충돌하면 스펙을 따른다. 판단은 ledger에 `Ruling: <결정> — <이유> — <틀렸을 때 비용>`으로 남기고 계속 진행한다. 마지막 보고에 모든 Ruling을 "Rulings I made"로 나열한다.

### Stop points (여기서는 멈추고 사용자에게 묻는다)

- 키움 API에 실제로 연결하는 모든 동작(실전·모의 모두). 단위 테스트와 E2E는 `ScriptedTransport`·`FixtureTransport`만 쓴다.
- Supabase Cloud 프로젝트 연결·`db push`, Vercel 배포, 워커 호스트 설정. 즉 **Task 16 Step 2~5는 사용자가 진행**하고, Codex는 Step 1(배포 파일·가이드 작성)까지만 한다.
- `master`로의 병합, 원격 저장소 push, PR 생성. 끝나면 `superpowers:finishing-a-development-branch`로 선택지를 제시한다.
- 비밀정보(키움 앱키·시크릿·토큰, 운영 DB 비밀번호)를 만들거나 파일에 쓰는 일. 로컬 전용 값(`kiwoom-worker-local`, E2E용 가짜 키)은 예외다.
- 이 계획 밖의 파일이나 사용자 설정(`~/.codex`, `~/.config`) 변경

### 완료 보고에 포함할 것

- 작업별 커밋 범위와 검토 결과(ledger 요약)
- 실행한 검증 명령과 결과: `pnpm db:test`, `uv run pytest`, `uv run pytest -m db`, `pnpm --filter web test`, `pnpm --filter web build`, `pnpm --filter web test:e2e`
- 연기한 Minor 지적과 보류(parked)한 지적, "Rulings I made" 전체
- 사용자가 할 일: Task 16 Step 2~5, 검증 문서의 남은 항목(V1·V3·V4·V5·V6·V7)

---

## File Structure

```text
package.json, pnpm-workspace.yaml      # pnpm 워크스페이스, Supabase CLI 스크립트
supabase/
  config.toml                          # 로컬 설정(가입 차단)
  migrations/20261017000100_core_schema.sql
  migrations/20261017000200_web_rpc.sql
  migrations/20261017000300_worker_rpc.sql
  seed.sql                             # 로컬 전용: kiwoom_worker 로그인 비밀번호
  tests/001_core_schema.test.sql, 002_web_rpc.test.sql, 003_worker_rpc.test.sql
packages/contracts/
  README.md, cases/validate.json, cases/evaluate.json
apps/worker/                           # uv 프로젝트 (패키지 kiwoom_worker)
  pyproject.toml, .python-version, profiles.example.toml
  src/kiwoom_worker/
    clock.py                           # Clock 프로토콜, SystemClock
    core/expr.py                       # 표현식 검증·평가
    kiwoom/allowlist.py, errors.py, parse.py, token.py, session.py, transport.py, fixture.py
    runner.py                          # execute_search / execute_sync / market_phase / RunFailure
    config.py, db.py, log.py, main.py
  tests/  (fakes.py, fixtures/, test_*.py, integration/test_postgres_db.py)
apps/web/                              # create-next-app 결과 + 아래 파일
  src/proxy.ts
  src/lib/supabase/{server.ts, client.ts, proxy.ts, database.types.ts}
  src/lib/auth/paths.ts
  src/lib/strategy/{types.ts, schema.ts, validate.ts, preview.ts, editor.ts}
  src/lib/display/{errors.ts, time.ts, worker.ts, run.ts}
  src/lib/rpc.ts, src/lib/csv.ts
  src/lib/data/{profiles.ts, conditions.ts, strategies.ts, runs.ts}
  src/app/login/{page.tsx, actions.ts}
  src/app/(app)/layout.tsx
  src/app/(app)/profiles/…, strategies/…, runs/…
  e2e/{global-setup.ts, mvp-flow.spec.ts}, playwright.config.ts, vitest.config.ts
deploy/worker/{kiwoom-worker.service, worker.env.example}
docs/guides/deployment.md
```

---

## Part A — 데이터베이스 기반

### Task 1: 워크스페이스·Supabase 초기화와 핵심 스키마·RLS

**Files:**
- Create: `package.json`, `pnpm-workspace.yaml`, `supabase/config.toml`(`pnpm supabase init`로 생성), `supabase/migrations/20261017000100_core_schema.sql`
- Modify: `.gitignore`
- Test: `supabase/tests/001_core_schema.test.sql`

**Interfaces:**
- Produces(테이블, 모두 `public` 스키마, PK는 `id uuid default gen_random_uuid()`, 시각은 `timestamptz`, 사용자 소유 테이블은 `user_id uuid not null references auth.users on delete cascade`):

| 테이블 | 컬럼(주요) | 제약 |
| --- | --- | --- |
| `broker_profiles` | `user_id, alias text, mode text, display_name text, last_ok_at, last_error_code text, last_error_message text, created_at` | `mode in ('real','demo')`, unique `(user_id, alias)`, `alias ~ '^[a-z0-9][a-z0-9-]{0,62}$'` |
| `conditions` | `user_id, profile_id → broker_profiles, seq text, name text, ref_description text null, is_active bool default true, first_seen_at, last_synced_at, deactivated_at null` | partial unique `(profile_id, seq) where is_active` |
| `strategies` | `user_id, profile_id, name text, current_version_id uuid null, created_at, updated_at, archived_at null` | `name` 1~100자 |
| `strategy_versions` | `user_id, strategy_id, version int, definition jsonb, condition_refs jsonb, created_at` | unique `(strategy_id, version)`. `strategies.current_version_id`의 FK는 이 테이블 생성 뒤 추가 |
| `runs` | `user_id, kind text, profile_id, strategy_id null, strategy_version_id null, status text, idempotency_key uuid, requested_at, started_at, finished_at, lease_owner text, lease_expires_at, attempt int default 0, max_attempts int default 3, error_code text, error_message text, window_start, window_end, market_phase text, compared_run_id uuid null, excluded_codes text[] default '{}', result_count int, sync_summary jsonb` | `kind in ('search','sync')`, `status in ('queued','running','succeeded','failed','timed_out','cancelled')`, `kind='search'`이면 `strategy_version_id` not null, unique `(user_id, idempotency_key)`, partial unique `(profile_id) where status in ('queued','running')`, `market_phase in ('pre','regular','post','weekend')` |
| `condition_snapshots` | `user_id, run_id, condition_id, seq, name, started_at, completed_at, page_count int, row_count int, is_complete bool, error_code text` | unique `(run_id, condition_id)` |
| `condition_snapshot_members` | `user_id, snapshot_id, code text, raw_code text, instrument_type text, name text, price bigint, change_rate numeric(8,2)` | PK `(snapshot_id, code)`, `code ~ '^[0-9A-Z]{6}$'`, `instrument_type in ('stock','elw','etn')` |
| `run_results` | `user_id, run_id, code, name, instrument_type, matched_condition_ids uuid[], diff text, price bigint, change_rate numeric(8,2)` | PK `(run_id, code)`, `diff in ('new','kept')` |
| `condition_sync_events` | `user_id, profile_id, run_id, event text, seq, old_name, new_name, condition_id, created_at` | `event in ('added','removed','replaced')` |

- RLS 규칙: 모든 테이블에서 `select`는 `user_id = (select auth.uid())`일 때만 허용한다. 직접 쓰기 권한은 다음뿐이다.
  - `broker_profiles` insert·update(`display_name`만): 소유자
  - `strategies` insert(소유한 `profile_id`만)·update(`name`, `archived_at`만): 소유자
  - `conditions`는 `ref_description` 컬럼만 update 권한(`grant update (ref_description)`)
  - 나머지 테이블은 함수로만 쓴다.
- 테스트 규약(Task 2·3도 같음): 사용자 생성은 `insert into auth.users (id, email) values (...)`. 사용자 전환은 `set local role authenticated; select set_config('request.jwt.claims', '{"sub":"<uuid>","role":"authenticated"}', true);`, 되돌릴 때는 `reset role`.

- [ ] **Step 1: 기준 커밋과 작업 브랜치 확인**

Run: `git log --oneline -1 && git branch --show-current`
Expected: 기준 커밋이 있고, 현재 브랜치가 `feat/kiwoom-mvp`(워크트리)다. 기준 커밋이 없으면 진행하지 말고 사용자에게 Execution의 "실행 전 준비" 1번을 요청한다.

- [ ] **Step 2: 워크스페이스와 Supabase 초기화**

- `package.json` 설정:
  - `"private": true`, `"packageManager": "pnpm@10.33.0"`
  - devDependency `"supabase": "2.121.0"`
  - scripts: `db:start`=`supabase start`, `db:reset`=`supabase db reset`, `db:test`=`supabase test db`, `db:types`=`supabase gen types typescript --local --schema public > apps/web/src/lib/supabase/database.types.ts`
- `pnpm-workspace.yaml`: `packages: ["apps/web"]`
- `pnpm install && pnpm supabase init` 실행 후 `config.toml`의 `[auth] enable_signup = false`, `[auth.email] enable_signup = false`로 바꾼다.
- `.gitignore`에 추가: `.superpowers/`, `node_modules/`, `.next/`, `.venv/`, `__pycache__/`, `.env*`, `!.env.example`, `apps/worker/profiles.toml`, `supabase/.temp/`, `playwright-report/`, `test-results/`

- [ ] **Step 3: 실패하는 pgTAP 테스트 작성** (`plan(8)`)

```sql
-- 001_core_schema.test.sql (요지)
select has_table('public','runs','runs table exists');
-- 사용자 A의 프로필·전략·run 생성(superuser로) 후 B로 전환
select is((select count(*) from public.broker_profiles), 0::bigint, 'B cannot see A profiles');
select is((select count(*) from public.strategies), 0::bigint, 'B cannot see A strategies');
select is((select count(*) from public.runs), 0::bigint, 'B cannot see A runs');
select throws_ok($$insert into public.strategies(user_id, profile_id, name) values ('<B>', '<A_profile>', 'x')$$, '42501', null, 'B cannot attach strategy to A profile');
select throws_ok($$update public.conditions set name = 'x'$$, '42501', null, 'name column not updatable');
reset role;
select throws_ok($$insert into public.conditions(user_id, profile_id, seq, name) values ('<A>','<A_profile>','1','dup')$$, '23505', null, 'two active rows with same seq rejected');  -- seq '1'이 이미 활성
select lives_ok($$update public.conditions set is_active=false where seq='1'; insert into public.conditions(user_id, profile_id, seq, name) values ('<A>','<A_profile>','1','new')$$, 'inactive + active same seq allowed');
```

- [ ] **Step 4: 실패 확인**

Run: `pnpm db:start && pnpm db:test`
Expected: FAIL. `relation "public.runs" does not exist`

- [ ] **Step 5: `20261017000100_core_schema.sql` 작성**

위 Interfaces의 테이블·제약·RLS 정책·컬럼 권한을 구현한다. `anon`의 모든 권한은 회수한다. `authenticated`에는 select와, 위에서 정한 insert·update 권한만 준다. `updated_at`은 트리거로 갱신한다.

- [ ] **Step 6: 통과 확인**

Run: `pnpm db:reset && pnpm db:test`
Expected: `001_core_schema.test.sql .. ok`

- [ ] **Step 7: Commit**

```bash
git add package.json pnpm-workspace.yaml pnpm-lock.yaml .gitignore supabase/
git commit -m "Add core schema with per-user RLS for condition strategies" -m "Tested: pnpm db:test (001_core_schema)" -m "Not-tested: hosted Supabase project"
```

### Task 2: 웹용 RPC (전략 버전 저장, 실행 요청, 취소)

**Files:**
- Create: `supabase/migrations/20261017000200_web_rpc.sql`
- Test: `supabase/tests/002_web_rpc.test.sql`

**Interfaces:**
- Consumes: Task 1 테이블
- Produces(전부 `public`, `security definer`, `set search_path = ''`, `authenticated`에만 `execute` 허용. 오류는 `raise exception using errcode = 'P0001', message = '<CODE>'`):
  - `public.strategy_leaf_ids(p_expr jsonb) returns uuid[]`: DFS 순서, 중복 제거
  - `public.create_strategy_version(p_strategy_id uuid, p_definition jsonb) returns public.strategy_versions`
    - 오류: `NOT_FOUND`(소유하지 않은 전략), `INVALID_DEFINITION`(`schemaVersion≠1`, `exchange≠'K'`, `profileId≠strategy.profile_id`), `PROFILE_MISMATCH`(리프가 다른 프로필의 조건식), `CONDITION_INACTIVE`
    - `condition_refs`는 `[{"conditionId","seq","name"}]` 배열(DFS 순서)로 저장한다. `version`은 기존 최대값 + 1이다. 저장 후 `current_version_id`를 갱신한다.
  - `public.request_run(p_kind text, p_profile_id uuid, p_strategy_id uuid, p_idempotency_key uuid) returns public.runs`
    - 같은 `(user, key)`의 run이 있으면 그 run을 그대로 반환한다.
    - 오류: `NOT_FOUND`, `STRATEGY_HAS_NO_VERSION`, `CONDITION_INACTIVE`(현재 버전의 `condition_refs` 중 하나라도 활성 행 `(id, seq, name)`과 다를 때), `PROFILE_BUSY`(프로필에 `queued`·`running` run이 있을 때, unique 위반을 잡아서 변환)
  - `public.cancel_run(p_run_id uuid) returns public.runs`: `queued`인 run만 `cancelled`로 바꾼다. 그 외에는 `RUN_NOT_CANCELLABLE`
  - 트리거 `strategy_versions_immutable`: update·delete를 `VERSION_IMMUTABLE`로 막는다.

- [ ] **Step 1: 실패하는 pgTAP 테스트 작성** (`plan(10)`)

```sql
select ok((public.create_strategy_version('<S>', '<def A AND B>')).version = 1, 'first version is 1');
select is((select jsonb_array_length(condition_refs) from public.strategy_versions where strategy_id='<S>'), 2, 'refs captured');
select throws_ok($$select public.create_strategy_version('<S>', '<def with other-profile cond>')$$, 'P0001', 'PROFILE_MISMATCH');
select throws_ok($$select public.create_strategy_version('<S>', '<def exchange A>')$$, 'P0001', 'INVALID_DEFINITION');
select throws_ok($$update public.strategy_versions set version = 9$$, 'P0001', 'VERSION_IMMUTABLE');
select is((public.request_run('search','<P>','<S>','<K1>')).id, (public.request_run('search','<P>','<S>','<K1>')).id, 'same key returns same run');
select throws_ok($$select public.request_run('search','<P>','<S>','<K2>')$$, 'P0001', 'PROFILE_BUSY');
select is((public.cancel_run('<run K1>')).status, 'cancelled', 'queued run cancellable');
-- 조건식 B를 비활성화(동기화로 교체된 상황) 후
select throws_ok($$select public.request_run('search','<P>','<S>','<K3>')$$, 'P0001', 'CONDITION_INACTIVE');
-- 사용자 B로 전환
select throws_ok($$select public.request_run('search','<P>','<S>','<K4>')$$, 'P0001', 'NOT_FOUND');
```

- [ ] **Step 2: 실패 확인**

Run: `pnpm db:test`
Expected: FAIL. `function public.create_strategy_version(uuid, jsonb) does not exist`

- [ ] **Step 3: `20261017000200_web_rpc.sql` 구현**

함수 안에서 `auth.uid()`로 소유권을 직접 확인한다(security definer라 RLS가 적용되지 않음). `anon`과 `public`의 `execute`는 회수한다.

- [ ] **Step 4: 통과 확인**

Run: `pnpm db:reset && pnpm db:test`
Expected: `002_web_rpc.test.sql .. ok`

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20261017000200_web_rpc.sql supabase/tests/002_web_rpc.test.sql
git commit -m "Gate strategy versions and run requests behind ownership-checked RPCs" -m "Tested: pnpm db:test (002_web_rpc)"
```

### Task 3: 워커 역할과 워커 RPC (선점, 리스, 확정, 실패)

**Files:**
- Create: `supabase/migrations/20261017000300_worker_rpc.sql`, `supabase/seed.sql`
- Test: `supabase/tests/003_worker_rpc.test.sql`

**Interfaces:**
- Consumes: Task 1·2
- Produces:
  - 역할 `kiwoom_worker`(마이그레이션에서는 `nologin`). 스키마 `worker`는 `kiwoom_worker`에만 `usage`·`execute`를 허용하고 `public`, `anon`, `authenticated`의 권한은 회수한다. `seed.sql`(로컬 전용)에서 `alter role kiwoom_worker with login password 'kiwoom-worker-local'`을 실행한다.
  - 테이블 `public.worker_heartbeats(worker_id text pk, aliases text[], version text, seen_at timestamptz)`: `authenticated`는 select만 가능하다.
  - 워커 함수가 넣는 모든 행의 `user_id`는 인자가 아니라 대상 run의 `user_id`에서 가져온다. 워커는 다른 사용자의 데이터를 만들 수 없다.
  - `worker.heartbeat(p_worker_id text, p_aliases text[], p_version text) returns void`
  - `worker.claim_next_run(p_worker_id text, p_aliases text[], p_lease_seconds int) returns jsonb`
    1. 리스가 만료된 `running` run을 정리한다. `attempt < max_attempts`이면 `queued`로 되돌리고, 아니면 `failed`(`LEASE_EXPIRED`)로 끝낸다.
    2. `alias = any(p_aliases)`인 가장 오래된 `queued` run을 `for update skip locked`로 1건 선점한다.
    3. 선점한 run은 `status='running'`, `attempt+1`, `lease_owner`, `lease_expires_at = now() + 리스 시간`, `started_at = coalesce(started_at, now())`로 바꾼다.
    4. 반환값: `{"run_id","kind","attempt","profile":{"id","alias","mode"},"definition","condition_refs"}`(sync 작업은 뒤의 두 키가 `null`). 선점할 run이 없으면 `null`
  - `worker.extend_lease(p_run_id uuid, p_worker_id text, p_lease_seconds int) returns boolean`
  - `worker.complete_search_run(p_run_id uuid, p_worker_id text, p_payload jsonb) returns boolean`. `p_payload` 형식:
    ```json
    {"window_start":"ISO","window_end":"ISO","market_phase":"weekend",
     "snapshots":[{"condition_id":"uuid","seq":"1","name":"…","started_at":"ISO","completed_at":"ISO","page_count":1,
                   "members":[{"code":"0010F0","raw_code":"A0010F0","instrument_type":"stock","name":"보원케미칼","price":3195,"change_rate":"6.86"}]}],
     "results":[{"code":"0010F0","matched_condition_ids":["uuid"]}],
     "excluded_codes":["000660"]}
    ```
    - run이 `running`이고 `lease_owner = p_worker_id`이고 리스가 남아 있을 때만 확정하고 `true`를 반환한다. 아니면 아무것도 쓰지 않고 `false`를 반환한다.
    - 결과의 `name`·`instrument_type`·`price`·`change_rate`는 `matched_condition_ids` 순서상 첫 스냅샷 멤버에서 가져온다. 어떤 스냅샷 멤버에도 없는 결과 코드가 있으면 `PAYLOAD_INVALID`
    - `diff`: 같은 전략·같은 프로필의 직전 `succeeded` run(`finished_at` 최신)에 그 코드가 있으면 `kept`, 없으면 `new`. 그 run을 `compared_run_id`로 기록한다.
    - 그 밖에 `result_count`, `excluded_codes`, 수집 구간, `market_phase`, `status='succeeded'`, `finished_at`을 저장한다. 프로필은 `last_ok_at = now()`로 바꾸고 `last_error_*`를 비운다.
  - `worker.complete_sync_run(p_run_id uuid, p_worker_id text, p_items jsonb) returns jsonb`(`[{seq,name}]`을 받아 `{added,removed,replaced,unchanged}`를 반환하고 `runs.sync_summary`에도 저장). 리스 조건은 위와 같다.
    - 활성 행 중 `(seq, name)`이 입력과 일치하면 `last_synced_at`만 갱신한다.
    - 일치하지 않는 활성 행은 비활성화한다. 같은 `seq`에 다른 이름이 들어오면 `replaced`(old_name, new_name), 아니면 `removed`
    - 남은 입력은 새 행으로 넣는다(`replaced`로 이미 기록된 seq는 `added` 이벤트를 남기지 않는다).
  - `worker.fail_run(p_run_id uuid, p_worker_id text, p_error_code text, p_error_message text, p_retryable boolean, p_partial jsonb) returns text`(바뀐 상태를 반환)
    - 리스를 가진 워커만 호출할 수 있다.
    - `p_retryable`이고 `attempt < max_attempts`이면 `queued`(리스 해제). 아니면 `RUN_TIMEOUT`은 `timed_out`, 그 외는 `failed`
    - `p_partial`(`[{condition_id,seq,name,started_at,completed_at,page_count,row_count,error_code}]`)은 `is_complete=false` 스냅샷(멤버 없음)으로 저장한다. 프로필의 `last_error_code·message`를 갱신한다.

- [ ] **Step 1: 실패하는 pgTAP 테스트 작성** (`plan(12)`, 워커 호출은 `set local role kiwoom_worker`)

```sql
select is(worker.claim_next_run('w1', array['other'], 60), null, 'alias filter respected');
select is((worker.claim_next_run('w1', array['demo-a'], 60))->>'kind', 'search', 'claims queued search run');
select is(worker.claim_next_run('w2', array['demo-a'], 60), null, 'running run not double-claimed');
select ok(not worker.complete_search_run('<R>', 'w2', '<payload>'), 'non-owner cannot complete');
select is((select count(*) from public.run_results where run_id='<R>'), 0::bigint, 'nothing written by non-owner');
select ok(worker.complete_search_run('<R>', 'w1', '<payload 002 matched A,B>'), 'owner completes');
select is((select diff from public.run_results where run_id='<R>' and code='002'), 'new', 'first run diff is new');
-- 두 번째 run을 같은 결과로 확정한 뒤
select is((select diff from public.run_results where run_id='<R2>' and code='002'), 'kept', 'second run diff is kept');
select ok(worker.complete_search_run('<R3>', 'w1', '<payload with results []>'), 'empty result succeeds');
select is((select result_count from public.runs where id='<R3>'), 0, 'zero count recorded');
select is(worker.fail_run('<R4>','w1','RATE_LIMITED','…',true,'[]'), 'queued', 'retryable requeues');
select is((worker.complete_sync_run('<SYNC>','w1','[{"seq":"0","name":"A"},{"seq":"1","name":"B2"}]'))->>'replaced', '1', 'renamed seq recorded as replaced');
```

추가 사항:
- 리스 만료 테스트: `update runs set lease_expires_at = now() - interval '1 second'` 뒤 다시 `claim`하면 `attempt = 2`로 다시 선점된다.
- `authenticated` 역할로 `worker.claim_next_run`을 호출하면 `42501`이 나야 한다.

- [ ] **Step 2: 실패 확인**

Run: `pnpm db:test`
Expected: FAIL. `schema "worker" does not exist`

- [ ] **Step 3: `20261017000300_worker_rpc.sql`, `seed.sql` 구현**

- [ ] **Step 4: 통과 확인**

Run: `pnpm db:reset && pnpm db:test`
Expected: 001~003 모두 `ok`

- [ ] **Step 5: Commit**

```bash
git add supabase/
git commit -m "Let a least-privilege worker role claim, lease and atomically settle runs" -m "Tested: pnpm db:test (003_worker_rpc)"
```

---

## Part B — Python 워커

### Task 4: 공용 계약 케이스와 Python 표현식 코어

**Files:**
- Create: `packages/contracts/README.md`, `packages/contracts/cases/validate.json`, `packages/contracts/cases/evaluate.json`
- Create: `apps/worker/pyproject.toml`, `apps/worker/.python-version`(`3.13`), `apps/worker/src/kiwoom_worker/__init__.py`, `apps/worker/src/kiwoom_worker/core/__init__.py`, `apps/worker/src/kiwoom_worker/core/expr.py`
- Test: `apps/worker/tests/test_expr_contracts.py`

**Interfaces:**
- Produces(`kiwoom_worker.core.expr`):
  - `MAX_DEPTH = 5`, `MAX_LEAVES = 10`
  - `@dataclass(frozen=True) class ConditionInfo: profile_id: str; active: bool`
  - `validate_definition(definition: object, conditions: Mapping[str, ConditionInfo]) -> list[str]`: 정렬·중복 제거된 문제 코드 목록. 코드 종류: `SCHEMA_INVALID`, `TOO_FEW_CHILDREN`, `EMPTY_SUBTRACT`, `MAX_DEPTH_EXCEEDED`, `MAX_LEAVES_EXCEEDED`, `UNKNOWN_CONDITION`, `INACTIVE_CONDITION`, `PROFILE_MISMATCH`
    - 모양 검사(`SCHEMA_INVALID`): 키 누락, 정의되지 않은 키, 잘못된 타입, `schemaVersion≠1`, `exchange≠"K"`, 알 수 없는 `type`
    - 개수 규칙은 해당 전용 코드로 보고한다.
    - 리프 조건식의 `profile_id`가 `definition["profileId"]`와 다르면 `PROFILE_MISMATCH`, `conditions`에 없으면 `UNKNOWN_CONDITION`, `active`가 거짓이면 `INACTIVE_CONDITION`
    - 모양 검사에 실패하면 `["SCHEMA_INVALID"]`만 반환한다(다른 규칙은 검사하지 않음).
  - `leaf_condition_ids(expr: Mapping[str, Any]) -> list[str]`: DFS 순서, 중복 제거
  - `@dataclass(frozen=True) class EvalResult: codes: list[str]; matches: dict[str, list[str]]; excluded: list[str]`
  - `evaluate(expr: Mapping[str, Any], sets: Mapping[str, frozenset[str]]) -> EvalResult`
    - `and`=교집합, `or`=합집합, `exclude`=`base − ∪subtract`
    - `codes`는 오름차순이다. `matches[code]`는 그 코드를 포함한 리프 ID 목록(DFS 순서)이다.
    - `excluded` = (모든 exclude 노드의 `eval(base) ∩ ∪subtract`의 합집합) − 최종 결과, 오름차순
- 케이스 파일 형식(README에 명시):
  - `validate.json`: `{"cases":[{"name","definition","conditions":{"<id>":{"profileId","active"}},"issues":[...]}]}`
  - `evaluate.json`: `{"cases":[{"name","expr","sets":{"<id>":[codes]},"expected":{"codes","matches","excluded"}}]}`
- `pyproject.toml`:
  - 패키지 `kiwoom-worker`, `requires-python = ">=3.12"`
  - deps: `websockets>=15,<18`, `httpx>=0.28,<0.29`, `psycopg[binary]>=3.3,<3.4`
  - dev 그룹: `pytest>=9`, `pytest-asyncio>=1.4`, `ruff>=0.17`
  - `[project.scripts] kiwoom-worker = "kiwoom_worker.main:cli"`
  - `[tool.pytest.ini_options] asyncio_mode = "auto"`, `markers = ["db: needs local Supabase"]`

- [ ] **Step 1: 계약 케이스 작성**

`evaluate.json` 필수 케이스(A=`["001","002"]`, B=`["002","003"]`, C=`["003","0010F0"]`):

| name | expr | expected.codes | 비고 |
| --- | --- | --- | --- |
| `and` | A AND B | `["002"]` | matches `{"002":["A","B"]}` |
| `or` | A OR B | `["001","002","003"]` | |
| `exclude` | A EXCLUDE [B] | `["001"]` | excluded `["002"]` |
| `exclude_multi` | A EXCLUDE [B, C] | `["001"]` | |
| `nested` | A AND (B OR C) | `["002"]` | |
| `empty_set` | A AND D(D=`[]`) | `[]` | |
| `duplicate_leaf` | A OR A | `["001","002"]` | matches에 A 한 번만 |
| `alnum_sort` | C OR A | `["001","0010F0","002","003"]` | 문자열 오름차순 |

`validate.json` 필수 케이스:
- 유효(중복 리프 포함)
- 자식 1개인 `and` → `TOO_FEW_CHILDREN`
- 빈 `subtract` → `EMPTY_SUBTRACT`
- 깊이 6 → `MAX_DEPTH_EXCEEDED`
- 리프 11개 → `MAX_LEAVES_EXCEEDED`
- 없는 ID → `UNKNOWN_CONDITION`
- 비활성 → `INACTIVE_CONDITION`
- 다른 프로필 → `PROFILE_MISMATCH`
- `SCHEMA_INVALID` 4건: `schemaVersion: 2`, `exchange: "A"`, 정의되지 않은 키 `"extra"`, `type: "not"`

- [ ] **Step 2: 실패하는 테스트 작성**

```python
CASES = Path(__file__).parents[3] / "packages/contracts/cases"

@pytest.mark.parametrize("case", load(CASES / "validate.json"), ids=lambda c: c["name"])
def test_validate_matches_contract(case):
    conds = {k: ConditionInfo(v["profileId"], v["active"]) for k, v in case["conditions"].items()}
    assert validate_definition(case["definition"], conds) == case["issues"]

@pytest.mark.parametrize("case", load(CASES / "evaluate.json"), ids=lambda c: c["name"])
def test_evaluate_matches_contract(case):
    result = evaluate(case["expr"], {k: frozenset(v) for k, v in case["sets"].items()})
    assert (result.codes, result.matches, result.excluded) == (
        case["expected"]["codes"], case["expected"]["matches"], case["expected"]["excluded"])

def test_leaf_ids_dfs_unique():
    assert leaf_condition_ids(and_(cond("A"), or_(cond("B"), cond("A")))) == ["A", "B"]
```

- [ ] **Step 3: 실패 확인**

Run: `cd apps/worker && uv sync && uv run pytest tests/test_expr_contracts.py -v`
Expected: FAIL. `ModuleNotFoundError: kiwoom_worker.core.expr`

- [ ] **Step 4: `expr.py` 구현**

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_expr_contracts.py -v && uv run ruff check`
Expected: 전부 PASS, ruff 문제 없음

- [ ] **Step 6: Commit**

```bash
git add packages/contracts apps/worker
git commit -m "Pin strategy semantics in shared contract cases and a Python evaluator" -m "Tested: uv run pytest tests/test_expr_contracts.py"
```

### Task 5: 키움 응답 파싱, 오류 분류, 호출 허용 목록

**Files:**
- Create: `apps/worker/src/kiwoom_worker/kiwoom/__init__.py`, `parse.py`, `errors.py`, `allowlist.py`
- Create: `apps/worker/tests/fixtures/phase0_cnsrreq_seq1.json`(출처: `scripts/phase0/output/20261017-135943/fixtures.json`의 `kiwoom-real-vibe.1` 메시지. 비밀정보가 없는지 확인한 뒤 복사)
- Test: `apps/worker/tests/test_parse.py`, `test_errors.py`, `test_allowlist.py`

**Interfaces:**
- Produces:
  - `parse.normalize_code(raw: str) -> tuple[str, str]`: `(code, instrument_type)`. 형식이 틀리면 `InvalidCode(ValueError)`
  - `parse.parse_signed_int(value: str | None) -> int | None`
  - `parse.parse_change_rate(value: str | None) -> Decimal | None`: 부호 있는 정수 ÷ 100, 소수 2자리
  - `@dataclass(frozen=True) class Member: code: str; raw_code: str; instrument_type: str; name: str | None; price: int | None; change_rate: Decimal | None`
  - `parse.parse_member(row: Mapping[str, object]) -> Member`: `price = abs(parse_signed_int(row["10"]))`
  - `errors.ErrorClass(StrEnum)`: `RATE_LIMIT`, `TOKEN_EXPIRED`, `IP_DEVICE`, `CONFIG`, `CONDITION_MISSING`, `INPUT`, `TRANSIENT`, `UNKNOWN`
  - `errors.resolve_return_code(return_code: object, return_msg: object) -> int | None`: 최상위 코드가 아래 표에 없으면 메시지 안의 `[dddd:` 또는 `CODE=dddd`를 쓴다.
  - `errors.classify(code: int) -> ErrorClass`

    | 분류 | 코드 |
    | --- | --- |
    | `RATE_LIMIT` | `{105110,1700,1701,1702}` |
    | `TOKEN_EXPIRED` | `{8005}` |
    | `IP_DEVICE` | `{8010,8040,8050,8103}` |
    | `CONFIG` | `{8001,8002,8030,8031,8104,900001}` |
    | `CONDITION_MISSING` | `{900004}` |
    | `INPUT` | 1500~1599 |
    | `TRANSIENT` | `{1999}` |
    | `UNKNOWN` | 그 외 |

  - `class KiwoomApiError(Exception)`: `return_code: int`, `error_class: ErrorClass`, `message: str`
  - `allowlist.ALLOWED_API_IDS = frozenset({"au10001","au10002","ka10171","ka10172"})`, `ALLOWED_TRNM = frozenset({"LOGIN","PING","CNSRLST","CNSRREQ"})`
  - `allowlist.assert_outgoing_allowed(packet: Mapping[str, object]) -> None`: 허용되지 않은 `trnm`, `CNSRREQ`의 `search_type≠"0"`, `stex_tp≠"K"`이면 `ForbiddenRequest`
  - `allowlist.assert_api_id_allowed(api_id: str) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_normalize_alnum_code(): assert normalize_code("A0010F0") == ("0010F0", "stock")
def test_normalize_prefixes(): assert [normalize_code(c)[1] for c in ("A005930","J123456","Q500001")] == ["stock","elw","etn"]
def test_normalize_rejects_bad(): pytest.raises(InvalidCode, normalize_code, "A00593")
def test_change_rate_8_digit(): assert parse_change_rate("00000686") == Decimal("6.86")
def test_change_rate_negative(): assert parse_change_rate("-0000252") == Decimal("-2.52")
def test_change_rate_9_digit_spec(): assert parse_change_rate("000001500") == Decimal("15.00")
def test_phase0_fixture_parses():
    msg = json.loads(FIXTURE.read_text()); members = [parse_member(r) for r in msg["data"]]
    assert len(members) == 28 and members[0] == Member("0010F0","A0010F0","stock","보원케미칼",3195,Decimal("6.86"))
def test_classify_table(): assert classify(105110) is ErrorClass.RATE_LIMIT and classify(900004) is ErrorClass.CONDITION_MISSING and classify(8010) is ErrorClass.IP_DEVICE
def test_embedded_code(): assert resolve_return_code(3, "[8005:Token이 유효하지 않습니다]") == 8005
def test_forbid_realtime(): pytest.raises(ForbiddenRequest, assert_outgoing_allowed, {"trnm":"CNSRREQ","seq":"1","search_type":"1","stex_tp":"K"})
def test_forbid_clear(): pytest.raises(ForbiddenRequest, assert_outgoing_allowed, {"trnm":"CNSRCLR","seq":"1"})
def test_forbid_order_api(): pytest.raises(ForbiddenRequest, assert_api_id_allowed, "kt10000")
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_parse.py tests/test_errors.py tests/test_allowlist.py -v`
Expected: FAIL. `ModuleNotFoundError`

- [ ] **Step 3: `parse.py`, `errors.py`, `allowlist.py` 구현**

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add apps/worker
git commit -m "Classify Kiwoom return codes and hard-block non-allowlisted requests" -m "Tested: uv run pytest (parse, errors, allowlist; phase0 fixture)"
```

### Task 6: 시계 추상화와 토큰 발급

**Files:**
- Create: `apps/worker/src/kiwoom_worker/clock.py`, `apps/worker/src/kiwoom_worker/kiwoom/token.py`, `apps/worker/tests/fakes.py`
- Test: `apps/worker/tests/test_token.py`

**Interfaces:**
- Consumes: `errors.KiwoomApiError`, `errors.resolve_return_code`, `errors.classify`, `allowlist.assert_api_id_allowed`
- Produces:
  - `clock.Clock(Protocol)`: `monotonic() -> float`, `now() -> datetime`(UTC aware), `async sleep(seconds: float) -> None`. 구현은 `clock.SystemClock`
  - `tests/fakes.FakeClock(start: datetime)`: `sleep`이 대기하지 않고 시각만 앞당긴다. `slept: list[float]`
  - `token.Credentials`(frozen dataclass): `alias: str`, `mode: Literal["real","demo"]`, `appkey: str`, `secretkey: str`. `__repr__`에 키가 나오지 않게 한다.
  - `token.BASE_URLS = {"real": "https://api.kiwoom.com", "demo": "https://mockapi.kiwoom.com"}`
  - `token.WS_URLS = {"real": "wss://api.kiwoom.com:10000/api/dostk/websocket", "demo": "wss://mockapi.kiwoom.com:10000/api/dostk/websocket"}`
  - `token.TokenProvider(client: httpx.AsyncClient, clock: Clock, refresh_margin_s: float = 300)`
    - `async get(creds: Credentials, *, force_refresh: bool = False) -> str`
    - 요청: `POST {BASE_URLS[mode]}/oauth2/token`, 헤더 `api-id: au10001`, `Content-Type: application/json;charset=UTF-8`, 본문 `{"grant_type":"client_credentials","appkey","secretkey"}`
    - 응답의 `token`과 `expires_dt`를 쓴다. `expires_dt`는 `%Y%m%d%H%M%S` 형식의 KST다.
    - 별칭별로 메모리에 캐시한다.

- [ ] **Step 1: 실패하는 테스트 작성** (`httpx.MockTransport` 사용)

```python
async def test_token_cached_until_margin(): ...  # 두 번 get → 요청 1회
async def test_token_refreshed_inside_margin(): ...  # 만료 4분 전 → 재요청
async def test_force_refresh(): ...  # force_refresh=True → 재요청
async def test_request_shape(): ...  # 헤더 api-id=au10001, 본문 grant_type=client_credentials
async def test_error_8001_is_config():
    with pytest.raises(KiwoomApiError) as e: await provider.get(creds)
    assert e.value.error_class is ErrorClass.CONFIG and creds.secretkey not in str(e.value)
def test_credentials_repr_hides_keys(): assert "secret" not in repr(Credentials("a","demo","key","secret"))
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_token.py -v`
Expected: FAIL

- [ ] **Step 3: `clock.py`, `token.py`, `fakes.FakeClock` 구현**

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/worker
git commit -m "Issue and cache Kiwoom access tokens per profile without leaking keys" -m "Tested: uv run pytest tests/test_token.py (MockTransport)"
```

### Task 7: 조건검색 WebSocket 세션

**Files:**
- Create: `apps/worker/src/kiwoom_worker/kiwoom/transport.py`, `apps/worker/src/kiwoom_worker/kiwoom/session.py`
- Modify: `apps/worker/tests/fakes.py`(`ScriptedTransport` 추가)
- Test: `apps/worker/tests/test_session.py`

**Interfaces:**
- Consumes: `parse.parse_member`, `parse.Member`, `errors.*`, `allowlist.assert_outgoing_allowed`, `clock.Clock`
- Produces:
  - `transport.Transport(Protocol)`: `async send(text: str) -> None`, `async recv(timeout: float) -> str`(시간 초과 시 `ResponseTimeout`), `async close() -> None`
  - `transport.open_websocket(url: str, *, open_timeout: float = 10) -> Transport`: `websockets.connect(url, ping_interval=None)`를 쓴다.
  - 예외(모두 `session.py`): `ProtocolError`, `ResponseTimeout`, `IncompletePagination`
  - `@dataclass(frozen=True) class ConditionItem: seq: str; name: str`
  - `@dataclass(frozen=True) class SearchResult: seq: str; started_at: datetime; completed_at: datetime; page_count: int; members: list[Member]`: 코드 기준으로 중복을 제거하며, 먼저 나온 행을 남긴다.
  - `ConditionSession(transport, *, clock, request_interval_s=0.25, response_timeout_s=10.0, max_pages=50, rate_limit_retries=3)`
    - `async login(token: str) -> None`
    - `async list_conditions() -> list[ConditionItem]`
    - `async search(seq: str) -> SearchResult`
    - 규칙:
      - 모든 송신 전에 `assert_outgoing_allowed`를 호출한다.
      - 수신한 `PING`은 그대로 되돌려 보내고 건너뛴다.
      - `CNSRLST` 전에 `search`를 부르면 `ProtocolError("CNSRLST_REQUIRED")`
      - `CNSRREQ` 송신 간격은 `request_interval_s` 이상으로 유지한다.
      - 데이터 응답은 `trnm=="CNSRREQ"`이고 `seq`가 같아야 받아들인다. bare 메시지와 다른 `seq`의 응답은 건너뛴다.
      - `return_code≠0`이면 `resolve_return_code`·`classify`를 거쳐 처리한다. `RATE_LIMIT`은 `1.0 * 2**n`초(n=0,1,2) 기다린 뒤 같은 페이지를 다시 요청하고, 횟수를 넘으면 `KiwoomApiError`
      - `cont_yn=="Y"`이면 같은 연결에서 `cont_yn:"Y"`, `next_key`를 붙여 다음 페이지를 요청한다. `next_key`가 비었거나 `max_pages`를 넘으면 `IncompletePagination`

- [ ] **Step 1: `ScriptedTransport` 작성**

`ScriptedTransport(responder: Callable[[dict], list[str | dict]])`: 송신 패킷마다 응답 목록을 큐에 넣는다. `sent: list[dict]`, `send_times: list[float]`(FakeClock 기준)을 기록한다.

- [ ] **Step 2: 실패하는 테스트 작성**

```python
async def test_login_sends_token_and_accepts_ack()
async def test_login_error_8010_is_ip_device()
async def test_ping_is_echoed()                       # sent[-1] == {"trnm":"PING"}
async def test_search_before_list_raises()            # ProtocolError CNSRLST_REQUIRED
async def test_list_parses_array_rows()               # [ConditionItem("0","급등주포착검색"), ...]
async def test_bare_message_skipped()                 # 응답: [{"trnm":"CNSRREQ"}, data seq=1] → members 28
async def test_stale_other_seq_ignored()              # 응답: [data seq=0, data seq=1] 요청 seq=1 → seq 1 결과
async def test_null_data_is_zero_rows()               # data None, cont_yn N → members == [], page_count 1
async def test_pagination_same_connection()           # 2페이지 → sent[2] has cont_yn "Y", next_key "k1"; 중복 코드 1회
async def test_cont_y_without_next_key_incomplete()
async def test_max_pages_incomplete()
async def test_rate_limit_then_success()              # 105110 후 데이터 → clock.slept[0] >= 1.0
async def test_rate_limit_exhausted()                 # 105110 ×4 → KiwoomApiError RATE_LIMIT
async def test_error_without_seq_attributed()         # 900004 → KiwoomApiError CONDITION_MISSING
async def test_requests_spaced()                      # send_times[2] - send_times[1] >= 0.25
async def test_response_timeout()
async def test_all_packets_allowlisted()              # 모든 CNSRREQ에 search_type "0", stex_tp "K"
```

- [ ] **Step 3: 실패 확인**

Run: `uv run pytest tests/test_session.py -v`
Expected: FAIL

- [ ] **Step 4: `transport.py`, `session.py` 구현**

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest -v && uv run ruff check`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/worker
git commit -m "Run condition searches one at a time with seq matching and paging" -m "Tested: uv run pytest tests/test_session.py (scripted transport, phase0 behaviors)" -m "Not-tested: live Kiwoom continuation (cont_yn=Y not yet observed)"
```

### Task 8: 실행 오케스트레이션 (`execute_search`, `execute_sync`)

**Files:**
- Create: `apps/worker/src/kiwoom_worker/runner.py`
- Test: `apps/worker/tests/test_runner.py`

**Interfaces:**
- Consumes: `core.expr.validate_definition/evaluate/leaf_condition_ids/ConditionInfo`, `ConditionSession`, `SearchResult`, 예외들, Task 3의 payload 형식
- Produces:
  - `@dataclass(frozen=True) class ConditionRefSnapshot: condition_id: str; seq: str; name: str`
  - `@dataclass(frozen=True) class SearchJob: run_id: str; profile_id: str; definition: dict[str, Any]; condition_refs: list[ConditionRefSnapshot]`
  - `SessionOpener = Callable[[bool], AbstractAsyncContextManager[ConditionSession]]`: 인자는 `force_token_refresh`. 반환하는 세션은 이미 `login`된 상태다.
  - `class RunFailure(Exception)`: `code: str`, `retryable: bool`, `message: str`, `partial: list[dict]`(Task 3의 `p_partial` 형식)
  - `to_run_failure(exc: BaseException, partial: list[dict]) -> RunFailure`

    | 예외 | code | retryable |
    | --- | --- | --- |
    | `RATE_LIMIT` | `RATE_LIMITED` | 예 |
    | `TOKEN_EXPIRED` | `TOKEN_INVALID` | 아니오 |
    | `IP_DEVICE` | `IP_DEVICE_AUTH` | 아니오 |
    | `CONFIG` | `PROFILE_CONFIG` | 아니오 |
    | `CONDITION_MISSING` | `CONDITION_CHANGED` | 아니오 |
    | `INPUT` | `KIWOOM_INPUT` | 아니오 |
    | `TRANSIENT`, `OSError`·연결 끊김 | `KIWOOM_TRANSIENT` | 예 |
    | `ResponseTimeout` | `RESPONSE_TIMEOUT` | 예 |
    | `IncompletePagination` | `INCOMPLETE_PAGINATION` | 예 |
    | `ProtocolError` | `KIWOOM_PROTOCOL` | 아니오 |
    | `UNKNOWN` | `KIWOOM_UNKNOWN` | 아니오 |

  - `market_phase(at: datetime) -> Literal["pre","regular","post","weekend"]`: KST 기준
  - `async execute_search(job: SearchJob, open_session: SessionOpener, clock: Clock) -> dict`: Task 3 `p_payload`를 반환하고 실패 시 `RunFailure`
    1. 표현식 검증(모든 ref는 `ConditionInfo(job.profile_id, True)`). 문제가 있으면 `INVALID_DEFINITION`(재시도 안 함)
    2. 세션을 열고 `list_conditions`
    3. 리프마다 `(seq, name)`이 목록과 같은지 확인한다. 다르면 `CONDITION_CHANGED`(메시지에 seq와 기대·실제 이름 포함)를 내고, `CNSRREQ`는 보내지 않는다.
    4. 고유 리프를 DFS 순서로 `search`
    5. `evaluate`
    6. payload를 만든다(`window_start`=첫 search 시작, `window_end`=마지막 완료, `market_phase(window_start)`).
    - `TOKEN_EXPIRED`는 `open_session(True)`로 실행 전체를 1회만 다시 시도한다.
    - 실패하면 완료된 조건식과 실패한 조건식을 `partial`로 넘긴다.
  - `async execute_sync(open_session: SessionOpener) -> list[dict]`: `[{"seq","name"}]`

- [ ] **Step 1: 실패하는 테스트 작성** (가짜 세션 사용)

```python
async def test_payload_for_and():           # A={001,002}, B={002,003}, AND → results == [{"code":"002","matched_condition_ids":["A","B"]}], snapshots 2개
async def test_renamed_condition_fails_before_search():  # RunFailure CONDITION_CHANGED, retryable False, session.searched == []
async def test_900004_maps_condition_changed()
async def test_duplicate_leaf_searched_once()            # session.searched == ["0"]
async def test_token_expired_retries_once_with_refresh() # opener 호출 인자 [False, True]
async def test_incomplete_pagination_retryable_with_partial()  # partial의 완료 항목은 row_count 포함, 실패 항목은 error_code "INCOMPLETE_PAGINATION"
async def test_ip_device_not_retryable()
async def test_excluded_codes_in_payload()               # A EXCLUDE [B] → excluded_codes ["002"]
async def test_invalid_definition_not_retryable()
def test_market_phase_boundaries():
    kst = ZoneInfo("Asia/Seoul")
    assert [market_phase(datetime(2026,10,19,h,m,tzinfo=kst)) for h,m in [(8,59),(9,0),(15,29),(15,30)]] == ["pre","regular","regular","post"]
    assert market_phase(datetime(2026,10,17,12,0,tzinfo=kst)) == "weekend"
async def test_execute_sync_returns_items()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL

- [ ] **Step 3: `runner.py` 구현**

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/worker
git commit -m "Refuse runs whose conditions changed and settle the rest into one payload" -m "Tested: uv run pytest tests/test_runner.py"
```

### Task 9: 설정, DB 어댑터, 워커 루프, fixture 전송

**Files:**
- Create: `apps/worker/src/kiwoom_worker/config.py`, `db.py`, `log.py`, `main.py`, `kiwoom/fixture.py`, `apps/worker/profiles.example.toml`
- Create: `apps/worker/tests/fixtures/e2e_market.json`
- Test: `apps/worker/tests/test_config.py`, `test_main.py`, `test_fixture.py`, `test_log.py`, `apps/worker/tests/integration/test_postgres_db.py`

**Interfaces:**
- Consumes: Task 3 함수, Task 6~8의 모든 Produces
- Produces:
  - `config.WorkerSettings`(frozen dataclass). 환경변수와 기본값:

    | 필드 | 환경변수 | 기본값 |
    | --- | --- | --- |
    | `database_url` | `KIWOOM_WORKER_DATABASE_URL` | 필수 |
    | `worker_id` | `KIWOOM_WORKER_ID` | 필수 |
    | `profiles_file` | `KIWOOM_WORKER_PROFILES_FILE` | 필수 |
    | `transport` | `KIWOOM_WORKER_TRANSPORT` | `"live"`(`"fixture"` 가능) |
    | `fixture_file` | `KIWOOM_WORKER_FIXTURE_FILE` | 없음 |
    | `poll_interval_s` | `KIWOOM_WORKER_POLL_INTERVAL_S` | `3.0` |
    | `heartbeat_interval_s` | `KIWOOM_WORKER_HEARTBEAT_INTERVAL_S` | `15.0` |
    | `lease_seconds` | `KIWOOM_WORKER_LEASE_SECONDS` | `60` |
    | `request_interval_s` | `KIWOOM_WORKER_REQUEST_INTERVAL_S` | `0.25` |
    | `response_timeout_s` | `KIWOOM_WORKER_RESPONSE_TIMEOUT_S` | `10.0` |
    | `max_pages` | `KIWOOM_WORKER_MAX_PAGES` | `50` |
    | `rate_limit_retries` | `KIWOOM_WORKER_RATE_LIMIT_RETRIES` | `3` |
    | `run_timeout_s` | `KIWOOM_WORKER_RUN_TIMEOUT_S` | `120.0` |

  - `config.load_settings(env: Mapping[str, str]) -> WorkerSettings`: `transport == "fixture"`인데 DB 호스트가 `localhost`·`127.0.0.1`이 아니면 `ConfigError`
  - `config.load_profiles(path: Path) -> dict[str, Credentials]`: TOML `[profiles.<alias>] mode, appkey, secretkey`. 파일 권한이 `0o600`보다 넓으면 `ConfigError`
  - `db.ClaimedRun`(frozen dataclass): `run_id`, `kind`, `attempt`, `profile_id`, `alias`, `mode`, `definition: dict | None`, `condition_refs: list[ConditionRefSnapshot]`. DB의 `condition_refs` 키 `conditionId`·`seq`·`name`을 `condition_id`·`seq`·`name`으로 바꾼다.
  - `db.WorkerDb(Protocol)`:
    - `heartbeat(worker_id, aliases, version) -> None`
    - `claim(worker_id, aliases, lease_seconds) -> ClaimedRun | None`
    - `extend_lease(run_id, worker_id, lease_seconds) -> bool`
    - `complete_search(run_id, worker_id, payload) -> bool`
    - `complete_sync(run_id, worker_id, items) -> dict | None`
    - `fail(run_id, worker_id, failure: RunFailure) -> str`
    - 모두 async다. 구현 `db.PostgresWorkerDb.connect(url) -> PostgresWorkerDb`는 psycopg `AsyncConnection`(autocommit)으로 `select worker.<fn>(...)`을 부르고 jsonb를 `Jsonb`로 넘긴다.
  - `log.RedactingFilter(secrets: Iterable[str])`: 로그 메시지와 인자 속 비밀값을 `***`로 바꾼다.
  - `kiwoom/fixture.FixtureTransport(market: dict)`: `{"conditions":[[seq,name]],"results":{"<seq>":[rows]}}`로 LOGIN·CNSRLST·CNSRREQ를 흉내 낸다. 0단계에서 관찰한 순서(두 번째 요청부터 bare 메시지가 먼저 옴)를 재현한다.
  - `main.process_one(db, settings, profiles, open_session_for, clock) -> bool`
    - 처리할 run이 없으면 `False`
    - 프로필의 로컬 `mode`가 DB의 `mode`와 다르면 `fail(PROFILE_CONFIG, retryable=False)`
    - 실행하는 동안 `lease_seconds/3` 간격으로 `extend_lease`
    - `asyncio.timeout(run_timeout_s)`를 넘으면 `RUN_TIMEOUT`(재시도 안 함)
    - `complete_*`가 `False`(리스 잃음)를 반환하면 경고 로그만 남기고 `fail`은 부르지 않는다.
  - `main.run_worker(settings, db, open_session_for, clock, stop: asyncio.Event) -> None`: `heartbeat_interval_s` 간격으로 heartbeat를 보내고, 처리할 run이 없으면 `poll_interval_s` 동안 쉰다.
  - `main.cli() -> None`: 환경 로드, 로깅(`RedactingFilter`), SIGTERM·SIGINT 수신 시 `stop` 설정. live 모드는 `TokenProvider` + `open_websocket`, fixture 모드는 `FixtureTransport`를 쓴다.
- `e2e_market.json`(Task 15에서 사용):
  - conditions: `[["0","기본종목"],["1","전일고가돌파"],["2","골든크로스"]]`
  - seq 0: `A005930` 삼성전자, `A0010F0` 보원케미칼, `A000660` SK하이닉스
  - seq 1: `A005930`, `A035720` `카카오, 테스트`
  - seq 2: `A0010F0`(등락률 `-0000252`)

- [ ] **Step 1: 실패하는 단위 테스트 작성** (가짜 DB 사용)

```python
async def test_process_one_completes_search()        # db.completed[0][0] == run_id
async def test_lease_lost_is_logged_not_failed()     # complete_search False → db.failed == []
async def test_mode_mismatch_fails_profile_config()
async def test_run_timeout_marks_timed_out()         # failure.code == "RUN_TIMEOUT" and not failure.retryable
async def test_lease_extended_during_run()           # 느린 세션 → extend 호출 ≥ 1
async def test_sync_job_completes_with_items()
def test_profiles_file_must_be_0600(tmp_path)
def test_fixture_transport_requires_local_db()
def test_redacting_filter_masks_secret()
async def test_fixture_transport_sends_bare_before_second_response()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest -m "not db" -v`
Expected: FAIL

- [ ] **Step 3: `config.py`, `db.py`, `log.py`, `fixture.py`, `main.py`, `profiles.example.toml` 구현**

- [ ] **Step 4: 단위 테스트 통과 확인**

Run: `uv run pytest -m "not db" -v && uv run ruff check`
Expected: PASS

- [ ] **Step 5: 통합 테스트 작성**

`tests/integration/test_postgres_db.py`, `@pytest.mark.db`. 관리자 URL로 사용자·프로필(`alias='it-demo'`)·전략 버전·run을 만든 뒤, 워커 URL로 다음을 확인한다.
- `claim` → `complete_search` 왕복: `run_results`에 행이 생긴다.
- `fail(retryable=True)`이면 상태가 `queued`로 돌아간다.

- [ ] **Step 6: 통합 테스트 실행**

Run:
```bash
KIWOOM_WORKER_TEST_DATABASE_URL=postgresql://kiwoom_worker:kiwoom-worker-local@127.0.0.1:54322/postgres \
KIWOOM_WORKER_TEST_ADMIN_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres \
uv run pytest -m db -v
```
Expected: PASS(먼저 `pnpm db:reset`)

- [ ] **Step 7: Commit**

```bash
git add apps/worker
git commit -m "Run the worker loop with leases, timeouts and a local-only fixture transport" -m "Tested: uv run pytest (unit + -m db against local Supabase)" -m "Not-tested: live Kiwoom from worker host"
```

---

## Part C — Next.js 웹

### Task 10: 웹 스캐폴드, Supabase SSR 인증, 로그인

**Files:**
- Create: `apps/web/`(`pnpm create next-app@16 apps/web --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --use-pnpm`)
- Create: `apps/web/src/lib/supabase/server.ts`, `client.ts`, `proxy.ts`, `apps/web/src/proxy.ts`, `apps/web/src/lib/auth/paths.ts`, `apps/web/src/app/login/page.tsx`, `apps/web/src/app/login/actions.ts`, `apps/web/src/app/(app)/layout.tsx`, `apps/web/src/app/page.tsx`, `apps/web/.env.example`, `apps/web/vitest.config.ts`
- Generate: `apps/web/src/lib/supabase/database.types.ts`(`pnpm db:types`)
- Test: `apps/web/src/lib/auth/paths.test.ts`

**Interfaces:**
- Consumes: Task 1~3 스키마(타입 생성)
- Produces:
  - `createServerClient(): Promise<SupabaseClient<Database>>`(`server.ts`, `cookies()` 사용)
  - `createBrowserClient(): SupabaseClient<Database>`(`client.ts`)
  - `updateSession(request: NextRequest): Promise<NextResponse>`(`lib/supabase/proxy.ts`): 세션을 갱신하고, 로그인하지 않은 사용자가 공개 경로가 아닌 곳에 접근하면 `/login?next=<path>`로 보낸다.
  - `isPublicPath(pathname: string): boolean`: `/login`만 `true`
  - `src/proxy.ts`: `export async function proxy(request)`, matcher는 `/((?!_next/static|_next/image|favicon.ico).*)`
  - `signIn(prev: SignInState, formData: FormData): Promise<SignInState>`(이메일·비밀번호, `useActionState`), `signOut(): Promise<void>`
  - 환경변수: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`(`.env.example`에 키 이름만)
  - `(app)/layout.tsx`: 상단 내비게이션(프로필·전략·실행 이력), 로그아웃 버튼, `<html lang="ko">`
  - shadcn: `pnpm dlx shadcn@4.22.0 init` 후 `button card input label badge table tabs select alert separator textarea`
  - 웹 deps: `@supabase/ssr@^0.12`, `@supabase/supabase-js@^2.118`, `zod@^4`. dev deps: `vitest@^5`. `package.json` scripts에 `test: vitest run`
  - `pnpm-workspace.yaml`은 그대로 둔다(`apps/web` 포함).

- [ ] **Step 1: 스캐폴드와 의존성 설치**

Run: 위 create-next-app 명령, shadcn init·add, 의존성 설치, `pnpm db:types`
Expected: `pnpm --filter web build` 성공

- [ ] **Step 2: 실패하는 테스트 작성**

```ts
test("only /login is public", () => {
  expect(["/login", "/profiles", "/runs/abc", "/"].map(isPublicPath)).toEqual([true, false, false, false]);
});
```

- [ ] **Step 3: 실패 확인**

Run: `pnpm --filter web test`
Expected: FAIL. `Cannot find module '@/lib/auth/paths'`

- [ ] **Step 4: 인증 파일 구현**

`paths.ts`, Supabase 클라이언트, `proxy.ts`, 로그인 페이지·액션, `(app)/layout.tsx`, `page.tsx`(`redirect('/profiles')`)를 만든다.

- [ ] **Step 5: 통과·동작 확인**

Run: `pnpm --filter web test && pnpm --filter web build`
Expected: PASS, 빌드 성공

수동 확인:
- `pnpm db:start`로 로컬 DB를 띄우고, Studio(`http://127.0.0.1:54323`)에서 사용자를 만든다.
- `pnpm --filter web dev`로 웹을 띄운다.
- 로그인하지 않고 `/profiles`에 가면 `/login`으로 이동한다.
- 로그인하면 `/profiles`로 돌아온다.

- [ ] **Step 6: Commit**

```bash
git add apps/web pnpm-lock.yaml
git commit -m "Scaffold the Next.js app behind Supabase session gating" -m "Tested: vitest paths, next build, manual login against local Supabase"
```

### Task 11: TS 전략 라이브러리 (스키마·검증·미리보기·편집기 상태)

**Files:**
- Create: `apps/web/src/lib/strategy/types.ts`, `schema.ts`, `validate.ts`, `preview.ts`, `editor.ts`
- Test: `apps/web/src/lib/strategy/validate.test.ts`, `preview.test.ts`, `editor.test.ts`

**Interfaces:**
- Consumes: `packages/contracts/cases/validate.json`(Task 4)
- Produces:
  - 타입: `StrategyExpr`, `StrategyDefinition`(스펙 5장 그대로), `ValidationIssueCode`(Task 4의 8개 코드), `ConditionInfo = { profileId: string; active: boolean }`
  - `strategyDefinitionSchema`: zod `strictObject` + `z.lazy` 재귀. 모양만 검사한다.
  - `validateDefinition(definition: unknown, conditions: ReadonlyMap<string, ConditionInfo>): ValidationIssueCode[]`: Python과 같은 규칙, 정렬·중복 제거
  - `renderExpression(expr: StrategyExpr, nameOf: (id: string) => string): string`
    - 연산자는 ` AND `, ` OR `, ` EXCLUDE `
    - 자식이 복합 노드이면 괄호로 감싼다. 최상위에는 괄호를 붙이지 않는다.
    - `subtract`가 2개 이상이면 `(B OR C)`로 묶는다.
  - `editorReducer(state: StrategyExpr | null, action: EditorAction): StrategyExpr | null`
    - `EditorAction` = `{type:"setRoot", node}` | `{type:"addChild", path: number[], node}` | `{type:"remove", path}` | `{type:"setOperator", path, operator: "and" | "or" | "exclude"}` | `{type:"setCondition", path, conditionId}`
    - `exclude` 노드의 자식 경로는 `[base, ...subtract]` 순서로 센다.
    - 연산자를 바꿀 때 `and`/`or` → `exclude`는 `base = children[0]`, `subtract = 나머지`이고, 반대 방향은 `children = [base, ...subtract]`
    - 상태는 바꾸지 않고(불변) 새 객체를 반환한다.
  - `toDefinition(profileId: string, expr: StrategyExpr): StrategyDefinition`: `{schemaVersion: 1, profileId, exchange: "K", expr}`. 편집기는 `expr`만 상태로 들고, 저장할 때 이 함수로 감싼다.

- [ ] **Step 1: 실패하는 테스트 작성**

```ts
// validate.test.ts
const cases = JSON.parse(readFileSync(join(__dirname, "../../../../../packages/contracts/cases/validate.json"), "utf8")).cases;
test.each(cases)("$name", (c) => {
  expect(validateDefinition(c.definition, new Map(Object.entries(c.conditions)))).toEqual(c.issues);
});
// preview.test.ts
expect(renderExpression(and(c("basic"), or(c("prev"), c("gc"))), names)).toBe("기본종목 AND (전일고가돌파 OR 골든크로스)");
expect(renderExpression(exclude(c("A"), [c("B")]), names)).toBe("A EXCLUDE B");
expect(renderExpression(exclude(c("A"), [c("B"), c("C")]), names)).toBe("A EXCLUDE (B OR C)");
expect(renderExpression(and(c("A"), exclude(c("B"), [c("C")])), names)).toBe("A AND (B EXCLUDE C)");
// editor.test.ts
test("addChild appends to group"); test("remove leaf from group"); test("and→exclude keeps first as base");
test("exclude→or flattens base+subtract"); test("reducer does not mutate input");
```

- [ ] **Step 2: 실패 확인**

Run: `pnpm --filter web test`
Expected: FAIL

- [ ] **Step 3: 구현**

- [ ] **Step 4: 통과 확인**

Run: `pnpm --filter web test && pnpm --filter web exec tsc --noEmit`
Expected: PASS, 타입 오류 없음

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/strategy
git commit -m "Validate and preview strategies in the web against the shared contract cases" -m "Tested: vitest (contracts parity, preview, editor reducer)"
```

### Task 12: 프로필·조건식 화면과 동기화 요청

**Files:**
- Create: `apps/web/src/lib/rpc.ts`, `apps/web/src/lib/display/errors.ts`, `time.ts`, `worker.ts`, `apps/web/src/lib/data/profiles.ts`, `conditions.ts`
- Create: `apps/web/src/app/(app)/profiles/page.tsx`, `actions.ts`, `profile-form.tsx`, `sync-button.tsx`, `apps/web/src/app/(app)/profiles/[profileId]/conditions/page.tsx`, `actions.ts`, `condition-table.tsx`
- Test: `apps/web/src/lib/display/worker.test.ts`, `errors.test.ts`, `time.test.ts`, `apps/web/src/lib/rpc.test.ts`

**Interfaces:**
- Consumes: Task 2 `request_run`, Task 3 `worker_heartbeats`, `runs.sync_summary`, `condition_sync_events`, Task 10 클라이언트
- Produces:
  - `mapRpcError(error: { message: string } | null): { code: string; message: string } | null`(`rpc.ts`): 알려진 코드(`PROFILE_BUSY`, `CONDITION_INACTIVE`, `STRATEGY_HAS_NO_VERSION`, `NOT_FOUND`, `PROFILE_MISMATCH`, `INVALID_DEFINITION`, `RUN_NOT_CANCELLABLE`)는 한국어 메시지로 바꾼다. 그 외는 `UNKNOWN`과 일반 메시지
  - `runErrorMessage(code: string | null): string`(`display/errors.ts`): Task 8 코드 전부와 `LEASE_EXPIRED`, `RUN_TIMEOUT`을 한국어로 바꾼다. 예: `IP_DEVICE_AUTH` → "워커 호스트 IP 또는 단말기 등록을 확인하세요"
  - `formatKst(iso: string): string`(`YYYY-MM-DD HH:mm:ss KST`)
  - `workerStatus(heartbeats: {aliases: string[]; seen_at: string}[], alias: string, now: Date): "online" | "stale" | "not_serving"`: 45초 이내 heartbeat 중 `alias`를 가진 것이 있으면 `online`, 오래된 것만 있으면 `stale`, 없으면 `not_serving`
  - 서버 액션:
    - `createProfile(prev, formData)`: insert `{alias, mode, display_name}`
    - `requestSync(prev, formData)`: hidden `idempotencyKey`(클라이언트에서 `crypto.randomUUID()`) → `rpc("request_run", {p_kind:"sync", p_profile_id, p_strategy_id:null, p_idempotency_key})`
    - `updateDescription(conditionId, text)`
  - 화면:
    - `/profiles`: 실전·모의 배지(실전은 눈에 띄는 색), `workerStatus` 표시, 마지막 성공 시각·오류(`runErrorMessage`), 최근 동기화 요약
    - `/profiles/[profileId]/conditions`: 활성 조건식 표(seq·이름·참고 설명 + "이름 기반 추정" 표기·마지막 동기화), 이름 검색, 최근 동기화 이벤트(추가·삭제·교체 건수)

- [ ] **Step 1: 실패하는 테스트 작성**

```ts
expect(workerStatus([{ aliases: ["kiwoom-demo"], seen_at: iso(-10) }], "kiwoom-demo", NOW)).toBe("online");
expect(workerStatus([{ aliases: ["kiwoom-demo"], seen_at: iso(-60) }], "kiwoom-demo", NOW)).toBe("stale");
expect(workerStatus([{ aliases: ["other"], seen_at: iso(-5) }], "kiwoom-demo", NOW)).toBe("not_serving");
expect(mapRpcError({ message: "PROFILE_BUSY" })?.code).toBe("PROFILE_BUSY");
expect(mapRpcError({ message: "CONDITION_INACTIVE" })?.message).toContain("다시 저장");
expect(formatKst("2026-10-17T04:59:43Z")).toBe("2026-10-17 13:59:43 KST");
expect(runErrorMessage("CONDITION_CHANGED")).toContain("동기화");
```

- [ ] **Step 2: 실패 확인**

Run: `pnpm --filter web test`
Expected: FAIL

- [ ] **Step 3: lib와 화면 구현**

- [ ] **Step 4: 통과·동작 확인**

Run: `pnpm --filter web test && pnpm --filter web build`
Expected: PASS

수동 확인(fixture 워커):
- `apps/worker`에서 `KIWOOM_WORKER_TRANSPORT=fixture KIWOOM_WORKER_FIXTURE_FILE=tests/fixtures/e2e_market.json … uv run kiwoom-worker`로 워커를 띄운다.
- 동기화하면 조건식 3개가 보인다.
- 워커를 끄면 상태가 `stale`이 된다.

- [ ] **Step 5: Commit**

```bash
git add apps/web
git commit -m "Show profiles, worker reachability and synced conditions" -m "Tested: vitest display/rpc, manual sync via fixture worker"
```

### Task 13: 전략 목록·편집기·버전 저장·실행 요청

**Files:**
- Create: `apps/web/src/lib/data/strategies.ts`
- Create: `apps/web/src/app/(app)/strategies/page.tsx`, `actions.ts`, `new-strategy-form.tsx`, `apps/web/src/app/(app)/strategies/[strategyId]/page.tsx`, `actions.ts`, `strategy-editor.tsx`, `run-button.tsx`
- Test: `apps/web/src/app/(app)/strategies/[strategyId]/actions.test.ts`

**Interfaces:**
- Consumes: Task 11 `validateDefinition`, `renderExpression`, `editorReducer`. Task 12 `mapRpcError`. Task 2 `create_strategy_version`, `request_run`
- Produces:
  - `createStrategy(prev, formData)`: `{profileId, name}`를 insert한 뒤 `/strategies/[id]`로 이동
  - `saveVersion(strategyId: string, definition: StrategyDefinition): Promise<{ ok: true; version: number } | { ok: false; issues?: ValidationIssueCode[]; error?: string }>`: 서버에서 해당 프로필의 활성 조건식으로 `validateDefinition`을 먼저 실행하고, 통과하면 RPC를 부른다.
  - `requestSearchRun(strategyId: string, idempotencyKey: string): Promise<{ error: string } | never>`: 성공하면 `/runs/[id]`로 이동, 실패하면 `mapRpcError` 메시지
  - 편집기(클라이언트):
    - 해당 프로필의 활성 조건식만 고를 수 있다.
    - 미리보기 문자열과 검증 오류를 바로 표시한다.
    - 저장하지 않은 변경이 있으면 실행 버튼을 막고 "저장 후 실행" 안내를 띄운다.
    - 실행 버튼은 렌더링할 때 `idempotencyKey`를 한 번 만들고, 누르는 동안 비활성화한다.
  - 상세 화면: 버전 목록(번호·시각·미리보기), 복제 버튼(같은 프로필로 새 전략 + 현재 정의로 버전 1)

- [ ] **Step 1: 실패하는 테스트 작성** (Supabase 클라이언트 모킹)

```ts
test("saveVersion rejects invalid definition without calling rpc", async () => { /* issues ["TOO_FEW_CHILDREN"], rpc not called */ });
test("saveVersion maps CONDITION_INACTIVE", async () => { /* rpc error → { ok:false, error: contains "다시 저장" } */ });
test("requestSearchRun maps PROFILE_BUSY", async () => { /* → { error: contains "이미 실행 중" } */ });
```

- [ ] **Step 2: 실패 확인**

Run: `pnpm --filter web test`
Expected: FAIL

- [ ] **Step 3: 구현**

- [ ] **Step 4: 통과·동작 확인**

Run: `pnpm --filter web test && pnpm --filter web build`
Expected: PASS

수동 확인:
- 전략 `기본종목 AND (전일고가돌파 OR 골든크로스)`를 저장하면 버전 1이 생긴다.
- 실행하면 `/runs/[id]`로 이동한다.
- 실행 버튼을 빠르게 두 번 눌러도 run은 1개만 생긴다.

- [ ] **Step 5: Commit**

```bash
git add apps/web
git commit -m "Edit, version and launch strategies from the web" -m "Tested: vitest actions (mocked supabase), manual save/run with fixture worker"
```

### Task 14: 실행 결과·이력 화면과 CSV

**Files:**
- Create: `apps/web/src/lib/csv.ts`, `apps/web/src/lib/display/run.ts`, `apps/web/src/lib/data/runs.ts`
- Create: `apps/web/src/app/(app)/runs/page.tsx`, `apps/web/src/app/(app)/runs/[runId]/page.tsx`, `run-poller.tsx`, `results-table.tsx`, `diagnostics.tsx`, `actions.ts`, `apps/web/src/app/(app)/runs/[runId]/csv/route.ts`
- Test: `apps/web/src/lib/csv.test.ts`, `apps/web/src/lib/display/run.test.ts`

**Interfaces:**
- Consumes: Task 3 `runs`·`run_results`·`condition_snapshots`·`compared_run_id`·`excluded_codes`, Task 2 `cancel_run`, Task 12 `formatKst`·`runErrorMessage`
- Produces:
  - `escapeCsvText(value: string | null): string`: 수식 방어 후 필요하면 따옴표로 감싼다. `,`, `"`, CR, LF가 있으면 `"`로 감싸고 내부 `"`는 `""`로 바꾼다.
  - `formatCsvNumber(value: number | string | null): string`: 숫자는 방어 없이 그대로 쓴다.
  - `RunCsvRow = { code; rawCode; name; instrumentType; matchedNames: string[]; diff: "new" | "kept"; price: number | null; changeRate: string | null }`
  - `buildRunCsv(rows: RunCsvRow[]): string`
    - BOM `\uFEFF`, 줄 구분 CRLF
    - 헤더: `종목코드,원본코드,종목명,유형,충족조건,변화,현재가,등락률`
    - `충족조건`은 `" | "`로 잇는다. `변화`는 `신규`/`유지`
  - `statusLabel(status)`: `대기`/`실행 중`/`성공`/`실패`/`시간 초과`/`취소`
  - `resultSummary(status: string, count: number | null): string`: 성공이면 `성공 · N건`(0건 포함), 그 외는 `statusLabel`
  - `marketPhaseLabel(phase)`: `장전`/`장중`/`장후`/`주말`
  - `windowExceeded(start: string, end: string): boolean`: 15초 초과
  - `droppedCodes(previous: string[], current: string[]): string[]`: 오름차순
  - `getRun(runId)`: run, 버전(정의·refs), 결과, 스냅샷, 비교 run의 결과 코드를 반환한다.
  - `cancelQueuedRun(runId)`: `cancel_run`을 호출한다.
  - CSV 라우트 `GET /runs/[runId]/csv`
    - 소유자의 `succeeded` run만 `200`과 `text/csv; charset=utf-8`, `Content-Disposition: attachment; filename="run-<runId>.csv"`를 반환한다.
    - 그 외는 `404`
  - 결과 화면에 표시할 것:
    - 상태, 수집 구간(KST), 장 구분 경고(`regular`가 아니면 "장 마감 이후 기준일 수 있음"), 수집 구간 경고, 건수(0건이면 "성공 · 0건")
    - 결과 표: 코드·이름·유형·조건 충족 배지(리프마다 ✓/✗)·현재가·등락률·변화
    - 이탈 목록, 고정 고지 문구(Global Constraints), 비교 대상 버전이 다르면 "버전 다름" 배지
    - 진단 탭: 조건식별 건수·수집 시각·오류, 제외된 종목
    - `queued`·`running`이면 `run-poller`가 2000ms마다 `router.refresh()`. `queued`이면 취소 버튼
  - `/runs`: 최근 50건(종류·전략·버전·프로필·상태·시각·건수)

- [ ] **Step 1: 실패하는 테스트 작성**

```ts
expect(buildRunCsv([]).startsWith("\uFEFF종목코드,원본코드")).toBe(true);
expect(buildRunCsv([]).split("\r\n").filter(Boolean)).toHaveLength(1);           // 헤더만
expect(escapeCsvText("=HYPERLINK(\"x\")")).toBe("\"'=HYPERLINK(\"\"x\"\")\"");
expect(["+1", "-x", "@a", "\tA", "\rA"].map(escapeCsvText).every((v) => v.replace(/^"/, "").startsWith("'"))).toBe(true);
expect(escapeCsvText("카카오, 테스트")).toBe("\"카카오, 테스트\"");
expect(formatCsvNumber("-2.52")).toBe("-2.52");                                   // 숫자는 방어하지 않음
expect(buildRunCsv([row({ code: "0010F0", rawCode: "A0010F0" })])).toContain("0010F0,A0010F0");
expect(windowExceeded("2026-10-17T05:00:00Z", "2026-10-17T05:00:16Z")).toBe(true);
expect(windowExceeded("2026-10-17T05:00:00Z", "2026-10-17T05:00:15Z")).toBe(false);
expect(droppedCodes(["001", "002"], [])).toEqual(["001", "002"]);
expect(marketPhaseLabel("weekend")).toBe("주말");
expect(resultSummary("succeeded", 0)).toBe("성공 · 0건");
expect(resultSummary("failed", null)).toBe("실패");
```

- [ ] **Step 2: 실패 확인**

Run: `pnpm --filter web test`
Expected: FAIL

- [ ] **Step 3: 구현**

- [ ] **Step 4: 통과·동작 확인**

Run: `pnpm --filter web test && pnpm --filter web build`
Expected: PASS

수동 확인(fixture 워커):
- 결과에 `005930`, `0010F0`가 보이고 `000660`은 없다.
- 두 번째 실행하면 모두 "유지"로 표시된다.
- 내려받은 CSV를 엑셀로 열면 한글이 정상이다.

- [ ] **Step 5: Commit**

```bash
git add apps/web
git commit -m "Present run results, history, diffs and a formula-safe CSV export" -m "Tested: vitest csv/run display, manual fixture runs"
```

### Task 15: E2E (로컬 Supabase + fixture 워커)

**Files:**
- Create: `apps/web/playwright.config.ts`, `apps/web/e2e/global-setup.ts`, `apps/web/e2e/mvp-flow.spec.ts`
- Modify: `apps/web/package.json`(`test:e2e: playwright test`, devDependency `@playwright/test@^1.64`)

**Interfaces:**
- Consumes: Task 9 `e2e_market.json`, `kiwoom-worker` CLI(fixture 모드), Task 10~14 화면
- Produces:
  - `global-setup.ts`
    - `supabase status -o env`에서 URL과 service role 키를 읽는다(로컬 전용).
    - `auth.admin.createUser({email:"e2e@example.test", password, email_confirm:true})`로 사용자를 만든다.
    - 프로필 `alias "e2e-demo", mode "demo"`를 넣는다.
    - 임시 `profiles.toml`(권한 0600, 가짜 키)을 쓴다.
  - `playwright.config.ts`의 `webServer`
    - `pnpm dev`(포트 3000)
    - `uv run --project ../worker kiwoom-worker`(env: fixture 전송, 로컬 워커 DB URL, `KIWOOM_WORKER_ID=e2e`, `KIWOOM_WORKER_PROFILES_FILE`=임시 파일)

E2E는 Task 10~14가 끝난 뒤 전체 연결을 확인하는 테스트다. 실패하면 테스트를 고치지 말고, 원인이 된 Task의 코드를 고친다.

- [ ] **Step 1: 설정·셋업·시나리오 작성**

```ts
test("sync → strategy → run → results → csv → rerun kept", async ({ page }) => {
  // 로그인 → /profiles → 동기화 → 조건식 3개 표시
  // 새 전략: 기본종목 AND (전일고가돌파 OR 골든크로스) 저장 → 미리보기 문자열 확인
  // 실행 → 상태 "성공" → 표에 005930, 0010F0 있음, 000660 없음
  // 고지 문구 표시 확인
  // CSV 다운로드 → 내용이 "\uFEFF"로 시작, "0010F0,A0010F0" 포함
  // 다시 실행 → 두 종목 모두 "유지"
});
```

- [ ] **Step 2: 실행**

Run: `pnpm db:reset && pnpm --filter web exec playwright install chromium && pnpm --filter web test:e2e`
Expected: `1 passed`. 실패하면 원인이 된 Task의 코드를 고친 뒤 다시 실행한다.

- [ ] **Step 3: Commit**

```bash
git add apps/web
git commit -m "Exercise the whole MVP flow end to end against a fixture worker" -m "Tested: playwright mvp-flow (local Supabase, fixture transport)" -m "Not-tested: live Kiwoom"
```

---

## Part D — 배포

### Task 16: Supabase Cloud·Vercel·워커 호스트 배포와 운영 검증

**Files:**
- Create: `docs/guides/deployment.md`, `deploy/worker/kiwoom-worker.service`, `deploy/worker/worker.env.example`
- Modify: `docs/references/kiwoom-condition-search-verification.md`(V5·V6 결과), `docs/plans/kiwoom-conditions-plan.md`(10장 진행 상태)

**Interfaces:**
- Consumes: 모든 이전 Task
- Produces:
  - `kiwoom-worker.service`
    - `ExecStart=/usr/local/bin/uv run --project /opt/kiwoom/apps/worker --frozen kiwoom-worker`
    - `EnvironmentFile=/etc/kiwoom-worker.env`(0600), `Restart=always`, `RestartSec=5`
    - 전용 사용자 `kiwoom`, `NoNewPrivileges=true`, `ProtectSystem=strict`, `ReadWritePaths=` 없음
  - `worker.env.example`: Task 9 환경변수 이름만, 값은 비운다.
  - `deployment.md` 절차
    1. Supabase: 프로젝트 생성 → `pnpm supabase link` → `pnpm supabase db push` → SQL 편집기에서 `alter role kiwoom_worker with login password '<생성한 값>'` → Auth에서 가입 끄기, Site URL을 Vercel 도메인으로 → 사용자 1명 생성
    2. Vercel: Root Directory `apps/web`, 환경변수 `NEXT_PUBLIC_SUPABASE_URL`·`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` → 배포
    3. 워커: 고정 IP 호스트(D1)에 uv 설치 → 저장소 배치 → `uv sync --frozen` → `profiles.toml`(0600)·`/etc/kiwoom-worker.env`(0600) → `systemctl enable --now kiwoom-worker`
       - DB URL은 Supabase pooler 세션 모드(`<role>.<project-ref>` 사용자명, 포트 5432)를 쓴다.
    4. 키움 포털에서 워커 호스트 IP 등록이 필요한지 확인한다(V5).

- [ ] **Step 1: 배포 파일·가이드 작성**

- [ ] **Step 2: Supabase·Vercel 배포**

Run: 가이드 1~2단계
Expected: Vercel URL에서 로그인 가능. 비로그인 접근은 `/login`으로 이동

- [ ] **Step 3: 워커 배포와 모의 프로필 검증** (사용자가 모의 프로필 호출을 허락한 경우에만)

Run: 가이드 3단계, 웹에서 `kiwoom-demo` 동기화 → 전략 실행
Expected:
- 프로필 상태 `online`, 동기화로 30개 조건식이 생긴다.
- 실행은 `succeeded`가 되고, 수집 구간이 표시된다.
- 리프 10개 이하 전략은 요청부터 성공까지 10초 이내에 끝난다(스펙 2장 비기능 요구). `runs.finished_at - runs.started_at`으로 확인한다.
- `journalctl -u kiwoom-worker`에 토큰·키가 없다.

- [ ] **Step 4: 운영 검증 기록**

- 워커 호스트에서 토큰을 발급·조회했는지, 8010·8050이 발생했는지(V5)를 기록한다.
- 로컬 `kiwoomcli` 토큰과 함께 쓸 때 영향이 있는지(V6)를 검증 문서에 기록한다.
- 장중 1회·장후 1회 전체 흐름을 확인한다(스펙 10장 6단계).
- 실전 프로필 실행은 사용자의 명시적 허락을 받은 뒤에만 한다.

- [ ] **Step 5: Commit**

```bash
git add docs deploy
git commit -m "Document and wire production deployment for web, database and worker" -m "Tested: hosted login, demo-profile sync and run from worker host" -m "Not-tested: real-profile run (pending explicit authorization)"
```
