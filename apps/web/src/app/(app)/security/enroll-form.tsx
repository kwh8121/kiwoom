"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { createBrowserClient } from "@/lib/supabase/client";

type Pending = { factorId: string; qrCode: string; secret: string };

export function EnrollForm() {
  const router = useRouter();
  const [enrolled, setEnrolled] = useState<string[] | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const supabase = createBrowserClient();
    supabase.auth.mfa.listFactors().then(({ data, error: listError }) => {
      if (listError) {
        setError("등록된 인증 앱을 불러오지 못했습니다.");
        return;
      }
      setEnrolled((data?.totp ?? []).map((factor) => factor.friendly_name ?? factor.id));
    });
  }, []);

  async function startEnrollment() {
    setBusy(true);
    setError(null);
    const supabase = createBrowserClient();
    const { data, error: enrollError } = await supabase.auth.mfa.enroll({
      factorType: "totp",
      friendlyName: `인증 앱 ${new Date().toISOString().slice(0, 10)}`,
    });
    if (enrollError || !data) {
      setError("등록을 시작하지 못했습니다.");
      setBusy(false);
      return;
    }
    setPending({ factorId: data.id, qrCode: data.totp.qr_code, secret: data.totp.secret });
    setBusy(false);
  }

  async function confirmEnrollment(event: React.FormEvent) {
    event.preventDefault();
    if (!pending) return;
    setBusy(true);
    setError(null);
    const supabase = createBrowserClient();
    const challenge = await supabase.auth.mfa.challenge({ factorId: pending.factorId });
    if (challenge.error) {
      setError("코드 확인을 시작하지 못했습니다.");
      setBusy(false);
      return;
    }
    const verified = await supabase.auth.mfa.verify({
      factorId: pending.factorId,
      challengeId: challenge.data.id,
      code,
    });
    if (verified.error) {
      setError("코드가 올바르지 않습니다. 인증 앱의 현재 코드를 확인해 주세요.");
      setBusy(false);
      return;
    }
    // Verified factors are what the row policies look for, so the requirement
    // takes effect from this point.
    setPending(null);
    setCode("");
    router.refresh();
  }

  return (
    <div className="space-y-4">
      {enrolled === null ? <p className="text-sm">확인 중…</p> : enrolled.length === 0 ? (
        <p className="text-sm">등록된 인증 앱이 없습니다.</p>
      ) : (
        <ul className="list-disc pl-5 text-sm">{enrolled.map((name) => <li key={name}>{name}</li>)}</ul>
      )}

      {pending === null ? (
        <Button type="button" onClick={startEnrollment} disabled={busy}>
          {busy ? "준비 중…" : "인증 앱 등록"}
        </Button>
      ) : (
        <form onSubmit={confirmEnrollment} className="space-y-3">
          {/* Supabase returns the QR as an SVG data URI. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={pending.qrCode} alt="인증 앱 등록 QR 코드" className="h-48 w-48" />
          <p className="text-sm">QR을 읽을 수 없으면 이 키를 직접 입력하세요: <code>{pending.secret}</code></p>
          <label className="block space-y-1">
            <span>인증 앱에 표시된 코드</span>
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
            {busy ? "확인 중…" : "등록 완료"}
          </Button>
        </form>
      )}
      {error && pending === null && <p role="alert" className="text-destructive text-sm">{error}</p>}
    </div>
  );
}
