import Link from "next/link";
import { notFound } from "next/navigation";
import { z } from "zod";
import { Badge } from "@/components/ui/badge";
import { getConditions } from "@/lib/data/conditions";
import { syncRemovalWarning, syncSummary } from "@/lib/data/profiles";
import { formatKst } from "@/lib/display/time";
import { runErrorMessage } from "@/lib/display/errors";
import { SyncButton } from "../../sync-button";
import { ConditionTable } from "./condition-table";

const eventLabels: Record<string, string> = { added: "추가", removed: "삭제", replaced: "교체" };
export default async function ConditionsPage({ params }: { params: Promise<{ profileId: string }> }) {
  const { profileId } = await params;
  if (!z.uuid().safeParse(profileId).success) notFound();
  const data = await getConditions(profileId);
  if (!data) notFound();
  return <div className="space-y-6">
    <Link href="/profiles" className="underline">프로필 목록</Link>
    <h1 className="text-2xl font-bold">{data.profile.display_name || data.profile.alias} · 조건식</h1>
    <Badge variant={data.profile.mode === "real" ? "destructive" : "secondary"}>{data.profile.mode === "real" ? "실전" : "모의"}</Badge>
    <SyncButton profileId={profileId} />
    <ConditionTable conditions={data.conditions} />
    <section className="space-y-3">
      <h2 className="text-xl font-semibold">최근 동기화 이벤트</h2>
      {data.runs.length === 0 && <p>동기화 이력이 없습니다.</p>}
      {data.runs.map((run) => <article key={run.id} className="space-y-2 rounded border p-3">
        <p>{formatKst(run.requested_at)} ({run.status})</p>
        <p>{syncSummary(run.sync_summary)}</p>
        {syncRemovalWarning(run.sync_summary) && <p role="alert" className="text-destructive">{syncRemovalWarning(run.sync_summary)}</p>}
        {run.error_code && <p role="alert">{runErrorMessage(run.error_code)}</p>}
        <ul className="space-y-1 text-sm">{data.events.filter((event) => event.run_id === run.id).map((event) => <li key={event.id}>
          {eventLabels[event.event] ?? "변경"} · seq {event.seq} · {event.old_name ?? "없음"} → {event.new_name ?? "없음"}
        </li>)}</ul>
      </article>)}
    </section>
  </div>;
}
