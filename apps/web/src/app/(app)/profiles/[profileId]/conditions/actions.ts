"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";
import { createServerClient } from "@/lib/supabase/server";

export async function updateDescription(conditionId: string, text: string): Promise<{ error?: string; success?: string }> {
  const parsed = z.object({ conditionId: z.uuid(), text: z.string().trim().max(2000) }).safeParse({ conditionId, text });
  if (!parsed.success) return { error: "설명은 2,000자 이내로 입력해 주세요." };
  const supabase = await createServerClient();
  const { data, error: authError } = await supabase.auth.getClaims();
  if (authError || !data?.claims?.sub) return { error: "로그인이 필요합니다." };
  const result = await supabase.from("conditions").update({ ref_description: parsed.data.text || null })
    .eq("id", parsed.data.conditionId).eq("is_active", true).select("profile_id").maybeSingle();
  if (result.error || !result.data) return { error: "설명을 저장하지 못했습니다. 조건식을 다시 확인해 주세요." };
  revalidatePath(`/profiles/${result.data.profile_id}/conditions`);
  return { success: "설명을 저장했습니다." };
}
