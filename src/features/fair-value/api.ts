import { invoke } from "@tauri-apps/api/core";
import type { FairValueDatasetResponse } from "./types";

export function getFairValueDataset(leagueId: string) {
  return invoke<FairValueDatasetResponse>("fair_value_dataset", { leagueId });
}
