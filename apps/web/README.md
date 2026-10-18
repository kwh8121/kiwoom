# 키움 조건검색 웹

Next.js 16과 Supabase SSR 기반 로그인 스캐폴드입니다. 회원가입 UI는 제공하지 않으며, 로컬 Supabase의 회원가입도 비활성화되어 있습니다.

저장소 루트에서 의존성을 설치하고 `.env.example`의 두 공개 설정을 `apps/web/.env.local`에 입력합니다. 비밀 키나 서비스 역할 키는 웹 환경에 추가하지 마세요.

```bash
pnpm install
pnpm --filter web dev
pnpm --filter web test
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
```

DB 타입은 실행 중인 로컬 Supabase에서만 생성합니다.

```bash
SUPABASE_TELEMETRY_DISABLED=1 XDG_CONFIG_HOME=/tmp/kiwoom-xdg pnpm db:types
```

`/login`만 공개 경로입니다. 로그인 후 기본 목적지는 `/profiles`이며, 프로필·전략·실행 이력 화면은 이후 작업에서 구현합니다. 로그인 수동 검증에는 Studio에서 관리자가 생성한 로컬 사용자가 필요합니다. 회원가입 활성화나 DB 초기화는 필요하지 않습니다.
