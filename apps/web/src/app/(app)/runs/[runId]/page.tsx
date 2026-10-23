import Link from "next/link";
import { notFound } from "next/navigation";
import { getRun } from "@/lib/data/runs";
import { resultSummary, marketPhaseLabel, windowExceeded, droppedCodes, tradingDataCaveat } from "@/lib/display/run";
import { formatKst } from "@/lib/display/time";
import { runErrorMessage } from "@/lib/display/errors";
import { strategyDefinitionSchema } from "@/lib/strategy/schema";
import { renderExpression } from "@/lib/strategy/preview";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RunPoller } from "./run-poller";
import { ResultsTable } from "./results-table";
import { Diagnostics } from "./diagnostics";

export default async function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  const data = await getRun(runId);
  if (!data) notFound();
  const { run, version, refs, results, snapshots, comparedRun, previousCodes, market } = data;
  const definition = strategyDefinitionSchema.safeParse(version?.definition);
  const dropped = droppedCodes(previousCodes, results.map(r => r.code));
  return <section className="space-y-6">
    <Link href="/runs" className="underline">실행 이력</Link><h1 className="text-2xl font-bold">{run.kind === "search" ? "조건 검색 결과" : "조건식 동기화 결과"}</h1>
    <p role="status">{resultSummary(run.status, run.result_count)}</p><p>요청: {formatKst(run.requested_at)}</p>
    {version && <p>전략 버전 {version.version}</p>}
    {definition.success && <p>{renderExpression(definition.data.expr, id => refs.find(ref => ref.conditionId === id)?.name ?? "알 수 없는 조건식")}</p>}
    <RunPoller runId={run.id} status={run.status} />
    {run.error_code && <p role="alert">{runErrorMessage(run.error_code)}</p>}
    {run.kind === "search" && <>
      <p>수집 구간: {run.window_start ? formatKst(run.window_start) : "—"} ~ {run.window_end ? formatKst(run.window_end) : "—"}</p>
      <p>장 구분: {marketPhaseLabel(run.market_phase)}</p>
      {tradingDataCaveat(run.market_phase, market) && <p role="alert">{tradingDataCaveat(run.market_phase, market)}</p>}
      {run.window_start && run.window_end && windowExceeded(run.window_start, run.window_end) && <p role="alert">수집 구간이 15초를 초과했습니다. 조건식별 수집 시각이 다를 수 있습니다.</p>}
      <p className="rounded border p-3">추출된 종목은 조건 조합의 결과일 뿐, 매수 추천이나 검증된 신호가 아닙니다.</p>
    </>}
    <Tabs defaultValue="results"><TabsList><TabsTrigger value="results">결과</TabsTrigger><TabsTrigger value="diagnostics">진단</TabsTrigger></TabsList>
      <TabsContent value="results" className="space-y-4">
        {run.status === "succeeded" ? <>
          {run.kind === "search" && <><a className="underline" href={`/runs/${run.id}/csv`}>CSV 다운로드</a>
            <ResultsTable results={results} refs={refs} />
            <section className="space-y-2"><h2 className="text-xl font-bold">이전 실행 비교</h2>
              {comparedRun ? <><Link href={`/runs/${comparedRun.id}`} className="underline">비교 대상 실행</Link>{comparedRun.strategy_version_id !== run.strategy_version_id && <Badge variant="outline">버전 다름</Badge>}<h3 className="font-semibold">이탈 목록</h3><p>{dropped.length ? dropped.join(", ") : "없음"}</p></> : <p>비교 대상이 없습니다.</p>}
            </section></>}
        </> : <p>성공한 실행의 결과만 표시합니다.</p>}
      </TabsContent>
      <TabsContent value="diagnostics"><Diagnostics snapshots={snapshots} excludedCodes={run.excluded_codes} /></TabsContent>
    </Tabs>
  </section>;
}
