import { createContext, useCallback, useContext, useMemo, type PropsWithChildren } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { PlayerDetailRequest } from "./types";

const PlayerDetailContext = createContext<{
  openPlayerDetail: (request: PlayerDetailRequest) => void;
  closePlayerDetail: () => void;
} | null>(null);

export function PlayerDetailProvider({ children }: PropsWithChildren) {
  const navigate = useNavigate();
  const location = useLocation();
  const openPlayerDetail = useCallback((next: PlayerDetailRequest) => {
    const query = new URLSearchParams({ leagueId: next.leagueId });
    navigate(`/players/${encodeURIComponent(next.playerId)}?${query.toString()}`, {
      state: {
        playerDetailContext: next.context ?? null,
        playerDetailReturnTo: `${location.pathname}${location.search}`,
      },
    });
  }, [location.pathname, location.search, navigate]);
  const closePlayerDetail = useCallback(() => navigate(-1), [navigate]);
  const value = useMemo(() => ({ openPlayerDetail, closePlayerDetail }), [openPlayerDetail, closePlayerDetail]);

  return <PlayerDetailContext.Provider value={value}>{children}</PlayerDetailContext.Provider>;
}

export function usePlayerDetail() {
  const value = useContext(PlayerDetailContext);
  if (!value) throw new Error("usePlayerDetail must be used within PlayerDetailProvider");
  return value;
}
