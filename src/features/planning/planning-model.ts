import type { MarketEntry } from "@/features/market/types";
import type { PlayerPerformanceEntry } from "@/features/player-detail/types";
import type { NextFixture, PlayerPosition, SquadPlayer } from "@/features/squad/types";

export type Formation = {
  id: string;
  label: string;
  GOALKEEPER: 1;
  DEFENDER: number;
  MIDFIELDER: number;
  FORWARD: number;
  UNKNOWN: 0;
};

export const FORMATIONS: Formation[] = [
  { id: "3-4-3", label: "3-4-3", GOALKEEPER: 1, DEFENDER: 3, MIDFIELDER: 4, FORWARD: 3, UNKNOWN: 0 },
  { id: "3-5-2", label: "3-5-2", GOALKEEPER: 1, DEFENDER: 3, MIDFIELDER: 5, FORWARD: 2, UNKNOWN: 0 },
  { id: "4-3-3", label: "4-3-3", GOALKEEPER: 1, DEFENDER: 4, MIDFIELDER: 3, FORWARD: 3, UNKNOWN: 0 },
  { id: "4-4-2", label: "4-4-2", GOALKEEPER: 1, DEFENDER: 4, MIDFIELDER: 4, FORWARD: 2, UNKNOWN: 0 },
  { id: "4-5-1", label: "4-5-1", GOALKEEPER: 1, DEFENDER: 4, MIDFIELDER: 5, FORWARD: 1, UNKNOWN: 0 },
  { id: "5-3-2", label: "5-3-2", GOALKEEPER: 1, DEFENDER: 5, MIDFIELDER: 3, FORWARD: 2, UNKNOWN: 0 },
  { id: "5-4-1", label: "5-4-1", GOALKEEPER: 1, DEFENDER: 5, MIDFIELDER: 4, FORWARD: 1, UNKNOWN: 0 },
];

export type PlanningPlayer = {
  id: string;
  name: string;
  firstName: string | null;
  teamId: string | null;
  position: PlayerPosition;
  marketValue: number | null;
  averagePoints: number | null;
  status: number | null;
  statusList: number[];
  statusText: string | null;
  source: "squad" | "market";
};

export type ExpectedPlayer = PlanningPlayer & {
  expectedPoints: number;
  availabilityFactor: number;
  fixtureFactor: number;
  recentAverage: number | null;
};

export type TransferSimulation = {
  purchase: ExpectedPlayer;
  price: number;
  sales: ExpectedPlayer[];
  saleProceeds: number;
  remainingBudget: number;
  baselinePoints: number;
  projectedPoints: number;
  pointsDelta: number;
  lineup: ExpectedPlayer[];
};

const LINEUP_POSITIONS: PlayerPosition[] = ["GOALKEEPER", "DEFENDER", "MIDFIELDER", "FORWARD"];

export function squadPlanningPlayer(player: SquadPlayer): PlanningPlayer {
  return { ...player, source: "squad" };
}

export function marketPlanningPlayer(player: MarketEntry): PlanningPlayer {
  return {
    id: player.playerId,
    name: player.name,
    firstName: player.firstName,
    teamId: player.teamId,
    position: player.position,
    marketValue: player.marketValue,
    averagePoints: player.averagePoints,
    status: player.status,
    statusList: player.statusList,
    statusText: player.statusText,
    source: "market",
  };
}

export function projectPlayer(
  player: PlanningPlayer,
  form: PlayerPerformanceEntry[] | undefined,
  fixtures: NextFixture[],
): ExpectedPlayer {
  const active = (form ?? [])
    .filter((entry) => entry.points != null && (entry.minutes ?? 0) > 0)
    .slice(-5);
  const recentAverage = active.length
    ? active.reduce((sum, entry) => sum + (entry.points ?? 0), 0) / active.length
    : null;
  const seasonAverage = Math.max(player.averagePoints ?? recentAverage ?? 0, 0);
  const performance = recentAverage == null ? seasonAverage : seasonAverage * 0.65 + recentAverage * 0.35;
  const availabilityFactor = availability(player);
  const fixtureFactor = fixtureWeight(player.teamId, fixtures);
  return {
    ...player,
    expectedPoints: round(performance * availabilityFactor * fixtureFactor),
    availabilityFactor,
    fixtureFactor,
    recentAverage: recentAverage == null ? null : round(recentAverage),
  };
}

export function optimizeLineup(players: ExpectedPlayer[], formation: Formation): ExpectedPlayer[] | null {
  const lineup: ExpectedPlayer[] = [];
  for (const position of LINEUP_POSITIONS) {
    const required = formation[position];
    const candidates = players
      .filter((player) => player.position === position)
      .sort((a, b) => b.expectedPoints - a.expectedPoints || a.name.localeCompare(b.name, "de"));
    if (candidates.length < required) return null;
    lineup.push(...candidates.slice(0, required));
  }
  return lineup;
}

export function simulateTransfer(
  squad: ExpectedPlayer[],
  purchase: ExpectedPlayer,
  price: number,
  budget: number,
  formation: Formation,
  squadLimit = 18,
): TransferSimulation | null {
  if (!Number.isFinite(price) || price <= 0 || purchase.position === "UNKNOWN") return null;
  const baseline = optimizeLineup(squad, formation);
  if (!baseline) return null;
  const minimumSales = Math.max(0, squad.length + 1 - squadLimit);
  let best: TransferSimulation | null = null;

  for (let count = minimumSales; count <= Math.min(3, squad.length); count += 1) {
    for (const sales of combinations(squad, count)) {
      const saleProceeds = sales.reduce((sum, player) => sum + Math.max(player.marketValue ?? 0, 0), 0);
      const remainingBudget = budget + saleProceeds - price;
      if (remainingBudget < 0) continue;
      const sold = new Set(sales.map((player) => player.id));
      const remaining = squad.filter((player) => !sold.has(player.id)).concat(purchase);
      const lineup = optimizeLineup(remaining, formation);
      if (!lineup) continue;
      const baselinePoints = lineupPoints(baseline);
      const projectedPoints = lineupPoints(lineup);
      const candidate: TransferSimulation = {
        purchase,
        price,
        sales,
        saleProceeds,
        remainingBudget,
        baselinePoints,
        projectedPoints,
        pointsDelta: round(projectedPoints - baselinePoints),
        lineup,
      };
      if (!best || candidate.projectedPoints > best.projectedPoints || (
        candidate.projectedPoints === best.projectedPoints && candidate.sales.length < best.sales.length
      )) best = candidate;
    }
  }
  return best;
}

export function lineupPoints(players: ExpectedPlayer[]) {
  return round(players.reduce((sum, player) => sum + player.expectedPoints, 0));
}

function availability(player: PlanningPlayer) {
  const text = player.statusText?.toLocaleLowerCase("de-DE") ?? "";
  if (/gesperrt|verletzt|nicht im kader|fällt aus/.test(text)) return 0.15;
  if ((player.status ?? 0) > 0 || player.statusList.length > 0) return 0.65;
  return 1;
}

function fixtureWeight(teamId: string | null, fixtures: NextFixture[]) {
  if (!teamId) return 0.95;
  const fixture = fixtures.find((entry) => entry.homeTeamId === teamId || entry.awayTeamId === teamId);
  if (!fixture) return 0.95;
  return fixture.homeTeamId === teamId ? 1.04 : 0.98;
}

function combinations<T>(items: T[], count: number): T[][] {
  if (count === 0) return [[]];
  const result: T[][] = [];
  function visit(start: number, selected: T[]) {
    if (selected.length === count) {
      result.push([...selected]);
      return;
    }
    for (let index = start; index <= items.length - (count - selected.length); index += 1) {
      selected.push(items[index]);
      visit(index + 1, selected);
      selected.pop();
    }
  }
  visit(0, []);
  return result;
}

function round(value: number) {
  return Math.round(value * 10) / 10;
}
