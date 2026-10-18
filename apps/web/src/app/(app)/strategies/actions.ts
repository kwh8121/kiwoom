"use server";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { createServerClient } from "@/lib/supabase/server";
export type StrategyActionState = { error?: string };
export async function createStrategy(_prev: StrategyActionState, formData: FormData): Promise<StrategyActionState> {
  const parsed = z.object({ profileId: z.uuid(), name: z.string().trim().min(1).max(100) }).safeParse(Object.fromEntries(formData));
  if (!parsed.success) return { error: "프로필과 전략 이름(1~100자)을 확인해 주세요." };
  const supabase = await createServerClient();
  const { data: auth, error: authError } = await supabase.auth.getClaims();
  if (authError || !auth?.claims?.sub) return { error: "로그인이 필요합니다." };
  const { data, error } = await supabase.from("strategies").insert({ profile_id: parsed.data.profileId, name: parsed.data.name, user_id: auth.claims.sub }).select("id").single();
  if (error || !data) return { error: "전략을 만들지 못했습니다. 프로필을 확인해 주세요." };
  revalidatePath("/strategies");
  redirect(`/strategies/${data.id}`);
}
