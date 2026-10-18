import { z } from "zod";
import { getRun } from "@/lib/data/runs";
import { buildRunCsv } from "@/lib/csv";

export async function GET(_request: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  if (!z.uuid().safeParse(runId).success) return new Response(null, { status: 404 });
  const data = await getRun(runId);
  if (!data || data.run.status !== "succeeded") return new Response(null, { status: 404 });
  return new Response(buildRunCsv(data.csvRows), { headers: {
    "Content-Type": "text/csv; charset=utf-8",
    "Content-Disposition": `attachment; filename="run-${runId}.csv"`,
    "Cache-Control": "private, no-store",
  } });
}
