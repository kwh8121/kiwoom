const messages = {
  PROFILE_BUSY: "이 프로필은 실행 중입니다. 완료 후 다시 요청해 주세요.",
  CONDITION_INACTIVE: "조건식이 변경되었습니다. 동기화한 뒤 전략을 다시 저장해 주세요.",
  STRATEGY_HAS_NO_VERSION: "전략을 저장한 뒤 실행해 주세요.",
  NOT_FOUND: "요청한 항목을 찾을 수 없습니다.",
  PROFILE_MISMATCH: "전략과 프로필이 일치하지 않습니다.",
  INVALID_DEFINITION: "전략 정의를 확인해 주세요.",
  RUN_NOT_CANCELLABLE: "이 실행은 취소할 수 없습니다.",
} as const;

export function mapRpcError(error: { message: string } | null): { code: string; message: string } | null {
  if (!error) return null;
  if (Object.hasOwn(messages, error.message)) {
    const code = error.message as keyof typeof messages;
    return { code, message: messages[code] };
  }
  return { code: "UNKNOWN", message: "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요." };
}
