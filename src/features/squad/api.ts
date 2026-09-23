import { invoke } from "@tauri-apps/api/core";
import type { NextMatchdayResponse, SquadResponse } from "./types";

export function getLeagueSquad(leagueId: string) {
  return invoke<SquadResponse>("league_squad", { leagueId });
}

export function getLeagueNextMatchday(leagueId: string) {
  return invoke<NextMatchdayResponse>("league_next_matchday", { leagueId });
}
