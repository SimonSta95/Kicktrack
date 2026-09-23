import { invoke } from "@tauri-apps/api/core";
import type { MarketActionResult, MarketResponse } from "./types";

export function getLeagueMarket(leagueId: string) {
  return invoke<MarketResponse>("league_market", { leagueId });
}

export function placeMarketOffer(leagueId: string, playerId: string, price: number) {
  return invoke<MarketActionResult>("market_place_offer", { leagueId, playerId, price });
}

export function withdrawMarketOffer(leagueId: string, playerId: string, offerId: string) {
  return invoke<MarketActionResult>("market_withdraw_offer", { leagueId, playerId, offerId });
}

export function listMarketPlayer(leagueId: string, playerId: string, price: number) {
  return invoke<MarketActionResult>("market_list_player", { leagueId, playerId, price });
}

export function unlistMarketPlayer(leagueId: string, playerId: string) {
  return invoke<MarketActionResult>("market_unlist_player", { leagueId, playerId });
}

export function acceptMarketOffer(leagueId: string, playerId: string, offerId: string) {
  return invoke<MarketActionResult>("market_accept_offer", { leagueId, playerId, offerId });
}

export function declineMarketOffer(leagueId: string, playerId: string, offerId: string) {
  return invoke<MarketActionResult>("market_decline_offer", { leagueId, playerId, offerId });
}

export function acceptKickbaseSellOffer(leagueId: string, playerId: string) {
  return invoke<MarketActionResult>("market_accept_kickbase_sell_offer", { leagueId, playerId });
}
