import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { BarChart3 } from "lucide-react";
import { getInwardFloatingPosition, type FloatingPosition } from "@/lib/floating-position";
import type { LeaguePurchasePriceStat } from "./league-price-api";

type Props = {
  stat: LeaguePurchasePriceStat | undefined;
  loading?: boolean;
};

export function LeaguePriceIndicator({ stat, loading = false }: Props) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<FloatingPosition | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  const enoughData = Boolean(stat && stat.sampleCount >= 3 && stat.typicalPrice != null);
  const value = enoughData ? formatCompactEuro(stat!.typicalPrice!) : loading ? "…" : "—";

  useLayoutEffect(() => {
    if (!open || !triggerRef.current || !popoverRef.current) return;
    const update = () => {
      if (!triggerRef.current || !popoverRef.current) return;
      setPosition(getInwardFloatingPosition(
        triggerRef.current.getBoundingClientRect(),
        popoverRef.current.getBoundingClientRect(),
        { margin: 10, gap: 7 },
      ));
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, stat]);

  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target) || popoverRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  return <>
    <button
      ref={triggerRef}
      type="button"
      className={`league-price-trigger${enoughData ? " has-data" : ""}`}
      onClick={(event) => { event.stopPropagation(); setOpen((value) => !value); }}
      aria-expanded={open}
      aria-label="Ligatypischen Kaufpreis anzeigen"
    >
      <span>{value}</span>
      {enoughData ? <small>{formatSignedPct(stat!.medianPremiumPct)}</small> : null}
    </button>
    {open ? createPortal(
      <div
        ref={popoverRef}
        className="league-price-popover"
        style={position ? { left: position.left, top: position.top } : { visibility: "hidden", left: 0, top: 0 }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="league-price-popover__head">
          <div><BarChart3 size={14}/><span>LIGATYPISCHER KAUFPREIS</span></div>
          <strong>{enoughData ? formatEuro(stat!.typicalPrice!) : "Zu wenig Daten"}</strong>
        </div>
        {!stat || stat.sampleCount === 0 ? <p className="league-price-popover__empty">Für diese Liga liegen noch keine auswertbaren Käufe mit historischem Marktwert vor.</p> : <>
          <div className="league-price-popover__metrics">
            <Metric label="Median" value={formatSignedPct(stat.medianPremiumPct)} />
            <Metric label="Ø Overpay" value={formatSignedPct(stat.averagePremiumPct)} />
            <Metric label="P25" value={formatSignedPct(stat.p25PremiumPct)} />
            <Metric label="P75" value={formatSignedPct(stat.p75PremiumPct)} />
            <Metric label="Gebotskorridor" value={stat.typicalPriceLow != null && stat.typicalPriceHigh != null ? `${formatCompactEuro(stat.typicalPriceLow)} – ${formatCompactEuro(stat.typicalPriceHigh)}` : "—"} />
          </div>
          <p className="league-price-popover__basis">
            {stat.usedSegment
              ? `${stat.sampleCount} echte Käufe im gleichen Marktwert-Segment.`
              : `${stat.sampleCount} echte Liga-Käufe${stat.segmentSampleCount > 0 ? ` · nur ${stat.segmentSampleCount} im ähnlichen MW-Bereich` : ""}.`}
            {stat.sampleCount < 5 ? " Aussage noch dünn." : " Median wird als typischer Wert verwendet; P25–P75 bildet den robusten Gebotskorridor."}
          </p>
          {stat.examples.length ? <div className="league-price-popover__examples">
            <span>LETZTE KÄUFE DER DATENBASIS</span>
            {stat.examples.map((example, index) => <div key={`${example.playerId}-${example.transferredAt}-${index}`}>
              <div><strong>{example.playerName}</strong><small>{formatDate(example.transferredAt)}</small></div>
              <div><span>{formatCompactEuro(example.marketValue)} → {formatCompactEuro(example.price)}</span><b className={example.premiumPct >= 0 ? "is-positive" : "is-negative"}>{formatSignedPct(example.premiumPct)}</b></div>
            </div>)}
          </div> : null}
          <p className="league-price-popover__note">Rein historisch: bezahlter Kaufpreis relativ zum gespeicherten Marktwert am bzw. vor dem Transfertag. Kein Fair-Value-Score.</p>
        </>}
      </div>,
      document.body,
    ) : null}
  </>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function formatEuro(value: number) {
  return new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value);
}
function formatCompactEuro(value: number) {
  if (Math.abs(value) >= 1_000_000) return `${new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2 }).format(value / 1_000_000)} Mio.`;
  if (Math.abs(value) >= 1_000) return `${new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 }).format(value / 1_000)} Tsd.`;
  return formatEuro(value);
}
function formatSignedPct(value: number | null) {
  if (value == null || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 }).format(value)} %`;
}
function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value.slice(0, 10) : new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit" }).format(date);
}
