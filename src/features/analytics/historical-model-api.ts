import { invoke } from "@tauri-apps/api/core";

export type HistoricalModelSummary = {
  modelVersion: string;
  historicalSamples: number;
  evaluatedSamples: number;
  directionHitRate: number | null;
  mae: number | null;
  intervalCoverage: number | null;
};

export function rebuildHistoricalModels(leagueId: string) {
  return invoke<HistoricalModelSummary>("rebuild_historical_models", { leagueId });
}
