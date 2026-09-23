export type PlayerPosition =
  | "GOALKEEPER"
  | "DEFENDER"
  | "MIDFIELDER"
  | "FORWARD"
  | "UNKNOWN";

export type SquadPlayer = {
  id: string;
  name: string;
  firstName: string | null;
  teamId: string | null;
  clubName: string | null;
  portraitDataUrl: string | null;
  teamLogoDataUrl: string | null;
  position: PlayerPosition;
  marketValue: number | null;
  marketValueChange24h: number | null;
  marketValueGainLoss: number | null;
  longMarketValueChange: number | null;
  pointsTotal: number | null;
  averagePoints: number | null;
  status: number | null;
  statusList: number[];
  statusText: string | null;
};

export type SquadResponse = {
  players: SquadPlayer[];
};


export type NextFixture = {
  matchId: string;
  homeTeamId: string;
  awayTeamId: string;
  homeTeamName: string;
  awayTeamName: string;
  kickoff: string | null;
};

export type NextMatchdayResponse = {
  dayNumber: number | null;
  fixtures: NextFixture[];
};
