import { invoke } from "@tauri-apps/api/core";

export type LeaguePurchaseExample = {
  playerId: string;
  playerName: string;
  transferredAt: string;
  marketValue: number;
  price: number;
  premiumPct: number;
};

export type LeaguePurchasePriceStat = {
  playerId: string;
  sampleCount: number;
  segmentSampleCount: number;
  usedSegment: boolean;
  medianPremiumPct: number | null;
  averagePremiumPct: number | null;
  p25PremiumPct: number | null;
  p75PremiumPct: number | null;
  typicalPrice: number | null;
  typicalPriceLow: number | null;
  typicalPriceHigh: number | null;
  examples: LeaguePurchaseExample[];
};

export function getLeaguePurchasePriceStats(
  leagueId: string,
  players: Array<{ playerId: string; marketValue: number | null }>,
) {
  return invoke<LeaguePurchasePriceStat[]>("league_purchase_price_stats", {
    leagueId,
    players,
  });
}
