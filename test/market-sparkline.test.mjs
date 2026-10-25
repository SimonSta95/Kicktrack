import test from "node:test";
import assert from "node:assert/strict";
import { selectMarketSparklinePoints } from "../src/features/market/market-sparkline.ts";

test("keeps a visible curve when only one observation is inside 14 days", () => {
  const points = [
    { date: "2026-08-28", value: 25_154_367 },
    { date: "2026-09-23", value: 21_285_754 },
    { date: "2026-09-24", value: 20_961_272 },
    { date: "2026-10-25", value: 23_154_618 },
  ];

  assert.deepEqual(
    selectMarketSparklinePoints(points, new Date("2026-10-25T12:00:00Z")),
    points,
  );
});

test("falls back to the latest valid observations for sparse long-term data", () => {
  const points = [
    { date: "invalid", value: 99 },
    { date: "2025-01-01", value: 100 },
    { date: "2026-10-25", value: 120 },
  ];

  assert.deepEqual(
    selectMarketSparklinePoints(points, new Date("2026-10-25T12:00:00Z")),
    [
      { date: "2025-01-01", value: 100 },
      { date: "2026-10-25", value: 120 },
    ],
  );
});
