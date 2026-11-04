import type {
  FairValueCurvePoint,
  FairValueDatasetPlayer,
  FairValueModel,
  FairValueRating,
} from "./types.ts";

const REGULAR_SHARE = 2 / 3;
const MIN_GAMES = 3;
const MIN_FAIR_PLAYERS = 30;
export const FAIR_VALUE_BAND = 0.25;

type Curve = {
  offsets: Map<number, number>;
  low: number;
  shape: number[];
};

export function buildFairValueModel(
  source: FairValueDatasetPlayer[],
  band = FAIR_VALUE_BAND,
): FairValueModel | null {
  const valid = source.filter((player) =>
    Number.isInteger(player.position)
    && player.position >= 1
    && player.position <= 4
    && Number.isFinite(player.marketValue)
    && player.marketValue >= 500_000
    && Number.isFinite(player.averagePoints)
    && player.averagePoints > 0
    && Number.isFinite(player.totalPoints)
    && player.totalPoints > 0,
  );
  const games = new Map(valid.map((player) => [player.playerId, estimateGames(player)]));
  const busiest = Math.max(0, ...games.values());
  const minGames = Math.max(MIN_GAMES, Math.ceil(busiest * REGULAR_SHARE));
  const regulars = valid.filter((player) => (games.get(player.playerId) ?? 0) >= minGames);
  if (regulars.length < MIN_FAIR_PLAYERS) return null;

  const curve = fitCurve(regulars);
  if (!curve) return null;
  const players = regulars.flatMap((player) => {
    const fairValue = curveValue(curve, player.position, player.averagePoints);
    if (fairValue == null || fairValue <= 0) return [];
    const gap = player.marketValue / fairValue - 1;
    return [{
      ...player,
      games: games.get(player.playerId) ?? 0,
      fairValue,
      gap,
      rating: rateGap(gap, band),
    }];
  });
  if (!players.length) return null;

  const curves: Record<number, FairValueCurvePoint[]> = {};
  for (const position of curve.offsets.keys()) {
    const top = curve.low + curve.shape.length - 1;
    const points = [];
    for (let value = curve.low; value < top; value += 5) points.push(value);
    if (points[points.length - 1] !== top) points.push(top);
    curves[position] = points.map((averagePoints) => ({
      points: averagePoints,
      value: curveValue(curve, position, averagePoints) ?? 0,
    }));
  }

  return {
    players: players.sort((a, b) => a.gap - b.gap),
    curves,
    minGames,
    band,
    typicalGap: median(players.map((player) => Math.abs(player.gap))),
    sourceCount: valid.length,
  };
}

function estimateGames(player: FairValueDatasetPlayer) {
  return player.averagePoints > 0 ? Math.max(0, Math.round(player.totalPoints / player.averagePoints)) : 0;
}

function fitCurve(players: FairValueDatasetPlayer[]): Curve | null {
  const positions = [...new Set(players.map((player) => player.position))].sort((a, b) => a - b);
  const rows = players.map((player) => [
    ...positions.map((position) => Number(player.position === position)),
    ...powers(player.averagePoints),
  ]);
  const solution = leastSquares(rows, players.map((player) => Math.log(player.marketValue)));
  if (!solution) return null;
  const slopes = solution.slice(positions.length);
  const low = Math.floor(Math.min(...players.map((player) => player.averagePoints)));
  const high = Math.ceil(Math.max(...players.map((player) => player.averagePoints)));
  const shape: number[] = [];
  for (let points = low; points <= high; points += 1) {
    const raw = slopes.reduce((sum, slope, index) => sum + slope * powers(points)[index], 0);
    shape.push(shape.length ? Math.max(raw, shape[shape.length - 1]) : raw);
  }
  if (!shape.length || shape.some((value) => !Number.isFinite(value))) return null;
  return { offsets: new Map(positions.map((position, index) => [position, solution[index]])), low, shape };
}

function curveValue(curve: Curve, position: number, averagePoints: number) {
  const offset = curve.offsets.get(position);
  if (offset == null) return null;
  const index = Math.min(Math.max(Math.round(averagePoints) - curve.low, 0), curve.shape.length - 1);
  const value = Math.exp(offset + curve.shape[index]);
  return Number.isFinite(value) ? Math.round(value) : null;
}

function leastSquares(rows: number[][], targets: number[]) {
  if (!rows.length || rows.length !== targets.length || !rows[0]?.length) return null;
  const size = rows[0].length;
  const matrix = Array.from({ length: size }, (_, rowIndex) => [
    ...Array.from({ length: size }, (_, columnIndex) => rows.reduce(
      (sum, row) => sum + row[rowIndex] * row[columnIndex],
      0,
    )),
    rows.reduce((sum, row, index) => sum + row[rowIndex] * targets[index], 0),
  ]);

  for (let column = 0; column < size; column += 1) {
    let pivot = column;
    for (let row = column + 1; row < size; row += 1) {
      if (Math.abs(matrix[row][column]) > Math.abs(matrix[pivot][column])) pivot = row;
    }
    if (Math.abs(matrix[pivot][column]) < 1e-9) return null;
    [matrix[column], matrix[pivot]] = [matrix[pivot], matrix[column]];
    for (let row = 0; row < size; row += 1) {
      if (row === column) continue;
      const factor = matrix[row][column] / matrix[column][column];
      for (let part = column; part <= size; part += 1) {
        matrix[row][part] -= factor * matrix[column][part];
      }
    }
  }
  const result = matrix.map((row, index) => row[size] / row[index]);
  return result.every(Number.isFinite) ? result : null;
}

function powers(points: number) {
  const normalized = points / 100;
  return [normalized, normalized ** 2, normalized ** 3];
}

function rateGap(gap: number, band: number): FairValueRating {
  if (gap <= -band) return "cheap";
  if (gap >= band) return "expensive";
  return "fair";
}

function median(values: number[]) {
  const sorted = [...values].sort((a, b) => a - b);
  if (!sorted.length) return 0;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}
