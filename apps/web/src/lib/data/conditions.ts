import { createServerClient } from "@/lib/supabase/server";
import type { Database } from "@/lib/supabase/database.types";

export type Condition = Database["public"]["Tables"]["conditions"]["Row"];

export async function getConditions(profileId: string) {
  const supabase = await createServerClient();
  // The session client applies RLS to both the route lookup and child rows.
  const profile = await supabase.from("broker_profiles").select("*").eq("id", profileId).maybeSingle();
  if (profile.error) throw new Error("프로필을 불러오지 못했습니다.");
  if (!profile.data) return null;
  const [conditions, runs] = await Promise.all([
    supabase.from("conditions").select("*").eq("profile_id", profileId).eq("is_active", true).order("seq"),
    supabase.from("runs").select("id, requested_at, status, sync_summary, error_code")
      .eq("profile_id", profileId).eq("kind", "sync").order("requested_at", { ascending: false }).limit(10),
  ]);
  if (conditions.error || runs.error) throw new Error("조건식과 동기화 이력을 불러오지 못했습니다.");
  const events = runs.data.length
    ? await supabase.from("condition_sync_events").select("*").eq("profile_id", profileId)
      .in("run_id", runs.data.map((run) => run.id)).order("created_at", { ascending: false })
    : { data: [], error: null };
  if (events.error) throw new Error("동기화 이벤트를 불러오지 못했습니다.");
  return { profile: profile.data, conditions: conditions.data, runs: runs.data, events: events.data };
}
