import { expect, test } from "vitest";
import { renderExpression } from "./preview";
import type { StrategyExpr } from "./types";
const c = (conditionId: string): StrategyExpr => ({ type: "condition", conditionId });
const names = (id: string) => ({ basic: "기본종목", prev: "전일고가돌파", gc: "골든크로스" })[id] ?? id;
test.each<[StrategyExpr, string]>([
  [c("basic"), "기본종목"],
  [{ type: "and", children: [c("basic"), { type: "or", children: [c("prev"), c("gc")] }] }, "기본종목 AND (전일고가돌파 OR 골든크로스)"],
  [{ type: "exclude", base: c("A"), subtract: [c("B")] }, "A EXCLUDE B"],
  [{ type: "exclude", base: c("A"), subtract: [c("B"), c("C")] }, "A EXCLUDE (B OR C)"],
  [{ type: "and", children: [c("A"), { type: "exclude", base: c("B"), subtract: [c("C")] }] }, "A AND (B EXCLUDE C)"],
  [{ type: "exclude", base: { type: "and", children: [c("A"), c("B")] }, subtract: [{ type: "or", children: [c("C"), c("D")] }, c("E")] }, "(A AND B) EXCLUDE ((C OR D) OR E)"],
  [{ type: "and", children: [{ type: "and", children: [c("A"), c("B")] }, c("C")] }, "(A AND B) AND C"],
])("renders %j", (expr, expected) => {
  expect(renderExpression(expr, names)).toBe(expected);
});
