import { describe, expect, it } from "vitest";
import { mapRpcError } from "./rpc";
describe("mapRpcError", () => {
  it.each(["PROFILE_BUSY", "CONDITION_INACTIVE", "STRATEGY_HAS_NO_VERSION", "NOT_FOUND", "PROFILE_MISMATCH", "INVALID_DEFINITION", "RUN_NOT_CANCELLABLE"])("maps %s", (code) => {
    expect(mapRpcError({ message: code })).toMatchObject({ code });
    expect(mapRpcError({ message: code })?.message).toMatch(/[가-힣]/);
  });
  it("asks for stale conditions to be saved again", () => {
    expect(mapRpcError({ message: "CONDITION_INACTIVE" })?.message).toContain("다시 저장");
  });
  it("never reflects unknown database error details", () => {
    expect(mapRpcError(null)).toBeNull();
    expect(mapRpcError({ message: "private database detail" })).toMatchObject({ code: "UNKNOWN" });
    expect(mapRpcError({ message: "private database detail" })?.message).not.toContain("private");
  });
});
