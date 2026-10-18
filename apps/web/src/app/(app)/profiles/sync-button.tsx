"use client";

import { useActionState, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { requestSync, type ProfileActionState } from "./actions";

export function SyncButton({ profileId, refreshPage = true }: { profileId: string; refreshPage?: boolean }) {
  const [key, setKey] = useState("");
  const [state, action, pending] = useActionState(async (prev: ProfileActionState, formData: FormData) => {
    const idempotencyKey = key || crypto.randomUUID();
    setKey(idempotencyKey);
    formData.set("idempotencyKey", idempotencyKey);
    const result = await requestSync(prev, formData);
    if (result.success) setKey("");
    return result;
  }, {});
  const router = useRouter();
  useEffect(() => {
    if (!refreshPage) return;
    const interval = setInterval(() => router.refresh(), 15_000);
    return () => clearInterval(interval);
  }, [refreshPage, router]);
  return <form action={action} className="space-y-2">
    <input type="hidden" name="profileId" value={profileId} />
    <input type="hidden" name="idempotencyKey" value={key} />
    <Button type="submit" disabled={pending}>{pending ? "요청 중…" : "조건식 동기화"}</Button>
    {state.error && <p role="alert" className="text-sm text-destructive">{state.error}</p>}
    {state.success && <p role="status" className="text-sm">{state.success}</p>}
  </form>;
}
