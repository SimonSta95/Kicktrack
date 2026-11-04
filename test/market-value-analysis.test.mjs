import test from "node:test";
import assert from "node:assert/strict";
import { analyzeMarketValues } from "../src/features/player-detail/market-value-analysis.ts";

test("calculates day-to-day changes without inventing missing calendar days", () => {
  const analysis = analyzeMarketValues([
    { date: "2026-09-01", value: 10_000_000 },
    { date: "2026-09-04", value: 11_000_000 },
    { date: "2026-09-05", value: 10_450_000 },
  ]);

  assert.ok(analysis);
  assert.equal(analysis.changes.length, 2);
  assert.deepEqual(analysis.changes.map(({ change }) => change), [1_000_000, -550_000]);
  assert.equal(analysis.upDays, 1);
  assert.equal(analysis.downDays, 1);
  assert.deepEqual(analysis.currentStreak, { direction: "down", count: 1 });
  assert.equal(analysis.distanceFromHighPct, -5);
});

test("deduplicates dates and derives streaks from consecutive observations", () => {
  const analysis = analyzeMarketValues([
    { date: "2026-09-03", value: 120 },
    { date: "2026-09-01", value: 100 },
    { date: "2026-09-02", value: 105 },
    { date: "2026-09-02", value: 110 },
    { date: "2026-09-04", value: 115 },
    { date: "2026-09-05", value: 110 },
  ]);

  assert.ok(analysis);
  assert.deepEqual(analysis.points.map(({ value }) => value), [100, 110, 120, 115, 110]);
  assert.equal(analysis.longestUpStreak, 2);
  assert.equal(analysis.longestDownStreak, 2);
  assert.deepEqual(analysis.currentStreak, { direction: "down", count: 2 });
  assert.equal(analysis.bestDay?.change, 10);
  assert.equal(analysis.worstDay?.change, -5);
});

test("returns null when no valid market values exist", () => {
  assert.equal(analyzeMarketValues([
    { date: "invalid", value: 100 },
    { date: "2026-09-01", value: 0 },
  ]), null);
});
