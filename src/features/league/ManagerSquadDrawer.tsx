import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { usePlayerDetail } from "@/features/player-detail/PlayerDetailProvider";
import "./manager-squad-drawer.css";
import { ArrowLeft, UsersRound, X } from "lucide-react";
import { getBundledTeamLogo } from "../../lib/team-assets";
import type { LeagueManager } from "./types";
import type { SquadPlayer } from "../squad/types";
import { getManagerSquad } from "./api";

const POSITION_LABEL: Record<SquadPlayer["position"], string> = {
  GOALKEEPER: "TW",
  DEFENDER: "ABW",
  MIDFIELDER: "MF",
  FORWARD: "ST",
  UNKNOWN: "—",
};

const POSITION_ORDER: Record<SquadPlayer["position"], number> = {
  GOALKEEPER: 1,
  DEFENDER: 2,
  MIDFIELDER: 3,
  FORWARD: 4,
  UNKNOWN: 5,
};

export function ManagerSquadDrawer({
  leagueId,
  manager,
  onClose,
}: {
  leagueId: string;
  manager: LeagueManager | null;
  onClose: () => void;
}) {
  const { openPlayerDetail } = usePlayerDetail();
  const query = useQuery({
    queryKey: ["league", "manager-squad", leagueId, manager?.id],
    queryFn: () => getManagerSquad(leagueId, manager!.id),
    enabled: Boolean(manager),
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });

  useEffect(() => {
    if (!manager) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [manager, onClose]);

  if (!manager) return null;

  const players = [...(query.data?.players ?? [])].sort(
    (a, b) => POSITION_ORDER[a.position] - POSITION_ORDER[b.position] || a.name.localeCompare(b.name, "de"),
  );

  return (
    <div className="manager-drawer-layer" role="presentation" onMouseDown={onClose}>
      <aside
        className="manager-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={`Kader von ${manager.name}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="manager-drawer__header">
          <div className="manager-drawer__identity">
            <span className="manager-drawer__avatar">{manager.name.slice(0, 1).toUpperCase()}</span>
            <div>
              <span className="manager-drawer__eyebrow">Manager</span>
              <h2>{manager.name}</h2>
            </div>
          </div>
          <button type="button" className="manager-drawer__close" onClick={onClose} aria-label="Schließen">
            <X size={18} />
          </button>
        </header>

        <div className="manager-drawer__meta">
          <span><strong>{manager.place ?? "—"}</strong> Rang</span>
          <span><strong>{manager.points == null ? "—" : formatNumber(manager.points)}</strong> Punkte</span>
          <span><strong>{players.length || "—"}</strong> Spieler</span>
        </div>

        <div className="manager-drawer__section-title">
          <UsersRound size={15} /> Kader
        </div>

        <div className="manager-drawer__body">
          {query.isLoading ? (
            <div className="manager-drawer__state">Kader wird geladen …</div>
          ) : query.isError ? (
            <div className="manager-drawer__state manager-drawer__state--error">
              <strong>Kader konnte nicht geladen werden.</strong>
              <button type="button" onClick={() => query.refetch()}>Erneut versuchen</button>
            </div>
          ) : players.length === 0 ? (
            <div className="manager-drawer__state">Keine Kaderspieler gefunden.</div>
          ) : (
            <div className="manager-squad-list">
              {players.map((player) => {
                const teamLogo = getBundledTeamLogo(player.teamId) ?? player.teamLogoDataUrl;
                return (
                  <button
                    type="button"
                    className="manager-squad-row manager-squad-row--interactive"
                    key={player.id}
                    onClick={() => openPlayerDetail({ playerId: player.id, leagueId, context: { source: "league", label: manager.name } })}
                    aria-label={`${player.name} öffnen`}
                  >
                    <div className="manager-squad-row__player">
                      <div className="manager-squad-row__portrait">
                        {player.portraitDataUrl ? <img src={player.portraitDataUrl} alt="" /> : <span>{player.name[0]}</span>}
                      </div>
                      {teamLogo ? <img className="manager-squad-row__team" src={teamLogo} alt="" aria-hidden /> : null}
                      <strong>{player.name}</strong>
                    </div>
                    <span className={`manager-position manager-position--${player.position.toLowerCase()}`}>
                      {POSITION_LABEL[player.position]}
                    </span>
                    <span className="manager-squad-row__value">
                      {player.marketValue == null ? "—" : formatCurrency(player.marketValue)}
                    </span>
                    <span className="manager-squad-row__points">
                      {player.pointsTotal == null ? "—" : formatNumber(player.pointsTotal)} Pkt.
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <footer className="manager-drawer__footer">
          <ArrowLeft size={14} /> Esc oder außerhalb klicken zum Schließen
        </footer>
      </aside>
    </div>
  );
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("de-DE", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 }).format(value);
}
