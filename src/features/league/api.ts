import { invoke } from "@tauri-apps/api/core";
import type { LeagueOverviewResponse } from "./types";
import type { SquadResponse } from "../squad/types";

export function getLeagueOverview(leagueId: string) {
  return invoke<LeagueOverviewResponse>("league_overview", { leagueId });
}

export function getManagerSquad(leagueId: string, managerId: string) {
  return invoke<SquadResponse>("manager_squad", { leagueId, managerId });
}
