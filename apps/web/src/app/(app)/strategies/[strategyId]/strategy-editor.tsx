"use client";
import { useReducer, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import type { Condition } from "@/lib/data/conditions";
import { editorReducer, toDefinition, type EditorAction } from "@/lib/strategy/editor";
import { renderExpression } from "@/lib/strategy/preview";
import { validateDefinition } from "@/lib/strategy/validate";
import type { StrategyDefinition, StrategyExpr } from "@/lib/strategy/types";
import { cloneStrategy, saveVersion } from "./actions";
import { RunButton } from "./run-button";

function ExpressionNode({ node, path, conditions, dispatch }: { node: StrategyExpr; path: number[]; conditions: Condition[]; dispatch: React.Dispatch<EditorAction> }) {
  const first = conditions[0];
  const leaf = (): StrategyExpr => ({ type: "condition", conditionId: first?.id ?? "" });
  const children = node.type === "condition" ? [] : node.type === "exclude" ? [node.base, ...node.subtract] : node.children;
  return <fieldset className="space-y-3 rounded border p-3"><legend>{path.length ? `항목 ${path[path.length - 1] + 1}` : "조건식 조합"}</legend>
    {node.type === "condition" ? <label>조건식<select className="ml-2 rounded border p-2" value={node.conditionId} onChange={e => dispatch({ type: "setCondition", path, conditionId: e.target.value })}>
      {!conditions.some(c => c.id === node.conditionId) && <option value={node.conditionId}>사용할 활성 조건식을 선택해 주세요</option>}
      {conditions.map(c => <option value={c.id} key={c.id}>{c.name}</option>)}</select></label> : <>
      <label>연산자<select className="ml-2 rounded border p-2" value={node.type} onChange={e => dispatch({ type: "setOperator", path, operator: e.target.value as "and" | "or" | "exclude" })}><option value="and">AND (모두 충족)</option><option value="or">OR (하나 이상)</option><option value="exclude">EXCLUDE (첫 항목에서 나머지 제외)</option></select></label>
      {children.map((child, i) => <ExpressionNode key={i} node={child} path={[...path, i]} conditions={conditions} dispatch={dispatch} />)}
      <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={!first} onClick={() => dispatch({ type: "addChild", path, node: leaf() })}>조건식 추가</Button><Button variant="outline" disabled={!first} onClick={() => dispatch({ type: "addChild", path, node: { type: "or", children: [leaf(), leaf()] } })}>그룹 추가</Button></div>
    </>}
    <Button variant="outline" onClick={() => dispatch({ type: "remove", path })}>삭제</Button>
  </fieldset>;
}

export function StrategyEditor({ strategyId, profileId, conditions, initial }: { strategyId: string; profileId: string; conditions: Condition[]; initial: StrategyDefinition | null }) {
  const [expr, dispatch] = useReducer(editorReducer, initial?.expr ?? null);
  const [saved, setSaved] = useState(initial ? JSON.stringify(initial.expr) : null);
  const [message, setMessage] = useState("");
  const [pending, startTransition] = useTransition();
  const router = useRouter();
  const definition = expr ? toDefinition(profileId, expr) : null;
  const issues = definition ? validateDefinition(definition, new Map(conditions.map(c => [c.id, { profileId: c.profile_id, active: c.is_active }]))) : ["조건식을 추가해 주세요."];
  const dirty = JSON.stringify(expr) !== saved;
  const first = conditions[0];
  return <div className="space-y-4">
    {!conditions.length && <p role="alert">활성 조건식이 없습니다. 프로필에서 조건식을 먼저 동기화해 주세요.</p>}
    {expr ? <ExpressionNode node={expr} path={[]} conditions={conditions} dispatch={dispatch} /> : <div className="flex gap-2"><Button disabled={!first} onClick={() => dispatch({ type: "setRoot", node: { type: "condition", conditionId: first.id } })}>조건식 추가</Button><Button disabled={!first} onClick={() => dispatch({ type: "setRoot", node: { type: "and", children: [{ type: "condition", conditionId: first.id }, { type: "condition", conditionId: first.id }] } })}>그룹으로 시작</Button></div>}
    <section aria-label="미리보기" className="rounded bg-muted p-4"><h2 className="font-medium">미리보기</h2><p>{expr ? renderExpression(expr, id => conditions.find(c => c.id === id)?.name ?? "비활성 또는 알 수 없는 조건식") : "조건식을 선택해 주세요."}</p></section>
    {issues.length > 0 && <ul aria-label="검증 오류" role="alert">{issues.map(issue => <li key={issue}>{issue}</li>)}</ul>}
    <Button disabled={pending || !definition || issues.length > 0 || !dirty} onClick={() => {
      if (!definition) return;
      const snapshot = JSON.stringify(definition.expr);
      startTransition(async () => {
        const result = await saveVersion(strategyId, definition);
        if (result.ok) { setSaved(snapshot); setMessage(`버전 ${result.version}을 저장했습니다.`); router.refresh(); }
        else setMessage(result.error ?? result.issues?.join(", ") ?? "저장하지 못했습니다.");
      });
    }}>{pending ? "처리 중…" : "새 버전 저장"}</Button>
    {message && <p role="status">{message}</p>}
    <RunButton key={saved ?? "draft"} strategyId={strategyId} disabled={pending || dirty || !saved || issues.length > 0} dirty={dirty} />
    <Button variant="outline" disabled={pending || dirty || !saved} onClick={() => startTransition(async () => { const result = await cloneStrategy(strategyId); setMessage(result.error); })}>저장된 전략 복제 (같은 프로필)</Button>
  </div>;
}
