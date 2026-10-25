import test from "node:test";
import assert from "node:assert/strict";
import { berlinDateOnly, dateOnlyToUtcMs, isDateOlderThan, recentDateCutoffMs } from "../src/lib/date-only.ts";

test("uses the Europe/Berlin calendar date around UTC midnight", () => {
  assert.equal(berlinDateOnly(new Date("2026-03-28T23:30:00Z")), "2026-03-29");
  assert.equal(berlinDateOnly(new Date("2026-10-25T23:30:00Z")), "2026-10-26");
});

test("calculates calendar cutoffs without local timezone parsing", () => {
  const now = new Date("2026-10-25T12:00:00Z");
  assert.equal(recentDateCutoffMs(7, now), dateOnlyToUtcMs("2026-10-19"));
  assert.equal(isDateOlderThan("2026-10-23", 2, now), false);
  assert.equal(isDateOlderThan("2026-10-22", 2, now), true);
  assert.equal(isDateOlderThan("invalid", 2, now), true);
});
