import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { forceRefreshLeague } from "./api";
import "./force-update.css";

const LAST_REFRESH_PREFIX = "kicktrack.forceRefresh.";

export function ForceUpdateButton({
  leagueId,
  compact = false,
  onFinished,
}: {
  leagueId: string;
  compact?: boolean;
  onFinished?: () => void;
}) {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!leagueId || phase) return;

    setError(null);
    try {
      setPhase("Kickbase-Daten werden frisch geladen …");
      await forceRefreshLeague(leagueId);

      setPhase("Analysen werden neu berechnet …");
      // The native refresh has already written today's fresh MW values.
      // Invalidate every league/analytics query so dynamics, 22U prediction,
      // league prices, trading and the visible screens rebuild from that state.
      // Manager squad drawers are inactive while closed; drop them entirely
      // so reopening a manager can never resurrect an old squad response.
      queryClient.removeQueries({
        queryKey: ["league", "manager-squad", leagueId],
      });

      await queryClient.invalidateQueries({
        queryKey: ["league", "overview", leagueId],
      });
      await queryClient.invalidateQueries();
      await queryClient.refetchQueries({ type: "active" });

      const now = new Date().toISOString();
      localStorage.setItem(`${LAST_REFRESH_PREFIX}${leagueId}`, now);
      setPhase("Aktualisiert");
      onFinished?.();

      window.setTimeout(() => setPhase(null), 1200);
    } catch (cause) {
      setPhase(null);
      setError(errorMessage(cause));
    }
  }

  return (
    <div className={`force-update${compact ? " force-update--compact" : ""}`}>
      <button type="button" className="force-update__button" onClick={run} disabled={Boolean(phase)}>
        <RefreshCw size={16} className={phase && phase !== "Aktualisiert" ? "is-spinning" : ""} />
        {phase ?? "Alle Daten aktualisieren"}
      </button>
      {error ? <span className="force-update__error">{error}</span> : null}
    </div>
  );
}

export function lastForceRefresh(leagueId: string) {
  const raw = localStorage.getItem(`${LAST_REFRESH_PREFIX}${leagueId}`);
  if (!raw) return null;
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? null : date;
}

function errorMessage(error: unknown) {
  if (typeof error === "object" && error !== null && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  return "Das Force Update konnte nicht vollständig abgeschlossen werden.";
}
