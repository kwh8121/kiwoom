import { describe, expect, it } from "vitest";
import { tradingDataCaveat } from "./run";

describe("stale data caveat", () => {
  // market_phase is computed from the clock alone, so a weekday holiday is
  // classified `regular` and the caveat used to disappear exactly when the
  // market had in fact been closed all day.
  it("warns on a weekday the market was closed", () => {
    const caveat = tradingDataCaveat("regular", { isClosure: true, calendarCoversYear: true });

    expect(caveat).not.toBeNull();
    expect(caveat).toContain("휴장");
  });

  it("stays quiet during trading hours on a confirmed trading day", () => {
    expect(tradingDataCaveat("regular", { isClosure: false, calendarCoversYear: true })).toBeNull();
  });

  // Not knowing is not the same as knowing the market was open. An unfilled
  // calendar has to produce a caveat, never silent confidence.
  it("says the calendar is unfilled rather than claiming the market was open", () => {
    const caveat = tradingDataCaveat("regular", { isClosure: false, calendarCoversYear: false });

    expect(caveat).not.toBeNull();
    expect(caveat).toContain("휴장일 달력");
  });

  it("keeps warning outside trading hours", () => {
    for (const phase of ["pre", "post", "weekend"]) {
      expect(tradingDataCaveat(phase, { isClosure: false, calendarCoversYear: true })).toContain("장 마감");
    }
  });

  it("says nothing when the phase was never recorded", () => {
    expect(tradingDataCaveat(null, { isClosure: false, calendarCoversYear: true })).toBeNull();
  });
});
