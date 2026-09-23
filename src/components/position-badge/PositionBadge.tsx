import type { PlayerPosition } from "@/features/squad/types";
import "./position-badge.css";

const LABELS: Record<PlayerPosition, string> = {
  GOALKEEPER: "TW",
  DEFENDER: "ABW",
  MIDFIELDER: "MF",
  FORWARD: "ST",
  UNKNOWN: "—",
};

export function PositionBadge({ position }: { position: PlayerPosition }) {
  return (
    <span
      className={`position-badge position-badge--${position.toLowerCase()}`}
      aria-label={`Position ${LABELS[position]}`}
    >
      {LABELS[position]}
    </span>
  );
}
