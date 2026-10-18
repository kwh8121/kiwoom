import { z } from "zod";
import type { StrategyDefinition, StrategyExpr } from "./types";

// Shape only: group arity, depth, and references belong to validateDefinition.
const expressionSchema: z.ZodType<StrategyExpr> = z.lazy(() =>
  z.discriminatedUnion("type", [
    z.strictObject({ type: z.literal("condition"), conditionId: z.string().min(1) }),
    z.strictObject({ type: z.literal("and"), children: z.array(expressionSchema) }),
    z.strictObject({ type: z.literal("or"), children: z.array(expressionSchema) }),
    z.strictObject({ type: z.literal("exclude"), base: expressionSchema, subtract: z.array(expressionSchema) }),
  ]),
);

export const strategyDefinitionSchema: z.ZodType<StrategyDefinition> = z.strictObject({
  schemaVersion: z.literal(1),
  profileId: z.string().min(1),
  exchange: z.literal("K"),
  expr: expressionSchema,
});
