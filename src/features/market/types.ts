import type { PlayerPosition } from "@/features/squad/types";

export type MarketOffer = {
  id: string | null;
  userId: string | null;
  userName: string | null;
  price: number | null;
  isKickbase: boolean;
};

export type MarketEntry = {
  playerId: string;
  name: string;
  firstName: string | null;
  teamId: string | null;
  clubName: string | null;
  portraitDataUrl: string | null;
  position: PlayerPosition;
  marketValue: number | null;
  marketValueChange24h: number | null;
  price: number | null;
  priceDifference: number | null;
  pointsTotal: number | null;
  averagePoints: number | null;
  status: number | null;
  statusList: number[];
  statusText: string | null;
  sellerId: string | null;
  sellerName: string | null;
  isKickbaseSeller: boolean;
  ownOfferId: string | null;
  ownOffer: number | null;
  offerCount: number | null;
  offers: MarketOffer[];
  expiresInSeconds: number | null;
  isNew: boolean;
};

export type MarketResponse = { entries: MarketEntry[] };
export type MarketActionResult = { ok: boolean };
