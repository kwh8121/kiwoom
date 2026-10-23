import { redirect } from "next/navigation";
import { createServerClient } from "@/lib/supabase/server";
import { secondFactorPending } from "@/lib/auth/mfa";
import { ChallengeForm } from "./challenge-form";

export default async function MfaPage() {
  const supabase = await createServerClient();
  const { data, error } = await supabase.auth.getClaims();
  if (error || !data?.claims) redirect("/login");
  // Nothing to ask for once the requirement is met.
  if (!(await secondFactorPending())) redirect("/profiles");
  return (
    <main className="mx-auto w-full max-w-md space-y-4 p-6">
      <h1 className="text-2xl font-bold">인증 앱 코드 입력</h1>
      <p className="text-sm">등록한 인증 앱에 표시된 6자리 코드를 입력해 주세요.</p>
      <ChallengeForm />
    </main>
  );
}
