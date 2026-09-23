import type { PlayerPosition } from "../squad/types";

export type FairValueReferencePlayer = {
  playerId: string;
  position: number | null;
  marketValue: number;
  averagePoints: number;
  totalPoints: number | null;
};

export type FairValueReferenceResponse = {
  players: FairValueReferencePlayer[];
  sampleSize: number;
};

export type FairValueEstimate = {
  fairValue: number | null;
  difference: number | null;
  differencePct: number | null;
  confidence: "LOW" | "MEDIUM" | "HIGH" | "NONE";
  confidenceLabel: string;
  referenceCount: number;
  estimatedGames: number | null;
};

export type FixtureOutlookItem = {
  dayNumber: number;
  matchId: string;
  teamId: string;
  opponentId: string;
  opponentName: string;
  isHome: boolean;
  kickoff: string | null;
  opponentAttackIndex: number;
  opponentDefenseIndex: number;
};

export type FixtureOutlookResponse = {
  fixturesByTeam: Record<string, FixtureOutlookItem[]>;
  completedMatches: number;
  dataQuality: "LOW" | "MEDIUM" | "HIGH";
};

export type FixtureRating = FixtureOutlookItem & {
  favorability: number;
  label: "Sehr gut" | "Gut" | "Neutral" | "Schwer" | "Sehr schwer";
};

const POSITION_CODE: Record<PlayerPosition, number | null> = {
  GOALKEEPER: 1,
  DEFENDER: 2,
  MIDFIELDER: 3,
  FORWARD: 4,
  UNKNOWN: null,
};

export function estimateFairValue(
  averagePoints: number | null,
  marketValue: number | null,
  position: PlayerPosition | number | null,
  targetPlayerId: string | null,
  reference: FairValueReferencePlayer[],
  totalPoints?: number | null,
): FairValueEstimate {
  if (!isFinitePositive(averagePoints) || !isFinitePositive(marketValue) || reference.length < 20) return emptyFairValue();

  const pos = typeof position === "number" ? position : position ? POSITION_CODE[position] : null;
  const valid = reference.filter((row) => row.playerId !== targetPlayerId && isFinitePositive(row.averagePoints) && isFinitePositive(row.marketValue));
  const samePosition = pos == null ? [] : valid.filter((row) => row.position === pos);
  const pool = samePosition.length >= 10 ? samePosition : valid;
  if (pool.length < 12) return emptyFairValue();

  const targetAverage = averagePoints as number;
  const nearest = [...pool]
    .sort((a, b) => Math.abs(a.averagePoints - targetAverage) - Math.abs(b.averagePoints - targetAverage))
    .slice(0, Math.min(14, pool.length));

  const bandwidth = Math.max(18, median(nearest.map((row) => Math.abs(row.averagePoints - targetAverage))) * 1.7);
  let weightSum = 0;
  let weightedLogValue = 0;
  for (const row of nearest) {
    const distance = Math.abs(row.averagePoints - targetAverage);
    const weight = Math.exp(-0.5 * (distance / bandwidth) ** 2);
    weightedLogValue += Math.log(row.marketValue) * weight;
    weightSum += weight;
  }
  if (weightSum <= 0) return emptyFairValue();

  const raw = Math.exp(weightedLogValue / weightSum);
  const fairValue = Math.round(raw / 10_000) * 10_000;
  const estimatedGames = estimateGames(totalPoints ?? null, averagePoints);
  const confidence = estimatedGames == null ? "LOW" : estimatedGames >= 10 && nearest.length >= 12 ? "HIGH" : estimatedGames >= 5 ? "MEDIUM" : "LOW";
  const difference = fairValue - (marketValue as number);
  return {
    fairValue,
    difference,
    differencePct: difference / (marketValue as number) * 100,
    confidence,
    confidenceLabel: confidence === "HIGH" ? "gute Datengrundlage" : confidence === "MEDIUM" ? "mittlere Datengrundlage" : "noch kleine Stichprobe",
    referenceCount: nearest.length,
    estimatedGames,
  };
}

export function rateFixture(item: FixtureOutlookItem, position: PlayerPosition | number | null): FixtureRating {
  const pos = typeof position === "number" ? position : position ? POSITION_CODE[position] : null;
  // Defense index >1 = opponent concedes more than average -> good for attackers.
  // Attack index >1 = opponent scores more than average -> bad for defenders/GKs.
  let raw: number;
  if (pos === 1 || pos === 2) raw = 1 / Math.max(0.55, item.opponentAttackIndex);
  else if (pos === 4) raw = item.opponentDefenseIndex;
  else raw = (item.opponentDefenseIndex + 1 / Math.max(0.55, item.opponentAttackIndex)) / 2;

  // Small home edge, deliberately weaker than the team-strength signal.
  raw *= item.isHome ? 1.06 : 0.96;
  const favorability = clamp(5.5 + (raw - 1) * 8, 1, 10);
  const rounded = Math.round(favorability * 10) / 10;
  const label = rounded >= 7.5 ? "Sehr gut" : rounded >= 6.2 ? "Gut" : rounded >= 4.5 ? "Neutral" : rounded >= 3.2 ? "Schwer" : "Sehr schwer";
  return { ...item, favorability: rounded, label };
}

export function averageFixtureRating(items: FixtureOutlookItem[], position: PlayerPosition | number | null) {
  if (!items.length) return null;
  const values = items.map((item) => rateFixture(item, position).favorability);
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function estimateGames(totalPoints: number | null, averagePoints: number | null) {
  if (!isFinitePositive(totalPoints) || !isFinitePositive(averagePoints)) return null;
  return Math.max(1, Math.round((totalPoints as number) / (averagePoints as number)));
}
function emptyFairValue(): FairValueEstimate {
  return { fairValue: null, difference: null, differencePct: null, confidence: "NONE", confidenceLabel: "zu wenig Daten", referenceCount: 0, estimatedGames: null };
}
function isFinitePositive(value: number | null | undefined): value is number { return typeof value === "number" && Number.isFinite(value) && value > 0; }
function median(values: number[]) { const sorted=[...values].sort((a,b)=>a-b); if(!sorted.length) return 0; const mid=Math.floor(sorted.length/2); return sorted.length%2 ? sorted[mid]! : (sorted[mid-1]!+sorted[mid]!)/2; }
function clamp(value:number,min:number,max:number){ return Math.min(max,Math.max(min,value)); }
