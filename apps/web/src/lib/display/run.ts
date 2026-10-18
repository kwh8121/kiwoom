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
