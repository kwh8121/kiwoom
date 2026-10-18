"use client";

import { useActionState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createProfile } from "./actions";

export function ProfileForm() {
  const [state, action, pending] = useActionState(createProfile, {});
  return <form action={action} className="space-y-3 rounded-lg border p-4">
    <h2 className="font-semibold">프로필 등록</h2>
    <p className="text-sm text-muted-foreground">워커에 등록된 별칭과 모드를 입력하세요.</p>
    <Label htmlFor="alias">별칭</Label>
    <Input id="alias" name="alias" placeholder="kiwoom-demo" pattern="[a-z0-9][a-z0-9-]{0,62}" maxLength={63} required />
    <Label htmlFor="display_name">표시 이름</Label>
    <Input id="display_name" name="display_name" maxLength={100} />
    <Label htmlFor="mode">모드</Label>
    <select id="mode" name="mode" defaultValue="demo" className="rounded border p-2">
      <option value="demo">모의</option><option value="real">실전</option>
    </select>
    {state.error && <p role="alert">{state.error}</p>}
    {state.success && <p role="status">{state.success}</p>}
    <Button type="submit" disabled={pending}>{pending ? "등록 중…" : "등록"}</Button>
  </form>;
}
