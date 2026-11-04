export type PlayerDetailContext = {
  source: "squad" | "league" | "market" | "other";
  label?: string;
};

export type PlayerDetailRequest = {
  playerId: string;
  leagueId: string;
  context?: PlayerDetailContext;
};

export type MarketValuePoint = {
  date: string;
  value: number;
};

export type PlayerPerformanceEntry = {
  dayNumber: number;
  points: number | null;
  minutes: number | null;
  status: number | null;
  homeTeamId: string | null;
  awayTeamId: string | null;
  homeGoals: number | null;
  awayGoals: number | null;
  playerTeamId: string | null;
};

export type PlayerDetail = {
  id: string;
  name: string;
  firstName: string | null;
  teamId: string | null;
  clubName: string | null;
  portraitDataUrl: string | null;
  position: number | null;
  marketValue: number | null;
  marketValueChange24h: number | null;
  marketValueGainLoss: number | null;
  pointsTotal: number | null;
  averagePoints: number | null;
  status: number | null;
  statusList: number[];
  statusText: string | null;
};

export type PlayerDetailResponse = {
  player: PlayerDetail;
  marketValues: MarketValuePoint[];
  performance: PlayerPerformanceEntry[];
  transfers: PlayerTransfer[];
  transfersAvailable: boolean;
};

export type PlayerTransfer = {
  managerId: string | null;
  managerName: string | null;
  date: string;
  price: number;
  transferType: number | null;
};

export type PerformanceBreakdownItem = {
  id: string;
  label: string;
  points: number;
  count: number | null;
};

export type PerformanceBreakdown = {
  dayNumber: number;
  totalPoints: number | null;
  items: PerformanceBreakdownItem[];
};
