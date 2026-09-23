import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Clock3, X } from "lucide-react";
import { getBundledTeamLogo } from "@/lib/team-assets";
import { usePlayerDetail } from "@/features/player-detail/PlayerDetailProvider";
import { getTradingAnalysis, type TradeCycle } from "./trading-api";

export function TradingAnalysisDrawer({ leagueId, onClose }: { leagueId: string; onClose: () => void }) {
  const { openPlayerDetail } = usePlayerDetail();
  const [filter, setFilter] = useState<"ALL" | "CLOSED" | "OPEN">("ALL");
  const query = useQuery({ queryKey: ["trading-analysis", leagueId], queryFn: () => getTradingAnalysis(leagueId), staleTime: 60_000 });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const trades = useMemo(() => (query.data?.trades ?? []).filter((trade) => {
    if (filter === "OPEN") return trade.cycleType === "OPEN_TRADE";
    if (filter === "CLOSED") return trade.cycleType === "CLOSED_TRADE" || trade.cycleType === "CLOSED_START_SQUAD_TRADE";
    return true;
  }), [filter, query.data]);

  return <div className="trading-layer" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}>
    <aside className="trading-drawer" role="dialog" aria-modal="true" aria-label="Trading-Auswertung">
      <header className="trading-header">
        <div><span className="trading-eyebrow">HISTORIE</span><h2>TRADING</h2><p>Realisierte Trades, offene Positionen und Exit-Timing.</p></div>
        <button type="button" className="trading-close" onClick={onClose} aria-label="Trading-Auswertung schließen"><X size={19}/></button>
      </header>

      {query.isLoading ? <div className="trading-state">Transferhistorie wird ausgewertet …</div> : query.isError ? <div className="trading-state is-error">{message(query.error)}</div> : query.data ? <>
        <div className="trading-summary">
          <Metric label="Realisierter P/L" value={money(query.data.summary.realizedPnl)} tone={tone(query.data.summary.realizedPnl)} />
          <Metric label="Ø ROI" value={query.data.summary.averageRoiPct == null ? "—" : `${signed(query.data.summary.averageRoiPct, 1)} %`} tone={tone(query.data.summary.averageRoiPct ?? 0)} />
          <Metric label="Trades" value={`${query.data.summary.closedTrades}`} sub={`${query.data.summary.openTrades} offen`} />
          <Metric label="Exit-Timing" value={`${query.data.summary.goodExits} gut`} sub={`${query.data.summary.earlyExits} zu früh`} />
        </div>

        <div className="trading-filters" role="group" aria-label="Trading-Filter">
          {(["ALL","CLOSED","OPEN"] as const).map((value) => <button type="button" key={value} className={filter === value ? "is-active" : ""} onClick={() => setFilter(value)}>{value === "ALL" ? "Alle" : value === "CLOSED" ? "Abgeschlossen" : "Offen"}</button>)}
        </div>

        <div className="trading-list">
          {trades.map((trade) => {
            const logo = getBundledTeamLogo(trade.teamId);
            return <button type="button" className="trade-row" key={`${trade.playerId}-${trade.sortDate}-${trade.cycleType}`} onClick={() => openPlayerDetail({ playerId: trade.playerId, leagueId, context: { source: "market", label: "Trading-Historie" } })}>
              <div className="trade-player">{logo ? <img src={logo} alt="" aria-hidden/> : null}<div><strong>{trade.playerName}</strong><span>{cycleLabel(trade)} · {dateLabel(trade.sellDate ?? trade.buyDate)}</span></div></div>
              <div className="trade-money"><span>{trade.cycleType === "OPEN_TRADE" ? "Live P/L" : "P/L"}</span><strong className={`is-${tone(trade.pnl ?? 0)}`}>{money(trade.pnl)}</strong>{trade.roiPct != null ? <small>{signed(trade.roiPct, 1)} % ROI</small> : null}</div>
              <div className="trade-holding"><Clock3 size={13}/><span>{trade.holdingDays == null ? "—" : `${trade.holdingDays} T`}</span></div>
              <div className="trade-verdict"><strong>{trade.verdict}</strong>{trade.sellDate ? <span>{trade.exitVerdict}{postLabel(trade)}</span> : <span>Position noch offen</span>}</div>
            </button>;
          })}
          {!trades.length ? <div className="trading-state">Für diesen Filter sind keine Trades vorhanden.</div> : null}
        </div>
      </> : null}
    </aside>
  </div>;
}

function Metric({ label, value, sub, tone: valueTone = "neutral" }: { label: string; value: string; sub?: string; tone?: "positive"|"negative"|"neutral" }) { return <div className="trading-metric"><span>{label}</span><strong className={`is-${valueTone}`}>{value}</strong>{sub ? <small>{sub}</small> : null}</div>; }
function cycleLabel(trade: TradeCycle) { if (trade.cycleType === "OPEN_TRADE") return "Offene Position"; if (trade.cycleType === "CLOSED_START_SQUAD_TRADE") return "Startbestand"; if (trade.cycleType === "UNPAIRED_SALE") return "Verkauf · Kaufpreis unbekannt"; return "Abgeschlossener Trade"; }
function postLabel(trade: TradeCycle) { const value = trade.post7dPct ?? trade.post3dPct; return value == null ? "" : ` · ${trade.post7dPct != null ? "+7T" : "+3T"} ${signed(value,1)} %`; }
function money(value: number | null) { return value == null ? "—" : new Intl.NumberFormat("de-DE", { style:"currency", currency:"EUR", maximumFractionDigits:0 }).format(value); }
function signed(value: number, digits = 0) { return `${value > 0 ? "+" : ""}${value.toLocaleString("de-DE", { minimumFractionDigits:digits, maximumFractionDigits:digits })}`; }
function tone(value: number) { return value > 0 ? "positive" as const : value < 0 ? "negative" as const : "neutral" as const; }
function dateLabel(value: string | null) { if (!value) return "Datum unbekannt"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value.slice(0,10) : date.toLocaleDateString("de-DE", { day:"2-digit", month:"2-digit", year:"2-digit" }); }
function message(error: unknown) { return error instanceof Error ? error.message : typeof error === "string" ? error : "Die Trading-Auswertung konnte nicht geladen werden."; }
