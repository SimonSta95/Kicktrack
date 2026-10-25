import { invoke } from "@tauri-apps/api/core";
import type { MarketValuePoint, PlayerPerformanceEntry } from "../player-detail/types";

export type MarketValueHistories = Record<string, MarketValuePoint[]>;
export type RecentFormsResponse = {
  forms: Record<string, PlayerPerformanceEntry[]>;
  unavailablePlayerIds: string[];
};

export function getMarketValueHistories(leagueId: string, playerIds: string[]) {
  return invoke<MarketValueHistories>("market_value_histories", { leagueId, playerIds });
}

export function getPlayerRecentForms(leagueId: string, playerIds: string[]) {
  return invoke<RecentFormsResponse>("player_recent_forms", { leagueId, playerIds });
}
