"use server";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { createServerClient } from "@/lib/supabase/server";
import { mapRpcError } from "@/lib/rpc";

export async function cancelQueuedRun(runId: string): Promise<{ error?: string }> {
  if (!z.uuid().safeParse(runId).success) return { error: "실행을 확인해 주세요." };
  const supabase = await createServerClient();
  const { data: auth, error: authError } = await supabase.auth.getClaims();
  if (authError || !auth?.claims?.sub) return { error: "로그인이 필요합니다." };
  // The RPC atomically checks ownership and queued status, including poll races.
  const { error } = await supabase.rpc("cancel_run", { p_run_id: runId });
  const mapped = mapRpcError(error);
  if (mapped) return { error: mapped.message };
  revalidatePath(`/runs/${runId}`);
  revalidatePath("/runs");
  return {};
}
