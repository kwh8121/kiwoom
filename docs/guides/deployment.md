# MVP 배포 가이드

이 가이드는 Next.js 웹, Supabase, 별도 고정 IP 워커를 연결하는 운영 절차를 설명합니다. **Task 16 Step 1 문서화 결과입니다.** 실제 Supabase Cloud/Vercel 연결, 서버 설치, Kiwoom 호출은 여기서 수행하거나 검증하지 않았습니다.

## 1. Supabase 프로젝트

1. Supabase 대시보드에서 프로젝트를 만들고, 접근이 제한된 환경별 설정 저장소에 DB 연결 정보를 보관합니다.
2. 저장소 루트에서 `pnpm supabase link`로 프로젝트를 연결하고, 마이그레이션을 검토한 뒤 `pnpm supabase db push`를 실행합니다.
3. DB 비밀번호와 분리해 `kiwoom_worker` 역할 전용의 강한 비밀번호를 생성합니다. SQL 편집기에서 다음 설정을 적용합니다.

   ```sql
   alter role kiwoom_worker with login password '<별도 생성한 역할 비밀번호>';
   ```

4. Authentication 설정에서 공개 회원가입을 끄고, 관리자가 단일 운영자 계정을 생성합니다. Site URL을 배포할 웹 도메인으로 지정합니다. 비밀번호 최소 길이를 **12자 이상**으로 올립니다(`supabase/config.toml`의 로컬 설정과 같은 값). 문자 종류 규칙은 걸지 않습니다. 길이가 추측 난이도를 결정하고, 종류 규칙은 예측 가능한 치환을 유도합니다. MFA는 아직 적용하지 않았습니다.
5. 워커가 사용할 각 별칭을 그 별칭을 소유하는 계정에 등록합니다. 별칭 등록은 운영자 단계이며, 클라이언트에는 쓰기 경로가 없습니다. 등록하지 않은 별칭의 프로필은 웹에서 만들 수 없고, 등록되지 않은 별칭으로는 워커가 아무 작업도 가져가지 않습니다.

   ```sql
   -- 운영자 계정 id는 Authentication > Users에서 확인합니다.
   insert into public.broker_alias_owners (alias, user_id)
   values ('<워커 profiles.toml의 별칭>', '<운영자 계정 uuid>');
   ```

   별칭은 `/etc/kiwoom-worker/profiles.toml`의 이름과 정확히 일치해야 합니다. 계정을 삭제하면 등록도 함께 삭제됩니다.
6. 워커 연결에는 직접 연결이 가능하면 SSL이 적용된 Postgres 연결을 사용합니다. 네트워크가 pooler를 요구하면 **session mode**를 사용하고 사용자명은 `<role>.<project-ref>`, 포트는 `5432`로 설정합니다. Transaction mode는 지속 연결이 필요한 이 워커에 사용하지 않습니다.
7. 서비스 키를 브라우저나 웹 환경변수에 넣지 않습니다. 웹은 publishable key를 사용하고, 워커는 제한된 Postgres 역할만 사용합니다.

이 MVP는 신뢰된 단일 운영자용입니다. 별칭은 워커의 로컬 Kiwoom 자격 증명을 선택하므로 `public.broker_alias_owners`가 각 별칭을 한 계정에 묶고, 하나의 별칭은 하나의 프로필만 쓸 수 있습니다. 워커는 등록된 소유자의 작업만 가져가고, heartbeat 조회는 호출자가 소유한 별칭으로 제한됩니다. 남은 다중 사용자 과제는 워커 하나가 여러 소유자를 담당할 때의 운영 경계입니다. 추가 계정을 만들 때는 그 계정의 별칭을 반드시 따로 등록합니다.

## 2. Vercel 웹

1. 저장소를 Vercel에 연결하고 Root Directory를 `apps/web`로 지정합니다.
2. 다음 환경변수를 Preview/Production에 설정합니다.

   ```text
   NEXT_PUBLIC_SUPABASE_URL
   NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
   ```

3. 배포 후 로그인 화면이 열리는지, 비로그인 `/profiles` 접근이 `/login`으로 이동하는지 확인합니다.
4. 공개 회원가입은 제공되지 않습니다. 계정을 추가할 때는 1장 5단계로 그 계정의 별칭을 등록해야 프로필을 만들 수 있습니다.

## 3. 고정 IP 워커 호스트

전용 Linux 호스트에 고정 egress IP를 준비합니다. 인바운드 포트는 열지 않습니다.

1. `kiwoom` 전용 사용자/그룹을 만들고, 저장소를 `/opt/kiwoom`에 배포합니다. 예: `sudo useradd --system --user-group --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin kiwoom`. 저장소 파일에는 그 계정에 필요한 최소한의 읽기 권한만 부여합니다.
2. 고정 경로 `/usr/local/bin/uv`에 uv를 설치하고 Python 요구사항과 lockfile을 확인합니다. 서비스 시작 전에 배포 계정(root)으로 고정 lockfile에서 가상환경을 만듭니다. `ProtectSystem=strict`가 켜진 뒤에는 서비스가 `/opt`에 쓸 수 없으므로, 런타임이 의존성을 설치하게 두지 않습니다.

   ```bash
   sudo /usr/local/bin/uv sync --project /opt/kiwoom/apps/worker --frozen
   sudo -u kiwoom test -x /opt/kiwoom/apps/worker/.venv/bin/kiwoom-worker
   ```

   저장소와 `.venv`는 서비스 계정이 읽고 실행할 수 있어야 합니다. 의존성을 바꾸는 배포마다 서비스를 멈추고, 새 lockfile을 배치한 뒤 이 동기화와 실행 권한 확인을 다시 수행하고 서비스를 시작합니다.
3. 키움 프로필 디렉터리와 설정 파일을 준비합니다.

   ```bash
   sudo install -d -o root -g kiwoom -m 0750 /etc/kiwoom-worker
   sudo install -o kiwoom -g kiwoom -m 0600 /dev/null /etc/kiwoom-worker/profiles.toml
   sudoedit /etc/kiwoom-worker/profiles.toml
   ```

   App Key/Secret은 명령행 인자, 셸 기록, 로그, 저장소에 넣지 않습니다. 파일 내용은 별도 비밀 관리 절차로 입력합니다.
4. `deploy/worker/worker.env.example`은 **변수 이름만 있고 모든 값이 비어 있는 템플릿**입니다. 이를 그대로 systemd에 사용하면 빈 문자열 설정 오류가 납니다. `/etc/kiwoom-worker.env`를 별도로 만들고 필수인 DB URL, 고유 worker ID, profiles 파일 경로를 설정합니다. 나머지 변수는 기본값을 쓸 때는 파일에서 생략하고, 값을 지정할 때만 추가합니다. `EnvironmentFile`은 `root:root`, `0600`으로 두고 실제 값을 저장소에 커밋하지 않습니다.
5. systemd unit을 설치하고 실행합니다.

   ```bash
   sudo install -o root -g root -m 0644 deploy/worker/kiwoom-worker.service /etc/systemd/system/kiwoom-worker.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now kiwoom-worker
   sudo systemctl status kiwoom-worker
   ```

   유닛은 권한을 전부 떨어뜨리고 시스콜을 `@system-service`로 제한합니다. 이 제한은 호스트에서만 실제로 확인할 수 있으므로, 기동 후 다음을 함께 봅니다.

   ```bash
   sudo systemd-analyze verify /etc/systemd/system/kiwoom-worker.service
   sudo systemd-analyze security kiwoom-worker.service
   journalctl -u kiwoom-worker | grep -i 'operation not permitted\|SIGSYS'
   ```

   `SIGSYS`나 `Operation not permitted`가 보이면 차단된 시스콜을 확인해 `SystemCallFilter`에 해당 집합을 더합니다. 필터를 통째로 지우지는 않습니다.

   중지 제한 시간은 `TimeoutStopSec=180s`입니다. 중지 신호를 받으면 진행 중인 실행을 끝낸 뒤 종료하므로, 실행 예산(`KIWOOM_WORKER_RUN_TIMEOUT_S`, 기본 120초)보다 길어야 합니다. 실행 예산을 늘리면 이 값도 함께 늘립니다.

6. 로그에서 키·토큰·DB 비밀번호가 나타나지 않는지 확인합니다.

`deploy/worker/kiwoom-worker.service`는 `ProtectSystem=strict`, `ProtectHome=true`, `NoNewPrivileges=true`, 전용 사용자와 사설 임시 디렉터리를 사용합니다. unit은 서비스 전용 파일시스템 쓰기 경로를 추가하지 않습니다.

## 4. 키움 연결 및 검증

1. 키움 포털에서 워커의 고정 IP 또는 지정 단말기 등록이 필요한지 확인합니다. V5는 아직 미확인입니다.
2. **실제 키움 모의 프로필 조회를 실행하기 전에 사용자의 명시적 승인을 받습니다.** 이 저장소의 구현·테스트에는 fixture transport만 사용했습니다.
3. 승인 뒤 웹에서 모의 프로필 동기화를 요청하고 worker 상태가 `online`이 되는지 확인합니다.
4. 실행 1건에서 `runs.started_at`, `runs.finished_at`, 상태, 수집 구간, CSV 결과를 확인합니다. 장중 1회와 장후 1회 결과는 별도로 기록합니다.
5. 장중 요청 제한, V5 IP/단말기 요구, V6 여러 IP의 동일 App Key 동작은 현재 미확인입니다. 이번 구현/fixture E2E는 이 항목의 증거가 아닙니다.

## 롤백

웹은 Vercel에서 이전 배포 버전으로 되돌립니다. 워커는 `sudo systemctl disable --now kiwoom-worker`로 중단하고, DB 역할 비밀번호를 별도로 회전합니다. 서비스 롤백과 마이그레이션 롤백은 별도 변경으로 검토합니다.

## 검증 범위와 미수행 단계

Step 1에서는 문서와 unit/environment 예시만 준비했습니다. Cloud 프로젝트 연결·`db push`, Vercel 배포, 워커 호스트 설정, 실전/모의 브로커 호출 및 V5/V6 검증은 수행하지 않았습니다.
