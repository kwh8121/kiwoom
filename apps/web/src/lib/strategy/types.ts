export type StrategyExpr =
  | { type: "condition"; conditionId: string }
  | { type: "and" | "or"; children: StrategyExpr[] }
  | { type: "exclude"; base: StrategyExpr; subtract: StrategyExpr[] };

export type StrategyDefinition = {
  schemaVersion: 1;
  profileId: string;
  exchange: "K";
  expr: StrategyExpr;
};

export type ValidationIssueCode =
  | "SCHEMA_INVALID"
  | "TOO_FEW_CHILDREN"
  | "EMPTY_SUBTRACT"
  | "MAX_DEPTH_EXCEEDED"
  | "MAX_LEAVES_EXCEEDED"
  | "UNKNOWN_CONDITION"
  | "INACTIVE_CONDITION"
  | "PROFILE_MISMATCH";

export type ConditionInfo = { profileId: string; active: boolean };
