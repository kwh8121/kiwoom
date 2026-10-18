"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";
import { createServerClient } from "@/lib/supabase/server";
import { mapRpcError } from "@/lib/rpc";

export type ProfileActionState = { error?: string; success?: string };
const profileInput = z.object({
  alias: z.string().regex(/^[a-z0-9][a-z0-9-]{0,62}$/),
  mode: z.enum(["real", "demo"]),
  display_name: z.string().trim().max(100),
});

export async function createProfile(_prev: ProfileActionState, formData: FormData): Promise<ProfileActionState> {
  const parsed = profileInput.safeParse(Object.fromEntries(formData));
  if (!parsed.success) return { error: "별칭(영문 소문자·숫자·하이픈, 최대 63자)과 모드를 확인해 주세요." };
  const supabase = await createServerClient();
  const { data, error: authError } = await supabase.auth.getClaims();
  if (authError || !data?.claims?.sub) return { error: "로그인이 필요합니다." };
  const { error } = await supabase.from("broker_profiles").insert({ ...parsed.data, display_name: parsed.data.display_name || null, user_id: data.claims.sub });
  if (error) return { error: "프로필을 만들지 못했습니다. 중복 별칭인지 확인해 주세요." };
  revalidatePath("/profiles");
  return { success: "프로필을 등록했습니다." };
}

export async function requestSync(_prev: ProfileActionState, formData: FormData): Promise<ProfileActionState> {
  const parsed = z.object({ profileId: z.uuid(), idempotencyKey: z.uuid() }).safeParse(Object.fromEntries(formData));
  if (!parsed.success) return { error: "동기화 요청을 확인해 주세요." };
  const supabase = await createServerClient();
  const { data, error: authError } = await supabase.auth.getClaims();
  if (authError || !data?.claims?.sub) return { error: "로그인이 필요합니다." };
  const { error } = await supabase.rpc("request_run", {
    p_kind: "sync", p_profile_id: parsed.data.profileId,
    // Generated RPC types omit SQL argument nullability; sync requires SQL NULL.
    p_strategy_id: null as unknown as string,
    p_idempotency_key: parsed.data.idempotencyKey,
  });
  const mapped = mapRpcError(error);
  if (mapped) return { error: mapped.message };
  revalidatePath("/profiles");
  revalidatePath(`/profiles/${parsed.data.profileId}/conditions`);
  return { success: "동기화 요청을 접수했습니다. 워커 처리 후 화면이 갱신됩니다." };
}
