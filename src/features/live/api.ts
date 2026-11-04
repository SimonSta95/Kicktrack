import { invoke } from "@tauri-apps/api/core";
import type { LiveMatchdayResponse } from "./types";

export function getLiveMatchday(leagueId: string) {
  return invoke<LiveMatchdayResponse>("live_matchday", { leagueId });
}
