import {
  Activity,
  CircleAlert,
  CircleSlash2,
  Dumbbell,
  Plane,
  RectangleVertical,
  UserMinus,
  type LucideIcon,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { getPlayerDetail } from "@/features/player-detail/api";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent,
} from "react";
import { createPortal } from "react-dom";
import { getInwardFloatingPosition } from "../../lib/floating-position";
import "./player-status.css";

export type PlayerStatusProps = {
  status: number | null;
  statusList?: number[] | null;
  statusText?: string | null;
  compact?: boolean;
  playerId?: string;
  leagueId?: string;
};

type StatusDefinition = {
  code: number;
  label: string;
  tone: string;
  Icon: LucideIcon;
  cardTone?: "red" | "yellow" | "mixed";
};

const STATUS_DEFINITIONS: StatusDefinition[] = [
  { code: 1, label: "Verletzt", tone: "injured", Icon: Activity },
  { code: 2, label: "Angeschlagen", tone: "doubtful", Icon: CircleAlert },
  { code: 4, label: "Aufbautraining", tone: "rehab", Icon: Dumbbell },
  { code: 8, label: "Rot gesperrt", tone: "suspended", Icon: RectangleVertical, cardTone: "red" },
  { code: 16, label: "Gelb-Rot gesperrt", tone: "suspended", Icon: RectangleVertical, cardTone: "mixed" },
  { code: 32, label: "Gelb gesperrt", tone: "suspended", Icon: RectangleVertical, cardTone: "yellow" },
  { code: 64, label: "Nicht im Kader", tone: "inactive", Icon: UserMinus },
  { code: 128, label: "Nicht in Liga", tone: "inactive", Icon: CircleSlash2 },
  { code: 256, label: "Abwesend", tone: "inactive", Icon: Plane },
];

export function getPlayerStatusLabel(status: number | null, statusList?: number[] | null, statusText?: string | null) {
  const activeCodes = getActiveCodes(status, statusList);
  const definitions = activeCodes
    .map((code) => STATUS_DEFINITIONS.find((definition) => definition.code === code))
    .filter((definition): definition is StatusDefinition => Boolean(definition));

  const rawCodes = statusList?.filter((code) => code > 0) ?? [];
  const hasUnknownStatus = rawCodes.length > 0 || (status != null && status > 0);
  if (!definitions.length) {
    if (!hasUnknownStatus) return "Fit";
    const unknown = rawCodes.length ? rawCodes.join(" + ") : String(status);
    return `Unbekannter Status (${unknown})`;
  }

  const label = definitions.map((definition) => definition.label).join(" · ");
  const detail = cleanStatusText(statusText);
  if (!detail || detail.localeCompare(label, "de", { sensitivity: "base" }) === 0) return label;
  return `${label} · ${detail}`;
}

export function PlayerStatus({ status, statusList, statusText, compact = true, playerId, leagueId }: PlayerStatusProps) {
  const definitions = useStatusDefinitions(status, statusList);
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [popoverStyle, setPopoverStyle] = useState<CSSProperties>({});
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<number | null>(null);

  const primary = definitions[0];
  const inlineDetailText = cleanStatusText(statusText);
  const detailQuery = useQuery({
    queryKey: ["player-detail", leagueId, playerId],
    queryFn: () => getPlayerDetail(leagueId!, playerId!),
    enabled: Boolean(open && primary && !inlineDetailText && leagueId && playerId),
    staleTime: 5 * 60_000,
  });

  const detailText = inlineDetailText ?? cleanStatusText(detailQuery.data?.player.statusText);
  const label = definitions.map((definition) => definition.label).join(" · ");

  function cancelClose() {
    if (closeTimer.current != null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }

  function scheduleClose() {
    cancelClose();
    closeTimer.current = window.setTimeout(() => {
      if (!pinned) setOpen(false);
    }, 110);
  }

  function updatePosition() {
    const trigger = triggerRef.current?.getBoundingClientRect();
    const popover = popoverRef.current?.getBoundingClientRect();
    if (!trigger || !popover) return;
    const next = getInwardFloatingPosition(trigger, popover, { margin: 12, gap: 8 });
    setPopoverStyle({ left: next.left, top: next.top });
  }

  useLayoutEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(updatePosition);
    const onViewportChange = () => updatePosition();
    window.addEventListener("resize", onViewportChange);
    window.addEventListener("scroll", onViewportChange, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
    };
  }, [open, detailText]);

  useEffect(() => {
    if (!pinned) return;
    const onPointerDown = (event: PointerEvent) => {
      const node = event.target as Node;
      if (triggerRef.current?.contains(node) || popoverRef.current?.contains(node)) return;
      setPinned(false);
      setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [pinned]);

  useEffect(() => () => cancelClose(), []);

  function togglePinned(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();
    cancelClose();
    setPinned((current) => {
      const next = !current;
      setOpen(next);
      return next;
    });
  }

  // IMPORTANT: Do not return before the hooks above have run. Table filtering can
  // reuse a cell component for a different player. If one render has no active
  // status and the next one does, an early return before useLayoutEffect/useEffect
  // changes the hook count and React throws error #310.
  if (!primary) return null;

  const TriggerIcon = primary.Icon;
  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`player-status-trigger player-status-trigger--${primary.tone}${compact ? " is-compact" : ""}`}
        aria-label={`Status: ${label}`}
        aria-expanded={open}
        onClick={togglePinned}
        onMouseDown={(event) => event.stopPropagation()}
        onMouseEnter={() => { cancelClose(); setOpen(true); }}
        onMouseLeave={scheduleClose}
        onFocus={() => { cancelClose(); setOpen(true); }}
        onBlur={() => { if (!pinned) scheduleClose(); }}
      >
        <StatusGlyph definition={primary} Icon={TriggerIcon} />
        {definitions.length > 1 ? <span className="player-status-trigger__count">+{definitions.length - 1}</span> : null}
      </button>
      {open && typeof document !== "undefined" ? createPortal(
        <div
          ref={popoverRef}
          className="player-status-popover"
          style={popoverStyle}
          role="status"
          onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}
          onClick={(event) => event.stopPropagation()}
        >
          <span className="player-status-popover__eyebrow">Spielerstatus</span>
          <div className="player-status-popover__statuses">
            {definitions.map((definition) => (
              <span key={definition.code} className={`player-status-chip player-status-chip--${definition.tone}`}>
                <StatusGlyph definition={definition} Icon={definition.Icon} />
                {definition.label}
              </span>
            ))}
          </div>
          {detailText ? <p>{detailText}</p> : detailQuery.isFetching ? <p className="player-status-popover__loading">Details werden geladen …</p> : null}
        </div>,
        document.body,
      ) : null}
    </>
  );
}

export function PlayerStatusDetails({ status, statusList, statusText }: PlayerStatusProps) {
  const definitions = useStatusDefinitions(status, statusList);
  const detailText = cleanStatusText(statusText);

  if (!definitions.length) {
    return (
      <div className="player-status-details is-fit">
        <span className="player-status-details__dot" />
        <div><span>Status</span><strong>Fit</strong></div>
      </div>
    );
  }

  const primary = definitions[0];
  return (
    <div className={`player-status-details player-status-details--${primary.tone}`}>
      <div className="player-status-details__icon"><StatusGlyph definition={primary} Icon={primary.Icon} /></div>
      <div className="player-status-details__content">
        <span>Status</span>
        <strong>{definitions.map((definition) => definition.label).join(" · ")}</strong>
        {detailText ? <p>{detailText}</p> : null}
      </div>
    </div>
  );
}

function useStatusDefinitions(status: number | null, statusList?: number[] | null) {
  return useMemo(() => {
    const activeCodes = getActiveCodes(status, statusList);
    return activeCodes
      .map((code) => STATUS_DEFINITIONS.find((definition) => definition.code === code))
      .filter((definition): definition is StatusDefinition => Boolean(definition));
  }, [status, statusList]);
}

function StatusGlyph({ definition, Icon }: { definition: StatusDefinition; Icon: LucideIcon }) {
  return (
    <span className={`player-status-glyph${definition.cardTone ? ` is-card-${definition.cardTone}` : ""}`} aria-hidden>
      <Icon />
      {definition.cardTone === "mixed" ? <span className="player-status-glyph__second-card" /> : null}
    </span>
  );
}

function getActiveCodes(status: number | null, statusList?: number[] | null) {
  const fromList = statusList?.filter((code) => code > 0) ?? [];
  if (fromList.length) return [...new Set(fromList)];
  if (!status || status <= 0) return [];
  return STATUS_DEFINITIONS
    .filter((definition) => (status & definition.code) === definition.code)
    .map((definition) => definition.code);
}

function cleanStatusText(value?: string | null) {
  const text = value?.trim();
  if (!text || text === "-" || text.toLowerCase() === "null") return null;
  return text;
}
