import { invoke } from "@tauri-apps/api/core";
import type { MarketValuePoint } from "../player-detail/types";

export type MarketValueHistories = Record<string, MarketValuePoint[]>;

export function getMarketValueHistories(playerIds: string[]) {
  return invoke<MarketValueHistories>("market_value_histories", { playerIds });
}
