export type LeagueManager = {
  id: string;
  name: string;
  profileImagePath: string | null;
  isSelf: boolean;
  teamValue: number | null;
  profit: number | null;
  points: number | null;
  currentMatchdayPoints: number | null;
  averagePoints: number | null;
  matchdayWins: number | null;
  place: number | null;
};

export type LeagueOverviewResponse = {
  managers: LeagueManager[];
};
