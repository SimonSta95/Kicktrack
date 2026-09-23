import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Banknote,
  CalendarClock,
  Gavel,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  UsersRound,
  WalletCards,
} from "lucide-react";
import { getLeagueNextMatchday, getLeagueSquad } from "@/features/squad/api";
import { getPlayerStatusLabel } from "@/components/player-status/PlayerStatus";
import { getLeagueMarket } from "@/features/market/api";
import { useMvPredictions } from "@/features/analytics/use-mv-predictions";
import { ForceUpdateButton, lastForceRefresh } from "@/features/refresh/ForceUpdateButton";
import { HistoricalModelButton } from "@/features/analytics/HistoricalModelButton";
import type { AccountUser, LeagueAccountContext } from "./types";
import { DEFAULT_SQUAD_LIMIT } from "@/lib/kickbase-rules";
import "./account-overview.css";

type Props = {
  user?: AccountUser | null;
  league: LeagueAccountContext;
};

const moneyFormatter = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});

const compactMoneyFormatter = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "EUR",
  notation: "compact",
  maximumFractionDigits: 2,
});

export function AccountOverviewPage({ league }: Props) {
  const [, rerender] = useState(0);
  const squadQuery = useQuery({
    queryKey: ["squad", league.leagueId],
    queryFn: () => getLeagueSquad(league.leagueId),
  });
  const marketQuery = useQuery({
    queryKey: ["market", league.leagueId],
    queryFn: () => getLeagueMarket(league.leagueId),
  });
  const nextMatchdayQuery = useQuery({
    queryKey: ["next-matchday", league.leagueId],
    queryFn: () => getLeagueNextMatchday(league.leagueId),
    staleTime: 15 * 60 * 1000,
  });

  const squad = squadQuery.data?.players ?? [];
  const market = marketQuery.data?.entries ?? [];
  const squadValue = squad.reduce((sum, player) => sum + Math.max(0, player.marketValue ?? 0), 0);
  const squadDelta24h = squad.reduce((sum, player) => sum + (player.marketValueChange24h ?? 0), 0);
  const liveSquadSize = squad.length || league.squadSize || 0;
  const squadLimit = league.squadLimit ?? DEFAULT_SQUAD_LIMIT;
  const slotsFree = Math.max(0, squadLimit - liveSquadSize);

  const predictionInputs = useMemo(
    () => squad.map((player) => ({
      playerId: player.id,
      marketValue: player.marketValue,
      marketValueChange24h: player.marketValueChange24h,
    })),
    [squad],
  );
  const predictionQuery = useMvPredictions(league.leagueId, predictionInputs);
  const predictedSquadDelta = useMemo(
    () => [...predictionQuery.byPlayer.values()].reduce((sum, prediction) => sum + (prediction.delta ?? 0), 0),
    [predictionQuery.byPlayer],
  );

  const activeBids = market
    .filter((entry) => entry.ownOffer != null && entry.ownOffer > 0)
    .sort((a, b) => (a.expiresInSeconds ?? Number.MAX_SAFE_INTEGER) - (b.expiresInSeconds ?? Number.MAX_SAFE_INTEGER));

  const statusProblems = squad.filter((player) =>
    (player.status ?? 0) !== 0 || player.statusList.some((code) => code !== 0),
  );
  const movers = [...squad]
    .filter((player) => player.marketValueChange24h != null)
    .sort((a, b) => Math.abs(b.marketValueChange24h ?? 0) - Math.abs(a.marketValueChange24h ?? 0))
    .slice(0, 5);

  const nextFixtures = useMemo(() => {
    const fixtures = nextMatchdayQuery.data?.fixtures ?? [];
    return fixtures
      .map((fixture) => {
        const homePlayers = squad.filter((player) => player.teamId === fixture.homeTeamId);
        const awayPlayers = squad.filter((player) => player.teamId === fixture.awayTeamId);
        if (!homePlayers.length && !awayPlayers.length) return null;

        const ownPlayers = homePlayers.length ? homePlayers : awayPlayers;
        const isHome = homePlayers.length > 0;
        return {
          id: fixture.matchId || `${fixture.homeTeamId}-${fixture.awayTeamId}`,
          players: ownPlayers.map((player) => player.name).join(", "),
          club: isHome ? fixture.homeTeamName : fixture.awayTeamName,
          opponent: isHome ? fixture.awayTeamName : fixture.homeTeamName,
          isHome,
          kickoff: fixture.kickoff,
        };
      })
      .filter((fixture): fixture is NonNullable<typeof fixture> => fixture != null)
      .sort((a, b) => (a.kickoff ?? "").localeCompare(b.kickoff ?? ""));
  }, [nextMatchdayQuery.data?.fixtures, squad]);

  const friday = fridayDeadline();
  const missingForPlus = Math.max(0, -(league.budget ?? 0));
  const riskAfterBids = (league.budgetAfterActiveBids ?? 0) < 0;
  const deadlineTone =
    (league.budget ?? 0) < 0 ? "negative" :
    riskAfterBids ? "warning" :
    "positive";

  const lastRefresh = lastForceRefresh(league.leagueId);

  return (
    <div className="overview-page">
      <header className="overview-header">
        <div>
          <h1>ÜBERSICHT</h1>
          <p>Dein Liga-Cockpit für Budget, Kader, Markt und das nächste 22-Uhr-Update.</p>
        </div>
        <div className="overview-header__actions">
          <span className="overview-refresh-time">
            {lastRefresh ? `Zuletzt komplett: ${formatTime(lastRefresh)}` : "Noch kein komplettes Force Update"}
          </span>
          <HistoricalModelButton leagueId={league.leagueId} />
          <ForceUpdateButton leagueId={league.leagueId} onFinished={() => rerender((value) => value + 1)} />
        </div>
      </header>

      <section className="overview-metrics">
        <Metric
          icon={<Banknote size={17} />}
          label="Aktuell verfügbar"
          value={money(league.budget)}
          tone={tone(league.budget)}
          hint="Kickbase Budget"
        />
        <Metric
          icon={<WalletCards size={17} />}
          label="Nach Geboten"
          value={money(league.budgetAfterActiveBids)}
          tone={tone(league.budgetAfterActiveBids)}
          hint={`${activeBids.length} aktive${activeBids.length === 1 ? "s" : ""} Gebot${activeBids.length === 1 ? "" : "e"}`}
        />
        <Metric
          icon={<UsersRound size={17} />}
          label="Kaderwert"
          value={money(squadValue)}
          hint={`${liveSquadSize} / ${squadLimit} · ${slotsFree} frei`}
        />
        <Metric
          icon={<TrendingUp size={17} />}
          label="Kader 24H"
          value={signedMoney(squadDelta24h)}
          tone={tone(squadDelta24h)}
          hint="Summe der aktuellen MW-Schritte"
        />
        <Metric
          icon={<CalendarClock size={17} />}
          label="Nächstes 22U"
          value={predictionQuery.isLoading ? "…" : signedMoney(predictedSquadDelta)}
          tone={tone(predictedSquadDelta)}
          hint="Modell-Summe für deinen Kader"
        />
      </section>

      <section className={`friday-card is-${deadlineTone}`}>
        <div className="friday-card__icon"><CalendarClock size={21} /></div>
        <div className="friday-card__main">
          <span>FREITAG · 20:00</span>
          <strong>{friday.label}</strong>
          <p>
            {(league.budget ?? 0) < 0
              ? `Du musst aktuell noch ${money(missingForPlus)} realisieren, um im Plus zu sein.`
              : riskAfterBids
                ? "Aktuell bist du im Plus, nach deinen offenen Geboten aber im Minus."
                : "Du bist aktuell im Plus. Offene Gebote gefährden die Deadline derzeit nicht."}
          </p>
        </div>
        <div className="friday-card__numbers">
          <span>Jetzt</span><strong className={toneClass(league.budget)}>{money(league.budget)}</strong>
          <span>Nach Geboten</span><strong className={toneClass(league.budgetAfterActiveBids)}>{money(league.budgetAfterActiveBids)}</strong>
        </div>
      </section>

      <div className="overview-grid">
        <OverviewPanel title="AKTIVE GEBOTE" icon={<Gavel size={16} />} badge={String(activeBids.length)}>
          {activeBids.length ? (
            <div className="overview-list">
              {activeBids.slice(0, 5).map((entry) => (
                <div key={entry.playerId} className="overview-list__row">
                  <div><strong>{entry.name}</strong><span>{remaining(entry.expiresInSeconds)}</span></div>
                  <b>{money(entry.ownOffer)}</b>
                </div>
              ))}
            </div>
          ) : <Empty>Keine aktiven Gebote.</Empty>}
        </OverviewPanel>

        <OverviewPanel title="KADER-AUFFÄLLIGKEITEN" icon={<ShieldAlert size={16} />} badge={String(statusProblems.length)}>
          {statusProblems.length ? (
            <div className="overview-list">
              {statusProblems.slice(0, 5).map((player) => (
                <div key={player.id} className="overview-list__row">
                  <div><strong>{player.name}</strong><span>{getPlayerStatusLabel(player.status, player.statusList, player.statusText)}</span></div>
                  <b>{compactMoney(player.marketValue)}</b>
                </div>
              ))}
            </div>
          ) : <Empty>Keine Statusprobleme im Kader.</Empty>}
        </OverviewPanel>

        <OverviewPanel title="MW-BEWEGUNGEN" icon={<TrendingUp size={16} />} badge="24H">
          {movers.length ? (
            <div className="overview-list">
              {movers.map((player) => (
                <div key={player.id} className="overview-list__row">
                  <div>
                    <strong>{player.name}</strong>
                    <span>{compactMoney(player.marketValue)}</span>
                  </div>
                  <b className={toneClass(player.marketValueChange24h)}>
                    {(player.marketValueChange24h ?? 0) < 0 ? <TrendingDown size={13} /> : <TrendingUp size={13} />}
                    {signedMoney(player.marketValueChange24h)}
                  </b>
                </div>
              ))}
            </div>
          ) : <Empty>Noch keine verwertbaren 24H-Daten.</Empty>}
        </OverviewPanel>

        <OverviewPanel title="22U-AUSBLICK" icon={<CalendarClock size={16} />} badge={predictionQuery.data?.modelVersion ?? "—"}>
          <div className="overview-forecast">
            <div><span>Prognose Kader</span><strong className={toneClass(predictedSquadDelta)}>{predictionQuery.isLoading ? "…" : signedMoney(predictedSquadDelta)}</strong></div>
            <div><span>Kaderspieler modelliert</span><strong>{predictionQuery.data?.predictions.length ?? 0}</strong></div>
            <div><span>Walk-forward Direction</span><strong>{formatRate(predictionQuery.data?.quality.directionHitRate)}</strong></div>
          </div>
        </OverviewPanel>

        <OverviewPanel
          title="NÄCHSTER SPIELTAG"
          icon={<CalendarClock size={16} />}
          badge={nextMatchdayQuery.data?.dayNumber != null ? `ST ${nextMatchdayQuery.data.dayNumber}` : "—"}
          wide
        >
          {nextMatchdayQuery.isLoading ? (
            <Empty>Spielplan wird geladen …</Empty>
          ) : nextFixtures.length ? (
            <div className="overview-list overview-fixtures">
              {nextFixtures.map((fixture) => (
                <div key={fixture.id} className="overview-list__row overview-fixture-row">
                  <div>
                    <strong>{fixture.players}</strong>
                    <span>{fixture.club} · {formatKickoff(fixture.kickoff)}</span>
                  </div>
                  <b>{fixture.isHome ? "vs" : "@"} {fixture.opponent}</b>
                </div>
              ))}
            </div>
          ) : (
            <Empty>{nextMatchdayQuery.isError ? "Spielplan konnte nicht geladen werden." : "Kein kommender Spieltag gefunden."}</Empty>
          )}
        </OverviewPanel>
      </div>

      {(squadQuery.isError || marketQuery.isError || nextMatchdayQuery.isError) ? (
        <div className="overview-warning"><AlertTriangle size={15} /> Einige Live-Daten konnten nicht vollständig geladen werden. Das Force Update versucht alle Kernbereiche erneut.</div>
      ) : null}
    </div>
  );
}

function Metric({ icon, label, value, hint, tone: valueTone = "neutral" }: {
  icon: ReactNode;
  label: string;
  value: string;
  hint: string;
  tone?: "positive" | "negative" | "neutral";
}) {
  return <article className="overview-metric"><div>{icon}<span>{label}</span></div><strong className={`is-${valueTone}`}>{value}</strong><small>{hint}</small></article>;
}

function OverviewPanel({ title, icon, badge, children, wide = false }: { title: string; icon: ReactNode; badge: string; children: ReactNode; wide?: boolean }) {
  return <section className={`overview-panel${wide ? " overview-panel--wide" : ""}`}><header><div>{icon}<span>{title}</span></div><b>{badge}</b></header>{children}</section>;
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="overview-empty">{children}</div>;
}

function fridayDeadline() {
  const now = new Date();
  const deadline = new Date(now);
  const daysUntilFriday = (5 - now.getDay() + 7) % 7;
  deadline.setDate(now.getDate() + daysUntilFriday);
  deadline.setHours(20, 0, 0, 0);

  if (deadline.getTime() <= now.getTime()) {
    deadline.setDate(deadline.getDate() + 7);
  }

  const diff = Math.max(0, deadline.getTime() - now.getTime());
  const days = Math.floor(diff / 86_400_000);
  const hours = Math.floor((diff % 86_400_000) / 3_600_000);
  const minutes = Math.floor((diff % 3_600_000) / 60_000);

  return {
    label: days > 0 ? `Noch ${days}T ${hours}H` : `Noch ${hours}H ${minutes}M`,
  };
}

function remaining(seconds: number | null) {
  if (seconds == null) return "Ablauf unbekannt";
  if (seconds <= 0) return "läuft ab";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function formatKickoff(value: string | null) {
  if (!value) return "Termin offen";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("de-DE", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function money(value: number | null | undefined) {
  return value == null ? "—" : moneyFormatter.format(value);
}

function compactMoney(value: number | null | undefined) {
  return value == null ? "—" : compactMoneyFormatter.format(value);
}

function signedMoney(value: number | null | undefined) {
  if (value == null) return "—";
  if (value === 0) return "0 €";
  return `${value > 0 ? "+" : ""}${money(value)}`;
}

function tone(value: number | null | undefined): "positive" | "negative" | "neutral" {
  if (value == null || value === 0) return "neutral";
  return value > 0 ? "positive" : "negative";
}

function toneClass(value: number | null | undefined) {
  return `is-${tone(value)}`;
}

function formatRate(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  const percent = Math.abs(value) <= 1 ? value * 100 : value;
  return `${percent.toFixed(1)} %`;
}

function formatTime(value: Date) {
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(value);
}
