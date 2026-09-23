import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, BarChart3, Calculator, CheckCircle2, Flame, Gavel, Search, ShoppingBag, Sparkles, Store, TimerReset, Trash2, WalletCards, X, XCircle } from "lucide-react";
import { getBundledTeamLogo } from "@/lib/team-assets";
import { usePlayerDetail } from "@/features/player-detail/PlayerDetailProvider";
import { PlayerStatus } from "@/components/player-status/PlayerStatus";
import { PositionBadge } from "@/components/position-badge/PositionBadge";
import { MarketDynamicsIndicator } from "@/components/market-dynamics/MarketDynamicsIndicator";
import { useMarketDynamics } from "@/features/analytics/use-market-dynamics";
import { getMarketValueHistories } from "@/features/analytics/api";
import type { MarketValuePoint } from "@/features/player-detail/types";
import { useMvPredictions } from "@/features/analytics/use-mv-predictions";
import { estimateFairValue } from "@/features/analytics/decision-intelligence";
import { useFairValueReference } from "@/features/analytics/use-decision-intelligence";
import { MvPredictionIndicator } from "@/components/mv-prediction/MvPredictionIndicator";
import { getLeagueAccountContext } from "@/features/account/api";
import { getLeagueNextMatchday, getLeagueSquad } from "@/features/squad/api";
import type { NextFixture, PlayerPosition } from "@/features/squad/types";
import { placeMarketOffer, withdrawMarketOffer } from "./api";
import type { MarketEntry } from "./types";
import { MarketSalesDrawer } from "./MarketSalesDrawer";
import { BudgetPlannerDrawer } from "./BudgetPlannerDrawer";
import { TradingAnalysisDrawer } from "./TradingAnalysisDrawer";
import { LeaguePriceIndicator } from "./LeaguePriceIndicator";
import { getLeaguePurchasePriceStats } from "./league-price-api";
import { bidReasonLabel, evaluateBidEligibility, resolveBalanceAfterActiveBids } from "./bid-eligibility";
import { DEFAULT_SQUAD_LIMIT, formatCreditLimitLabel } from "@/lib/kickbase-rules";
import "./market.css";

const POSITION_ORDER: Record<PlayerPosition, number> = { GOALKEEPER: 1, DEFENDER: 2, MIDFIELDER: 3, FORWARD: 4, UNKNOWN: 5 };
const POSITION_LABEL: Record<PlayerPosition, string> = { GOALKEEPER: "TW", DEFENDER: "ABW", MIDFIELDER: "MF", FORWARD: "ST", UNKNOWN: "—" };
const POSITION_FILTERS: Array<{ value: "ALL" | PlayerPosition; label: string }> = [
  { value: "ALL", label: "Alle" }, { value: "GOALKEEPER", label: "TW" }, { value: "DEFENDER", label: "ABW" }, { value: "MIDFIELDER", label: "MF" }, { value: "FORWARD", label: "ST" },
];

function compareNullableNumbers(a: number | null, b: number | null) {
  if (a == null && b == null) return 0;
  if (a == null) return -1;
  if (b == null) return 1;
  return a - b;
}

export function MarketPage({ entries, leagueId }: { entries: MarketEntry[]; leagueId: string }) {
  const { openPlayerDetail } = usePlayerDetail();
  const queryClient = useQueryClient();
  const [sorting, setSorting] = useState<SortingState>([{ id: "expiresInSeconds", desc: false }]);
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState<"ALL" | PlayerPosition>("ALL");
  const [signalFilter, setSignalFilter] = useState<"ALL" | "HOT" | "VALUE" | "BIDS">("ALL");
  const [actionEntry, setActionEntry] = useState<MarketEntry | null>(null);
  const [salesOpen, setSalesOpen] = useState(false);
  const [salesInitialPlayerId, setSalesInitialPlayerId] = useState<string | null>(null);
  const [budgetPlannerOpen, setBudgetPlannerOpen] = useState(false);
  const [tradingOpen, setTradingOpen] = useState(false);
  const fetchedAt = useMemo(() => Date.now(), [entries]);
  const [now, setNow] = useState(() => Date.now());
  const squadQuery = useQuery({ queryKey: ["squad", leagueId], queryFn: () => getLeagueSquad(leagueId) });
  const accountQuery = useQuery({ queryKey: ["account", "league", leagueId], queryFn: () => getLeagueAccountContext(leagueId) });
  const ownPlayerIds = useMemo(() => new Set((squadQuery.data?.players ?? []).map((player) => player.id)), [squadQuery.data]);
  const fixturesQuery = useQuery({ queryKey: ["fixtures", "next", leagueId], queryFn: () => getLeagueNextMatchday(leagueId), staleTime: 10 * 60 * 1000 });
  const fairReferenceQuery = useFairValueReference();

  // /market does not reliably contain tfhmvt for every listing. We already keep one
  // daily 22:00 market-value snapshot per player, so use the latest real daily step
  // as a transparent fallback for the 24H column and all analyses that depend on it.
  const historyPlayerIds = useMemo(() => [...new Set(entries.map((entry) => entry.playerId))].sort(), [entries]);
  const historiesQuery = useQuery({
    queryKey: ["analytics", "market-value-histories", historyPlayerIds],
    queryFn: () => getMarketValueHistories(historyPlayerIds),
    enabled: historyPlayerIds.length > 0,
    staleTime: 5 * 60 * 1000,
  });
  const effectiveEntries = useMemo(() => entries.map((entry) => {
    const fallback = latestDailyMarketValueDelta(historiesQuery.data?.[entry.playerId] ?? []);
    if (fallback == null) return entry;

    // Kickbase /market occasionally reports tfhmvt=0 or omits it while the
    // persisted daily 22h history contains a real move. Prefer the real daily
    // snapshot in that case, but keep a genuine API value when both agree.
    const apiValue = entry.marketValueChange24h;
    if (apiValue == null || (apiValue === 0 && fallback !== 0)) {
      return { ...entry, marketValueChange24h: fallback };
    }
    return entry;
  }), [entries, historiesQuery.data]);

  const fairValueByPlayer = useMemo(() => {
    const map = new Map<string, ReturnType<typeof estimateFairValue>>();
    const reference = fairReferenceQuery.data?.players ?? [];
    for (const entry of effectiveEntries) {
      map.set(entry.playerId, estimateFairValue(entry.averagePoints, entry.marketValue, entry.position, entry.playerId, reference, entry.pointsTotal));
    }
    return map;
  }, [effectiveEntries, fairReferenceQuery.data?.players]);

  const dynamicsInputs = useMemo(() => effectiveEntries.map((entry) => ({ id: entry.playerId, marketValue: entry.marketValue, marketValueChange24h: entry.marketValueChange24h })), [effectiveEntries]);
  const dynamicsByPlayer = useMarketDynamics(dynamicsInputs);
  const predictionInputs = useMemo(() => effectiveEntries.map((entry) => ({ playerId: entry.playerId, marketValue: entry.marketValue, marketValueChange24h: entry.marketValueChange24h })), [effectiveEntries]);
  const predictionQuery = useMvPredictions(leagueId, predictionInputs);
  const leaguePriceInputs = useMemo(() => effectiveEntries.map((entry) => ({
    playerId: entry.playerId,
    marketValue: entry.marketValue,
  })), [effectiveEntries]);
  const leaguePriceQuery = useQuery({
    queryKey: ["analytics", "league-purchase-prices", leagueId, leaguePriceInputs],
    queryFn: () => getLeaguePurchasePriceStats(leagueId, leaguePriceInputs),
    enabled: leagueId.length > 0 && leaguePriceInputs.length > 0,
    staleTime: 5 * 60 * 1000,
  });
  const leaguePriceByPlayer = useMemo(() => new Map((leaguePriceQuery.data ?? []).map((stat) => [stat.playerId, stat])), [leaguePriceQuery.data]);

  const columns = useMemo<ColumnDef<MarketEntry>[]>(() => [
    {
      accessorKey: "name", header: "Spieler",
      cell: ({ row }) => {
        const logo = getBundledTeamLogo(row.original.teamId);
        return <div className="market-player">
          <span className="market-player__portrait">{row.original.portraitDataUrl ? <img src={row.original.portraitDataUrl} alt="" /> : row.original.name.slice(0, 1).toUpperCase()}</span>
          {logo ? <img className="market-player__team" src={logo} alt="" aria-hidden /> : null}
          <span className="market-player__name-block">
            {row.original.firstName ? <span className="market-player__first-name">{row.original.firstName}</span> : null}
            <strong>{row.original.name}</strong>
          </span>
          <PlayerStatus status={row.original.status} statusList={row.original.statusList} statusText={row.original.statusText} playerId={row.original.playerId} leagueId={leagueId} />
          {row.original.isNew ? <span className="market-player__new">NEU</span> : null}
        </div>;
      },
    },
    {
      id: "position", accessorFn: (entry) => POSITION_ORDER[entry.position], header: "Pos.",
      cell: ({ row }) => <PositionBadge position={row.original.position} />,
    },
    {
      id: "seller", accessorFn: (entry) => entry.isKickbaseSeller ? "Kickbase" : entry.sellerName ?? entry.sellerId ?? "Manager", header: "Anbieter",
      cell: ({ row }) => {
        const ownListing = ownPlayerIds.has(row.original.playerId);
        return <span className={ownListing ? "market-seller market-seller--self" : row.original.isKickbaseSeller ? "market-seller market-seller--kickbase" : "market-seller"}>{ownListing ? "Du" : row.original.isKickbaseSeller ? "Kickbase" : row.original.sellerName ?? "Manager"}</span>;
      },
    },
    { accessorKey: "marketValue", header: "Marktwert", sortingFn: (a,b)=>compareNullableNumbers(a.original.marketValue,b.original.marketValue), cell: ({row}) => <MarketValueCell value={row.original.marketValue} fair={fairValueByPlayer.get(row.original.playerId)} loading={fairReferenceQuery.isLoading}/> },
    { accessorKey: "marketValueChange24h", header: "24H", sortingFn: (a,b)=>compareNullableNumbers(a.original.marketValueChange24h,b.original.marketValueChange24h), cell: ({row}) => <SignedMoney value={row.original.marketValueChange24h}/> },
    { id: "trend", header: "Trend", enableSorting: false, cell: ({row}) => <div className="market-trend-cell"><MvPredictionIndicator prediction={predictionQuery.byPlayer.get(row.original.playerId)} quality={predictionQuery.data?.quality} /><MarketDynamicsIndicator dynamics={dynamicsByPlayer.get(row.original.playerId)} /></div> },
    { accessorKey: "price", header: "Preis", sortingFn: (a,b)=>compareNullableNumbers(a.original.price,b.original.price), cell: ({row}) => <Money value={row.original.price} strong/> },
    {
      id: "leaguePrice",
      accessorFn: (entry) => leaguePriceByPlayer.get(entry.playerId)?.typicalPrice ?? undefined,
      header: "Typ. Preis",
      sortingFn: "basic",
      sortUndefined: "last",
      cell: ({row}) => <LeaguePriceIndicator stat={leaguePriceByPlayer.get(row.original.playerId)} loading={leaguePriceQuery.isLoading} />,
    },
    { id: "opponent", accessorFn: (entry) => opponentLabel(entry.teamId, fixturesQuery.data?.fixtures ?? []), header: fixturesQuery.data?.dayNumber ? `Gegner ST${fixturesQuery.data.dayNumber}` : "Gegner", cell: ({row}) => <span className="market-empty">{opponentLabel(row.original.teamId, fixturesQuery.data?.fixtures ?? [])}</span> },
    { id: "points", accessorFn: (entry) => entry.pointsTotal ?? undefined, header: "Punkte", sortingFn: "basic", sortUndefined: "last", cell: ({row}) => <MarketPointsCell total={row.original.pointsTotal} average={row.original.averagePoints} /> },
    { id: "pointsPerMillion", accessorFn: (entry) => pointsPerMillion(entry.averagePoints, entry.marketValue) ?? undefined, header: "Pkt/Mio", sortingFn: "basic", sortUndefined: "last", cell: ({row}) => <NumberValue value={pointsPerMillion(row.original.averagePoints, row.original.marketValue)} decimals={1}/> },
    { accessorKey: "ownOffer", header: "Mein Gebot", sortingFn: (a,b)=>compareNullableNumbers(a.original.ownOffer,b.original.ownOffer), cell: ({row}) => row.original.ownOffer == null ? <span className="market-empty">—</span> : <span className="market-own-offer">{formatCurrency(row.original.ownOffer)}</span> },
    { id: "expiresInSeconds", accessorFn: (entry) => entry.expiresInSeconds ?? undefined, header: "Restzeit", sortingFn: "basic", sortUndefined: "last", cell: ({row}) => <Expiry seconds={row.original.expiresInSeconds} elapsedSeconds={Math.floor((now - fetchedAt) / 1000)}/> },
    {
      id: "actions", header: "", enableSorting: false,
      cell: ({ row }) => {
        const ownListing = ownPlayerIds.has(row.original.playerId);
        if (ownListing) {
          return <button type="button" className="market-action-trigger is-sale" onClick={(event) => { event.stopPropagation(); setSalesInitialPlayerId(row.original.playerId); setSalesOpen(true); }} aria-label={`${row.original.name}: Verkauf verwalten`}>
            <Store size={15} /><span>Verkauf</span>
          </button>;
        }
        return <button type="button" className={`market-action-trigger${row.original.ownOffer != null ? " has-offer" : ""}`} onClick={(event) => { event.stopPropagation(); setActionEntry(row.original); }} aria-label={`${row.original.name}: Gebot verwalten`}>
          <Gavel size={15} /><span>{row.original.ownOffer != null ? "Ändern" : "Bieten"}</span>
        </button>;
      },
    },
  ], [dynamicsByPlayer, fairReferenceQuery.isLoading, fairValueByPlayer, fetchedAt, fixturesQuery.data?.dayNumber, fixturesQuery.data?.fixtures, leagueId, leaguePriceByPlayer, leaguePriceQuery.isLoading, now, ownPlayerIds, predictionQuery.byPlayer, predictionQuery.data?.quality]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const efficientPlayerIds = useMemo(() => {
    const ids = new Set<string>();
    for (const entry of effectiveEntries) {
      if (isEfficientMarketEntry(entry)) ids.add(entry.playerId);
    }
    return ids;
  }, [effectiveEntries]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("de-DE");
    return effectiveEntries.filter((entry) => {
      if (position !== "ALL" && entry.position !== position) return false;
      if (needle && !`${entry.firstName ?? ""} ${entry.name ?? ""} ${entry.sellerName ?? ""}`.toLocaleLowerCase("de-DE").includes(needle)) return false;
      if (signalFilter === "BIDS") return entry.ownOffer != null;
      if (signalFilter === "HOT") {
        const code = dynamicsByPlayer.get(entry.playerId)?.code;
        return code === "TURNING_UP" || code === "ACCELERATING_UP" || code === "STABLE_UP";
      }
      if (signalFilter === "VALUE") return efficientPlayerIds.has(entry.playerId);
      return true;
    });
  }, [dynamicsByPlayer, effectiveEntries, efficientPlayerIds, position, query, signalFilter]);

  const table = useReactTable({ data: filtered, columns, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel() });

  const stats = useMemo(() => {
    const ownOffers = entries.filter((entry) => entry.ownOffer != null).length;
    const endingSoon = entries.filter((entry) => entry.expiresInSeconds != null && entry.expiresInSeconds <= 3600).length;
    const hot = effectiveEntries.filter((entry) => {
      const code = dynamicsByPlayer.get(entry.playerId)?.code;
      return code === "TURNING_UP" || code === "ACCELERATING_UP" || code === "STABLE_UP";
    }).length;
    const value = efficientPlayerIds.size;
    return { ownOffers, endingSoon, hot, value };
  }, [dynamicsByPlayer, efficientPlayerIds, effectiveEntries, entries]);

  const displayedBalanceAfterBids = resolveBalanceAfterActiveBids(
    accountQuery.data?.budget ?? null,
    accountQuery.data?.budgetAfterActiveBids ?? null,
    entries.reduce((sum, entry) => sum + Math.max(0, entry.ownOffer ?? 0), 0),
  );

  const refreshMarket = async () => {
    await queryClient.invalidateQueries({ queryKey: ["market", leagueId] });
    await queryClient.invalidateQueries({ queryKey: ["account", "league", leagueId] });
  };

  return <section className="market-page">
    <header className="market-page__header"><div><h1 className="market-page__title">MARKT</h1><p className="market-page__subtitle">Live-Transfermarkt deiner Liga.</p></div></header>

    <div className="market-summary">
      <Summary icon={<ShoppingBag size={16}/>} label="Auf dem Markt" value={`${entries.length} Spieler`} />
      <Summary icon={<WalletCards size={16}/>} label="Nach Geboten" value={displayedBalanceAfterBids == null ? "—" : formatCurrency(displayedBalanceAfterBids)} tone={toneFor(displayedBalanceAfterBids ?? 0)} />
      <Summary icon={<TimerReset size={16}/>} label="Aktiv" value={`${stats.ownOffers} Gebote`} subvalue={stats.endingSoon ? `${stats.endingSoon} laufen < 1h aus` : undefined} />
    </div>

    <div className="market-signal-filter" role="group" aria-label="Marktsignale filtern">
      <button type="button" className={signalFilter === "ALL" ? "is-active" : ""} onClick={() => setSignalFilter("ALL")}>Alle</button>
      <button type="button" className={signalFilter === "HOT" ? "is-active" : ""} onClick={() => setSignalFilter("HOT")} title="Wende aufwärts oder stabil/beschleunigt steigende MW-Dynamik"><Flame size={13}/>Hot <strong>{stats.hot}</strong></button>
      <button type="button" className={signalFilter === "VALUE" ? "is-active" : ""} onClick={() => setSignalFilter("VALUE")} title="Mindestens 70 Ø Punkte und 8,0 Punkte pro Mio."><Sparkles size={13}/>Effizient <strong>{stats.value}</strong></button>
      <button type="button" className={signalFilter === "BIDS" ? "is-active" : ""} onClick={() => setSignalFilter("BIDS")}><Gavel size={13}/>Meine Gebote <strong>{stats.ownOffers}</strong></button>
    </div>

    <div className="market-toolbar">
      <div className="market-position-filter" role="group" aria-label="Nach Position filtern">{POSITION_FILTERS.map((filter) => <button type="button" key={filter.value} className={position===filter.value?"is-active":""} onClick={()=>setPosition(filter.value)}>{filter.label}</button>)}</div>
      <div className="market-toolbar__right">
        <button type="button" className="market-budget-trigger" onClick={() => setBudgetPlannerOpen(true)}>
          <Calculator size={16}/><span>Budgetplaner</span>
        </button>
        <button type="button" className="market-trading-trigger" onClick={() => setTradingOpen(true)}>
          <BarChart3 size={16}/><span>Trading</span>
        </button>
        <button type="button" className="market-sales-trigger" onClick={() => { setSalesInitialPlayerId(null); setSalesOpen(true); }}>
          <Store size={16}/><span>Meine Verkäufe</span>{ownPlayerIds.size ? <strong>{entries.filter((entry) => ownPlayerIds.has(entry.playerId)).length}</strong> : null}
        </button>
        <label className="market-search"><Search size={16}/><input value={query} onChange={(event)=>setQuery(event.target.value)} placeholder="Spieler oder Anbieter suchen …" aria-label="Markt durchsuchen"/></label>
      </div>
    </div>

    <div className="market-table-frame"><div className="market-table-scroll"><table className="market-table">
      <thead>{table.getHeaderGroups().map((group)=><tr key={group.id}>{group.headers.map((header)=>{const sortable=header.column.getCanSort(); const direction=header.column.getIsSorted(); return <th key={header.id}><button type="button" className="market-table-sort" disabled={!sortable} onClick={header.column.getToggleSortingHandler()}>{flexRender(header.column.columnDef.header,header.getContext())}{sortable?<SortIcon direction={direction}/>:null}</button></th>})}</tr>)}</thead>
      <tbody>{table.getRowModel().rows.length === 0 ? <tr><td className="market-table-empty" colSpan={columns.length}>Keine Spieler für diesen Filter.</td></tr> : table.getRowModel().rows.map((row)=><tr key={row.id} className="market-row" tabIndex={0} onClick={()=>openPlayerDetail({playerId:row.original.playerId,leagueId,context:{source:"market",label:"Transfermarkt"}})} onKeyDown={(event)=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();openPlayerDetail({playerId:row.original.playerId,leagueId,context:{source:"market",label:"Transfermarkt"}})}}}>{row.getVisibleCells().map((cell)=><td key={cell.id}>{flexRender(cell.column.columnDef.cell,cell.getContext())}</td>)}</tr>)}</tbody>
    </table></div></div>

    {actionEntry ? <MarketActionDrawer entry={actionEntry} entries={entries} leagueId={leagueId} onClose={()=>setActionEntry(null)} onChanged={refreshMarket} /> : null}
    {salesOpen ? <MarketSalesDrawer entries={entries} leagueId={leagueId} initialPlayerId={salesInitialPlayerId} onClose={() => setSalesOpen(false)} onChanged={refreshMarket} /> : null}
    {budgetPlannerOpen ? <BudgetPlannerDrawer entries={entries} squadPlayers={squadQuery.data?.players ?? []} leagueId={leagueId} onClose={() => setBudgetPlannerOpen(false)} /> : null}
    {tradingOpen ? <TradingAnalysisDrawer leagueId={leagueId} onClose={() => setTradingOpen(false)} /> : null}
  </section>;
}

function MarketActionDrawer({ entry, entries, leagueId, onClose, onChanged }: { entry: MarketEntry; entries: MarketEntry[]; leagueId: string; onClose: () => void; onChanged: () => Promise<void> }) {
  const [priceText, setPriceText] = useState(() => String(entry.ownOffer ?? entry.price ?? entry.marketValue ?? ""));
  const [message, setMessage] = useState<string | null>(null);
  const accountQuery = useQuery({ queryKey: ["account", "league", leagueId], queryFn: () => getLeagueAccountContext(leagueId), staleTime: 0 });
  const squadQuery = useQuery({ queryKey: ["squad", leagueId], queryFn: () => getLeagueSquad(leagueId), staleTime: 0 });
  const logo = getBundledTeamLogo(entry.teamId);
  const price = parseEuroInput(priceText);
  const squadValue = (squadQuery.data?.players ?? []).reduce((sum, player) => sum + Math.max(0, player.marketValue ?? 0), 0);
  const visibleActiveBidTotal = entries.reduce((sum, marketEntry) => sum + Math.max(0, marketEntry.ownOffer ?? 0), 0);
  const balanceAfterActiveBids = resolveBalanceAfterActiveBids(
    accountQuery.data?.budget ?? null,
    accountQuery.data?.budgetAfterActiveBids ?? null,
    visibleActiveBidTotal,
  );
  const eligibility = evaluateBidEligibility({
    bid: price,
    marketValue: entry.marketValue,
    squadValue,
    balanceAfterActiveBids,
    existingBid: entry.ownOffer,
    squadSize: accountQuery.data?.squadSize ?? squadQuery.data?.players.length ?? null,
    squadLimit: accountQuery.data?.squadLimit ?? DEFAULT_SQUAD_LIMIT,
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const offerMutation = useMutation({
    mutationFn: async () => {
      const [freshAccount, freshSquad] = await Promise.all([accountQuery.refetch(), squadQuery.refetch()]);
      const freshSquadValue = (freshSquad.data?.players ?? []).reduce((sum, player) => sum + Math.max(0, player.marketValue ?? 0), 0);
      const freshBalanceAfterActiveBids = resolveBalanceAfterActiveBids(
        freshAccount.data?.budget ?? null,
        freshAccount.data?.budgetAfterActiveBids ?? null,
        visibleActiveBidTotal,
      );
      const freshEligibility = evaluateBidEligibility({
        bid: price,
        marketValue: entry.marketValue,
        squadValue: freshSquadValue,
        balanceAfterActiveBids: freshBalanceAfterActiveBids,
        existingBid: entry.ownOffer,
        squadSize: freshAccount.data?.squadSize ?? freshSquad.data?.players.length ?? null,
        squadLimit: freshAccount.data?.squadLimit ?? DEFAULT_SQUAD_LIMIT,
      });
      if (!freshEligibility.allowed) {
        throw new Error(freshEligibility.reasons.map(bidReasonLabel).join(" "));
      }
      return placeMarketOffer(leagueId, entry.playerId, price!);
    },
    onSuccess: async () => { setMessage(entry.ownOffer != null ? "Gebot aktualisiert." : "Gebot abgegeben."); await onChanged(); window.setTimeout(onClose, 550); },
    onError: (error) => setMessage(errorMessage(error)),
  });
  const withdrawMutation = useMutation({
    mutationFn: () => withdrawMarketOffer(leagueId, entry.playerId, entry.ownOfferId!),
    onSuccess: async () => { setMessage("Gebot zurückgezogen."); await onChanged(); window.setTimeout(onClose, 550); },
    onError: (error) => setMessage(errorMessage(error)),
  });
  const busy = offerMutation.isPending || withdrawMutation.isPending;
  const validPrice = price != null && price > 0;
  const canSubmit = validPrice && eligibility.allowed && !accountQuery.isFetching && !squadQuery.isFetching;

  return <div className="market-action-layer" role="presentation" onMouseDown={(event)=>{if(event.currentTarget===event.target)onClose()}}>
    <aside className="market-action-drawer" role="dialog" aria-modal="true" aria-label={`Gebot für ${entry.name}`}>
      <header className="market-action-drawer__header">
        <div className="market-action-player">
          <span className="market-action-player__portrait">{entry.portraitDataUrl ? <img src={entry.portraitDataUrl} alt=""/> : entry.name.slice(0,1)}</span>
          <div><div className="market-action-player__name">{logo?<img src={logo} alt="" aria-hidden/>:null}<strong>{entry.name}</strong><PlayerStatus status={entry.status} statusList={entry.statusList} statusText={entry.statusText} compact={false} playerId={entry.playerId} leagueId={leagueId}/></div><span>{POSITION_LABEL[entry.position]} · {entry.isKickbaseSeller ? "Kickbase" : entry.sellerName ?? "Manager"}</span></div>
        </div>
        <button type="button" className="market-action-close" onClick={onClose} aria-label="Schließen"><X size={19}/></button>
      </header>

      <div className="market-action-stats">
        <ActionStat label="Marktwert" value={entry.marketValue == null ? "—" : formatCurrency(entry.marketValue)} />
        <ActionStat label="Preis" value={entry.price == null ? "—" : formatCurrency(entry.price)} />
        <ActionStat label="Verfügbar" value={accountQuery.data?.budget == null ? "—" : formatCurrency(accountQuery.data.budget)} />
        <ActionStat label="Nach Geboten" value={balanceAfterActiveBids == null ? "—" : formatCurrency(balanceAfterActiveBids)} />
      </div>

      <form className="market-bid-form" onSubmit={(event) => { event.preventDefault(); if (canSubmit && !busy) offerMutation.mutate(); }}>
        <label htmlFor="market-bid-price">{entry.ownOffer != null ? "Gebot ändern" : "Gebot abgeben"}</label>
        <div className="market-bid-input"><input id="market-bid-price" inputMode="numeric" value={priceText} onChange={(event)=>{setPriceText(event.target.value);setMessage(null)}} autoFocus/><span>€</span></div>
        <div className="market-bid-shortcuts">
          {[entry.marketValue, entry.price].filter((value, index, arr): value is number => value != null && arr.indexOf(value)===index).map((value)=><button key={value} type="button" onClick={()=>setPriceText(String(value))}>{value===entry.marketValue?"Marktwert":"Preis"} · {formatCurrency(value)}</button>)}
        </div>
        {entry.ownOffer != null ? <p className="market-current-bid">Aktuelles Gebot: <strong>{formatCurrency(entry.ownOffer)}</strong></p> : null}
        <div className="market-bid-eligibility" aria-live="polite">
          <EligibilityLine status={eligibility.squadSlotsFree == null || eligibility.squadSlotsFree > 0 ? "ok" : "blocked"} label={eligibility.squadSlotsFree == null ? "Kaderplätze werden geprüft" : eligibility.squadSlotsFree > 0 ? `${eligibility.squadSlotsFree} Kaderplatz${eligibility.squadSlotsFree === 1 ? "" : "e"} frei` : `Kader voll · ${DEFAULT_SQUAD_LIMIT} / ${DEFAULT_SQUAD_LIMIT}`} />
          <EligibilityLine status={eligibility.maximumBid == null ? "warning" : price == null || price <= eligibility.maximumBid ? "ok" : "blocked"} label={eligibility.maximumBid == null ? "Budgetgrenze derzeit nicht verfügbar" : `${formatCreditLimitLabel()} · max. ${formatCurrency(eligibility.maximumBid)}`} />
          {eligibility.minimumBid != null ? <EligibilityLine status={price == null || price >= eligibility.minimumBid ? "ok" : "blocked"} label={`Mindestens Marktwert · ${formatCurrency(eligibility.minimumBid)}`} /> : null}
        </div>
        {!eligibility.allowed && validPrice ? <p className="market-bid-blocker">{eligibility.reasons.map(bidReasonLabel).join(" ")}</p> : null}
        {message ? <p className={`market-action-message${offerMutation.isError||withdrawMutation.isError?" is-error":""}`}>{message}</p> : null}
        <div className="market-bid-actions" style={{ display: "grid", gridTemplateColumns: entry.ownOffer != null && entry.ownOfferId ? "1fr 1fr" : "1fr", gap: 10, marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
          {entry.ownOffer != null && entry.ownOfferId ? <button type="button" className="market-withdraw-button" disabled={busy} onClick={()=>withdrawMutation.mutate()} style={{ minHeight: 42, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 7, borderRadius: 7 }}><Trash2 size={16}/> Zurückziehen</button> : null}
          <button type="submit" disabled={!canSubmit||busy} style={{ minHeight: 42, width: "100%", display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 7, padding: "0 14px", border: "1px solid #ff4600", borderRadius: 7, background: "#ff4600", color: "#111214", font: "inherit", fontSize: 12, fontWeight: 800, opacity: !canSubmit || busy ? 0.45 : 1, cursor: !canSubmit || busy ? "not-allowed" : "pointer", visibility: "visible" }}><Gavel size={16}/>{offerMutation.isPending?"Wird gesendet …":entry.ownOffer!=null?"Gebot aktualisieren":"Gebot abgeben"}</button>
        </div>
      </form>
    </aside>
  </div>;
}

function EligibilityLine({ status, label }: { status: "ok" | "blocked" | "warning"; label: string }) {
  const ok = status === "ok";
  return <div className={`market-bid-eligibility__line is-${status}`}>{ok ? <CheckCircle2 size={14}/> : <XCircle size={14}/>}<span>{label}</span></div>;
}

function latestDailyMarketValueDelta(history: MarketValuePoint[]) {
  const points = history
    .filter((point) => Number.isFinite(point.value) && Boolean(point.date))
    .slice()
    .sort((a, b) => a.date.localeCompare(b.date));

  if (points.length < 2) return null;
  const latest = points[points.length - 1];
  let previousIndex = points.length - 2;
  while (previousIndex >= 0 && points[previousIndex].date === latest.date) previousIndex -= 1;
  if (previousIndex < 0) return null;
  return latest.value - points[previousIndex].value;
}

function ActionStat({label,value}:{label:string;value:string}){return <div><span>{label}</span><strong>{value}</strong></div>}
function Summary({icon,label,value,subvalue,tone}:{icon:ReactNode;label:string;value:string;subvalue?:string;tone?:"positive"|"negative"|"neutral"}) { return <div className="market-summary__metric"><div className="market-summary__label">{icon}{label}</div><strong className={tone?`is-${tone}`:undefined}>{value}</strong>{subvalue?<span>{subvalue}</span>:null}</div> }
function MarketValueCell({ value, fair, loading }: { value: number | null; fair?: ReturnType<typeof estimateFairValue>; loading: boolean }) {
  return <span className="market-value-cell"><Money value={value}/>{fair?.fairValue != null && fair.differencePct != null ? <small className={fair.differencePct >= 0 ? "tone-positive" : "tone-negative"}>Fair {formatMillions(fair.fairValue)} · {fair.differencePct >= 0 ? "+" : ""}{fair.differencePct.toFixed(0)}%</small> : loading ? <small>Fair …</small> : null}</span>;
}
function formatMillions(value: number) { return `${(value / 1_000_000).toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} Mio.`; }

function Money({value,strong}:{value:number|null;strong?:boolean}) { return value==null?<span className="market-empty">—</span>:<span className={strong?"market-value is-strong":"market-value"}>{formatCurrency(value)}</span> }
function SignedMoney({value}:{value:number|null}) { if(value==null)return <span className="market-empty">—</span>; return <span className={`market-value is-${toneFor(value)}`}>{formatSignedCurrency(value)}</span> }
function NumberValue({value,decimals=0}:{value:number|null;decimals?:number}) { return value==null?<span className="market-empty">—</span>:<span className="market-value">{new Intl.NumberFormat("de-DE",{maximumFractionDigits:decimals,minimumFractionDigits:decimals}).format(value)}</span> }
function MarketPointsCell({total,average}:{total:number|null;average:number|null}) {
  if (total == null && average == null) return <span className="market-empty">—</span>;
  return <span className="market-points-cell">
    <strong>{total == null ? "—" : new Intl.NumberFormat("de-DE").format(total)}</strong>
    <small>{average == null ? "Ø —" : `Ø ${new Intl.NumberFormat("de-DE",{maximumFractionDigits:1,minimumFractionDigits:1}).format(average)}`}</small>
  </span>;
}
function Expiry({seconds,elapsedSeconds}:{seconds:number|null;elapsedSeconds:number}) { if(seconds==null)return <span className="market-empty">—</span>; const remaining=Math.max(seconds-elapsedSeconds,0); const text=formatDuration(remaining); return <span className={`market-expiry${remaining<=3600?" is-soon":""}`}>{text}</span> }
function SortIcon({direction}:{direction:false|"asc"|"desc"}) { if(direction==="asc")return <ArrowUp size={12}/>; if(direction==="desc")return <ArrowDown size={12}/>; return <ArrowUpDown size={12}/> }
function formatCurrency(value:number){return new Intl.NumberFormat("de-DE",{style:"currency",currency:"EUR",maximumFractionDigits:0}).format(value)}
function formatSignedCurrency(value:number){const sign=value>0?"+":value<0?"−":"";return `${sign}${formatCurrency(Math.abs(value))}`}
function formatDuration(seconds:number){const hours=Math.floor(seconds/3600);const minutes=Math.floor((seconds%3600)/60);if(hours>=24)return `${Math.floor(hours/24)}T ${hours%24}h`;if(hours>0)return `${hours}h ${minutes}m`;return `${minutes}m`}
function toneFor(value:number){return value>0?"positive":value<0?"negative":"neutral"}
function parseEuroInput(value:string){const normalized=value.replace(/[^0-9]/g,"");if(!normalized)return null;const number=Number(normalized);return Number.isSafeInteger(number)?number:null}
function errorMessage(error:unknown){if(error instanceof Error)return error.message;if(typeof error==="string")return error;if(error&&typeof error==="object"){const candidate=error as {message?:unknown;status?:unknown};if(typeof candidate.message==="string"&&candidate.message.trim()){const suffix=typeof candidate.status==="number"?` (HTTP ${candidate.status})`:"";return `${candidate.message}${suffix}`}}return "Kickbase hat die Aktion abgelehnt."}

function finiteNumber(value: unknown) {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function pointsPerMillion(averagePoints: number | null | undefined, marketValue: number | null | undefined) {
  const average = finiteNumber(averagePoints);
  const value = finiteNumber(marketValue);
  if (average == null || value == null || value <= 0) return null;
  const result = average / (value / 1_000_000);
  return Number.isFinite(result) ? result : null;
}

function isEfficientMarketEntry(entry: MarketEntry) {
  const average = finiteNumber(entry.averagePoints);
  const ppm = pointsPerMillion(entry.averagePoints, entry.marketValue);
  return average != null && average >= 70 && ppm != null && ppm >= 8;
}

function opponentLabel(teamId: string | null, fixtures: NextFixture[]) {
  if (!teamId) return "—";
  const fixture = fixtures.find((item) => item.homeTeamId === teamId || item.awayTeamId === teamId);
  if (!fixture) return "—";
  const home = fixture.homeTeamId === teamId;
  return `${home ? "vs." : "@"} ${home ? fixture.awayTeamName : fixture.homeTeamName}`;
}
