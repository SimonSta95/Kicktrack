import { useQuery } from "@tanstack/react-query";
import { getFairValueReference, getFixtureOutlook } from "./decision-intelligence-api";

export function useFairValueReference() {
  return useQuery({ queryKey: ["analytics", "fair-value-reference"], queryFn: getFairValueReference, staleTime: 30 * 60 * 1000, retry: 1 });
}

export function useFixtureOutlook() {
  return useQuery({ queryKey: ["analytics", "fixture-outlook"], queryFn: getFixtureOutlook, staleTime: 30 * 60 * 1000, retry: 1 });
}
