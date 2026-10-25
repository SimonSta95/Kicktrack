import type { MarketValuePoint, PlayerPerformanceEntry } from "@/features/player-detail/types";
import type { MvPrediction } from "@/features/analytics/mv-prediction";
import { dateOnlyToUtcMs, isDateOlderThan } from "@/lib/date-only";
import { selectMarketSparklinePoints } from "./market-sparkline";
import "./market-mini-charts.css";

export function MarketSparkline({ points, prediction, currentValue }: { points: MarketValuePoint[]; prediction?: MvPrediction; currentValue: number | null }) {
  const recent = selectMarketSparklinePoints(points);
  if (recent.length < 2) return <span className="market-empty" title="Keine ausreichenden MW-Verlaufsdaten vorhanden">—</span>;
  const stale = isDateOlderThan(recent[recent.length - 1].date, 2);
  const delta = recent[recent.length - 1].value - recent[0].value;
  const color = delta > 0 ? "#63cf83" : delta < 0 ? "#ed7770" : "#e6b45d";
  const expected = !stale && prediction?.expectedValue != null && Number.isFinite(prediction.expectedValue) && currentValue != null ? prediction.expectedValue : null;
  const values = recent.map(p => p.value).concat(expected == null ? [] : [expected]);
  const min = Math.min(...values), span = Math.max(Math.max(...values) - min, 1);
  const x = (date: string) => 4 + ((dateOnlyToUtcMs(date) - dateOnlyToUtcMs(recent[0].date)) / Math.max(dateOnlyToUtcMs(recent[recent.length - 1].date) - dateOnlyToUtcMs(recent[0].date), 1)) * (expected == null ? 88 : 73);
  const y = (value: number) => 26 - ((value - min) / span) * 22;
  const path = recent.map((point, index) => `${index ? "L" : "M"}${x(point.date).toFixed(1)},${y(point.value).toFixed(1)}`).join(" ");
  return <span className={`market-mini-spark ${stale ? "is-stale" : ""}`} title={`${recent[0].date} bis ${recent[recent.length-1].date}${stale ? " · Daten veraltet" : ""}${expected == null ? "" : ` · Prognose: ${Math.round(expected).toLocaleString("de-DE")} €`}`}>
    <svg viewBox="0 0 100 30" width="100" height="30" role="img" aria-label="Marktwertentwicklung">
      <path d={path} stroke={color} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" fill="none" />
      {expected != null && <path d={`M${x(recent[recent.length-1].date)},${y(recent[recent.length-1].value)} L97,${y(expected)}`} stroke={color} strokeWidth="2" strokeDasharray="3 3" fill="none" />}
    </svg>
    {stale && <span className="market-mini-stale">!</span>}
  </span>;
}

export function RecentFormBars({ entries = [], loading = false, unavailable = false }: { entries?: PlayerPerformanceEntry[]; loading?: boolean; unavailable?: boolean }) {
  const recent = entries.filter(e => e.dayNumber > 0 && e.points != null).sort((a,b) => a.dayNumber - b.dayNumber).slice(-6);
  if (!recent.length) return <span className="market-empty" title={loading ? "Lade Punkteverlauf" : unavailable ? "Punkteverlauf konnte nicht geladen werden" : "Keine Punkte verfügbar"}>—</span>;
  const label = recent.map(e => `ST${e.dayNumber}: ${e.points} Punkte`).join(" · ");
  return <span className="market-form-bars" title={label} role="img" aria-label={label}>
    {recent.map(e => <span key={e.dayNumber} className="market-form-bar" style={{ height: `${Math.max(3, Math.min(27, Math.round(Math.max(0,e.points ?? 0) / 180 * 27)))}px`, backgroundColor: (e.points ?? 0) >= 100 ? "#63cf83" : (e.points ?? 0) >= 40 ? "#e6b45d" : "#ed7770" }} />)}
  </span>;
}
