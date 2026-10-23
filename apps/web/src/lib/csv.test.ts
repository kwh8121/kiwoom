import { describe, expect, it } from "vitest";
import { buildRunCsv, escapeCsvText, formatCsvNumber, type RunCsvRow } from "./csv";
const row = (overrides: Partial<RunCsvRow> = {}): RunCsvRow => ({ code: "005930", rawCode: "A005930", name: "삼성전자", instrumentType: "stock", matchedNames: ["조건 A", "조건 B"], diff: "new", price: 70000, changeRate: "-2.52", ...overrides });
describe("run CSV", () => {
  it("emits a BOM and only a CRLF-terminated header for no results", () => {
    expect(buildRunCsv([])).toBe("\uFEFF종목코드,원본코드,종목명,유형,충족조건,변화,현재가,등락률\r\n");
  });
  it.each(["=SUM(A1)", "+1", "-x", "@a", "\tA", "\rA"])("neutralizes text formula prefix %j", value => {
    expect(escapeCsvText(value).replace(/^"/, "").startsWith("'")).toBe(true);
  });
  it.each([" =SUM(A1)", "  @a", "\u00a0=1", "\n=1", " \t-x"])("neutralizes whitespace-prefixed formula %j", value => {
    expect(escapeCsvText(value).replace(/^"/, "").startsWith("'")).toBe(true);
  });
  it("leaves ordinary leading whitespace alone", () => {
    expect(escapeCsvText(" 삼성전자")).toBe(" 삼성전자");
  });
  it("quotes delimiters, newlines and doubled embedded quotes", () => {
    expect(escapeCsvText('=HYPERLINK("x")')).toBe('"\'=HYPERLINK(""x"")"');
    expect(escapeCsvText("카카오, 테스트")).toBe('"카카오, 테스트"');
    expect(escapeCsvText("a\nb")).toBe('"a\nb"');
    expect(escapeCsvText("a\rb")).toBe('"a\rb"');
    expect(escapeCsvText(null)).toBe("");
  });
  it("keeps numeric negatives, zero and missing values distinct", () => {
    expect(formatCsvNumber("-2.52")).toBe("-2.52");
    expect(formatCsvNumber(-2.52)).toBe("-2.52");
    expect(formatCsvNumber(0)).toBe("0");
    expect(formatCsvNumber(null)).toBe("");
  });
  it("preserves alphanumeric/raw codes, joined names and differences", () => {
    expect(buildRunCsv([row({ code: "0010F0", rawCode: "A0010F0" })])).toContain("0010F0,A0010F0,삼성전자,stock,조건 A | 조건 B,신규,70000,-2.52\r\n");
    expect(buildRunCsv([row({ diff: "kept", name: "=name", matchedNames: ["@condition"] })])).toContain("'=name,stock,'@condition,유지");
  });
});

// Route-level checks use the same owner-scoped data boundary as the page.
import { beforeEach, vi } from "vitest";
const { getRun } = vi.hoisted(() => ({ getRun: vi.fn() }));
vi.mock("@/lib/data/runs", () => ({ getRun }));
import { GET } from "@/app/(app)/runs/[runId]/csv/route";
const runId = "00000000-0000-4000-8000-000000000001";
const requestCsv = (id = runId) => GET(new Request(`http://localhost/runs/${id}/csv`), { params: Promise.resolve({ runId: id }) });
describe("CSV download authorization boundary", () => {
  beforeEach(() => vi.resetAllMocks());
  it.each(["queued", "running", "failed", "timed_out", "cancelled"])("returns 404 for %s", async status => {
    getRun.mockResolvedValue({ run: { status, kind: "search" }, csvRows: [] });
    expect((await requestCsv()).status).toBe(404);
  });
  it("returns 404 for a succeeded sync run, which has no result rows to export", async () => {
    getRun.mockResolvedValue({ run: { status: "succeeded", kind: "sync" }, csvRows: [] });
    expect((await requestCsv()).status).toBe(404);
  });
  it("returns 404 for missing or RLS-hidden runs and invalid IDs", async () => {
    getRun.mockResolvedValue(null);
    expect((await requestCsv()).status).toBe(404);
    expect((await requestCsv("invalid")).status).toBe(404);
  });
  it("downloads succeeded owner-visible results with UTF8 BOM and private headers", async () => {
    getRun.mockResolvedValue({ run: { status: "succeeded", kind: "search" }, csvRows: [row()] });
    const response = await requestCsv();
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("text/csv; charset=utf-8");
    expect(response.headers.get("Content-Disposition")).toBe(`attachment; filename="run-${runId}.csv"`);
    expect(response.headers.get("Cache-Control")).toContain("no-store");
    const bytes = new Uint8Array(await response.arrayBuffer());
    expect([...bytes.slice(0, 3)]).toEqual([239, 187, 191]);
    expect(new TextDecoder().decode(bytes)).toContain("A005930");
  });
});

const { createServerClient } = vi.hoisted(() => ({ createServerClient: vi.fn() }));
vi.mock("@/lib/supabase/server", () => ({ createServerClient }));
describe("owner-scoped run data", () => {
  beforeEach(() => vi.resetAllMocks());
  it("returns no data without a verified session", async () => {
    const from = vi.fn();
    createServerClient.mockResolvedValue({ auth: { getClaims: async () => ({ data: null, error: null }) }, from });
    const { getRun: actualGetRun } = await vi.importActual<typeof import("@/lib/data/runs")>("@/lib/data/runs");
    expect(await actualGetRun(runId)).toBeNull();
    expect(from).not.toHaveBeenCalled();
  });
  it("checks the claimed owner and stops for a hidden run", async () => {
    const eq = vi.fn();
    const query = { select: vi.fn(), eq, maybeSingle: async () => ({ data: null, error: null }) };
    query.select.mockReturnValue(query);
    eq.mockReturnValue(query);
    const from = vi.fn().mockReturnValue(query);
    createServerClient.mockResolvedValue({ auth: { getClaims: async () => ({ data: { claims: { sub: "owner-id" } }, error: null }) }, from });
    const { getRun: actualGetRun } = await vi.importActual<typeof import("@/lib/data/runs")>("@/lib/data/runs");
    expect(await actualGetRun(runId)).toBeNull();
    expect(eq).toHaveBeenCalledWith("user_id", "owner-id");
    expect(from).toHaveBeenCalledTimes(1);
  });
});

it("loads every result/member page and preserves frozen names and original codes", async () => {
  const codes = Array.from({ length: 501 }, (_, i) => String(i).padStart(6, "0"));
  const tables: Record<string, unknown> = {
    runs: { id: runId, strategy_version_id: "version-id", compared_run_id: null, status: "succeeded" },
    strategy_versions: { condition_refs: [{ conditionId: "condition-id", seq: "1", name: "저장된 이름" }] },
    run_results: codes.map(code => ({ code, name: "종목", instrument_type: "stock", matched_condition_ids: ["condition-id"], diff: "new", price: 10, change_rate: -2.52 })),
    condition_snapshots: [{ id: "snapshot-id", condition_id: "condition-id" }],
    condition_snapshot_members: codes.map(code => ({ code, raw_code: `A${code}`, snapshot_id: "snapshot-id" })),
  };
  const from = vi.fn((table: string) => {
    let start = 0;
    let end = 499;
    const query = {
      select: () => query, eq: () => query, order: () => query, in: () => query,
      range: (first: number, last: number) => { start = first; end = last; return query; },
      maybeSingle: async () => ({ data: tables[table], error: null }),
      then: (resolve: (value: unknown) => unknown) => Promise.resolve({ data: Array.isArray(tables[table]) ? tables[table].slice(start, end + 1) : tables[table], error: null }).then(resolve),
    };
    return query;
  });
  createServerClient.mockResolvedValue({ auth: { getClaims: async () => ({ data: { claims: { sub: "owner-id" } }, error: null }) }, from });
  const { getRun: actualGetRun } = await vi.importActual<typeof import("@/lib/data/runs")>("@/lib/data/runs");
  const data = await actualGetRun(runId);
  expect(data?.csvRows).toHaveLength(501);
  expect(data?.csvRows[500]).toMatchObject({ rawCode: "A000500", matchedNames: ["저장된 이름"], changeRate: "-2.52" });
});
