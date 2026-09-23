import { invoke } from "@tauri-apps/api/core";

export type ForceRefreshResult = {
  refreshedAt: string;
  squadPlayers: number;
  marketPlayers: number;
  managers: number;
  marketValueSnapshots: number;
};

export function forceRefreshLeague(leagueId: string) {
  return invoke<ForceRefreshResult>("force_refresh_league", { leagueId });
}
