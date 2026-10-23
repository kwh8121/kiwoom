"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { createBrowserClient } from "@/lib/supabase/client";

export function ChallengeForm() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const supabase = createBrowserClient();
    const factors = await supabase.auth.mfa.listFactors();
    const factor = factors.data?.totp?.[0];
    if (factors.error || !factor) {
      setError("등록된 인증 앱을 찾지 못했습니다.");
      setBusy(false);
      return;
    }
    const challenge = await supabase.auth.mfa.challenge({ factorId: factor.id });
    if (challenge.error) {
      setError("코드 확인을 시작하지 못했습니다.");
      setBusy(false);
      return;
    }
    const verified = await supabase.auth.mfa.verify({
      factorId: factor.id,
      challengeId: challenge.data.id,
      code,
    });
    if (verified.error) {
      setError("코드가 올바르지 않습니다. 인증 앱의 현재 코드를 확인해 주세요.");
      setBusy(false);
      return;
    }
    // The session is aal2 from here, so the app screens will fill.
    router.replace("/profiles");
    router.refresh();
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <label className="block space-y-1">
        <span>인증 코드</span>
        <input
          className="w-full rounded border p-2"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={code}
          onChange={(event) => setCode(event.target.value.trim())}
          required
        />
      </label>
      {error && <p role="alert" className="text-destructive text-sm">{error}</p>}
      <Button type="submit" disabled={busy || code.length === 0}>
        {busy ? "확인 중…" : "확인"}
      </Button>
    </form>
  );
}
