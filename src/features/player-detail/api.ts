import { invoke } from "@tauri-apps/api/core";
import type { PerformanceBreakdown, PlayerDetailResponse } from "./types";

export function getPlayerDetail(leagueId: string, playerId: string) {
  return invoke<PlayerDetailResponse>("player_detail", { leagueId, playerId });
}

export function getPlayerPerformanceBreakdown(leagueId: string, playerId: string, dayNumber: number) {
  return invoke<PerformanceBreakdown>("player_performance_breakdown", { leagueId, playerId, dayNumber });
}
