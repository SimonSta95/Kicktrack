import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getMvPredictions, type MvPredictionInput } from "./mv-prediction";

export function useMvPredictions(leagueId: string, inputs: MvPredictionInput[]) {
  const stableInputs = useMemo(
    () => inputs
      .filter((input) => input.playerId && input.marketValue != null)
      .map((input) => ({
        playerId: input.playerId,
        marketValue: input.marketValue,
        marketValueChange24h: input.marketValueChange24h,
      })),
    [inputs],
  );

  const signature = useMemo(
    () => stableInputs.map((input) => `${input.playerId}:${input.marketValue ?? "-"}:${input.marketValueChange24h ?? "-"}`).join("|"),
    [stableInputs],
  );

  const query = useQuery({
    queryKey: ["mv-predictions", leagueId, signature],
    queryFn: () => getMvPredictions(leagueId, stableInputs),
    enabled: Boolean(leagueId && stableInputs.length),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });

  const byPlayer = useMemo(
    () => new Map((query.data?.predictions ?? []).map((prediction) => [prediction.playerId, prediction])),
    [query.data],
  );

  return { ...query, byPlayer };
}
