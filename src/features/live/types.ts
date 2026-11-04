import type { LeagueManager } from "@/features/league/types";

export type LiveLineupPlayer = {
  playerId: string;
  name: string;
  position: number | null;
  points: number;
  teamId: string | null;
  status: number | null;
};

export type LiveMatchdayResponse = {
  dayNumber: number | null;
  managers: LeagueManager[];
  ownLineup: LiveLineupPlayer[];
  ownLineupAvailable: boolean;
  updatedAtUnix: number;
};
