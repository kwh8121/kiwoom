import { describe, expect, it } from "vitest";
import { syncRemovalWarning } from "./profiles";

describe("large condition removal warning", () => {
  // CNSRLST returns one flat list with no completeness marker, so a truncated
  // broker response and a real bulk deletion look identical. The database
  // cannot tell them apart and neither can the worker, so this is a warning
  // the person can judge, not a refusal.
  it("warns when half or more of the conditions disappeared at once", () => {
    const warning = syncRemovalWarning({ added: 0, removed: 28, replaced: 0, unchanged: 2 });

    expect(warning).not.toBeNull();
    expect(warning).toContain("28");
    // It has to say what to do, or the warning is just alarming.
    expect(warning).toContain("다시 동기화");
  });

  it("stays quiet for an ordinary removal", () => {
    expect(syncRemovalWarning({ added: 0, removed: 1, replaced: 0, unchanged: 29 })).toBeNull();
  });

  it("stays quiet when a single condition profile loses its only condition", () => {
    // One of one is half or more, but a single removal is ordinary editing.
    expect(syncRemovalWarning({ added: 0, removed: 1, replaced: 0, unchanged: 0 })).toBeNull();
  });

  it("stays quiet for a first sync that only adds", () => {
    expect(syncRemovalWarning({ added: 30, removed: 0, replaced: 0, unchanged: 0 })).toBeNull();
  });

  it("ignores a summary it cannot read", () => {
    expect(syncRemovalWarning(null)).toBeNull();
    expect(syncRemovalWarning("broken")).toBeNull();
  });
});
