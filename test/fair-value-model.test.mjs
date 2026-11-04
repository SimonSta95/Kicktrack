import test from "node:test";
import assert from "node:assert/strict";
import { buildFairValueModel } from "../src/features/fair-value/fair-value-model.ts";

function player(position, points, index, games = 8) {
  const x = points / 100;
  const offset = 13.6 + position * 0.16;
  const value = Math.round(Math.exp(offset + 2.2 * x - 0.35 * x ** 2 + 0.04 * x ** 3));
  return {
    playerId: `${position}-${index}`,
    name: `Spieler ${position}-${index}`,
    firstName: null,
    position,
    marketValue: value,
    averagePoints: points,
    totalPoints: points * games,
    status: 0,
    ownerId: "manager",
    ownerName: "Manager",
    ownerIsSelf: false,
    onMarket: false,
  };
}

test("fits a monotonic position-aware fair-value curve", () => {
  const players = [];
  for (let position = 1; position <= 4; position += 1) {
    for (let index = 0; index < 10; index += 1) {
      players.push(player(position, 45 + index * 12, index));
    }
  }

  const model = buildFairValueModel(players);
  assert.ok(model);
  assert.equal(model.players.length, 40);
  assert.equal(model.minGames, 6);
  assert.equal(Object.keys(model.curves).length, 4);
  for (const curve of Object.values(model.curves)) {
    for (let index = 1; index < curve.length; index += 1) {
      assert.ok(curve[index].value >= curve[index - 1].value);
    }
  }
});

test("excludes rotation players from the fitted cohort", () => {
  const regulars = Array.from({ length: 32 }, (_, index) => player((index % 4) + 1, 55 + index * 3, index));
  const rotation = player(3, 120, 99, 2);
  const model = buildFairValueModel([...regulars, rotation]);

  assert.ok(model);
  assert.equal(model.players.some((entry) => entry.playerId === rotation.playerId), false);
});

test("does not publish a curve for an undersized cohort", () => {
  assert.equal(buildFairValueModel(Array.from({ length: 20 }, (_, index) => player((index % 4) + 1, 60 + index, index))), null);
});
