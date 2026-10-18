"use client";
import { useActionState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Profile } from "@/lib/data/profiles";
import { createStrategy } from "./actions";
export function NewStrategyForm({ profiles }: { profiles: Profile[] }) {
  const [state, action, pending] = useActionState(createStrategy, {});
  return <form action={action} className="flex flex-wrap items-end gap-3 rounded border p-4">
    <label>프로필<select name="profileId" required className="block rounded border p-2">{profiles.map(p => <option key={p.id} value={p.id}>{p.display_name || p.alias} ({p.mode === "real" ? "실전" : "모의"})</option>)}</select></label>
    <label>전략 이름<Input name="name" required maxLength={100} /></label>
    <Button type="submit" disabled={pending || profiles.length === 0}>{pending ? "생성 중…" : "전략 만들기"}</Button>
    {profiles.length === 0 && <p>프로필을 먼저 등록해 주세요.</p>}
    {state.error && <p role="alert">{state.error}</p>}
  </form>;
}
