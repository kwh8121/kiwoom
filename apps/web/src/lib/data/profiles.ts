import { createServerClient } from "@/lib/supabase/server";
import type { Database, Json } from "@/lib/supabase/database.types";

export type Profile = Database["public"]["Tables"]["broker_profiles"]["Row"];
export type SyncRun = Pick<Database["public"]["Tables"]["runs"]["Row"], "id" | "requested_at" | "status" | "sync_summary" | "error_code">;

export function syncSummary(summary: Json | null): string {
  if (!summary || typeof summary !== "object" || Array.isArray(summary)) return "요약 없음";
  const count = (key: string) => typeof summary[key] === "number" ? summary[key] : 0;
  return `추가 ${count("added")} · 삭제 ${count("removed")} · 교체 ${count("replaced")} · 유지 ${count("unchanged")}`;
}

export async function getProfiles() {
  const supabase = await createServerClient();
  const [profiles, heartbeats] = await Promise.all([
    supabase.from("broker_profiles").select("*").order("created_at"),
    // The view narrows a shared worker's alias roster to the caller's own
    // aliases, which is all reachability needs.
    supabase.from("my_worker_heartbeats").select("aliases, seen_at"),
  ]);
  if (profiles.error || heartbeats.error) throw new Error("프로필과 워커 상태를 불러오지 못했습니다.");

  // One query for every profile, not one per profile: this page auto-refreshes,
  // so a per-profile lookup multiplied the round trips on each refresh.
  const latestByProfile = new Map<string, SyncRun>();
  if (profiles.data.length > 0) {
    const { data, error } = await supabase.from("latest_profile_sync_runs")
      .select("id, requested_at, status, sync_summary, error_code, profile_id");
    if (error) throw new Error("최근 동기화를 불러오지 못했습니다.");
    for (const { profile_id, ...run } of data) {
      if (profile_id !== null) latestByProfile.set(profile_id, run as SyncRun);
    }
  }

  const items = profiles.data.map((profile) => ({ ...profile, latestSync: latestByProfile.get(profile.id) ?? null }));
  // A view cannot declare its columns non-null, so the row type admits nulls the
  // query never produces. Drop an uninterpretable row instead of reading it as a
  // worker whose last heartbeat is unknown.
  const reachability = heartbeats.data.flatMap(({ aliases, seen_at }) =>
    aliases && seen_at ? [{ aliases, seen_at }] : []);
  return { profiles: items, heartbeats: reachability };
}
