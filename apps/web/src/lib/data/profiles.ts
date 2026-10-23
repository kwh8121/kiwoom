import { createServerClient } from "@/lib/supabase/server";
import type { Database, Json } from "@/lib/supabase/database.types";

export type Profile = Database["public"]["Tables"]["broker_profiles"]["Row"];
export type SyncRun = Pick<Database["public"]["Tables"]["runs"]["Row"], "id" | "requested_at" | "status" | "sync_summary" | "error_code">;

function counts(summary: Json | null): ((key: string) => number) | null {
  if (!summary || typeof summary !== "object" || Array.isArray(summary)) return null;
  return (key) => (typeof summary[key] === "number" ? summary[key] : 0);
}

export function syncSummary(summary: Json | null): string {
  const count = counts(summary);
  if (!count) return "요약 없음";
  return `추가 ${count("added")} · 삭제 ${count("removed")} · 교체 ${count("replaced")} · 유지 ${count("unchanged")}`;
}

// 조건식 목록(CNSRLST)은 완료 표시 없는 단일 배열로 오므로, 증권사가 잘린 목록을
// 돌려준 것과 사용자가 실제로 지운 것을 워커도 데이터베이스도 구분할 수 없다.
// 그래서 동기화를 거부하지 않는다. 거부하면 정당한 대량 삭제가 막히고 우회할
// 방법이 없다. 대신 사람이 판단할 수 있게 드러내고, 복구 방법을 함께 알린다.
export function syncRemovalWarning(summary: Json | null): string | null {
  const count = counts(summary);
  if (!count) return null;
  const removed = count("removed");
  // 하나만 사라진 것은 평범한 편집이다. 절반 이상이 한 번에 사라지는 모양이
  // 잘린 목록이 만드는 모양이다.
  if (removed < 2) return null;
  const before = removed + count("replaced") + count("unchanged");
  if (before === 0 || removed * 2 < before) return null;
  return `이번 동기화에서 조건식 ${removed}개가 한 번에 비활성화되었습니다(이전 ${before}개 중). 증권사가 잘린 목록을 돌려준 경우일 수 있습니다. 직접 지운 것이 아니라면 다시 동기화해 주세요. 되살아난 조건식은 원래 식별자를 유지하므로 전략은 그대로 다시 동작합니다.`;
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
