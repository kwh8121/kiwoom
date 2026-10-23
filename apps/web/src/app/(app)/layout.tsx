import Link from "next/link";
import { redirect } from "next/navigation";
import { Button } from "@/components/ui/button";
import { createServerClient } from "@/lib/supabase/server";
import { signOut } from "@/app/login/actions";
import { secondFactorPending } from "@/lib/auth/mfa";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const supabase = await createServerClient();
  const { data, error } = await supabase.auth.getClaims();
  if (error || !data?.claims) redirect("/login");
  // The row policies refuse to fill these screens until the second factor is
  // presented, so send the person to the challenge instead of empty pages.
  if (await secondFactorPending()) redirect("/mfa");
  return (
    <>
      <header className="border-b">
        <nav aria-label="주 메뉴" className="mx-auto flex max-w-6xl items-center gap-6 p-4">
          <Link href="/profiles">프로필</Link>
          <Link href="/strategies">전략</Link>
          <Link href="/runs">실행 이력</Link>
          <Link href="/security">보안</Link>
          <form action={signOut} className="ml-auto"><Button variant="outline" type="submit">로그아웃</Button></form>
        </nav>
      </header>
      <main className="mx-auto w-full max-w-6xl p-6">{children}</main>
    </>
  );
}
