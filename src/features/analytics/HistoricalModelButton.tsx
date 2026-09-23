import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BrainCircuit } from "lucide-react";
import { rebuildHistoricalModels, type HistoricalModelSummary } from "./historical-model-api";
import "./historical-model-button.css";

export function HistoricalModelButton({ leagueId }: { leagueId: string }) {
  const queryClient = useQueryClient();
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState<HistoricalModelSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function rebuild() {
    if (!leagueId || running) return;
    setRunning(true);
    setError(null);
    try {
      const result = await rebuildHistoricalModels(leagueId);
      setSummary(result);
      await queryClient.invalidateQueries();
      await queryClient.refetchQueries({ type: "active" });
    } catch (cause) {
      setError(message(cause));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="historical-model-action">
      <button type="button" onClick={rebuild} disabled={running} title="22U-Walk-forward-Backtest und Liga-Preislernen aus der gesamten Historie neu aufbauen">
        <BrainCircuit size={16} />
        {running ? "Historie wird gelernt …" : "Modelle aus Historie"}
      </button>
      {summary ? <span>{summary.evaluatedSamples.toLocaleString("de-DE")} Backtests · {rate(summary.directionHitRate)}</span> : null}
      {error ? <span className="is-error">{error}</span> : null}
    </div>
  );
}

function rate(value: number | null) {
  if (value == null) return "—";
  const pct = Math.abs(value) <= 1 ? value * 100 : value;
  return `${pct.toFixed(1)} % Direction`;
}
function message(error: unknown) {
  if (typeof error === "object" && error && "message" in error && typeof (error as { message?: unknown }).message === "string") return (error as { message: string }).message;
  return "Historische Modelle konnten nicht neu aufgebaut werden.";
}
