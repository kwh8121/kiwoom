"use client";

import { useActionState, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Condition } from "@/lib/data/conditions";
import { formatKst } from "@/lib/display/time";
import { updateDescription } from "./actions";

function DescriptionForm({ condition }: { condition: Condition }) {
  const [state, action, pending] = useActionState(async (_prev: { error?: string; success?: string }, formData: FormData) => {
    return updateDescription(condition.id, String(formData.get("description") ?? ""));
  }, {});
  return <form action={action} className="min-w-48 space-y-2">
    <Label htmlFor={`description-${condition.id}`}>참고 설명 (이름 기반 추정)</Label>
    <Textarea id={`description-${condition.id}`} name="description" defaultValue={condition.ref_description ?? ""} maxLength={2000} />
    <Button type="submit" variant="outline" size="sm" disabled={pending}>{pending ? "저장 중…" : "설명 저장"}</Button>
    {state.error && <p role="alert">{state.error}</p>}
    {state.success && <p role="status">{state.success}</p>}
  </form>;
}

export function ConditionTable({ conditions }: { conditions: Condition[] }) {
  const [query, setQuery] = useState("");
  const filtered = conditions.filter((condition) => condition.name.toLocaleLowerCase("ko").includes(query.trim().toLocaleLowerCase("ko")));
  return <div className="space-y-3">
    <Label htmlFor="condition-search">조건식 이름 검색</Label>
    <Input id="condition-search" value={query} onChange={(event) => setQuery(event.target.value)} type="search" />
    <p className="text-sm text-muted-foreground">참고 설명은 이름 기반 추정이며 실제 조건식의 내부 규칙과 다를 수 있습니다.</p>
    <Table>
      <TableHeader><TableRow><TableHead>seq</TableHead><TableHead>이름</TableHead><TableHead>참고 설명</TableHead><TableHead>마지막 동기화</TableHead></TableRow></TableHeader>
      <TableBody>{filtered.map((condition) => <TableRow key={condition.id}>
        <TableCell>{condition.seq}</TableCell><TableCell>{condition.name}</TableCell>
        <TableCell><DescriptionForm condition={condition} /></TableCell><TableCell>{formatKst(condition.last_synced_at)}</TableCell>
      </TableRow>)}</TableBody>
    </Table>
    {filtered.length === 0 && <p>표시할 활성 조건식이 없습니다. 이름 검색을 확인하거나 동기화해 주세요.</p>}
  </div>;
}
