import Link from "next/link";
import { getRuns } from "@/lib/data/runs";
import { resultSummary } from "@/lib/display/run";
import { formatKst } from "@/lib/display/time";
export default async function RunsPage() {
  const { runs, strategies, versions, profiles } = await getRuns();
  return <section className="space-y-4"><h1 className="text-2xl font-bold">실행 이력</h1><p>최근 50건</p>
    {!runs.length ? <p>실행 이력이 없습니다.</p> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">최근 실행 이력</caption>
      <thead><tr>{["종류", "전략", "버전", "프로필", "상태·건수", "요청 시각"].map(label => <th scope="col" key={label} className="border-b p-2">{label}</th>)}</tr></thead>
      <tbody>{runs.map(run => {
        const profile = profiles.find(p => p.id === run.profile_id);
        const version = versions.find(v => v.id === run.strategy_version_id);
        return <tr key={run.id}><td className="p-2"><Link className="underline" href={`/runs/${run.id}`}>{run.kind === "search" ? "검색" : "동기화"}</Link></td>
          <td className="p-2">{strategies.find(s => s.id === run.strategy_id)?.name ?? "—"}</td><td className="p-2">{version?.version ?? "—"}</td>
          <td className="p-2">{profile ? `${profile.display_name || profile.alias} (${profile.mode === "real" ? "실전" : "모의"})` : "—"}</td>
          <td className="p-2">{resultSummary(run.status, run.result_count)}</td><td className="p-2">{formatKst(run.requested_at)}</td></tr>;
      })}</tbody></table></div>}
  </section>;
}
