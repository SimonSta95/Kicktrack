export type AccountUser = {
  id: string | null;
  email: string | null;
  username: string | null;
};

export type LeagueSummary = {
  id: string;
  name: string;
};

export type AccountBootstrap = {
  user: AccountUser;
  leagues: LeagueSummary[];
};

export type LeagueAccountContext = {
  leagueId: string;
  leagueName: string;
  budget: number | null;
  budgetAfterActiveBids: number | null;
  squadSize: number | null;
  squadLimit: number | null;
};
