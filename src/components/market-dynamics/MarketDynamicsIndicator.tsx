import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  IconActivity,
  IconArrowDown,
  IconArrowDownRight,
  IconArrowRight,
  IconArrowUp,
  IconArrowUpRight,
  IconChevronsDown,
  IconChevronsUp,
  IconArrowElbowRight,
} from "@tabler/icons-react";
import type { MarketDynamics, MarketDynamicsCode } from "../../features/analytics/player-analytics";
import { getInwardFloatingPosition } from "../../lib/floating-position";
import "./market-dynamics.css";


type Props = {
  dynamics: MarketDynamics | undefined;
  detail?: boolean;
};

const ICONS: Record<MarketDynamicsCode, typeof IconActivity> = {
  ACCELERATING_UP: IconChevronsUp,
  STABLE_UP: IconArrowUp,
  SLOWING_UP: IconArrowUpRight,
  TURNING_UP: IconArrowElbowRight,
  TURNING_DOWN: IconArrowElbowRight,
  SIDEWAYS: IconArrowRight,
  RECOVERING: IconArrowDownRight,
  STABLE_DOWN: IconArrowDown,
  ACCELERATING_DOWN: IconChevronsDown,
  UNKNOWN: IconActivity,
};

export function MarketDynamicsGlyph({ dynamics, size = 18 }: { dynamics: MarketDynamics | undefined; size?: number }) {
  const value = dynamics ?? fallbackDynamics();
  const Icon = ICONS[value.code];
  const style = value.code === "TURNING_DOWN" ? { transform: "scaleY(-1)" } : undefined;
  return <Icon size={size} stroke={2.2} style={style} aria-hidden />;
}

export function MarketDynamicsIndicator({ dynamics, detail = false }: Props) {
  const value = dynamics ?? fallbackDynamics();
  const [open, setOpen] = useState(false);
  const [locked, setLocked] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: 0, top: 0 });

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

  if (detail) {
    return (
      <span className={`market-dynamics market-dynamics--detail tone-${value.tone}`}>
        <MarketDynamicsGlyph dynamics={value} size={20} />
        <span>{value.label}</span>
      </span>
    );
  }

  const popover = open ? (
    <div ref={popoverRef} className="market-dynamics-popover" style={position} role="dialog" aria-label="Marktwert-Dynamik">
      <div className="market-dynamics-popover__head">
        <span className={`market-dynamics__icon tone-${value.tone}`}><MarketDynamicsGlyph dynamics={value} size={20} /></span>
        <div><small>MW-Dynamik</small><strong>{value.label}</strong></div>
      </div>
      <p>{value.reason}</p>
      {value.recentSteps.length ? (
        <div className="market-dynamics-popover__steps">
          <small>Letzte Refreshes</small>
          <div>{value.recentSteps.slice(-5).map((step, index) => <span className={step > 0 ? "is-positive" : step < 0 ? "is-negative" : ""} key={`${step}-${index}`}>{formatStep(step)}</span>)}</div>
        </div>
      ) : null}
    </div>
  ) : null;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`market-dynamics__trigger tone-${value.tone}`}
        aria-label={`MW-Dynamik: ${value.label}`}
        aria-expanded={open}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => { if (!locked) setOpen(false); }}
        onFocus={() => setOpen(true)}
        onBlur={() => { if (!locked) setOpen(false); }}
        onClick={(event) => {
          event.stopPropagation();
          setLocked((current) => {
            const next = !current;
            setOpen(next);
            return next;
          });
        }}
      >
        <MarketDynamicsGlyph dynamics={value} size={18} />
      </button>
      {popover ? createPortal(popover, document.body) : null}
    </>
  );
}

function fallbackDynamics(): MarketDynamics {
  return {
    code: "UNKNOWN",
    label: "Zu wenig Daten",
    tone: "neutral",
    reason: "Für eine belastbare Dynamik fehlen noch tägliche Marktwert-Schritte.",
    recentSteps: [],
    recentVelocity: null,
    olderVelocity: null,
    streak: 0,
  };
}

function formatStep(value: number) {
  const sign = value > 0 ? "+" : "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${sign}${(value / 1_000_000).toLocaleString("de-DE", { maximumFractionDigits: 2 })} Mio.`;
  if (abs >= 1_000) return `${sign}${Math.round(value / 1_000).toLocaleString("de-DE")}k`;
  return `${sign}${value.toLocaleString("de-DE")}`;
}
