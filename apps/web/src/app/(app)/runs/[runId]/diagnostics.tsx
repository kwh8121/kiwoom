import type { Snapshot } from "@/lib/data/runs";
import { formatKst } from "@/lib/display/time";
import { runErrorMessage } from "@/lib/display/errors";
export function Diagnostics({ snapshots, excludedCodes }: { snapshots: Snapshot[]; excludedCodes: string[] }) {
  return <div className="space-y-4"><h2 className="text-xl font-bold">조건식별 진단</h2>
    {!snapshots.length ? <p>수집된 조건식 스냅샷이 없습니다.</p> : <ul className="space-y-3">{snapshots.map(snapshot => <li key={snapshot.id} className="rounded border p-3">
      <h3 className="font-semibold">{snapshot.name} ({snapshot.seq})</h3><p>{snapshot.row_count === null ? "건수 미확인" : `${snapshot.row_count}건`} · {snapshot.page_count ?? 0}페이지 · {snapshot.is_complete ? "수집 완료" : "수집 미완료"}</p>
      <p>시작: {snapshot.started_at ? formatKst(snapshot.started_at) : "—"} · 완료: {snapshot.completed_at ? formatKst(snapshot.completed_at) : "—"}</p>
      {snapshot.error_code && <p role="alert">{runErrorMessage(snapshot.error_code)}</p>}
    </li>)}</ul>}
    <h2 className="text-xl font-bold">제외된 종목</h2><p>{excludedCodes.length ? [...excludedCodes].sort().join(", ") : "없음"}</p>
  </div>;
}
