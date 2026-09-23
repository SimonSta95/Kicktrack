import assert from "node:assert/strict";
import test from "node:test";

import {
  calculateBidCapacity,
  evaluateBidEligibility,
  resolveBalanceAfterActiveBids,
} from "../src/features/market/bid-eligibility.ts";

test("uses Kickbase budget-after-bids as the authoritative balance", () => {
  assert.equal(resolveBalanceAfterActiveBids(10_000_000, 7_500_000, 4_000_000), 7_500_000);
});

test("falls back to visible active bids when Kickbase omits budget-after-bids", () => {
  assert.equal(resolveBalanceAfterActiveBids(10_000_000, null, 2_500_000), 7_500_000);
  assert.equal(resolveBalanceAfterActiveBids(null, null, 2_500_000), null);
});

test("calculates the 33 percent credit boundary from the adjusted squad value", () => {
  const capacity = calculateBidCapacity(30_000_000, -3_000_000);

  assert.deepEqual(capacity, {
    effectiveBalance: -3_000_000,
    adjustedSquadValue: 27_000_000,
    minimumBalance: -8_910_000,
    maximumBid: 5_910_000,
  });
});

test("credits an existing bid back before calculating an updated bid capacity", () => {
  const capacity = calculateBidCapacity(30_000_000, 2_000_000, 1_500_000);

  assert.equal(capacity.effectiveBalance, 3_500_000);
  assert.equal(capacity.minimumBalance, -9_900_000);
  assert.equal(capacity.maximumBid, 13_400_000);
});

test("rejects bids below market value", () => {
  const result = evaluateBidEligibility({
    bid: 4_999_999,
    marketValue: 5_000_000,
    squadValue: 30_000_000,
    balanceAfterActiveBids: 10_000_000,
    squadSize: 17,
    squadLimit: 18,
  });

  assert.equal(result.allowed, false);
  assert.deepEqual(result.reasons, ["BELOW_MARKET_VALUE"]);
});

test("rejects bids when the 18-player squad is full", () => {
  const result = evaluateBidEligibility({
    bid: 5_000_000,
    marketValue: 5_000_000,
    squadValue: 30_000_000,
    balanceAfterActiveBids: 10_000_000,
    squadSize: 18,
    squadLimit: 18,
  });

  assert.equal(result.allowed, false);
  assert.ok(result.reasons.includes("SQUAD_FULL"));
});

test("rejects bids when the budget boundary cannot be determined", () => {
  const result = evaluateBidEligibility({
    bid: 5_000_000,
    marketValue: 5_000_000,
    squadValue: 30_000_000,
    balanceAfterActiveBids: null,
    squadSize: 17,
    squadLimit: 18,
  });

  assert.equal(result.allowed, false);
  assert.deepEqual(result.reasons, ["BUDGET_UNAVAILABLE"]);
});

test("allows a valid bid exactly at the computed maximum", () => {
  const capacity = calculateBidCapacity(30_000_000, 2_000_000);
  assert.notEqual(capacity.maximumBid, null);

  const result = evaluateBidEligibility({
    bid: capacity.maximumBid,
    marketValue: 5_000_000,
    squadValue: 30_000_000,
    balanceAfterActiveBids: 2_000_000,
    squadSize: 17,
    squadLimit: 18,
  });

  assert.equal(result.allowed, true);
  assert.deepEqual(result.reasons, []);
});
