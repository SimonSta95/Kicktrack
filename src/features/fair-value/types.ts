export type FairValueDatasetPlayer = {
  playerId: string;
  name: string;
  firstName: string | null;
  position: number;
  marketValue: number;
  averagePoints: number;
  totalPoints: number;
  status: number;
  ownerId: string | null;
  ownerName: string | null;
  ownerIsSelf: boolean;
  onMarket: boolean;
};

export type FairValueDatasetResponse = {
  players: FairValueDatasetPlayer[];
  managerCount: number;
  loadedManagerCount: number;
  unavailableManagerCount: number;
};

export type FairValueRating = "cheap" | "fair" | "expensive";

export type RatedFairValuePlayer = FairValueDatasetPlayer & {
  games: number;
  fairValue: number;
  gap: number;
  rating: FairValueRating;
};

export type FairValueCurvePoint = {
  points: number;
  value: number;
};

export type FairValueModel = {
  players: RatedFairValuePlayer[];
  curves: Record<number, FairValueCurvePoint[]>;
  minGames: number;
  band: number;
  typicalGap: number;
  sourceCount: number;
};
