import type { StrategyExpr } from "./types";

export function renderExpression(expr: StrategyExpr, nameOf: (id: string) => string): string {
  function child(node: StrategyExpr): string {
    const text = renderExpression(node, nameOf);
    return node.type === "condition" ? text : `(${text})`;
  }
  if (expr.type === "condition") return nameOf(expr.conditionId);
  if (expr.type === "exclude") {
    const subtract = expr.subtract.map(child).join(" OR ");
    return `${child(expr.base)} EXCLUDE ${expr.subtract.length > 1 ? `(${subtract})` : subtract}`;
  }
  return expr.children.map(child).join(expr.type === "and" ? " AND " : " OR ");
}
