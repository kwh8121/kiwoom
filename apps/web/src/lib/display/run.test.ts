import { describe, expect, it } from "vitest";
import { statusLabel, resultSummary, marketPhaseLabel, windowExceeded, droppedCodes } from "./run";
describe("run display", () => {
  it("labels every execution status", () => {
    expect(["queued", "running", "succeeded", "failed", "timed_out", "cancelled"].map(statusLabel)).toEqual(["대기", "실행 중", "성공", "실패", "시간 초과", "취소"]);
    expect(statusLabel("unknown")).toBe("알 수 없음");
  });
  it("distinguishes successful empty results from failures", () => {
    expect(resultSummary("succeeded", 0)).toBe("성공 · 0건");
    expect(resultSummary("succeeded", 12)).toBe("성공 · 12건");
    expect(resultSummary("failed", null)).toBe("실패");
  });
  it("labels all market phases", () => expect(["pre", "regular", "post", "weekend"].map(marketPhaseLabel)).toEqual(["장전", "장중", "장후", "주말"]));
  it("warns strictly after fifteen seconds", () => {
    expect(windowExceeded("2026-10-17T05:00:00Z", "2026-10-17T05:00:16Z")).toBe(true);
    expect(windowExceeded("2026-10-17T05:00:00Z", "2026-10-17T05:00:15Z")).toBe(false);
  });
  it("sorts dropped codes lexically, removes duplicates and handles empty runs", () => {
    expect(droppedCodes(["002", "001", "001"], [])).toEqual(["001", "002"]);
    expect(droppedCodes(["005930", "0010F0", "000660"], ["005930", "0010F0"])).toEqual(["000660"]);
  });
});
