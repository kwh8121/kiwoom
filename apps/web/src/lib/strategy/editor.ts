import type { StrategyDefinition, StrategyExpr } from "./types";

export type EditorAction =
  | { type: "setRoot"; node: StrategyExpr }
  | { type: "addChild"; path: number[]; node: StrategyExpr }
  | { type: "remove"; path: number[] }
  | { type: "setOperator"; path: number[]; operator: "and" | "or" | "exclude" }
  | { type: "setCondition"; path: number[]; conditionId: string };

type Group = Exclude<StrategyExpr, { type: "condition" }>;

function childrenOf(node: Group): StrategyExpr[] {
  return node.type === "exclude" ? [node.base, ...node.subtract] : node.children;
}

// Removing an exclude base promotes the first subtract child. No child left
// means the node is removed; incomplete groups remain editable drafts.
function withChildren(node: Group, children: StrategyExpr[]): StrategyExpr | null {
  if (node.type !== "exclude") return { ...node, children };
  const [base, ...subtract] = children;
  return base ? { type: "exclude", base, subtract } : null;
}

function updateAt(
  node: StrategyExpr,
  path: number[],
  update: (node: StrategyExpr) => StrategyExpr | null,
): StrategyExpr | null {
  if (path.length === 0) return update(node);
  if (node.type === "condition") return node;
  const [index, ...rest] = path;
  const children = childrenOf(node);
  if (!Number.isInteger(index) || index < 0 || index >= children.length) return node;
  const current = children[index];
  const changed = updateAt(current, rest, update);
  if (changed === current) return node;
  return withChildren(node, children.flatMap((child, i) => i === index ? (changed ? [changed] : []) : [child]));
}

export function editorReducer(state: StrategyExpr | null, action: EditorAction): StrategyExpr | null {
  if (action.type === "setRoot") return action.node;
  if (!state) return null;

  return updateAt(state, action.path, (node) => {
    switch (action.type) {
      case "remove":
        return null;
      case "setCondition":
        return node.type === "condition" ? { ...node, conditionId: action.conditionId } : node;
      case "addChild":
        return node.type === "condition" ? node : withChildren(node, [...childrenOf(node), action.node]);
      case "setOperator": {
        if (node.type === "condition" || node.type === action.operator) return node;
        const children = childrenOf(node);
        if (action.operator !== "exclude") return { type: action.operator, children };
        const [base, ...subtract] = children;
        return base ? { type: "exclude", base, subtract } : node;
      }
    }
  });
}

export function toDefinition(profileId: string, expr: StrategyExpr): StrategyDefinition {
  return { schemaVersion: 1, profileId, exchange: "K", expr };
}
