"use server";

import { redirect } from "next/navigation";
import { z } from "zod";
import { safeNextPath } from "@/lib/auth/paths";
import { createServerClient } from "@/lib/supabase/server";

export type SignInState = { error?: string };

const credentials = z.object({
  email: z.email(),
  password: z.string().min(1),
});

export async function signIn(_prev: SignInState, formData: FormData): Promise<SignInState> {
  const parsed = credentials.safeParse({ email: formData.get("email"), password: formData.get("password") });
  if (!parsed.success) return { error: "이메일과 비밀번호를 확인해 주세요." };
  const supabase = await createServerClient();
  const { error } = await supabase.auth.signInWithPassword(parsed.data);
  if (error) return { error: "로그인에 실패했습니다. 이메일과 비밀번호를 확인해 주세요." };
  const next = formData.get("next");
  redirect(safeNextPath(typeof next === "string" ? next : undefined));
}

export async function signOut(): Promise<void> {
  const supabase = await createServerClient();
  const { error } = await supabase.auth.signOut();
  if (error) throw new Error("로그아웃에 실패했습니다. 다시 시도해 주세요.");
  redirect("/login");
}
