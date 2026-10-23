import Link from "next/link";
import { getStrategies } from "@/lib/data/strategies";
import { formatKst } from "@/lib/display/time";
import { NewStrategyForm } from "./new-strategy-form";
export default async function StrategiesPage() {
  const { strategies, profiles } = await getStrategies();
  return <section className="space-y-6"><h1 className="text-2xl font-bold">전략</h1><NewStrategyForm profiles={profiles} />
    <ul className="space-y-3">{strategies.map(s => <li key={s.id} className="rounded border p-4"><Link href={`/strategies/${s.id}`} className="font-medium underline">{s.name}</Link><p>{profiles.find(p => p.id === s.profile_id)?.display_name || profiles.find(p => p.id === s.profile_id)?.alias} · {s.current_version_id ? "저장된 버전 있음" : "초안"} · {formatKst(s.updated_at)}</p></li>)}</ul>
    {!strategies.length && <p>등록된 전략이 없습니다.</p>}</section>;
}
