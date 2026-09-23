import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, ImageDown, Search, UserPlus, UsersRound } from "lucide-react";
import type { NextFixture, PlayerPosition, SquadPlayer } from "./types";
import { getLeagueNextMatchday } from "./api";
import { getBundledTeamLogo } from "../../lib/team-assets";
import { usePlayerDetail } from "../player-detail/PlayerDetailProvider";
import { PlayerStatus } from "../../components/player-status/PlayerStatus";
import { PositionBadge } from "../../components/position-badge/PositionBadge";
import { MarketDynamicsIndicator } from "../../components/market-dynamics/MarketDynamicsIndicator";
import { useMarketDynamics } from "../analytics/use-market-dynamics";
import { useMvPredictions } from "../analytics/use-mv-predictions";
import { MvPredictionIndicator } from "../../components/mv-prediction/MvPredictionIndicator";
import { PortraitManagerDrawer } from "../assets/PortraitManagerDrawer";
import "./squad.css";

const POSITION_ORDER: Record<PlayerPosition, number> = {
  GOALKEEPER: 1,
  DEFENDER: 2,
  MIDFIELDER: 3,
  FORWARD: 4,
  UNKNOWN: 5,
};

const POSITION_FILTERS: Array<{ value: "ALL" | PlayerPosition; label: string }> = [
  { value: "ALL", label: "Alle" },
  { value: "GOALKEEPER", label: "TW" },
  { value: "DEFENDER", label: "ABW" },
  { value: "MIDFIELDER", label: "MF" },
  { value: "FORWARD", label: "ST" },
];

function compareNullableNumbers(a: number | null, b: number | null) {
  if (a == null && b == null) return 0;
  if (a == null) return -1;
  if (b == null) return 1;
  return a - b;
}

export function SquadPage({ players, leagueId }: { players: SquadPlayer[]; leagueId: string }) {
  const { openPlayerDetail } = usePlayerDetail();
  const [sorting, setSorting] = useState<SortingState>([{ id: "position", desc: false }]);
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState<"ALL" | PlayerPosition>("ALL");
  const [portraitManagerOpen, setPortraitManagerOpen] = useState(false);
  const dynamicsInputs = useMemo(() => players.map((player) => ({ id: player.id, marketValue: player.marketValue, marketValueChange24h: player.marketValueChange24h })), [players]);
  const dynamicsByPlayer = useMarketDynamics(dynamicsInputs);
  const predictionInputs = useMemo(() => players.map((player) => ({ playerId: player.id, marketValue: player.marketValue, marketValueChange24h: player.marketValueChange24h })), [players]);
  const predictionQuery = useMvPredictions(leagueId, predictionInputs);
  const fixturesQuery = useQuery({ queryKey: ["fixtures", "next", leagueId], queryFn: () => getLeagueNextMatchday(leagueId), staleTime: 10 * 60 * 1000 });

  const columns = useMemo<ColumnDef<SquadPlayer>[]>(() => [
    {
      accessorKey: "name",
      header: "Spieler",
      cell: ({ row }) => {
        const teamLogo = getBundledTeamLogo(row.original.teamId) ?? row.original.teamLogoDataUrl;

        return (
          <div className="player-cell">
            <div className="player-cell__avatar" aria-hidden>
              {row.original.portraitDataUrl ? (
                <img src={row.original.portraitDataUrl} alt="" />
              ) : (
                <span>{row.original.name.slice(0, 1).toUpperCase()}</span>
              )}
            </div>
            <div className="player-cell__identity">
              <div className="player-cell__identity-header">
                {teamLogo ? (
                  <img
                    className="player-cell__team-logo"
                    src={teamLogo}
                    alt=""
                    aria-hidden
                  />
                ) : null}
                <span className="player-cell__name-block">
                  {row.original.firstName ? <span className="player-cell__first-name">{row.original.firstName}</span> : null}
                  <strong>{row.original.name}</strong>
                </span>
                <PlayerStatus
                  status={row.original.status}
                  statusList={row.original.statusList}
                  statusText={row.original.statusText}
                  playerId={row.original.id}
                  leagueId={leagueId}
                />
              </div>
            </div>
          </div>
        );
      },
    },
    {
      id: "position",
      accessorFn: (player) => POSITION_ORDER[player.position],
      header: "Pos.",
      cell: ({ row }) => <PositionBadge position={row.original.position} />,
    },
    {
      accessorKey: "marketValue",
      header: "Marktwert",
      sortingFn: (a, b) => compareNullableNumbers(a.original.marketValue, b.original.marketValue),
      cell: ({ row }) => <NumericCell value={row.original.marketValue} format="currency" />,
    },
    {
      accessorKey: "marketValueChange24h",
      header: "24H",
      sortingFn: (a, b) => compareNullableNumbers(a.original.marketValueChange24h, b.original.marketValueChange24h),
      cell: ({ row }) => <SignedValue value={row.original.marketValueChange24h} />,
    },
    {
      id: "prediction",
      header: "22U",
      enableSorting: false,
      cell: ({ row }) => <MvPredictionIndicator prediction={predictionQuery.byPlayer.get(row.original.id)} quality={predictionQuery.data?.quality} />,
    },
    {
      id: "dynamics",
      header: "Dynamik",
      enableSorting: false,
      cell: ({ row }) => <MarketDynamicsIndicator dynamics={dynamicsByPlayer.get(row.original.id)} />,
    },
    {
      accessorKey: "marketValueGainLoss",
      header: "MW +/-",
      sortingFn: (a, b) => compareNullableNumbers(a.original.marketValueGainLoss, b.original.marketValueGainLoss),
      cell: ({ row }) => <SignedValue value={row.original.marketValueGainLoss} />,
    },
    {
      id: "opponent",
      accessorFn: (player) => opponentLabel(player.teamId, fixturesQuery.data?.fixtures ?? []),
      header: fixturesQuery.data?.dayNumber ? `Gegner ST${fixturesQuery.data.dayNumber}` : "Nächster Gegner",
      cell: ({ row }) => <span className="table-number">{opponentLabel(row.original.teamId, fixturesQuery.data?.fixtures ?? [])}</span>,
    },
    {
      accessorKey: "pointsTotal",
      header: "Punkte",
      sortingFn: (a, b) => compareNullableNumbers(a.original.pointsTotal, b.original.pointsTotal),
      cell: ({ row }) => <NumericCell value={row.original.pointsTotal} />,
    },
    {
      accessorKey: "averagePoints",
      header: "Ø Pkt.",
      sortingFn: (a, b) => compareNullableNumbers(a.original.averagePoints, b.original.averagePoints),
      cell: ({ row }) => <NumericCell value={row.original.averagePoints} decimals={1} />,
    },
    {
      id: "pointsPerMillion",
      accessorFn: (player) => pointsPerMillion(player.averagePoints, player.marketValue) ?? undefined,
      header: "Pkt/Mio",
      sortingFn: "basic", sortUndefined: "last",
      cell: ({ row }) => <NumericCell value={pointsPerMillion(row.original.averagePoints, row.original.marketValue)} decimals={1} />,
    },
  ], [dynamicsByPlayer, fixturesQuery.data?.dayNumber, fixturesQuery.data?.fixtures, leagueId, predictionQuery.byPlayer, predictionQuery.data?.quality]);

  const filteredPlayers = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("de-DE");
    return players.filter((player) => {
      const matchesPosition = position === "ALL" || player.position === position;
      const matchesQuery = !needle || player.name.toLocaleLowerCase("de-DE").includes(needle);
      return matchesPosition && matchesQuery;
    });
  }, [players, position, query]);

  const freeSlots = Math.max(18 - players.length, 0);
  const showRosterSlots = position === "ALL" && query.trim() === "";

  const table = useReactTable({
    data: filteredPlayers,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const totals = useMemo(() => {
    const knownMarketValues = players.map((player) => player.marketValue).filter(isNumber);
    const knownChanges = players.map((player) => player.marketValueChange24h).filter(isNumber);
    const knownAverages = players.map((player) => player.averagePoints).filter(isNumber);

    return {
      marketValue: knownMarketValues.reduce((sum, value) => sum + value, 0),
      change24h: knownChanges.reduce((sum, value) => sum + value, 0),
      averagePoints:
        knownAverages.length > 0
          ? knownAverages.reduce((sum, value) => sum + value, 0) / knownAverages.length
          : null,
    };
  }, [players]);

  return (
    <section className="squad-page">
      <header className="squad-page__header">
        <div>
          <h1 className="squad-page__title">KADER</h1>
          <p className="squad-page__subtitle">Dein aktueller Kader als kompakte Arbeitsansicht.</p>
        </div>
        <div className="squad-page__header-actions">
          <button type="button" className="squad-assets-trigger" onClick={() => setPortraitManagerOpen(true)}><ImageDown size={15}/><span>Spielerbilder</span></button>
          <div className={`squad-page__count ${players.length >= 18 ? "is-full" : ""}`}>
            <UsersRound size={16} />
            <span><strong>{players.length} / 18</strong> Spieler</span>
            <small>{Math.max(18 - players.length, 0)} frei</small>
          </div>
        </div>
      </header>

      <div className="squad-summary">
        <SummaryMetric label="Kaderwert" value={formatCurrency(totals.marketValue)} />
        <SummaryMetric label="24H Bewegung" value={formatSignedCurrency(totals.change24h)} tone={toneFor(totals.change24h)} />
        <SummaryMetric label="Ø Punkte" value={totals.averagePoints == null ? "—" : formatNumber(totals.averagePoints, 1)} />
      </div>

      <div className="squad-toolbar">
        <div className="position-filter" role="group" aria-label="Nach Position filtern">
          {POSITION_FILTERS.map((filter) => (
            <button
              type="button"
              key={filter.value}
              className={position === filter.value ? "is-active" : ""}
              onClick={() => setPosition(filter.value)}
            >
              {filter.label}
            </button>
          ))}
        </div>

        <label className="squad-search">
          <Search size={15} aria-hidden />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Spieler suchen …"
            aria-label="Spieler suchen"
          />
        </label>
      </div>

      <div className="squad-table-frame">
        <table className="squad-table">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const sortable = header.column.getCanSort();
                  const direction = header.column.getIsSorted();
                  return (
                    <th key={header.id}>
                      <button
                        type="button"
                        className="table-sort"
                        disabled={!sortable}
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {sortable ? <SortIcon direction={direction} /> : null}
                      </button>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className="squad-player-row"
                tabIndex={0}
                onClick={() => openPlayerDetail({ playerId: row.original.id, leagueId, context: { source: "squad", label: "Dein Kader" } })}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    openPlayerDetail({ playerId: row.original.id, leagueId, context: { source: "squad", label: "Dein Kader" } });
                  }
                }}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            ))}

            {showRosterSlots
              ? Array.from({ length: freeSlots }, (_, index) => (
                  <tr className="squad-slot-row" key={`free-slot-${index}`}>
                    <td colSpan={columns.length}>
                      <div className="squad-slot">
                        <UserPlus size={14} aria-hidden />
                        <span>Freier Kaderplatz</span>
                        <small>Slot {players.length + index + 1} / 18</small>
                      </div>
                    </td>
                  </tr>
                ))
              : null}
          </tbody>
        </table>

        {filteredPlayers.length === 0 && !showRosterSlots ? (
          <div className="squad-empty">Keine Spieler passen zu deinem Filter.</div>
        ) : null}
      </div>
      {portraitManagerOpen ? <PortraitManagerDrawer leagueId={leagueId} onClose={() => setPortraitManagerOpen(false)} /> : null}
    </section>
  );
}

function SummaryMetric({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "positive" | "negative" | "neutral" }) {
  return (
    <div className="squad-summary__item">
      <span>{label}</span>
      <strong className={`tone-${tone}`}>{value}</strong>
    </div>
  );
}

function NumericCell({ value, format, decimals = 0 }: { value: number | null; format?: "currency"; decimals?: number }) {
  if (value == null) return <span className="table-null">—</span>;
  return <span className="table-number">{format === "currency" ? formatCurrency(value) : formatNumber(value, decimals)}</span>;
}

function SignedValue({ value }: { value: number | null }) {
  if (value == null) return <span className="table-null">—</span>;
  return <span className={`table-number tone-${toneFor(value)}`}>{formatSignedCurrency(value)}</span>;
}

function SortIcon({ direction }: { direction: false | "asc" | "desc" }) {
  if (direction === "asc") return <ArrowUp size={13} />;
  if (direction === "desc") return <ArrowDown size={13} />;
  return <ArrowUpDown size={13} className="table-sort__idle" />;
}

function toneFor(value: number) {
  if (value > 0) return "positive" as const;
  if (value < 0) return "negative" as const;
  return "neutral" as const;
}

function isNumber(value: number | null): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("de-DE", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatSignedCurrency(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatCompactCurrency(value)}`;
}

function formatCompactCurrency(value: number) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toLocaleString("de-DE", { maximumFractionDigits: 2 })} Mio. €`;
  if (abs >= 1_000) return `${Math.round(value / 1_000).toLocaleString("de-DE")} Tsd. €`;
  return `${value.toLocaleString("de-DE")} €`;
}

function formatNumber(value: number, decimals = 0) {
  return value.toLocaleString("de-DE", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function pointsPerMillion(averagePoints: number | null, marketValue: number | null) {
  if (averagePoints == null || marketValue == null || marketValue <= 0) return null;
  return averagePoints / (marketValue / 1_000_000);
}

function opponentLabel(teamId: string | null, fixtures: NextFixture[]) {
  if (!teamId) return "—";
  const fixture = fixtures.find((item) => item.homeTeamId === teamId || item.awayTeamId === teamId);
  if (!fixture) return "—";
  const home = fixture.homeTeamId === teamId;
  const opponent = home ? fixture.awayTeamName : fixture.homeTeamName;
  return `${home ? "vs." : "@"} ${opponent}`;
}
