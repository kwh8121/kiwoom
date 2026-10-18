"use server";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";
import { createServerClient } from "@/lib/supabase/server";
import { mapRpcError } from "@/lib/rpc";
import { validateDefinition } from "@/lib/strategy/validate";
import { strategyDefinitionSchema } from "@/lib/strategy/schema";
import type { StrategyDefinition, ValidationIssueCode } from "@/lib/strategy/types";

type SaveResult = { ok: true; version: number } | { ok: false; issues?: ValidationIssueCode[]; error?: string };

export async function saveVersion(strategyId: string, definition: StrategyDefinition): Promise<SaveResult> {
  if (!z.uuid().safeParse(strategyId).success) return { ok: false, error: "전략을 확인해 주세요." };
  const supabase = await createServerClient();
  const { data: auth, error: authError } = await supabase.auth.getClaims();
  if (authError || !auth?.claims?.sub) return { ok: false, error: "로그인이 필요합니다." };
  const strategy = await supabase.from("strategies").select("profile_id").eq("id", strategyId).maybeSingle();
  if (strategy.error || !strategy.data) return { ok: false, error: "전략을 찾을 수 없습니다." };
  const conditions = await supabase.from("conditions").select("id, profile_id, is_active")
    .eq("profile_id", strategy.data.profile_id).eq("is_active", true);
  if (conditions.error) return { ok: false, error: "활성 조건식을 불러오지 못했습니다." };
  const issues = validateDefinition(definition, new Map(conditions.data.map(c => [c.id, { profileId: c.profile_id, active: c.is_active }])));
  const parsed = strategyDefinitionSchema.safeParse(definition);
  if (parsed.success && parsed.data.profileId !== strategy.data.profile_id && !issues.includes("PROFILE_MISMATCH")) issues.push("PROFILE_MISMATCH");
  if (issues.length) return { ok: false, issues: issues.sort() };
  const { data, error } = await supabase.rpc("create_strategy_version", { p_strategy_id: strategyId, p_definition: definition });
  const mapped = mapRpcError(error);
  if (mapped || !data) return { ok: false, error: mapped?.message ?? "버전을 저장하지 못했습니다." };
  revalidatePath(`/strategies/${strategyId}`);
  revalidatePath("/strategies");
  return { ok: true, version: data.version };
}

export async function requestSearchRun(strategyId: string, idempotencyKey: string): Promise<{ error: string } | never> {
  if (!z.uuid().safeParse(strategyId).success || !z.uuid().safeParse(idempotencyKey).success) return { error: "실행 요청을 확인해 주세요." };
  const supabase = await createServerClient();
  const { data: auth, error: authError } = await supabase.auth.getClaims();
  if (authError || !auth?.claims?.sub) return { error: "로그인이 필요합니다." };
  const strategy = await supabase.from("strategies").select("profile_id").eq("id", strategyId).maybeSingle();
  if (strategy.error || !strategy.data) return { error: "전략을 찾을 수 없습니다." };
  const { data, error } = await supabase.rpc("request_run", { p_kind: "search", p_profile_id: strategy.data.profile_id, p_strategy_id: strategyId, p_idempotency_key: idempotencyKey });
  const mapped = mapRpcError(error);
  if (mapped || !data) return { error: mapped?.message ?? "실행을 요청하지 못했습니다." };
  redirect(`/runs/${data.id}`);
}

export async function cloneStrategy(strategyId: string): Promise<{ error: string } | never> {
  if (!z.uuid().safeParse(strategyId).success) return { error: "전략을 확인해 주세요." };
  const supabase = await createServerClient();
  const { data: auth, error: authError } = await supabase.auth.getClaims();
  if (authError || !auth?.claims?.sub) return { error: "로그인이 필요합니다." };
  const source = await supabase.from("strategies").select("*").eq("id", strategyId).maybeSingle();
  if (source.error || !source.data?.current_version_id) return { error: "저장된 전략이 필요합니다." };
  const version = await supabase.from("strategy_versions").select("definition").eq("id", source.data.current_version_id).eq("strategy_id", strategyId).maybeSingle();
  const definition = strategyDefinitionSchema.safeParse(version.data?.definition);
  if (version.error || !definition.success) return { error: "전략 정의를 불러오지 못했습니다." };
  const clone = await supabase.from("strategies").insert({ name: `${source.data.name.slice(0, 94)} (복제)`, profile_id: source.data.profile_id, user_id: auth.claims.sub }).select("id").single();
  if (clone.error || !clone.data) return { error: "전략을 복제하지 못했습니다." };
  const saved = await saveVersion(clone.data.id, definition.data);
  // A failed save leaves a recoverable draft, with its destination in the message.
  if (!saved.ok) return { error: `복제 초안이 생성되었지만 버전 저장에 실패했습니다. 전략 목록에서 다시 저장해 주세요. ${saved.error ?? saved.issues?.join(", ") ?? ""}` };
  revalidatePath("/strategies");
  redirect(`/strategies/${clone.data.id}`);
}
