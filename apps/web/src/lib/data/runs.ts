import { z } from "zod";
import { createServerClient } from "@/lib/supabase/server";
import type { Database, Json } from "@/lib/supabase/database.types";
import type { RunCsvRow } from "@/lib/csv";

export type Run = Database["public"]["Tables"]["runs"]["Row"];
export type RunResult = Database["public"]["Tables"]["run_results"]["Row"];
export type Snapshot = Database["public"]["Tables"]["condition_snapshots"]["Row"];
export type ConditionRef = { conditionId: string; seq: string; name: string };
const refsSchema = z.array(z.object({ conditionId: z.string(), seq: z.string(), name: z.string() }));
function conditionRefs(value: Json | undefined): ConditionRef[] {
  const parsed = refsSchema.safeParse(value);
  return parsed.success ? parsed.data : [];
}

async function allRows<T>(fetchPage: (start: number, end: number) => PromiseLike<{ data: T[] | null; error: unknown }>) {
  const rows: T[] = [];
  const pageSize = 500;
  for (let start = 0; ; start += pageSize) {
    const page = await fetchPage(start, start + pageSize - 1);
    if (page.error) throw new Error("실행 결과를 불러오지 못했습니다.");
    rows.push(...(page.data ?? []));
    if (!page.data || page.data.length < pageSize) return { data: rows, error: null };
  }
}

export async function getRuns() {
  const supabase = await createServerClient();
  const runs = await supabase.from("runs").select("*").order("requested_at", { ascending: false }).limit(50);
  if (runs.error) throw new Error("실행 이력을 불러오지 못했습니다.");
  const strategyIds = [...new Set(runs.data.flatMap(run => run.strategy_id ? [run.strategy_id] : []))];
  const versionIds = [...new Set(runs.data.flatMap(run => run.strategy_version_id ? [run.strategy_version_id] : []))];
  const profileIds = [...new Set(runs.data.map(run => run.profile_id))];
  // Each metadata query is bounded to at most fifty referenced IDs.
  const [strategies, versions, profiles] = await Promise.all([
    strategyIds.length ? supabase.from("strategies").select("id, name").in("id", strategyIds) : Promise.resolve({ data: [], error: null }),
    versionIds.length ? supabase.from("strategy_versions").select("id, version").in("id", versionIds) : Promise.resolve({ data: [], error: null }),
    profileIds.length ? supabase.from("broker_profiles").select("id, alias, display_name, mode").in("id", profileIds) : Promise.resolve({ data: [], error: null }),
  ]);
  if (strategies.error || versions.error || profiles.error) throw new Error("실행 이력을 불러오지 못했습니다.");
  return { runs: runs.data, strategies: strategies.data, versions: versions.data, profiles: profiles.data };
}

export async function getRun(runId: string) {
  if (!z.uuid().safeParse(runId).success) return null;
  const supabase = await createServerClient();
  const { data: auth, error: authError } = await supabase.auth.getClaims();
  if (authError || !auth?.claims?.sub) return null;
  const found = await supabase.from("runs").select("*").eq("id", runId).eq("user_id", auth.claims.sub).maybeSingle();
  if (found.error) throw new Error("실행을 불러오지 못했습니다.");
  if (!found.data) return null;
  const run = found.data;
  const [results, snapshots, version, comparedRun, previousResults] = await Promise.all([
    allRows((start, end) => supabase.from("run_results").select("*").eq("run_id", run.id).order("code").range(start, end)),
    supabase.from("condition_snapshots").select("*").eq("run_id", run.id).order("seq"),
    run.strategy_version_id ? supabase.from("strategy_versions").select("*").eq("id", run.strategy_version_id).maybeSingle() : Promise.resolve({ data: null, error: null }),
    run.compared_run_id ? supabase.from("runs").select("id, strategy_version_id").eq("id", run.compared_run_id).maybeSingle() : Promise.resolve({ data: null, error: null }),
    run.compared_run_id ? allRows((start, end) => supabase.from("run_results").select("code").eq("run_id", run.compared_run_id!).order("code").range(start, end)) : Promise.resolve({ data: [], error: null }),
  ]);
  if (results.error || snapshots.error || version.error || comparedRun.error || previousResults.error) throw new Error("실행 결과를 불러오지 못했습니다.");
  const members = snapshots.data.length ? await allRows((start, end) => supabase.from("condition_snapshot_members").select("snapshot_id, code, raw_code").in("snapshot_id", snapshots.data.map(s => s.id)).order("snapshot_id").order("code").range(start, end)) : { data: [], error: null };
  if (members.error) throw new Error("원본 종목코드를 불러오지 못했습니다.");
  const refs = conditionRefs(version.data?.condition_refs);
  // Follow the frozen DFS ref order when a code occurs in multiple snapshots.
  const rawCodes = new Map<string, string>();
  const orderedSnapshots = [...snapshots.data].sort((a, b) => refs.findIndex(r => r.conditionId === a.condition_id) - refs.findIndex(r => r.conditionId === b.condition_id));
  for (const snapshot of orderedSnapshots) {
    for (const member of members.data.filter(m => m.snapshot_id === snapshot.id)) {
      if (!rawCodes.has(member.code)) rawCodes.set(member.code, member.raw_code);
    }
  }
  const csvRows: RunCsvRow[] = results.data.map(result => ({
    code: result.code, rawCode: rawCodes.get(result.code) ?? "", name: result.name,
    instrumentType: result.instrument_type,
    matchedNames: refs.filter(ref => result.matched_condition_ids.includes(ref.conditionId)).map(ref => ref.name),
    diff: result.diff === "new" ? "new" : "kept", price: result.price,
    changeRate: result.change_rate === null ? null : String(result.change_rate),
  }));
  return { run, results: results.data, snapshots: snapshots.data, version: version.data, refs, comparedRun: comparedRun.data, previousCodes: previousResults.data.map(r => r.code), csvRows };
}
