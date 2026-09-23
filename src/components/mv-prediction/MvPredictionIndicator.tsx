import { useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { IconClockHour10 } from "@tabler/icons-react";
import type { MvPrediction, MvPredictionQuality } from "../../features/analytics/mv-prediction";
import { getInwardFloatingPosition } from "../../lib/floating-position";
import "./mv-prediction-indicator.css";

export function MvPredictionIndicator({ prediction, quality, detail = false }: { prediction?: MvPrediction; quality?: MvPredictionQuality; detail?: boolean }) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const popoverId = useId();

  useLayoutEffect(() => {
    if (!open) return;
    const update = () => {
      const trigger = triggerRef.current?.getBoundingClientRect();
      const popover = popoverRef.current?.getBoundingClientRect();
      if (!trigger || !popover) return;
      setPosition(getInwardFloatingPosition(trigger, popover, { margin: 12, gap: 8 }));
    };
    const frame = window.requestAnimationFrame(update);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open]);

  if (!prediction || prediction.delta == null) return <span className="mv-prediction-empty">—</span>;
  const tone = prediction.delta > 0 ? "positive" : prediction.delta < 0 ? "negative" : "neutral";
  const content = <>
    <div className="mv-prediction-popover__eyebrow">Nächster 22-Uhr-Refresh</div>
    <div className={`mv-prediction-popover__headline tone-${tone}`}><IconClockHour10 size={17}/>{formatSignedCurrency(prediction.delta)}</div>
    {prediction.expectedValue != null ? <div className="mv-prediction-popover__value">Erwarteter MW <strong>{formatCurrency(prediction.expectedValue)}</strong></div> : null}
    {prediction.lowDelta != null && prediction.highDelta != null ? <div className="mv-prediction-popover__range"><span>Erfahrungsbereich</span><strong>{formatSignedCurrency(prediction.lowDelta)} bis {formatSignedCurrency(prediction.highDelta)}</strong></div> : null}
    <div className="mv-prediction-popover__meta"><span className={`confidence confidence--${prediction.confidence.toLowerCase()}`}>{prediction.confidence}</span><span>n={prediction.sampleCount}</span><span>{prediction.historyDays} Tage Historie</span></div>
    {quality && quality.evaluatedCount > 0 ? <div className="mv-prediction-popover__quality"><span>Historische Modellgüte</span><strong>{quality.directionHitRate == null ? "—" : `${Math.round(quality.directionHitRate * 100)}% Richtung`} · {quality.mae == null ? "MAE —" : `MAE ${formatCompactCurrency(quality.mae)}`}</strong>{quality.intervalCoverage != null ? <small>Bereich traf {Math.round(quality.intervalCoverage * 100)}% · n={quality.evaluatedCount}</small> : null}</div> : null}
  </>;

  if (detail) return <div className="mv-prediction-detail">{content}</div>;

  return <>
    <button
      ref={triggerRef}
      type="button"
      className={`mv-prediction-trigger tone-${tone}`}
      aria-expanded={open}
      aria-controls={popoverId}
      onClick={(event) => { event.stopPropagation(); setOpen((value) => !value); }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <IconClockHour10 size={16}/><span>{formatSignedCompact(prediction.delta)}</span>
    </button>
    {open ? createPortal(<div ref={popoverRef} id={popoverId} className="mv-prediction-popover" style={{ left: position.left, top: position.top }} role="dialog" onClick={(event)=>event.stopPropagation()}>{content}</div>, document.body) : null}
  </>;
}

function formatCurrency(value: number) { return new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value); }
function formatSignedCurrency(value: number) { const sign = value > 0 ? "+" : value < 0 ? "−" : ""; return `${sign}${formatCurrency(Math.abs(value))}`; }
function formatCompactCurrency(value: number) { const abs=Math.abs(value); if(abs>=1_000_000)return `${(value/1_000_000).toLocaleString("de-DE",{maximumFractionDigits:2})} Mio. €`; if(abs>=1_000)return `${Math.round(value/1_000).toLocaleString("de-DE")} Tsd. €`; return `${Math.round(value).toLocaleString("de-DE")} €`; }
function formatSignedCompact(value: number) { return `${value>0?"+":value<0?"−":""}${formatCompactCurrency(Math.abs(value))}`; }
