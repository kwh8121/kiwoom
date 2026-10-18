import { readFileSync } from "node:fs";
import { expect, test } from "vitest";
import { strategyDefinitionSchema } from "./schema";
import { validateDefinition } from "./validate";
import type { ConditionInfo, StrategyDefinition, StrategyExpr, ValidationIssueCode } from "./types";

const rawCases = readFileSync(new URL("../../../../../packages/contracts/cases/validate.json", import.meta.url), "utf8");
const cases = JSON.parse(rawCases).cases as {
  name: string; definition: unknown; conditions: Record<string, ConditionInfo>; issues: ValidationIssueCode[];
}[];
const floatFixtureStart = rawCases.indexOf('"name": "schema_invalid_schema_version_float"');
const nextFixtureStart = rawCases.indexOf('"name":', floatFixtureStart + 1);
const floatFixtureText = rawCases.slice(floatFixtureStart, nextFixtureStart < 0 ? undefined : nextFixtureStart);
const floatFixtureVersion = floatFixtureText.match(/"schemaVersion"\s*:\s*([0-9.]+)/)?.[1];
if (floatFixtureVersion !== "1.0") {
  throw new Error("schema_invalid_schema_version_float must retain its lexical 1.0 value");
}

for (const c of cases) {
  // JSON.parse erases Python's int/float distinction: both 1 and 1.0 become JS 1.
  test.skipIf(c.name === "schema_invalid_schema_version_float")(c.name, () => {
    expect(validateDefinition(c.definition, new Map(Object.entries(c.conditions)))).toEqual(c.issues);
  });
}
const leaf = (conditionId: string): StrategyExpr => ({ type: "condition", conditionId });
const definition = (expr: StrategyExpr): StrategyDefinition => ({ schemaVersion: 1, profileId: "p", exchange: "K", expr });
const conditions = new Map<string, ConditionInfo>([["A", { profileId: "p", active: true }]]);

test("JSON decimal schemaVersion loses lexical distinction before validation", () => {
  expect(floatFixtureVersion).toBe("1.0");
  expect(JSON.parse('{"schemaVersion":1.0}').schemaVersion).toBe(1);
  expect(validateDefinition(definition(leaf("A")), conditions)).toEqual([]);
});

test.each([null, [], {}, { ...definition(leaf("A")), schemaVersion: 1.5 }, { ...definition(leaf("A")), extra: true }, definition({ type: "condition", conditionId: "" }), { ...definition(leaf("A")), profileId: "" }, definition({ type: "and", children: [null] } as unknown as StrategyExpr)])("rejects malformed input: %j", (input) => {
  expect(validateDefinition(input, conditions)).toEqual(["SCHEMA_INVALID"]);
});

test("schema validates shape while validator reports arity", () => {
  const input = definition({ type: "and", children: [] });
  expect(strategyDefinitionSchema.safeParse(input).success).toBe(true);
  expect(validateDefinition(input, conditions)).toEqual(["TOO_FEW_CHILDREN"]);
});

test("sorts and deduplicates simultaneous issues", () => {
  const expr: StrategyExpr = { type: "or", children: [leaf("A"), leaf("A"), leaf("missing"), { type: "exclude", base: leaf("missing"), subtract: [] }] };
  expect(validateDefinition(definition(expr), new Map([["A", { profileId: "other", active: false }]]))).toEqual(["EMPTY_SUBTRACT", "INACTIVE_CONDITION", "PROFILE_MISMATCH", "UNKNOWN_CONDITION"]);
});

test("counts duplicate occurrences toward the ten leaf limit", () => {
  expect(validateDefinition(definition({ type: "and", children: Array.from({ length: 10 }, () => leaf("A")) }), conditions)).toEqual([]);
  expect(validateDefinition(definition({ type: "and", children: Array.from({ length: 11 }, () => leaf("A")) }), conditions)).toEqual(["MAX_LEAVES_EXCEEDED"]);
});

test("root depth is one and exclude base participates in depth", () => {
  let expr = leaf("A");
  for (let i = 0; i < 4; i++) expr = { type: "exclude", base: expr, subtract: [leaf("A")] };
  expect(validateDefinition(definition(expr), conditions)).toEqual([]);
  expect(validateDefinition(definition({ type: "exclude", base: expr, subtract: [leaf("A")] }), conditions)).toEqual(["MAX_DEPTH_EXCEEDED"]);
});
