import { expect, test } from "vitest";
import { editorReducer, toDefinition } from "./editor";
import type { EditorAction } from "./editor";
import type { StrategyExpr } from "./types";
const c = (conditionId: string): StrategyExpr => ({ type: "condition", conditionId });
const group: StrategyExpr = { type: "and", children: [c("A"), c("B")] };
const exclude: StrategyExpr = { type: "exclude", base: c("A"), subtract: [c("B"), c("C")] };

test("sets and removes root including an empty editor", () => {
  expect(editorReducer(null, { type: "setRoot", node: c("A") })).toEqual(c("A"));
  expect(editorReducer(group, { type: "remove", path: [] })).toBeNull();
  expect(editorReducer(null, { type: "addChild", path: [], node: c("A") })).toBeNull();
});
test("addChild appends to group", () => {
  expect(editorReducer(group, { type: "addChild", path: [], node: c("C") })).toEqual({ type: "and", children: [c("A"), c("B"), c("C")] });
});
test("remove leaf from group preserves draft arity", () => {
  expect(editorReducer(group, { type: "remove", path: [0] })).toEqual({ type: "and", children: [c("B")] });
});
test("and to exclude keeps first as base", () => {
  expect(editorReducer(group, { type: "setOperator", path: [], operator: "exclude" })).toEqual({ type: "exclude", base: c("A"), subtract: [c("B")] });
});
test("exclude to or flattens base and subtract", () => {
  expect(editorReducer(exclude, { type: "setOperator", path: [], operator: "or" })).toEqual({ type: "or", children: [c("A"), c("B"), c("C")] });
});
test("changes group operators in place in a nested tree", () => {
  const root: StrategyExpr = { type: "or", children: [group, c("C")] };
  expect(editorReducer(root, { type: "setOperator", path: [0], operator: "or" })).toEqual({ type: "or", children: [{ type: "or", children: [c("A"), c("B")] }, c("C")] });
});
test("exclude paths count base first then subtract", () => {
  expect(editorReducer(exclude, { type: "setCondition", path: [0], conditionId: "X" })).toEqual({ type: "exclude", base: c("X"), subtract: [c("B"), c("C")] });
  expect(editorReducer(exclude, { type: "setCondition", path: [2], conditionId: "X" })).toEqual({ type: "exclude", base: c("A"), subtract: [c("B"), c("X")] });
  expect(editorReducer(exclude, { type: "remove", path: [0] })).toEqual({ type: "exclude", base: c("B"), subtract: [c("C")] });
  expect(editorReducer(exclude, { type: "remove", path: [1] })).toEqual({ type: "exclude", base: c("A"), subtract: [c("C")] });
  expect(editorReducer(exclude, { type: "addChild", path: [], node: c("D") })).toEqual({ type: "exclude", base: c("A"), subtract: [c("B"), c("C"), c("D")] });
});
test("removing the final exclude base removes that node", () => {
  expect(editorReducer({ type: "exclude", base: c("A"), subtract: [] }, { type: "remove", path: [0] })).toBeNull();
});
test.each<EditorAction>([
  { type: "remove", path: [-1] }, { type: "remove", path: [0.5] }, { type: "remove", path: [9] },
  { type: "setCondition", path: [0, 0], conditionId: "X" },
  { type: "setCondition", path: [], conditionId: "X" },
])("invalid paths and incompatible actions leave the state unchanged: %j", (action) => {
  expect(editorReducer(group, action)).toBe(group);
});
test("cannot convert empty group or a leaf into exclude without a base", () => {
  const empty: StrategyExpr = { type: "or", children: [] };
  expect(editorReducer(empty, { type: "setOperator", path: [], operator: "exclude" })).toBe(empty);
  expect(editorReducer(c("A"), { type: "setOperator", path: [], operator: "and" })).toEqual(c("A"));
});
test("reducer does not mutate frozen nested input and shares untouched nodes", () => {
  const root: StrategyExpr = Object.freeze({ type: "or", children: Object.freeze([Object.freeze(exclude), Object.freeze(c("D"))]) }) as unknown as StrategyExpr;
  Object.freeze(exclude.subtract);
  Object.freeze(exclude.base);
  const result = editorReducer(root, { type: "setCondition", path: [0, 1], conditionId: "X" });
  expect(result).toEqual({ type: "or", children: [{ type: "exclude", base: c("A"), subtract: [c("X"), c("C")] }, c("D")] });
  expect(root).toEqual({ type: "or", children: [exclude, c("D")] });
  if (result?.type === "or" && root.type === "or") expect(result.children[1]).toBe(root.children[1]);
});
test("wraps editor expression for saving", () => {
  expect(toDefinition("p", group)).toEqual({ schemaVersion: 1, profileId: "p", exchange: "K", expr: group });
});
