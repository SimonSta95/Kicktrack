import test from "node:test";
import assert from "node:assert/strict";
import { FORMATIONS, optimizeLineup, projectPlayer, simulateTransfer } from "../src/features/planning/planning-model.ts";

function player(id, position, points, marketValue = 5_000_000) {
  return {
    id, name: id, firstName: null, teamId: "home", position, marketValue,
    averagePoints: points, status: 0, statusList: [], statusText: null, source: "squad",
  };
}

function projected(id, position, points, marketValue) {
  return projectPlayer(player(id, position, points, marketValue), undefined, [{
    matchId: "m", homeTeamId: "home", awayTeamId: "away", homeTeamName: "H", awayTeamName: "A", kickoff: null,
  }]);
}

function fullSquad() {
  return [
    projected("g1", "GOALKEEPER", 70, 4_000_000), projected("g2", "GOALKEEPER", 40, 2_000_000),
    ...Array.from({ length: 6 }, (_, i) => projected(`d${i}`, "DEFENDER", 80 - i * 5, 6_000_000 - i * 300_000)),
    ...Array.from({ length: 6 }, (_, i) => projected(`m${i}`, "MIDFIELDER", 90 - i * 5, 7_000_000 - i * 300_000)),
    ...Array.from({ length: 4 }, (_, i) => projected(`f${i}`, "FORWARD", 85 - i * 5, 8_000_000 - i * 300_000)),
  ];
}

test("optimizer respects the selected formation", () => {
  const lineup = optimizeLineup(fullSquad(), FORMATIONS.find((item) => item.id === "4-4-2"));
  assert.ok(lineup);
  assert.equal(lineup.length, 11);
  assert.equal(lineup.filter((entry) => entry.position === "DEFENDER").length, 4);
  assert.equal(lineup.filter((entry) => entry.position === "MIDFIELDER").length, 4);
  assert.equal(lineup.filter((entry) => entry.position === "FORWARD").length, 2);
});

test("projection blends recent form and discounts unavailable players", () => {
  const base = player("p", "MIDFIELDER", 100);
  const fit = projectPlayer(base, [{ dayNumber: 1, points: 140, minutes: 90, status: 0, homeTeamId: null, awayTeamId: null, homeGoals: null, awayGoals: null, playerTeamId: null }], []);
  const unavailable = projectPlayer({ ...base, statusText: "Verletzt" }, undefined, []);
  assert.ok(fit.expectedPoints > 100);
  assert.ok(unavailable.expectedPoints < 20);
});

test("transfer simulation finds a valid sale for a full squad", () => {
  const squad = fullSquad();
  const purchase = projected("new", "MIDFIELDER", 130, 12_000_000);
  const result = simulateTransfer(squad, purchase, 12_000_000, 7_000_000, FORMATIONS[3]);
  assert.ok(result);
  assert.equal(result.sales.length, 1);
  assert.ok(result.remainingBudget >= 0);
  assert.ok(result.lineup.some((entry) => entry.id === "new"));
});
