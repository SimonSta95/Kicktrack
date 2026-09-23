import { invoke } from "@tauri-apps/api/core";

export type TradeCycle = {
  cycleType: "CLOSED_TRADE" | "CLOSED_START_SQUAD_TRADE" | "OPEN_TRADE" | "UNPAIRED_SALE" | string;
  playerId: string;
  playerName: string;
  teamId: string | null;
  clubName: string | null;
  buyDate: string | null;
  sellDate: string | null;
  buyPrice: number | null;
  sellPrice: number | null;
  currentMarketValue: number | null;
  marketValueAtSale: number | null;
  pnl: number | null;
  roiPct: number | null;
  holdingDays: number | null;
  post3dPct: number | null;
  post7dPct: number | null;
  exitVerdict: string;
  verdict: string;
  sortDate: string;
};

export type TradingAnalysis = {
  summary: {
    closedTrades: number;
    openTrades: number;
    realizedPnl: number;
    averageRoiPct: number | null;
    timedSales: number;
    goodExits: number;
    earlyExits: number;
  };
  trades: TradeCycle[];
};

export function getTradingAnalysis(leagueId: string) {
  return invoke<TradingAnalysis>("trading_analysis", { leagueId });
}
