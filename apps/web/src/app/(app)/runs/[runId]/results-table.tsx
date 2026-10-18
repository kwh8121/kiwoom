import { Badge } from "@/components/ui/badge";
import type { ConditionRef, RunResult } from "@/lib/data/runs";
export function ResultsTable({ results, refs }: { results: RunResult[]; refs: ConditionRef[] }) {
  if (!results.length) return <p>조건 조합에 해당하는 종목이 없습니다.</p>;
  return <div className="overflow-x-auto"><table className="w-full border-collapse text-left text-sm"><caption className="sr-only">조건 조합 결과</caption>
    <thead><tr>{["코드", "이름", "유형", "조건 충족", "현재가", "등락률", "변화"].map(title => <th key={title} scope="col" className="border-b p-2">{title}</th>)}</tr></thead>
    <tbody>{results.map(result => <tr key={result.code}>
      <td className="p-2 font-mono">{result.code}</td><td className="p-2">{result.name ?? "—"}</td><td className="p-2">{result.instrument_type}</td>
      <td className="p-2"><div className="flex flex-wrap gap-1">{refs.map((ref, index) => <Badge key={`${ref.conditionId}-${index}`} variant="outline">{result.matched_condition_ids.includes(ref.conditionId) ? "✓" : "✗"} {ref.name}</Badge>)}</div></td>
      <td className="p-2">{result.price === null ? "—" : result.price.toLocaleString("ko-KR")}</td>
      <td className="p-2">{result.change_rate === null ? "—" : `${result.change_rate}%`}</td>
      <td className="p-2"><Badge variant={result.diff === "new" ? "default" : "secondary"}>{result.diff === "new" ? "신규" : "유지"}</Badge></td>
    </tr>)}</tbody></table></div>;
}
