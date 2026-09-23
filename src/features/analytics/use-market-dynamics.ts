import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { analyzeMarketDynamics, type MarketDynamics } from "./player-analytics";
import { getMarketValueHistories } from "./api";

export type DynamicsPlayerInput = {
  id: string;
  marketValue: number | null;
  marketValueChange24h: number | null;
};

export function useMarketDynamics(players: DynamicsPlayerInput[]) {
  const ids = useMemo(() => [...new Set(players.map((player) => player.id).filter(Boolean))].sort(), [players]);
  const historiesQuery = useQuery({
    queryKey: ["analytics", "market-value-histories", ids],
    queryFn: () => getMarketValueHistories(ids),
    enabled: ids.length > 0,
    staleTime: 5 * 60 * 1000,
  });

  return useMemo(() => {
    const result = new Map<string, MarketDynamics>();
    for (const player of players) {
      const history = historiesQuery.data?.[player.id] ?? [];
      result.set(player.id, analyzeMarketDynamics(history, player.marketValue, player.marketValueChange24h));
    }
    return result;
  }, [historiesQuery.data, players]);
}
