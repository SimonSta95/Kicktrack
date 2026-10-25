const BERLIN_TIME_ZONE = "Europe/Berlin";
const DAY_MS = 86_400_000;

export function dateOnlyToUtcMs(value: string): number {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return Number.NaN;
  return Date.parse(`${value}T00:00:00Z`);
}

export function berlinDateOnly(now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: BERLIN_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

export function recentDateCutoffMs(days: number, now = new Date()): number {
  return dateOnlyToUtcMs(berlinDateOnly(now)) - Math.max(days - 1, 0) * DAY_MS;
}

export function isDateOlderThan(value: string, days: number, now = new Date()): boolean {
  const timestamp = dateOnlyToUtcMs(value);
  if (!Number.isFinite(timestamp)) return true;
  return dateOnlyToUtcMs(berlinDateOnly(now)) - timestamp > Math.max(days, 0) * DAY_MS;
}
