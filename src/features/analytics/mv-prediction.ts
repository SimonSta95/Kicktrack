import { invoke } from "@tauri-apps/api/core";

export type MvPredictionInput = {
  playerId: string;
  marketValue: number | null;
  marketValueChange24h: number | null;
};

export type MvPrediction = {
  playerId: string;
  delta: number | null;
  expectedValue: number | null;
  lowDelta: number | null;
  highDelta: number | null;
  confidence: "HOCH" | "MITTEL" | "UNSICHER" | string;
  sampleCount: number;
  historyDays: number;
  baselineDelta: number | null;
  method: string;
};

export type MvPredictionQuality = {
  evaluatedCount: number;
  directionHitRate: number | null;
  mae: number | null;
  medianAbsError: number | null;
  within100kRate: number | null;
  bias: number | null;
  intervalCoverage: number | null;
  highConfidenceHitRate: number | null;
  highConfidenceCount: number;
};

export type MvPredictionBatch = {
  targetDate: string;
  modelName: string;
  modelVersion: string;
  predictions: MvPrediction[];
  quality: MvPredictionQuality;
};

export function getMvPredictions(leagueId: string, inputs: MvPredictionInput[]) {
  return invoke<MvPredictionBatch>("mv_predictions", { leagueId, inputs });
}
