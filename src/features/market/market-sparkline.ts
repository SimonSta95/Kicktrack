import { dateOnlyToUtcMs, recentDateCutoffMs } from "../../lib/date-only.ts";

export type SparklinePoint = {
  date: string;
  value: number;
};

/**
 * Use the same useful horizon as the player detail's 90-day view. Kickbase
 * history can contain calendar gaps, so a strict 14-day window would hide a
 * valid curve even though older observations are available.
 */
export function selectMarketSparklinePoints(
  points: SparklinePoint[],
  now = new Date(),
): SparklinePoint[] {
  const byDate = new Map<string, SparklinePoint>();
  for (const point of points) {
    if (
      Number.isFinite(point.value)
      && point.value > 0
      && Number.isFinite(dateOnlyToUtcMs(point.date))
    ) {
      byDate.set(point.date, point);
    }
  }

  const valid = [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  const cutoff = recentDateCutoffMs(90, now);
  const recent = valid.filter((point) => dateOnlyToUtcMs(point.date) >= cutoff);

  if (recent.length >= 2) return recent;
  return valid.slice(-30);
}
