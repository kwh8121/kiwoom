"use client";
import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { cancelQueuedRun } from "./actions";

export function RunPoller({ runId, status }: { runId: string; status: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState("");
  useEffect(() => {
    if (status !== "queued" && status !== "running") return;
    const timer = setInterval(() => router.refresh(), 2000);
    return () => clearInterval(timer);
  }, [router, status]);
  if (status !== "queued") return null;
  return <div className="space-y-2"><Button disabled={pending} variant="outline" onClick={() => startTransition(async () => {
    const result = await cancelQueuedRun(runId);
    setError(result.error ?? "");
    if (!result.error) router.refresh();
  })}>{pending ? "취소 중…" : "실행 취소"}</Button>{error && <p role="alert">{error}</p>}</div>;
}
