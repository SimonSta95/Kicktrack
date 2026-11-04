import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BadgeEuro, CircleDot, Store, UsersRound } from "lucide-react";
import { usePlayerDetail } from "@/features/player-detail/PlayerDetailProvider";
import { getFairValueDataset } from "./api";
import { buildFairValueModel } from "./fair-value-model";
import type { FairValueCurvePoint, FairValueRating, RatedFairValuePlayer } from "./types";
import "./fair-value.css";

const POSITIONS = [
  { value: 0, label: "Alle" },
  { value: 1, label: "TW" },
  { value: 2, label: "ABW" },
  { value: 3, label: "MF" },
  { value: 4, label: "ST" },
] as const;

type Scope = "all" | "market" | "mine";
type RatingFilter = "all" | FairValueRating;

export function FairValuePage({ leagueId }: { leagueId: string }) {
  const { openPlayerDetail } = usePlayerDetail();
  const [position, setPosition] = useState(3);
  const [scope, setScope] = useState<Scope>("all");
  const [rating, setRating] = useState<RatingFilter>("all");
  const [fitOnly, setFitOnly] = useState(true);
  const query = useQuery({
    queryKey: ["fair-value", "dataset", leagueId],
    queryFn: () => getFairValueDataset(leagueId),
    staleTime: 10 * 60 * 1000,
  });
  const model = useMemo(() => buildFairValueModel(query.data?.players ?? []), [query.data?.players]);
  const filtered = useMemo(() => {
    if (!model) return [];
    return model.players.filter((player) => {
      if (position && player.position !== position) return false;
      if (fitOnly && player.status !== 0) return false;
      if (scope === "market" && !player.onMarket) return false;
      if (scope === "mine" && !player.ownerIsSelf) return false;
      if (rating !== "all" && player.rating !== rating) return false;
      return true;
    });
  }, [fitOnly, model, position, rating, scope]);

  if (query.isLoading) return <FairValueState>Fair-Value-Daten werden aus den Liga-Kadern geladen …</FairValueState>;
  if (query.isError) return <FairValueState error retry={() => query.refetch()}>Die Fair-Value-Daten konnten nicht geladen werden.</FairValueState>;

  return (
    <section className="fair-value-page">
      <header className="fair-value-header">
        <div><h1>FAIR VALUE</h1><p>Was Stammspieler mit vergleichbaren Punkten auf ihrer Position in deiner Liga kosten.</p></div>
        <div className="fair-value-source"><UsersRound size={15}/><span>{query.data?.loadedManagerCount ?? 0}/{query.data?.managerCount ?? 0} Managerkader</span></div>
      </header>

      {model ? (
        <>
          <div className="fair-value-summary">
            <Summary label="Bewertet" value={String(model.players.length)} hint={`ab ${model.minGames} geschätzten Einsätzen`} icon={<CircleDot size={15}/>} />
            <Summary label="Günstig" value={String(model.players.filter((player) => player.rating === "cheap").length)} hint="mindestens 25 % unter Fair Value" tone="cheap" />
            <Summary label="Teuer" value={String(model.players.filter((player) => player.rating === "expensive").length)} hint="mindestens 25 % über Fair Value" tone="expensive" />
            <Summary label="Typische Abweichung" value={`± ${percent(model.typicalGap)}`} hint="kleinere Abstände sind wenig belastbar" icon={<BadgeEuro size={15}/>} />
          </div>

          <div className="fair-value-filters">
            <FilterGroup label="Position">{POSITIONS.map((item) => <FilterButton key={item.value} active={position === item.value} onClick={() => setPosition(item.value)}>{item.label}</FilterButton>)}</FilterGroup>
            <FilterGroup label="Auswahl">
              <FilterButton active={scope === "all"} onClick={() => setScope("all")}>Alle</FilterButton>
              <FilterButton active={scope === "market"} onClick={() => setScope("market")}>Auf dem Markt</FilterButton>
              <FilterButton active={scope === "mine"} onClick={() => setScope("mine")}>Mein Kader</FilterButton>
            </FilterGroup>
            <button type="button" className={`fair-value-fit${fitOnly ? " is-active" : ""}`} aria-pressed={fitOnly} onClick={() => setFitOnly((value) => !value)}>Nur fitte Spieler</button>
          </div>

          {(query.data?.unavailableManagerCount ?? 0) > 0 ? <div className="fair-value-warning"><AlertTriangle size={14}/> {query.data!.unavailableManagerCount} Managerkader konnten nicht geladen werden; Kurve und Stichprobe sind entsprechend unvollständig.</div> : null}

          <section className="fair-value-chart-card">
            <header><div><span>Marktwert und Punkte</span><strong>{filtered.length} Spieler in der Auswahl</strong></div><p>{position ? "Die Linie zeigt den Fair Value der Position; die Marktwert-Achse ist logarithmisch." : "Wähle eine Position, um ihre Fair-Value-Kurve und das ±25-%-Band zu sehen."}</p></header>
            {filtered.length ? (
              <FairValueChart
                players={filtered}
                curve={position ? model.curves[position] : undefined}
                band={model.band}
                onPick={(playerId) => openPlayerDetail({ playerId, leagueId, context: { source: "other", label: "Fair Value" } })}
              />
            ) : <div className="fair-value-empty">Keine Spieler passen zu dieser Auswahl.</div>}
            <div className="fair-value-legend"><span><i className="is-cheap"/> Günstig</span><span><i className="is-fair"/> Fair</span><span><i className="is-expensive"/> Teuer</span>{position ? <><span><b/> Fair Value</span><span><b className="is-dashed"/> ± 25 %</span></> : null}</div>
          </section>

          <div className="fair-value-rating-filter">
            {(["all", "cheap", "fair", "expensive"] as const).map((value) => <FilterButton key={value} active={rating === value} onClick={() => setRating(value)}>{ratingLabel(value)}</FilterButton>)}
            <span>Modellbasis: {model.sourceCount} Spieler aus Managerkadern und Transfermarkt.</span>
          </div>
        </>
      ) : (
        <div className="fair-value-insufficient"><AlertTriangle size={20}/><strong>Noch keine belastbare Kurve</strong><p>Für das Modell werden mindestens 30 Spieler mit Marktwert, Ø Punkten und ausreichend belegten Einsätzen benötigt.</p></div>
      )}
    </section>
  );
}

function FairValueChart({ players, curve, band, onPick }: { players: RatedFairValuePlayer[]; curve?: FairValueCurvePoint[]; band: number; onPick: (playerId: string) => void }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const width = 1120, height = 430, left = 76, right = 22, top = 20, bottom = 48;
  const allValues = [...players.map((player) => player.marketValue), ...(curve ?? []).flatMap((point) => [point.value * (1 - band), point.value * (1 + band)])].filter((value) => value > 0);
  const minValue = Math.max(250_000, Math.min(...allValues));
  const maxValue = Math.max(minValue * 2, Math.max(...allValues));
  const maxPoints = Math.max(50, ...players.map((player) => player.averagePoints), ...(curve ?? []).map((point) => point.points));
  const xMax = Math.ceil(maxPoints / 50) * 50;
  const x = (value: number) => left + value / xMax * (width - left - right);
  const logMin = Math.log(minValue), logMax = Math.log(maxValue);
  const y = (value: number) => top + (1 - (Math.log(Math.max(value, minValue)) - logMin) / Math.max(logMax - logMin, 0.0001)) * (height - top - bottom);
  const xTicks = Array.from({ length: xMax / 50 + 1 }, (_, index) => index * 50);
  const yTicks = [250_000, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000, 20_000_000, 50_000_000, 100_000_000, 200_000_000].filter((value) => value >= minValue && value <= maxValue);
  const hovered = players.find((player) => player.playerId === hoveredId) ?? null;
  const path = (points: FairValueCurvePoint[], factor = 1) => points.map((point, index) => `${index ? "L" : "M"}${x(point.points).toFixed(1)},${y(point.value * factor).toFixed(1)}`).join(" ");

  return (
    <div className="fair-value-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Marktwert im Verhältnis zu durchschnittlichen Punkten">
        {yTicks.map((tick) => <g key={tick}><line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} className="fair-grid"/><text x={left - 10} y={y(tick) + 4} textAnchor="end" className="fair-axis-label">{compactMoney(tick)}</text></g>)}
        {xTicks.map((tick) => <g key={tick}><line x1={x(tick)} x2={x(tick)} y1={top} y2={height - bottom} className="fair-grid"/><text x={x(tick)} y={height - 20} textAnchor="middle" className="fair-axis-label">{tick}</text></g>)}
        {curve ? <><path d={path(curve, 1 + band)} className="fair-curve-band"/><path d={path(curve, 1 - band)} className="fair-curve-band"/><path d={path(curve)} className="fair-curve"/></> : null}
        {players.map((player) => {
          const cx = x(player.averagePoints), cy = y(player.marketValue);
          const className = `fair-dot is-${player.rating}`;
          return <g key={player.playerId} className="fair-dot-target" tabIndex={0} role="button" aria-label={`${displayName(player)}, Fair-Value-Details öffnen`} onMouseEnter={() => setHoveredId(player.playerId)} onMouseLeave={() => setHoveredId(null)} onFocus={() => setHoveredId(player.playerId)} onBlur={() => setHoveredId(null)} onClick={() => onPick(player.playerId)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onPick(player.playerId); } }}><circle cx={cx} cy={cy} r="12" fill="transparent"/>{player.rating === "expensive" ? <path d={`M${cx},${cy - 6} L${cx + 6},${cy} L${cx},${cy + 6} L${cx - 6},${cy} Z`} className={className}/> : <circle cx={cx} cy={cy} r={player.rating === "cheap" ? 5 : 3.5} className={className}/>}</g>;
        })}
        <text x={(left + width - right) / 2} y={height - 2} textAnchor="middle" className="fair-axis-title">Ø Punkte</text>
      </svg>
      {hovered ? <FairTooltip player={hovered} left={`${x(hovered.averagePoints) / width * 100}%`} top={`${y(hovered.marketValue) / height * 100}%`}/> : null}
    </div>
  );
}

function FairTooltip({ player, left, top }: { player: RatedFairValuePlayer; left: string; top: string }) {
  return <div className="fair-tooltip" style={{ left, top }}><strong>{displayName(player)}</strong><span>Ø Punkte <b>{number(player.averagePoints, 1)}</b></span><span>Marktwert <b>{compactMoney(player.marketValue)}</b></span><span>Fair Value <b>{compactMoney(player.fairValue)}</b></span><span>{ratingLabel(player.rating)} <b className={`is-${player.rating}`}>{signedPercent(player.gap)}</b></span>{player.ownerName ? <small>{player.ownerName}{player.onMarket ? " · auf dem Markt" : ""}</small> : player.onMarket ? <small><Store size={10}/> Kickbase-Markt</small> : null}</div>;
}

function Summary({ label, value, hint, icon, tone }: { label: string; value: string; hint: string; icon?: React.ReactNode; tone?: "cheap" | "expensive" }) { return <article className="fair-value-summary__item"><span>{icon}{label}</span><strong className={tone ? `is-${tone}` : undefined}>{value}</strong><small>{hint}</small></article>; }
function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) { return <div className="fair-filter-group" aria-label={label}>{children}</div>; }
function FilterButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) { return <button type="button" className={active ? "is-active" : ""} onClick={onClick}>{children}</button>; }
function FairValueState({ children, error = false, retry }: { children: React.ReactNode; error?: boolean; retry?: () => void }) { return <div className={`fair-value-state${error ? " is-error" : ""}`}><BadgeEuro size={24}/><strong>{children}</strong>{retry ? <button type="button" onClick={retry}>Erneut versuchen</button> : null}</div>; }
function displayName(player: RatedFairValuePlayer) { const first = player.firstName?.trim(); return first && !player.name.toLocaleLowerCase("de-DE").startsWith(first.toLocaleLowerCase("de-DE")) ? `${first} ${player.name}` : player.name; }
function ratingLabel(value: RatingFilter) { return value === "all" ? "Alle" : value === "cheap" ? "Günstig" : value === "expensive" ? "Teuer" : "Fair"; }
function compactMoney(value: number) { return new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", notation: "compact", maximumFractionDigits: 1 }).format(value); }
function number(value: number, digits = 0) { return value.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits }); }
function percent(value: number) { return `${number(value * 100, 1)} %`; }
function signedPercent(value: number) { return `${value > 0 ? "+" : ""}${percent(value)}`; }
