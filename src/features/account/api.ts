import { invoke } from "@tauri-apps/api/core";
import type { AccountBootstrap, LeagueAccountContext } from "./types";

export function getAccountBootstrap() {
  return invoke<AccountBootstrap>("account_bootstrap");
}

export function getLeagueAccountContext(leagueId: string) {
  return invoke<LeagueAccountContext>("league_account_context", { leagueId });
}
