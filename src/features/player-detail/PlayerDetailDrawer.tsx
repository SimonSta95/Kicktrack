import { useEffect, useMemo, useState, type Dispatch, type PointerEvent as ReactPointerEvent, type SetStateAction } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarRange, ChevronRight, MapPin } from "lucide-react";
import { getBundledTeamLogo } from "../../lib/team-assets";
import { PlayerStatusDetails } from "../../components/player-status/PlayerStatus";
import { getPlayerDetail, getPlayerPerformanceBreakdown } from "./api";
import { dateOnlyToUtcMs, isDateOlderThan, recentDateCutoffMs } from "@/lib/date-only";
import type { MarketValuePoint, PerformanceBreakdown, PlayerDetailRequest, PlayerDetailResponse, PlayerPerformanceEntry, PlayerTransfer } from "./types";
import { analyzeMarketValues, type MarketValueAnalysis, type MarketValueChange } from "./market-value-analysis";
import { analyzeMarketDynamics, analyzePoints } from "../analytics/player-analytics";
import { MarketDynamicsIndicator } from "../../components/market-dynamics/MarketDynamicsIndicator";
import { useMvPredictions } from "../analytics/use-mv-predictions";
import { estimateFairValue, rateFixture } from "../analytics/decision-intelligence";
import { useFairValueReference, useFixtureOutlook } from "../analytics/use-decision-intelligence";
import { MvPredictionIndicator } from "../../components/mv-prediction/MvPredictionIndicator";
import { getLeagueNextMatchday } from "../squad/api";
import type { NextFixture } from "../squad/types";
import "./player-detail.css";

const RANGE_PRESETS = [
  { label: "7T", days: 7 },
  { label: "30T", days: 30 },
  { label: "90T", days: 90 },
  { label: "1J", days: 365 },
  { label: "Gesamt", days: null },
] as const;

export function PlayerDetailPage({ request, onClose }: { request: PlayerDetailRequest; onClose: () => void }) {
  const queryClient = useQueryClient();
  const detailQuery = useQuery({
    queryKey: ["player-detail", request?.leagueId, request?.playerId],
    queryFn: () => getPlayerDetail(request!.leagueId, request!.playerId),
    staleTime: 0,
    refetchOnMount: "always",
  });
  const [selectedDay, setSelectedDay] = useState<number | null>(null);
  useEffect(() => {
    if (detailQuery.data && request?.playerId) {
      void queryClient.invalidateQueries({ queryKey: ["analytics", "market-value-histories"] });
    }
  }, [detailQuery.dataUpdatedAt, request?.playerId, queryClient]);

  useEffect(() => {
    setSelectedDay(null);
  }, [request?.playerId]);

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [request, onClose]);

  const breakdownQuery = useQuery({
    queryKey: ["player-breakdown", request?.leagueId, request?.playerId, selectedDay],
    queryFn: () => getPlayerPerformanceBreakdown(request!.leagueId, request!.playerId, selectedDay!),
    enabled: Boolean(request && selectedDay != null),
  });

  return (
    <section className="player-detail player-detail--page" aria-label="Spielerdetails">
      {detailQuery.isLoading || !detailQuery.data ? (
        <DrawerState error={detailQuery.isError} retry={() => detailQuery.refetch()} onClose={onClose} />
      ) : (
        <PlayerDetailContent
          data={detailQuery.data}
          leagueId={request.leagueId}
          contextLabel={request.context?.label}
          selectedDay={selectedDay}
          setSelectedDay={setSelectedDay}
          breakdown={breakdownQuery.data}
          breakdownLoading={breakdownQuery.isLoading}
          breakdownError={breakdownQuery.isError}
          onClose={onClose}
        />
      )}
    </section>
  );
}

type PlayerDetailContentProps = {
  data: PlayerDetailResponse;
  leagueId: string;
  contextLabel?: string;
  selectedDay: number | null;
  setSelectedDay: Dispatch<SetStateAction<number | null>>;
  breakdown: PerformanceBreakdown | undefined;
  breakdownLoading: boolean;
  breakdownError: boolean;
  onClose: () => void;
};

function PlayerDetailContent({ data, leagueId, contextLabel, selectedDay, setSelectedDay, breakdown, breakdownLoading, breakdownError, onClose }: PlayerDetailContentProps) {
  const player = data.player;
  const teamLogo = getBundledTeamLogo(player.teamId);
  const fixturesQuery = useQuery({ queryKey: ["fixtures", "next", leagueId], queryFn: () => getLeagueNextMatchday(leagueId), staleTime: 10 * 60 * 1000 });
  const fairReferenceQuery = useFairValueReference();
  const fixtureOutlookQuery = useFixtureOutlook();
  const nextFixture = useMemo(() => findFixture(player.teamId, fixturesQuery.data?.fixtures ?? []), [fixturesQuery.data?.fixtures, player.teamId]);
  const fairValue = useMemo(() => estimateFairValue(
    player.averagePoints, player.marketValue, player.position, player.id, fairReferenceQuery.data?.players ?? [], player.pointsTotal,
  ), [fairReferenceQuery.data?.players, player.averagePoints, player.id, player.marketValue, player.pointsTotal, player.position]);
  const outlook = useMemo(() => player.teamId ? (fixtureOutlookQuery.data?.fixturesByTeam[player.teamId] ?? []) : [], [fixtureOutlookQuery.data?.fixturesByTeam, player.teamId]);
  return (
    <>
      <header className="player-detail__header">
        <div className="player-detail__identity">
          <div className="player-detail__portrait">
            {player.portraitDataUrl ? <img src={player.portraitDataUrl} alt="" /> : <span>{player.name.slice(0, 1)}</span>}
          </div>
          <div className="player-detail__title-wrap">
            {contextLabel ? <button type="button" className="player-detail__context" onClick={onClose}><ArrowLeft size={13} /> {contextLabel}</button> : <span className="player-detail__eyebrow">Spieler</span>}
            <div className="player-detail__name-line">
              {teamLogo ? <img src={teamLogo} className="player-detail__team-logo" alt="" /> : null}
              <h2>{player.firstName ? <span className="player-detail__first-name">{player.firstName} </span> : null}{primaryPlayerName(player.name, player.firstName)}</h2>
            </div>
            <span className="player-detail__club">{player.clubName ?? "Bundesliga"}</span>
            <PlayerStatusDetails status={player.status} statusList={player.statusList} statusText={player.statusText} compact={false} />
          </div>
        </div>
        <button type="button" className="player-detail__back" onClick={onClose} aria-label="Zurück"><ArrowLeft size={17} /> Zurück</button>
      </header>

      <div className="player-detail__metrics">
        <Metric label="Marktwert" value={player.marketValue == null ? "—" : formatCurrency(player.marketValue)} />
        <Metric label="24H" value={player.marketValueChange24h == null ? "—" : formatSignedCurrency(player.marketValueChange24h)} tone={player.marketValueChange24h == null ? "neutral" : tone(player.marketValueChange24h)} />
        <Metric label="Punkte" value={player.pointsTotal == null ? "—" : formatNumber(player.pointsTotal)} />
        <Metric label="Ø Punkte" value={player.averagePoints == null ? "—" : formatNumber(player.averagePoints, 1)} />
        <Metric label="Pkt/Mio" value={formatPointsPerMillion(player.averagePoints, player.marketValue)} />
        <Metric
          label="Fair Value"
          value={fairValue.fairValue == null ? "—" : formatCurrency(fairValue.fairValue)}
          subvalue={fairValue.differencePct == null ? (fairReferenceQuery.isLoading ? "Referenz wird geladen" : fairValue.confidenceLabel) : `${fairValue.differencePct >= 0 ? "+" : ""}${formatNumber(fairValue.differencePct, 1)}% · ${fairValue.confidenceLabel}`}
          tone={fairValue.difference == null ? "neutral" : tone(fairValue.difference)}
        />
      </div>

      <div className="player-detail__scroll">
        <NextFixtureCard fixture={nextFixture} teamId={player.teamId} dayNumber={fixturesQuery.data?.dayNumber ?? null} loading={fixturesQuery.isLoading} />
        <FixtureOutlookSection items={outlook} position={player.position} quality={fixtureOutlookQuery.data?.dataQuality ?? null} completedMatches={fixtureOutlookQuery.data?.completedMatches ?? 0} loading={fixtureOutlookQuery.isLoading} />
        <AnalyticsOverview leagueId={leagueId} playerId={player.id} marketValues={data.marketValues} performance={data.performance} marketValue={player.marketValue} currentDelta={player.marketValueChange24h} />
        <MarketValueSection points={data.marketValues} />
        <TransfersSection transfers={data.transfers} available={data.transfersAvailable} marketValues={data.marketValues} />
        <PerformanceSection entries={data.performance} selectedDay={selectedDay} onSelect={setSelectedDay} />
        <PointsAnalysisSection entries={data.performance} />
        {selectedDay != null ? (
          <BreakdownSection day={selectedDay} data={breakdown} loading={breakdownLoading} error={breakdownError} />
        ) : null}
      </div>
    </>
  );
}


function NextFixtureCard({ fixture, teamId, dayNumber, loading }: { fixture: NextFixture | null; teamId: string | null; dayNumber: number | null; loading: boolean }) {
  if (loading) return <section className="player-next-fixture is-loading"><MapPin size={15}/><span>Nächster Gegner wird geladen …</span></section>;
  if (!fixture || !teamId) return null;
  const isHome = fixture.homeTeamId === teamId;
  const opponentId = isHome ? fixture.awayTeamId : fixture.homeTeamId;
  const opponent = isHome ? fixture.awayTeamName : fixture.homeTeamName;
  const opponentLogo = getBundledTeamLogo(opponentId);
  return <section className="player-next-fixture">
    <div><span>{dayNumber == null ? "Nächster Spieltag" : `Spieltag ${dayNumber}`}</span><strong>{isHome ? "Heimspiel" : "Auswärtsspiel"}</strong></div>
    <div className="player-next-fixture__opponent">{opponentLogo ? <img src={opponentLogo} alt="" aria-hidden/> : null}<strong>{isHome ? "vs." : "@"} {opponent}</strong>{fixture.kickoff ? <small>{formatKickoff(fixture.kickoff)}</small> : null}</div>
  </section>;
}

function FixtureOutlookSection({ items, position, quality, completedMatches, loading }: { items: import("../analytics/decision-intelligence").FixtureOutlookItem[]; position: number | null; quality: "LOW" | "MEDIUM" | "HIGH" | null; completedMatches: number; loading: boolean }) {
  if (loading) return null;
  if (!items.length) return null;
  const rated = items.map((item) => rateFixture(item, position));
  const average = rated.reduce((sum, item) => sum + item.favorability, 0) / rated.length;
  const qualityLabel = quality === "HIGH" ? "hohe Datenbasis" : quality === "MEDIUM" ? "mittlere Datenbasis" : "frühe Saison · geringe Datenbasis";
  return <section className="player-section fixture-outlook">
    <div className="player-section__heading"><div><span>Restprogramm</span><strong>{average.toFixed(1)} / 10</strong></div><small>{qualityLabel} · {completedMatches} Spiele</small></div>
    <div className="fixture-outlook__list">{rated.map((item) => {
      const logo = getBundledTeamLogo(item.opponentId);
      const toneClass = item.favorability >= 6.2 ? "is-good" : item.favorability < 4.5 ? "is-hard" : "is-neutral";
      return <div className={`fixture-outlook__item ${toneClass}`} key={`${item.dayNumber}-${item.matchId}-${item.opponentId}`}>
        <span className="fixture-outlook__day">ST {item.dayNumber}</span>
        <div>{logo ? <img src={logo} alt="" aria-hidden /> : null}<strong>{item.isHome ? "vs." : "@"} {item.opponentName}</strong></div>
        <span className="fixture-outlook__rating">{item.favorability.toFixed(1)} <small>{item.label}</small></span>
      </div>;
    })}</div>
    <p className="fixture-outlook__hint">Rating ist positionsabhängig: TW/ABW gegen gegnerische Offensive, ST gegen gegnerische Defensive, MF kombiniert beide Seiten. Heim/Auswärts wird leicht gewichtet.</p>
  </section>;
}

function findFixture(teamId: string | null, fixtures: NextFixture[]) {
  if (!teamId) return null;
  return fixtures.find((fixture) => fixture.homeTeamId === teamId || fixture.awayTeamId === teamId) ?? null;
}

function formatKickoff(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function AnalyticsOverview({ leagueId, playerId, marketValues, performance, marketValue, currentDelta }: { leagueId: string; playerId: string; marketValues: MarketValuePoint[]; performance: PlayerPerformanceEntry[]; marketValue: number | null; currentDelta: number | null }) {
  const dynamics = useMemo(() => analyzeMarketDynamics(marketValues, marketValue, currentDelta), [marketValues, marketValue, currentDelta]);
  const points = useMemo(() => analyzePoints(performance), [performance]);
  const predictionInputs = useMemo(() => [{ playerId, marketValue, marketValueChange24h: currentDelta }], [playerId, marketValue, currentDelta]);
  const predictionQuery = useMvPredictions(leagueId, predictionInputs);
  const prediction = predictionQuery.byPlayer.get(playerId);
  return (
    <section className="player-section analytics-overview">
      <div className="player-section__heading"><div><span>Analyse</span><strong>Faktenbasiert</strong></div><small>Keine zusammengesetzten Scores</small></div>
      <div className="analytics-overview__grid">
        <div className="analytics-card">
          <span className="analytics-card__label">MW-Dynamik</span>
          <strong className={`analytics-dynamics tone-${dynamics.tone}`}><MarketDynamicsIndicator dynamics={dynamics} detail /></strong>
          <p>{dynamics.reason}</p>
          {dynamics.recentSteps.length ? <div className="analytics-steps">{dynamics.recentSteps.slice(-4).map((step, index) => <span className={`tone-${tone(step)}`} key={`${step}-${index}`}>{formatSignedCurrency(step)}</span>)}</div> : null}
        </div>
        <div className="analytics-card">
          <span className="analytics-card__label">Punkteform</span>
          <strong className={`analytics-dynamics ${points.form === "UP" ? "tone-positive" : points.form === "DOWN" ? "tone-negative" : ""}`}>{points.formLabel}</strong>
          <p>{points.sampleSize ? `${points.sampleSize} aktive Spieltage · ${points.volatilityLabel}` : "Noch keine aktuelle Saisonbasis."}</p>
          <div className="analytics-steps"><span>R3 {points.rolling3 == null ? "—" : formatNumber(points.rolling3, 1)}</span><span>R5 {points.rolling5 == null ? "—" : formatNumber(points.rolling5, 1)}</span></div>
        </div>
        <div className="analytics-card analytics-card--prediction">
          <span className="analytics-card__label">Next Refresh · 22 Uhr</span>
          {prediction ? <MvPredictionIndicator prediction={prediction} quality={predictionQuery.data?.quality} detail /> : <strong className="analytics-dynamics">Noch keine Prognose</strong>}
        </div>
      </div>
    </section>
  );
}

function PointsAnalysisSection({ entries }: { entries: PlayerPerformanceEntry[] }) {
  const analysis = useMemo(() => analyzePoints(entries), [entries]);
  if (!analysis.sampleSize) return null;
  return (
    <section className="player-section">
      <div className="player-section__heading"><div><span>Punkteanalyse</span><strong>{analysis.sampleSize} Spieltage</strong></div><small>Aktuelle Saison</small></div>
      <div className="points-analysis-grid">
        <AnalysisMetric label="Saison Ø" value={formatOptional(analysis.seasonAverage)} />
        <AnalysisMetric label="Letzte 3" value={formatOptional(analysis.rolling3)} />
        <AnalysisMetric label="Letzte 5" value={formatOptional(analysis.rolling5)} />
        <AnalysisMetric label={analysis.sampleSize >= 8 ? "Median" : "Median · vorläufig"} value={formatOptional(analysis.median)} />
        <AnalysisMetric label="Floor · P25" value={formatOptional(analysis.floor)} />
        <AnalysisMetric label="Ceiling · P75" value={formatOptional(analysis.ceiling)} />
        <AnalysisMetric label="Ø Minuten" value={analysis.minutesAverage == null ? "—" : `${formatNumber(analysis.minutesAverage, 0)}'`} />
        <AnalysisMetric label="Schwankung" value={analysis.volatilityLabel} text />
      </div>
    </section>
  );
}

function AnalysisMetric({ label, value, text = false }: { label: string; value: string; text?: boolean }) {
  return <div className={`analysis-metric ${text ? "is-text" : ""}`}><span>{label}</span><strong>{value}</strong></div>;
}
function formatOptional(value: number | null) { return value == null ? "—" : formatNumber(value, 1); }

function MarketValueSection({ points }: { points: MarketValuePoint[] }) {
  const [preset, setPreset] = useState<(typeof RANGE_PRESETS)[number]["label"]>("90T");
  const presetPoints = useMemo(() => filterPreset(points, preset), [points, preset]);
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(Math.max(presetPoints.length - 1, 0));

  useEffect(() => {
    setStart(0);
    setEnd(Math.max(presetPoints.length - 1, 0));
  }, [presetPoints, preset]);

  const visible = presetPoints.slice(Math.min(start, end), Math.max(start, end) + 1);
  const analysis = useMemo(() => analyzeMarketValues(visible), [visible]);
  const delta = analysis?.totalChange ?? 0;

  return (
    <section className="player-section player-market-history">
      <div className="player-section__heading">
        <div>
          <span>Marktwertverlauf</span>
          <strong className={`tone-${tone(delta)}`}>
            {analysis && analysis.changes.length ? `${formatSignedCurrency(delta)} · ${formatSignedPercent(analysis.totalChangePct)}` : "—"}
          </strong>
        </div>
        <div className="chart-presets">
          {RANGE_PRESETS.map((item) => <button type="button" key={item.label} className={preset === item.label ? "is-active" : ""} onClick={() => setPreset(item.label)}>{item.label}</button>)}
        </div>
      </div>
      <div className="mv-history-freshness">{points.length ? `Letzter gespeicherter MW: ${formatDate(points[points.length - 1].date)}${isDateOlderThan(points[points.length - 1].date, 2) ? " · Historie möglicherweise veraltet" : ""}` : "Keine Marktwerthistorie verfügbar"}</div>
      {analysis && analysis.changes.length ? (
        <>
          <div className="mv-analysis-layout">
            <div className="mv-analysis-main">
              <MarketValueChart points={analysis.points} />
              <DailyChangeBars changes={analysis.changes} />
            </div>
            <MarketValueStatistics analysis={analysis} />
          </div>
          <RecentMarketValues changes={analysis.changes} />
        </>
      ) : <div className="player-section__empty">Für diesen Zeitraum liegen noch nicht genug Marktwerte vor.</div>}
      {presetPoints.length > 2 ? (
        <div className="chart-range-control">
          <CalendarRange size={14} />
          <span>{formatDate(presetPoints[Math.min(start, end)]?.date)}</span>
          <div className="dual-range">
            <input aria-label="Start des Marktwertzeitraums" type="range" min={0} max={presetPoints.length - 1} value={Math.min(start, end)} onChange={(e) => setStart(Math.min(Number(e.target.value), Math.max(start, end) - 1))} />
            <input aria-label="Ende des Marktwertzeitraums" type="range" min={0} max={presetPoints.length - 1} value={Math.max(start, end)} onChange={(e) => setEnd(Math.max(Number(e.target.value), Math.min(start, end) + 1))} />
          </div>
          <span>{formatDate(presetPoints[Math.max(start, end)]?.date)}</span>
        </div>
      ) : null}
    </section>
  );
}

function DailyChangeBars({ changes }: { changes: MarketValueChange[] }) {
  const visible = changes.slice(-120);
  const max = Math.max(...visible.map((change) => Math.abs(change.change)), 1);
  return (
    <div className="mv-daily-changes">
      <span className="mv-daily-changes__label">Änderung zur vorherigen Messung</span>
      <div className="mv-daily-changes__bars" role="img" aria-label="Tägliche Marktwertänderungen">
        {visible.map((change) => {
          const height = Math.max(3, Math.abs(change.change) / max * 48);
          return (
            <span className="mv-daily-change" key={change.date} title={`${formatDate(change.date)}: ${formatSignedCurrency(change.change)} (${formatSignedPercent(change.changePct)})`}>
              {change.change > 0 ? <i className="is-positive" style={{ height }} /> : null}
              <b />
              {change.change < 0 ? <i className="is-negative" style={{ height }} /> : null}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function MarketValueStatistics({ analysis }: { analysis: MarketValueAnalysis }) {
  const streak = analysis.currentStreak.direction === "flat"
    ? "Keine laufende Serie"
    : `${analysis.currentStreak.count}× ${analysis.currentStreak.direction === "up" ? "steigend" : "fallend"}`;
  return (
    <aside className="mv-statistics" aria-label="Marktwertstatistik">
      <header><span>Statistik</span><strong>{analysis.points.length} Messpunkte</strong></header>
      <StatRow label="Veränderung" value={`${formatSignedCurrency(analysis.totalChange)} · ${formatSignedPercent(analysis.totalChangePct)}`} toneValue={analysis.totalChange} />
      <StatRow label="Höchstwert" value={formatCurrency(analysis.high.value)} sub={formatDate(analysis.high.date)} />
      <StatRow label="Tiefstwert" value={formatCurrency(analysis.low.value)} sub={formatDate(analysis.low.date)} />
      <StatRow label="Abstand zum Hoch" value={formatSignedPercent(analysis.distanceFromHighPct)} toneValue={analysis.distanceFromHighPct} />
      <StatRow label="Durchschnitt" value={formatCurrency(Math.round(analysis.averageValue))} />
      <StatRow label="Ø je Messung" value={formatSignedCurrency(Math.round(analysis.averageChange))} toneValue={analysis.averageChange} />
      <StatRow label="Steigend / fallend" value={`${analysis.upDays} / ${analysis.downDays}`} />
      <StatRow label="Aktuelle Serie" value={streak} toneValue={analysis.currentStreak.direction === "up" ? 1 : analysis.currentStreak.direction === "down" ? -1 : 0} />
      <StatRow label="Längste Serie" value={`↑ ${analysis.longestUpStreak} · ↓ ${analysis.longestDownStreak}`} />
      <StatRow label="Bester Tag" value={analysis.bestDay ? formatSignedCurrency(analysis.bestDay.change) : "—"} sub={analysis.bestDay ? formatDate(analysis.bestDay.date) : undefined} toneValue={1} />
      <StatRow label="Schlechtester Tag" value={analysis.worstDay ? formatSignedCurrency(analysis.worstDay.change) : "—"} sub={analysis.worstDay ? formatDate(analysis.worstDay.date) : undefined} toneValue={-1} />
      <StatRow label="Schwankung" value={`± ${formatNumber(analysis.volatilityPct, 1)} %`} sub="Standardabweichung der Änderungen" />
    </aside>
  );
}

function StatRow({ label, value, sub, toneValue }: { label: string; value: string; sub?: string; toneValue?: number }) {
  return <div className="mv-statistics__row"><span>{label}</span><div><strong className={toneValue == null ? undefined : `tone-${tone(toneValue)}`}>{value}</strong>{sub ? <small>{sub}</small> : null}</div></div>;
}

function RecentMarketValues({ changes }: { changes: MarketValueChange[] }) {
  const recent = changes.slice(-14).reverse();
  if (!recent.length) return null;
  return (
    <div className="mv-recent">
      <header><span>Letzte 14 Messungen</span><small>Nur tatsächlich vorhandene Tageswerte</small></header>
      <div className="mv-recent__table-wrap">
        <table>
          <thead><tr><th>Datum</th><th>Marktwert</th><th>Veränderung</th><th>Prozent</th></tr></thead>
          <tbody>{recent.map((change) => <tr key={change.date}><td>{formatDate(change.date)}</td><td>{formatCurrency(change.value)}</td><td className={`tone-${tone(change.change)}`}>{formatSignedCurrency(change.change)}</td><td className={`tone-${tone(change.changePct)}`}>{formatSignedPercent(change.changePct)}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}

function MarketValueChart({ points }: { points: MarketValuePoint[] }) {
  const width = 720, height = 220, padX = 18, padY = 18;
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const values = points.map((p) => p.value);
  const min = Math.min(...values), max = Math.max(...values);
  const span = Math.max(max - min, 1);
  const coords = points.map((point) => ({
    ...point,
    x: padX + ((dateOnlyToUtcMs(point.date) - dateOnlyToUtcMs(points[0].date)) / Math.max(dateOnlyToUtcMs(points[points.length - 1].date) - dateOnlyToUtcMs(points[0].date), 1)) * (width - padX * 2),
    y: padY + (1 - (point.value - min) / span) * (height - padY * 2),
  }));
  const path = coords.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const area = `${path} L${coords[coords.length - 1].x},${height - padY} L${coords[0].x},${height - padY} Z`;
  const hovered = hoveredIndex == null ? null : coords[hoveredIndex];

  function handlePointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width || !coords.length) return;
    const localX = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
    const chartX = (localX / rect.width) * width;
    const index = coords.reduce((best, point, i) => Math.abs(point.x - chartX) < Math.abs(coords[best].x - chartX) ? i : best, 0);
    setHoveredIndex(index);
  }

  return (
    <div className="mv-chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Marktwertverlauf"
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setHoveredIndex(null)}
      >
        <defs><linearGradient id="mv-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="currentColor" stopOpacity=".24"/><stop offset="1" stopColor="currentColor" stopOpacity="0"/></linearGradient></defs>
        <path className="mv-chart__area" d={area} />
        <path className="mv-chart__line" d={path} />
        {hovered ? (
          <>
            <line className="mv-chart__crosshair" x1={hovered.x} x2={hovered.x} y1={padY} y2={height - padY} />
            <circle className="mv-chart__hover-point" cx={hovered.x} cy={hovered.y} r="5" />
          </>
        ) : null}
      </svg>
      {hovered ? (
        <div
          className={`mv-chart__tooltip ${hovered.x > width * 0.72 ? "is-left" : ""}`}
          style={{ left: `${(hovered.x / width) * 100}%`, top: `${(hovered.y / height) * 100}%` }}
        >
          <span>{formatDate(hovered.date)} · nach 22 Uhr</span>
          <strong>{formatCurrency(hovered.value)}</strong>
        </div>
      ) : null}
      <div className="mv-chart__labels"><span>{formatCurrency(min)}</span><span>{formatCurrency(max)}</span></div>
    </div>
  );
}

function TransfersSection({ transfers, available, marketValues }: { transfers: PlayerTransfer[]; available: boolean; marketValues: MarketValuePoint[] }) {
  return (
    <section className="player-section player-transfers">
      <div className="player-section__heading">
        <div><span>Transfers in der Liga</span><strong>{transfers.length ? `${transfers.length} erfasst` : "Keine erfasst"}</strong></div>
        <small>Abgeschlossene Kickbase-Transfers</small>
      </div>
      {transfers.length ? (
        <div className="player-transfers__list">
          {transfers.map((transfer, index) => {
            const date = transfer.date.slice(0, 10);
            const marketValuePoint = marketValueOnOrBefore(marketValues, date);
            const marketValue = marketValuePoint?.value ?? null;
            const premium = marketValue == null ? null : transfer.price - marketValue;
            const premiumPct = marketValue != null && marketValue > 0 && premium != null ? premium / marketValue * 100 : null;
            return (
              <article className="player-transfer" key={`${transfer.managerId ?? "kickbase"}-${transfer.date}-${transfer.price}-${index}`}>
                <span className="player-transfer__avatar">{(transfer.managerName ?? "K").slice(0, 1).toUpperCase()}</span>
                <div className="player-transfer__owner">
                  <span>Wechsel zu</span>
                  <strong>{transfer.managerName ?? "Kickbase / unbekannt"}</strong>
                  <small>{formatDate(date)}</small>
                </div>
                <div className="player-transfer__price">
                  <strong>{formatCurrency(transfer.price)}</strong>
                  {premium != null && premiumPct != null ? <small className={`tone-${tone(premium)}`}>{formatSignedCurrency(premium)} · {formatSignedPercent(premiumPct)} zum MW</small> : <small>MW am Transfertag nicht verfügbar</small>}
                </div>
              </article>
            );
          })}
        </div>
      ) : available ? (
        <div className="player-section__empty">Kickbase liefert für diesen Spieler in der aktiven Liga keine abgeschlossenen Transfers.</div>
      ) : (
        <div className="player-section__empty">Die Transferhistorie konnte gerade nicht geladen werden. Die übrigen Spielerdaten bleiben verfügbar.</div>
      )}
    </section>
  );
}

function marketValueOnOrBefore(points: MarketValuePoint[], date: string) {
  let result: MarketValuePoint | null = null;
  for (const point of points) {
    if (point.date > date) break;
    if (point.date <= date && point.value > 0) result = point;
  }
  if (!result) return null;
  const ageMs = dateOnlyToUtcMs(date) - dateOnlyToUtcMs(result.date);
  return ageMs >= 0 && ageMs <= 2 * 86_400_000 ? result : null;
}

function PerformanceSection({ entries, selectedDay, onSelect }: { entries: PlayerPerformanceEntry[]; selectedDay: number | null; onSelect: (day: number) => void }) {
  // The backend already removes upcoming fixtures. We deliberately do not pad
  // this to 34 bars: only matchdays that have actually become active belong here.
  const activeMatchdays = entries.filter((entry) => entry.dayNumber > 0);
  const positiveMax = Math.max(100, ...activeMatchdays.map((entry) => Math.max(entry.points ?? 0, 0)));
  const negativeMax = Math.max(20, ...activeMatchdays.map((entry) => Math.abs(Math.min(entry.points ?? 0, 0))));

  return (
    <section className="player-section">
      <div className="player-section__heading">
        <div><span>Performance</span><strong>{activeMatchdays.length} {activeMatchdays.length === 1 ? "aktiver Spieltag" : "aktive Spieltage"}</strong></div>
        <small>Balken anklicken für Aufschlüsselung</small>
      </div>
      {activeMatchdays.length ? (
        <div className="performance-bars" role="list" aria-label="Punkte nach aktivem Spieltag">
          {activeMatchdays.map((entry) => {
            const points = entry.points ?? 0;
            const height = points >= 0
              ? Math.max(8, Math.min(100, points / positiveMax * 100))
              : Math.max(8, Math.min(42, Math.abs(points) / negativeMax * 42));
            const performanceTone = getPerformanceTone(points);
            return (
              <button
                key={entry.dayNumber}
                type="button"
                className={`performance-bar is-${performanceTone} ${selectedDay === entry.dayNumber ? "is-active" : ""}`}
                onClick={() => onSelect(entry.dayNumber)}
                title={`Spieltag ${entry.dayNumber}: ${points} Punkte`}
              >
                <span className="performance-bar__value">{points}</span>
                <span className="performance-bar__track"><span style={{ height: `${height}%` }} /></span>
                <span className="performance-bar__day">{entry.dayNumber}</span>
              </button>
            );
          })}
        </div>
      ) : <div className="player-section__empty">Noch kein Spieltag dieser Saison ist aktiv.</div>}
    </section>
  );
}

function getPerformanceTone(points: number) {
  // Kickbase-style performance bands: strong matchdays green, ordinary/low
  // positive matchdays orange, minus points red. No future/zero placeholders.
  if (points >= 100) return "great";
  if (points >= 0) return "okay";
  return "bad";
}

function BreakdownSection({ day, data, loading, error }: { day: number; data: PerformanceBreakdown | undefined; loading: boolean; error: boolean }) {
  return (
    <section className="player-section player-breakdown">
      <div className="player-section__heading"><div><span>Spieltag {day}</span><strong>{data?.totalPoints == null ? "Punkte-Aufschlüsselung" : `${data.totalPoints} Punkte`}</strong></div></div>
      {loading ? <div className="player-section__empty">Aufschlüsselung wird geladen …</div> : error ? <div className="player-section__empty">Kickbase konnte die Aufschlüsselung nicht liefern.</div> : data?.items?.length ? (
        <div className="breakdown-list">{data.items.map((item) => <div className="breakdown-row" key={item.id}><span>{item.label}{item.count && item.count > 1 ? ` × ${item.count}` : ""}</span><strong className={`tone-${tone(item.points)}`}>{item.points > 0 ? "+" : ""}{item.points}</strong></div>)}</div>
      ) : <div className="player-section__empty">Für diesen Spieltag liefert Kickbase keine einzelne Punkte-Aufschlüsselung.</div>}
    </section>
  );
}

function primaryPlayerName(name: string, firstName: string | null) {
  if (!firstName) return name;
  const normalizedName = name.trim();
  const normalizedFirst = firstName.trim();
  if (!normalizedFirst) return normalizedName;
  const lowerName = normalizedName.toLocaleLowerCase("de-DE");
  const lowerFirst = normalizedFirst.toLocaleLowerCase("de-DE");
  if (lowerName === lowerFirst) return normalizedName;
  if (lowerName.startsWith(`${lowerFirst} `)) return normalizedName.slice(normalizedFirst.length).trimStart();
  return normalizedName;
}

function DrawerState({ error, retry, onClose }: { error: boolean; retry: () => void; onClose: () => void }) {
  return <div className="player-detail__state"><button className="player-detail__back player-detail__back--state" onClick={onClose}><ArrowLeft size={17}/> Zurück</button><strong>{error ? "Spieler konnte nicht geladen werden." : "Spieler wird geladen …"}</strong>{error ? <button type="button" onClick={retry}>Erneut versuchen <ChevronRight size={14}/></button> : null}</div>;
}
type MetricTone = "positive" | "negative" | "neutral";
function Metric({ label, value, subvalue, tone: metricTone = "neutral" }: { label: string; value: string; subvalue?: string; tone?: MetricTone }) { return <div><span>{label}</span><strong className={`tone-${metricTone}`}>{value}</strong>{subvalue ? <small className="player-detail__metric-sub">{subvalue}</small> : null}</div>; }
function filterPreset(points: MarketValuePoint[], label: string) { const preset = RANGE_PRESETS.find((p) => p.label === label); if (!preset?.days || !points.length) return points; const cutoff = recentDateCutoffMs(preset.days); return points.filter((point) => dateOnlyToUtcMs(point.date) >= cutoff); }
function tone(value: number) { return value > 0 ? "positive" : value < 0 ? "negative" : "neutral"; }
function formatCurrency(value: number) { return new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value); }
function formatSignedCurrency(value: number) { const sign = value > 0 ? "+" : ""; const abs = Math.abs(value); if (abs >= 1_000_000) return `${sign}${(value / 1_000_000).toLocaleString("de-DE", { maximumFractionDigits: 2 })} Mio. €`; if (abs >= 1_000) return `${sign}${Math.round(value / 1_000).toLocaleString("de-DE")} Tsd. €`; return `${sign}${value.toLocaleString("de-DE")} €`; }
function formatSignedPercent(value: number) { return `${value > 0 ? "+" : ""}${formatNumber(value, 1)} %`; }
function formatNumber(value: number, digits = 0) { return value.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits }); }
function formatDate(date?: string) { if (!date) return "—"; const [y,m,d] = date.split("-"); return `${d}.${m}.${y.slice(2)}`; }

function formatPointsPerMillion(averagePoints: number | null, marketValue: number | null) {
  if (averagePoints == null || marketValue == null || marketValue <= 0) return "—";
  return formatNumber(averagePoints / (marketValue / 1_000_000), 1);
}
