import Link from "next/link";
import { notFound } from "next/navigation";
import { z } from "zod";
import { getStrategy } from "@/lib/data/strategies";
import { strategyDefinitionSchema } from "@/lib/strategy/schema";
import { renderExpression } from "@/lib/strategy/preview";
import { formatKst } from "@/lib/display/time";
import { StrategyEditor } from "./strategy-editor";
export default async function StrategyPage({ params }: { params: Promise<{ strategyId: string }> }) {
  const { strategyId } = await params;
  if (!z.uuid().safeParse(strategyId).success) notFound();
  const data = await getStrategy(strategyId);
  if (!data) notFound();
  const { strategy, profile, conditions, versions } = data;
  const current = versions.find(v => v.id === strategy.current_version_id);
  const parsed = strategyDefinitionSchema.safeParse(current?.definition);
  return <section className="space-y-6"><Link href="/strategies" className="underline">전략 목록</Link><h1 className="text-2xl font-bold">{strategy.name}</h1>
    <p>{profile.display_name || profile.alias} · {profile.mode === "real" ? "실전" : "모의"}</p>
    <StrategyEditor key={strategy.id} strategyId={strategy.id} profileId={strategy.profile_id} conditions={conditions} initial={parsed.success ? parsed.data : null} />
    <section className="space-y-3"><h2 className="text-xl font-bold">저장된 버전</h2>{!versions.length && <p>저장된 버전이 없습니다.</p>}
      <ol className="space-y-3">{versions.map(v => { const definition = strategyDefinitionSchema.safeParse(v.definition); return <li key={v.id} className="rounded border p-3"><p>버전 {v.version} · {formatKst(v.created_at)}{v.id === strategy.current_version_id ? " · 현재 버전" : ""}</p><p>{definition.success ? renderExpression(definition.data.expr, id => conditions.find(c => c.id === id)?.name ?? "비활성 또는 알 수 없는 조건식") : "정의를 표시할 수 없습니다."}</p></li>; })}</ol>
    </section></section>;
}
