import { strategyDefinitionSchema } from "./schema";
import type { ConditionInfo, StrategyExpr, ValidationIssueCode } from "./types";

export function validateDefinition(
  definition: unknown,
  conditions: ReadonlyMap<string, ConditionInfo>,
): ValidationIssueCode[] {
  const parsed = strategyDefinitionSchema.safeParse(definition);
  if (!parsed.success) return ["SCHEMA_INVALID"];
  const { profileId, expr } = parsed.data;
  const issues = new Set<ValidationIssueCode>();

  function visit(expr: StrategyExpr, depth: number): number {
    if (depth > 5) issues.add("MAX_DEPTH_EXCEEDED");
    if (expr.type === "condition") {
      const condition = conditions.get(expr.conditionId);
      if (!condition) issues.add("UNKNOWN_CONDITION");
      else {
        if (condition.profileId !== profileId) issues.add("PROFILE_MISMATCH");
        if (!condition.active) issues.add("INACTIVE_CONDITION");
      }
      return 1;
    }

    let children: StrategyExpr[];
    if (expr.type === "exclude") {
      if (expr.subtract.length === 0) issues.add("EMPTY_SUBTRACT");
      children = [expr.base, ...expr.subtract];
    } else {
      if (expr.children.length < 2) issues.add("TOO_FEW_CHILDREN");
      children = expr.children;
    }
    const leaves = children.reduce((count, child) => count + visit(child, depth + 1), 0);
    if (leaves > 10) issues.add("MAX_LEAVES_EXCEEDED");
    return leaves;
  }

  visit(expr, 1);
  return [...issues].sort();
}
