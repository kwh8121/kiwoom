"use client";
import { useRef, useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { requestSearchRun } from "./actions";
export function RunButton({ strategyId, disabled, dirty }: { strategyId: string; disabled: boolean; dirty: boolean }) {
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState("");
  const submitting = useRef(false);
  return <div className="space-y-2"><Button disabled={disabled || pending} onClick={() => {
    if (submitting.current) return;
    submitting.current = true;
    startTransition(async () => {
      try { const result = await requestSearchRun(strategyId, idempotencyKey); setError(result.error); }
      finally { submitting.current = false; }
    });
  }}>{pending ? "실행 요청 중…" : "검색 실행"}</Button>{dirty && <p>저장 후 실행해 주세요.</p>}{error && <p role="alert">{error}</p>}</div>;
}
