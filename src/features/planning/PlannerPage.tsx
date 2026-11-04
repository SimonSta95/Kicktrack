import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRightLeft, Calculator, CircleAlert, RefreshCw, ShieldCheck, Sparkles, UsersRound } from "lucide-react";
import { getLeagueAccountContext } from "@/features/account/api";
import { getPlayerRecentForms } from "@/features/analytics/api";
import { getLeagueMarket } from "@/features/market/api";
import { getLeagueNextMatchday, getLeagueSquad } from "@/features/squad/api";
import type { PlayerPosition } from "@/features/squad/types";
import {
  FORMATIONS,
  lineupPoints,
  marketPlanningPlayer,
  optimizeLineup,
  projectPlayer,
  simulateTransfer,
  squadPlanningPlayer,
  type ExpectedPlayer,
} from "./planning-model";
import "./planning.css";

const POSITION_LABEL: Record<PlayerPosition, string> = {
  GOALKEEPER: "Tor",
  DEFENDER: "Abwehr",
  MIDFIELDER: "Mittelfeld",
  FORWARD: "Sturm",
  UNKNOWN: "Unbekannt",
};

export function PlannerPage({ leagueId }: { leagueId: string }) {
  const [formationId, setFormationId] = useState("4-4-2");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [marketPlayerId, setMarketPlayerId] = useState("");
  const [price, setPrice] = useState("");
  const formation = FORMATIONS.find((item) => item.id === formationId) ?? FORMATIONS[3];
  const squadQuery = useQuery({ queryKey: ["squad", leagueId], queryFn: () => getLeagueSquad(leagueId), staleTime: 60_000 });
  const marketQuery = useQuery({ queryKey: ["market", leagueId], queryFn: () => getLeagueMarket(leagueId), staleTime: 60_000 });
  const accountQuery = useQuery({ queryKey: ["account", "league", leagueId], queryFn: () => getLeagueAccountContext(leagueId), staleTime: 30_000 });
  const fixturesQuery = useQuery({ queryKey: ["league", "next-matchday", leagueId], queryFn: () => getLeagueNextMatchday(leagueId), staleTime: 10 * 60_000 });
  const allIds = useMemo(() => [...new Set([
    ...(squadQuery.data?.players.map((player) => player.id) ?? []),
    ...(marketQuery.data?.entries.map((player) => player.playerId) ?? []),
  ])].sort(), [marketQuery.data?.entries, squadQuery.data?.players]);
  const formsQuery = useQuery({
    queryKey: ["analytics", "player-recent-forms", leagueId, allIds],
    queryFn: () => getPlayerRecentForms(leagueId, allIds),
    enabled: allIds.length > 0,
    staleTime: 30 * 60_000,
    retry: false,
  });

  const squad = useMemo(() => (squadQuery.data?.players ?? []).map((player) => projectPlayer(
    squadPlanningPlayer(player), formsQuery.data?.forms[player.id], fixturesQuery.data?.fixtures ?? [],
  )), [fixturesQuery.data?.fixtures, formsQuery.data?.forms, squadQuery.data?.players]);
  const market = useMemo(() => (marketQuery.data?.entries ?? []).map((player) => projectPlayer(
    marketPlanningPlayer(player), formsQuery.data?.forms[player.playerId], fixturesQuery.data?.fixtures ?? [],
  )).filter((player) => player.position !== "UNKNOWN"), [fixturesQuery.data?.fixtures, formsQuery.data?.forms, marketQuery.data?.entries]);
  const optimized = useMemo(() => optimizeLineup(squad, formation) ?? [], [formation, squad]);

  useEffect(() => {
    setSelectedIds(optimized.map((player) => player.id));
  }, [formationId, optimized]);

  const selected = useMemo(() => selectedIds.flatMap((id) => {
    const player = squad.find((candidate) => candidate.id === id);
    return player ? [player] : [];
  }), [selectedIds, squad]);
  const purchase = market.find((player) => player.id === marketPlayerId) ?? null;
  const numericPrice = Number(price.replace(/[^0-9]/g, ""));
  const budget = accountQuery.data?.budgetAfterActiveBids ?? accountQuery.data?.budget ?? 0;
  const simulation = useMemo(() => purchase ? simulateTransfer(
    squad, purchase, numericPrice || purchase.marketValue || 0, budget, formation, accountQuery.data?.squadLimit ?? 18,
  ) : null, [accountQuery.data?.squadLimit, budget, formation, numericPrice, purchase, squad]);

  function selectMarketPlayer(id: string) {
    const player = market.find((candidate) => candidate.id === id);
    const listing = marketQuery.data?.entries.find((candidate) => candidate.playerId === id);
    setMarketPlayerId(id);
    setPrice(String(listing?.price ?? player?.marketValue ?? ""));
  }

  function togglePlayer(player: ExpectedPlayer) {
    if (selectedIds.includes(player.id)) {
      setSelectedIds((ids) => ids.filter((id) => id !== player.id));
      return;
    }
    const limit = formation[player.position];
    if (typeof limit !== "number") return;
    const samePosition = selected.filter((candidate) => candidate.position === player.position);
    if (samePosition.length < limit) {
      setSelectedIds((ids) => [...ids, player.id]);
      return;
    }
    const weakest = [...samePosition].sort((a, b) => a.expectedPoints - b.expectedPoints)[0];
    setSelectedIds((ids) => ids.map((id) => id === weakest.id ? player.id : id));
  }

  if (squadQuery.isLoading || marketQuery.isLoading || accountQuery.isLoading) return <PlannerState>Planungsdaten werden geladen …</PlannerState>;
  if (squadQuery.isError || marketQuery.isError || accountQuery.isError) return <PlannerState error>Planungsdaten konnten nicht vollständig geladen werden.</PlannerState>;

  return (
    <section className="planner-page">
      <header className="planner-header">
        <div><span className="planner-kicker">Matchday Lab</span><h1>AUFSTELLUNG & TRANSFERS</h1><p>Plane deine beste Elf und prüfe, ob ein Marktspieler deinen Kader wirklich verbessert.</p></div>
        <div className="planner-model-note"><Sparkles size={16}/><div><strong>Expected Points</strong><span>Ø Punkte · letzte Form · Einsatzstatus · Heim/Auswärts</span></div></div>
      </header>

      <div className="planner-metrics">
        <Metric label="Geplante Elf" value={`${selected.length}/11`} hint={formation.label} />
        <Metric label="Erwartete Punkte" value={formatPoints(lineupPoints(selected))} hint={`Spieltag ${fixturesQuery.data?.dayNumber ?? "–"}`} />
        <Metric label="Verfügbares Budget" value={money(budget)} hint="nach sichtbaren Geboten" />
      </div>

      <div className="planner-layout">
        <section className="planner-card lineup-planner">
          <header className="planner-card__header"><div><UsersRound size={17}/><span>Aufstellungsplaner</span></div><button type="button" onClick={() => setSelectedIds(optimized.map((player) => player.id))}><RefreshCw size={13}/>Beste Elf</button></header>
          <div className="formation-tabs" role="group" aria-label="Formation wählen">
            {FORMATIONS.map((item) => <button type="button" className={item.id === formation.id ? "is-active" : ""} key={item.id} onClick={() => setFormationId(item.id)}>{item.label}</button>)}
          </div>
          <div className="lineup-pitch">
            {(["FORWARD", "MIDFIELDER", "DEFENDER", "GOALKEEPER"] as PlayerPosition[]).map((position) => (
              <div className={`lineup-row is-${position.toLowerCase()}`} key={position}>
                {selected.filter((player) => player.position === position).sort((a, b) => b.expectedPoints - a.expectedPoints).map((player) => <PlayerChip key={player.id} player={player} onClick={() => togglePlayer(player)} />)}
                {Array.from({ length: Math.max(formation[position] - selected.filter((player) => player.position === position).length, 0) }, (_, index) => <div className="lineup-empty" key={index}>+</div>)}
              </div>
            ))}
          </div>
          <div className="planner-bench"><div className="planner-subheading"><span>Bank & Alternativen</span><small>Klick ersetzt den schwächsten Spieler derselben Position</small></div>
            <div className="bench-list">{squad.filter((player) => !selectedIds.includes(player.id)).sort((a, b) => b.expectedPoints - a.expectedPoints).map((player) => <button type="button" key={player.id} onClick={() => togglePlayer(player)}><span>{player.firstName ? `${player.firstName} ` : ""}{player.name}</span><small>{POSITION_LABEL[player.position]} · {formatPoints(player.expectedPoints)}</small></button>)}</div>
          </div>
        </section>

        <section className="planner-card transfer-simulator">
          <header className="planner-card__header"><div><Calculator size={17}/><span>Transfer-Simulator</span></div><small>keine echte Aktion</small></header>
          <label className="sim-field"><span>Marktspieler</span><select value={marketPlayerId} onChange={(event) => selectMarketPlayer(event.target.value)}><option value="">Spieler auswählen …</option>{market.sort((a, b) => b.expectedPoints - a.expectedPoints).map((player) => <option value={player.id} key={player.id}>{player.name} · {formatPoints(player.expectedPoints)}</option>)}</select></label>
          <label className="sim-field"><span>Geplanter Kaufpreis</span><input inputMode="numeric" value={price} onChange={(event) => setPrice(event.target.value)} placeholder="0 €" /></label>

          {!purchase ? <div className="sim-placeholder"><ArrowRightLeft size={24}/><strong>Transfer auswählen</strong><p>KickTrack sucht danach die punkteschonendste Verkaufslösung.</p></div> : simulation ? <div className="simulation-result">
            <div className={`simulation-verdict ${simulation.pointsDelta >= 0 ? "is-positive" : "is-negative"}`}><span>Effekt auf deine beste Elf</span><strong>{signedPoints(simulation.pointsDelta)}</strong><small>{formatPoints(simulation.baselinePoints)} → {formatPoints(simulation.projectedPoints)}</small></div>
            <div className="simulation-lines">
              <ResultLine label="Kauf" value={`${purchase.name} · ${money(simulation.price)}`} />
              <ResultLine label="Verkaufen" value={simulation.sales.length ? simulation.sales.map((player) => player.name).join(", ") : "Niemanden"} />
              <ResultLine label="Geschätzter Erlös" value={money(simulation.saleProceeds)} />
              <ResultLine label="Restbudget" value={money(simulation.remainingBudget)} />
            </div>
            <div className="simulation-note"><ShieldCheck size={14}/><span>Verkaufserlöse werden mit dem aktuellen Marktwert geschätzt. Tatsächliche Kickbase-Angebote können darunter oder darüber liegen.</span></div>
          </div> : <div className="sim-placeholder is-warning"><CircleAlert size={24}/><strong>Kein gültiges Szenario</strong><p>Budget, Kaderlimit oder Positionsbesetzung lassen sich mit höchstens drei Verkäufen nicht erfüllen.</p></div>}
        </section>
      </div>
    </section>
  );
}

function PlayerChip({ player, onClick }: { player: ExpectedPlayer; onClick: () => void }) {
  return <button type="button" className="lineup-player" onClick={onClick} title="Aus der geplanten Elf entfernen"><span>{player.name}</span><strong>{formatPoints(player.expectedPoints)}</strong><small>{player.availabilityFactor < 1 ? "Status-Risiko" : player.fixtureFactor > 1 ? "Heimspiel" : "Auswärts/ohne Spiel"}</small></button>;
}

function Metric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return <div className="planner-metric"><span>{label}</span><strong>{value}</strong><small>{hint}</small></div>;
}

function ResultLine({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function PlannerState({ children, error = false }: { children: string; error?: boolean }) {
  return <div className={`planner-state${error ? " is-error" : ""}`}>{error ? <CircleAlert size={20}/> : <RefreshCw className="is-spinning" size={20}/>}<span>{children}</span></div>;
}

function money(value: number) { return `${Math.round(value).toLocaleString("de-DE")} €`; }
function formatPoints(value: number) { return `${value.toLocaleString("de-DE", { maximumFractionDigits: 1 })} P`; }
function signedPoints(value: number) { return `${value >= 0 ? "+" : ""}${value.toLocaleString("de-DE", { maximumFractionDigits: 1 })} P`; }
