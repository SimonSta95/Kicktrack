import { createContext, useCallback, useContext, useMemo, useState, type PropsWithChildren } from "react";
import { PlayerDetailDrawer } from "./PlayerDetailDrawer";
import type { PlayerDetailRequest } from "./types";

const PlayerDetailContext = createContext<{
  openPlayerDetail: (request: PlayerDetailRequest) => void;
  closePlayerDetail: () => void;
} | null>(null);

export function PlayerDetailProvider({ children }: PropsWithChildren) {
  const [request, setRequest] = useState<PlayerDetailRequest | null>(null);
  const openPlayerDetail = useCallback((next: PlayerDetailRequest) => setRequest(next), []);
  const closePlayerDetail = useCallback(() => setRequest(null), []);
  const value = useMemo(() => ({ openPlayerDetail, closePlayerDetail }), [openPlayerDetail, closePlayerDetail]);

  return (
    <PlayerDetailContext.Provider value={value}>
      {children}
      <PlayerDetailDrawer request={request} onClose={closePlayerDetail} />
    </PlayerDetailContext.Provider>
  );
}

export function usePlayerDetail() {
  const value = useContext(PlayerDetailContext);
  if (!value) throw new Error("usePlayerDetail must be used within PlayerDetailProvider");
  return value;
}
