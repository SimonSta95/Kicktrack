import { useEffect, useMemo, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Calculator, CircleDollarSign, ShieldCheck, TrendingUp, WalletCards, X } from "lucide-react";
import { getLeagueAccountContext } from "@/features/account/api";
import type { SquadPlayer } from "@/features/squad/types";
import type { MarketEntry } from "./types";
import { calculateBidCapacity, resolveBalanceAfterActiveBids } from "./bid-eligibility";
import { formatCreditLimitLabel } from "@/lib/kickbase-rules";
import { warnLog } from "../../lib/logging";

type Props = {
  entries?: MarketEntry[] | null;
  squadPlayers?: SquadPlayer[] | null;
  leagueId: string;
  onClose: () => void;
};


export function BudgetPlannerDrawer({ entries, squadPlayers, leagueId, onClose }: Props) {
  const accountQuery = useQuery({
    queryKey: ["account", "league", leagueId],
    queryFn: () => getLeagueAccountContext(leagueId),
    staleTime: 0,
    refetchOnMount: "always",
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const data = useMemo(() => {
    // Legacy DBs / older API payloads can legitimately miss collection fields.
    // The planner is informational and must never take down the whole route.
    const safeSquadPlayers = Array.isArray(squadPlayers) ? squadPlayers : [];
    const safeEntries = Array.isArray(entries) ? entries : [];

    const squadValue = safeSquadPlayers.reduce((sum, player) => sum + Math.max(0, player.marketValue ?? 0), 0);
    const ownIds = new Set(safeSquadPlayers.map((player) => player.id));
    const ownListings = safeEntries.filter((entry) => ownIds.has(entry.playerId));
    const activeBids = safeEntries.filter((entry) => !ownIds.has(entry.playerId) && entry.ownOffer != null);
    const visibleBidTotal = activeBids.reduce((sum, entry) => sum + (entry.ownOffer ?? 0), 0);

    const bestIncoming = ownListings
      .map((entry) => {
        const offers = Array.isArray(entry.offers) ? entry.offers : [];
        const best = offers
          .filter((offer) => offer?.price != null && offer.price > 0)
          .sort((a, b) => (b.price ?? 0) - (a.price ?? 0))[0];
        return best?.price ? { playerId: entry.playerId, name: entry.name, price: best.price } : null;
      })
      .filter((value): value is { playerId: string; name: string; price: number } => value != null);

    const bestIncomingTotal = bestIncoming.reduce((sum, offer) => sum + offer.price, 0);
    const askingTotal = ownListings.reduce((sum, entry) => sum + Math.max(0, entry.price ?? 0), 0);

    if (import.meta.env.DEV) {
      const malformedOfferEntries = safeEntries
        .filter((entry) => entry.offers != null && !Array.isArray(entry.offers))
        .map((entry) => entry.playerId);
      if (malformedOfferEntries.length) {
        warnLog(
          "[KickTrack][DEBUG][budget-planner] non-array offers",
          { count: malformedOfferEntries.length },
        );
      }
    }

    const budget = accountQuery.data?.budget ?? null;
    const apiAfterBids = accountQuery.data?.budgetAfterActiveBids ?? null;
    const afterBids = resolveBalanceAfterActiveBids(budget, apiAfterBids, visibleBidTotal);
    const reservedByApi = budget != null && apiAfterBids != null ? Math.max(0, budget - apiAfterBids) : null;
    const reservedEffective = budget != null && afterBids != null ? Math.max(0, budget - afterBids) : null;

    const capacity = calculateBidCapacity(squadValue, afterBids);
    const minimumBalance = capacity.minimumBalance;
    const maximumAdditionalBid = capacity.maximumBid;

    return {
      squadValue,
      budget,
      afterBids,
      activeBids,
      visibleBidTotal,
      reservedByApi,
      reservedEffective,
      budgetSource: apiAfterBids != null ? "api" as const : afterBids != null ? "market-fallback" as const : "unavailable" as const,
      ownListings,
      askingTotal,
      bestIncoming,
      bestIncomingTotal,
      minimumBalance,
      maximumAdditionalBid,
      afterBidsAndBestSales: afterBids == null ? null : afterBids + bestIncomingTotal,
      slotsAfterBestSales: Math.min(18, Math.max(0, 18 - safeSquadPlayers.length + bestIncoming.length)),
    };
  }, [accountQuery.data, entries, squadPlayers]);

  return (
    <div className="budget-planner-layer" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}>
      <aside className="budget-planner-drawer" role="dialog" aria-modal="true" aria-label="Budgetplaner">
        <header className="budget-planner-header">
          <div>
            <span className="budget-planner-eyebrow">FINANZEN</span>
            <h2>BUDGETPLANER</h2>
            <p>Gebote und echte Verkaufsoptionen getrennt betrachten.</p>
          </div>
          <button type="button" className="budget-planner-close" onClick={onClose} aria-label="Budgetplaner schließen"><X size={19} /></button>
        </header>

        <div className="budget-planner-content">
          <section className="budget-planner-hero">
            <BudgetMetric icon={<WalletCards size={16}/>} label="Aktuell verfügbar" value={money(data.budget)} />
            <BudgetMetric icon={<Calculator size={16}/>} label="Nach aktiven Geboten" value={money(data.afterBids)} tone={tone(data.afterBids)} />
            <BudgetMetric icon={<ShieldCheck size={16}/>} label="Weitere Gebotskapazität" value={money(data.maximumAdditionalBid)} />
          </section>

          <section className="budget-planner-section">
            <div className="budget-planner-section__title">
              <div><CircleDollarSign size={16}/><span>Aktive Gebote</span></div>
              <strong>{data.activeBids.length}</strong>
            </div>
            <div className="budget-planner-lines">
              <BudgetLine label={data.budgetSource === "api" ? "Laut Kickbase reserviert" : "Aus aktiven Geboten berechnet"} value={money(data.budgetSource === "api" ? data.reservedByApi : data.reservedEffective)} emphasize />
              <BudgetLine label="In der aktuellen Marktliste sichtbar" value={money(data.visibleBidTotal)} />
            </div>
            {data.activeBids.length ? (
              <div className="budget-planner-list">
                {data.activeBids.map((entry) => (
                  <div key={entry.playerId}><span>{entry.name}</span><strong>{money(entry.ownOffer)}</strong></div>
                ))}
              </div>
            ) : <p className="budget-planner-empty">Keine aktiven Gebote.</p>}
          </section>

          <section className="budget-planner-section">
            <div className="budget-planner-section__title">
              <div><TrendingUp size={16}/><span>Verkäufe</span></div>
              <strong>{data.ownListings.length} gelistet</strong>
            </div>
            <div className="budget-planner-lines">
              <BudgetLine label="Summe deiner Verkaufspreise" value={money(data.askingTotal)} mutedNote="nicht als Liquidität gerechnet" />
              <BudgetLine label="Beste aktuell vorhandene Angebote" value={money(data.bestIncomingTotal)} emphasize />
            </div>
            {data.bestIncoming.length ? (
              <div className="budget-planner-list">
                {data.bestIncoming.map((offer) => (
                  <div key={offer.playerId}><span>{offer.name}</span><strong>{money(offer.price)}</strong></div>
                ))}
              </div>
            ) : <p className="budget-planner-empty">Aktuell keine konkreten eingehenden Verkaufsangebote.</p>}
          </section>

          <section className="budget-planner-section budget-planner-scenarios">
            <div className="budget-planner-section__title"><div><Calculator size={16}/><span>Szenarien</span></div></div>
            <Scenario label="Wenn alle aktiven Gebote durchgehen" value={data.afterBids} note={data.budgetSource === "api" ? "Kickbase-Budget nach aktiven Geboten" : "aus aktuellem Budget und sichtbaren Geboten berechnet"} />
            <Scenario label="+ alle aktuell besten Verkaufsangebote" value={data.afterBidsAndBestSales} note={data.bestIncoming.length ? `${data.bestIncoming.length} reale Verkaufsoption${data.bestIncoming.length === 1 ? "" : "en"}` : "keine realen Angebote vorhanden"} />
          </section>

          <section className="budget-planner-credit">
            <div><span>{formatCreditLimitLabel()}</span><strong>{money(data.minimumBalance)}</strong></div>
            <p>Lokale Vorprüfung auf Basis deines aktuellen Kaderwerts ({money(data.squadValue)}). Kickbase bleibt die verbindliche Instanz beim Absenden eines Gebots.</p>
          </section>
        </div>
      </aside>
    </div>
  );
}

function BudgetMetric({ icon, label, value, tone: valueTone = "neutral" }: { icon: ReactNode; label: string; value: string; tone?: "positive" | "negative" | "neutral" }) {
  return <div className="budget-planner-metric"><div>{icon}<span>{label}</span></div><strong className={`is-${valueTone}`}>{value}</strong></div>;
}
function BudgetLine({ label, value, emphasize, mutedNote }: { label: string; value: string; emphasize?: boolean; mutedNote?: string }) {
  return <div className={`budget-planner-line${emphasize ? " is-emphasis" : ""}`}><div><span>{label}</span>{mutedNote ? <small>{mutedNote}</small> : null}</div><strong>{value}</strong></div>;
}
function Scenario({ label, value, note }: { label: string; value: number | null; note: string }) {
  return <div className="budget-planner-scenario"><div><strong>{label}</strong><span>{note}</span></div><b className={`is-${tone(value)}`}>{money(value)}</b></div>;
}
function money(value: number | null) { return value == null ? "—" : new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value); }
function tone(value: number | null) { return value == null || value === 0 ? "neutral" as const : value > 0 ? "positive" as const : "negative" as const; }
