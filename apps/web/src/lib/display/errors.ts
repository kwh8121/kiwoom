const messages: Record<string, string> = {
  RATE_LIMITED: "조회 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.",
  TOKEN_INVALID: "워커의 인증 정보를 확인해 주세요.",
  IP_DEVICE_AUTH: "워커 호스트 IP 또는 단말기 등록을 확인하세요",
  PROFILE_CONFIG: "워커의 프로필 별칭과 실전·모의 설정을 확인해 주세요.",
  CONDITION_CHANGED: "조건식을 동기화한 뒤 전략을 다시 저장해 주세요.",
  KIWOOM_INPUT: "키움 조회 입력값을 확인해 주세요.",
  KIWOOM_TRANSIENT: "키움 연결에 일시적인 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.",
  KIWOOM_UNKNOWN: "키움 조회 중 알 수 없는 오류가 발생했습니다.",
  RESPONSE_TIMEOUT: "키움 응답 대기 시간이 초과되었습니다. 다시 시도해 주세요.",
  INCOMPLETE_PAGINATION: "연속 조회를 완료하지 못했습니다. 다시 시도해 주세요.",
  KIWOOM_PROTOCOL: "키움 응답 형식을 처리하지 못했습니다. 워커를 확인해 주세요.",
  INVALID_DEFINITION: "전략 정의가 유효하지 않습니다. 전략을 확인한 뒤 다시 저장해 주세요.",
  LEASE_EXPIRED: "워커의 실행 임대가 만료되었습니다. 워커 상태를 확인해 주세요.",
  RUN_TIMEOUT: "전체 실행 제한 시간을 초과했습니다. 다시 요청해 주세요.",
};

export function runErrorMessage(code: string | null): string {
  if (code === null) return "";
  return Object.hasOwn(messages, code) ? messages[code] : "실행 중 오류가 발생했습니다. 워커 상태를 확인해 주세요.";
}
