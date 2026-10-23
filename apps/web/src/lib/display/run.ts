const statuses: Record<string, string> = { queued: "대기", running: "실행 중", succeeded: "성공", failed: "실패", timed_out: "시간 초과", cancelled: "취소" };
const phases: Record<string, string> = { pre: "장전", regular: "장중", post: "장후", weekend: "주말" };
export function statusLabel(status: string): string {
  return Object.hasOwn(statuses, status) ? statuses[status] : "알 수 없음";
}
export function resultSummary(status: string, count: number | null): string {
  return status === "succeeded" ? `성공 · ${count ?? 0}건` : statusLabel(status);
}
export function marketPhaseLabel(phase: string | null): string {
  return phase && Object.hasOwn(phases, phase) ? phases[phase] : "미확인";
}
export function windowExceeded(start: string, end: string): boolean {
  return Date.parse(end) - Date.parse(start) > 15_000;
}
export function droppedCodes(previous: string[], current: string[]): string[] {
  const codes = new Set(current);
  return [...new Set(previous)].filter(code => !codes.has(code)).sort();
}

// market_phase records what the clock said, which is accurate but not the same
// as the market having been open: a weekday the exchange was closed is still
// `regular`. The closure calendar supplies what the clock cannot, and an
// unfilled calendar means unknown, never "open".
export function tradingDataCaveat(
  phase: string | null,
  market: { isClosure: boolean; calendarCoversYear: boolean },
): string | null {
  if (phase === null) return null;
  if (phase !== "regular") return "장 마감 이후 기준일 수 있음";
  if (market.isClosure) return "휴장일에 수집된 결과입니다. 직전 거래일 기준 데이터일 수 있습니다.";
  if (!market.calendarCoversYear) {
    return "거래일 여부를 확인하지 못했습니다. 이 해의 휴장일 달력이 등록되지 않았을 수 있습니다. 직전 거래일 기준 데이터일 수 있습니다.";
  }
  return null;
}
