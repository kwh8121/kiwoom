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
    supabase.from("worker_heartbeats").select("aliases, seen_at"),
  ]);
  if (profiles.error || heartbeats.error) throw new Error("프로필과 워커 상태를 불러오지 못했습니다.");
  const items = await Promise.all(profiles.data.map(async (profile) => {
    const { data, error } = await supabase.from("runs")
      .select("id, requested_at, status, sync_summary, error_code")
      .eq("profile_id", profile.id).eq("kind", "sync")
      .order("requested_at", { ascending: false }).limit(1).maybeSingle();
    if (error) throw new Error("최근 동기화를 불러오지 못했습니다.");
    return { ...profile, latestSync: data };
  }));
  return { profiles: items, heartbeats: heartbeats.data };
}
