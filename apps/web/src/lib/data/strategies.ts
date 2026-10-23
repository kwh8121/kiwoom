import { createServerClient } from "@/lib/supabase/server";
import type { Database } from "@/lib/supabase/database.types";
export type Strategy = Database["public"]["Tables"]["strategies"]["Row"];
export type StrategyVersion = Database["public"]["Tables"]["strategy_versions"]["Row"];

export async function getStrategies() {
  const supabase = await createServerClient();
  const [strategies, profiles] = await Promise.all([
    supabase.from("strategies").select("*").is("archived_at", null).order("updated_at", { ascending: false }),
    supabase.from("broker_profiles").select("*").order("created_at"),
  ]);
  if (strategies.error || profiles.error) throw new Error("전략과 프로필을 불러오지 못했습니다.");
  return { strategies: strategies.data, profiles: profiles.data };
}

export async function getStrategy(strategyId: string) {
  const supabase = await createServerClient();
  const strategy = await supabase.from("strategies").select("*").eq("id", strategyId).maybeSingle();
  if (strategy.error) throw new Error("전략을 불러오지 못했습니다.");
  if (!strategy.data) return null;
  const [versions, conditions, profile] = await Promise.all([
    supabase.from("strategy_versions").select("*").eq("strategy_id", strategyId).order("version", { ascending: false }),
    supabase.from("conditions").select("*").eq("profile_id", strategy.data.profile_id).eq("is_active", true).order("seq"),
    supabase.from("broker_profiles").select("*").eq("id", strategy.data.profile_id).maybeSingle(),
  ]);
  if (versions.error || conditions.error || profile.error) throw new Error("전략 버전과 조건식을 불러오지 못했습니다.");
  if (!profile.data) return null;
  return { strategy: strategy.data, versions: versions.data, conditions: conditions.data, profile: profile.data };
}
