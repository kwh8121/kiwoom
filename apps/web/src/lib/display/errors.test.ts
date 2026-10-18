import { expect, it } from "vitest";
import { runErrorMessage } from "./errors";
it.each(["RATE_LIMITED", "TOKEN_INVALID", "IP_DEVICE_AUTH", "PROFILE_CONFIG", "CONDITION_CHANGED", "KIWOOM_INPUT", "KIWOOM_TRANSIENT", "KIWOOM_UNKNOWN", "RESPONSE_TIMEOUT", "INCOMPLETE_PAGINATION", "KIWOOM_PROTOCOL", "INVALID_DEFINITION", "LEASE_EXPIRED", "RUN_TIMEOUT"])("translates %s", (code) => {
  expect(runErrorMessage(code)).toMatch(/[가-힣]/);
  expect(runErrorMessage(code)).not.toBe(runErrorMessage("UNKNOWN_CODE"));
});
it("gives actionable condition and registration guidance", () => {
  expect(runErrorMessage("CONDITION_CHANGED")).toContain("동기화");
  expect(runErrorMessage("IP_DEVICE_AUTH")).toBe("워커 호스트 IP 또는 단말기 등록을 확인하세요");
  expect(runErrorMessage(null)).toBe("");
});
