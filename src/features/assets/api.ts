import { invoke } from "@tauri-apps/api/core";

export type PortraitReviewItem = {
  playerId: string;
  playerName: string;
  clubName: string | null;
  fotmobId: string | null;
  portraitUrl: string | null;
  confidence: number | null;
  reason: string | null;
  candidateName: string | null;
  candidateTeam: string | null;
  candidatePosition: string | null;
  candidateShirtNumber: string | null;
};

export type PortraitManagerState = {
  cached: number;
  review: number;
  failed: number;
  rejected: number;
  missing: number;
  reviewItems: PortraitReviewItem[];
};

export type PortraitSyncSummary = {
  requested: number;
  cached: number;
  review: number;
  failed: number;
  skipped: number;
};

export function getPortraitManagerState() {
  return invoke<PortraitManagerState>("portrait_manager_state");
}
export function syncMissingPortraits(leagueId: string, retryFailed = false) {
  return invoke<PortraitSyncSummary>("sync_missing_portraits", { leagueId, retryFailed });
}
export function acceptPortraitCandidate(playerId: string) {
  return invoke<boolean>("accept_portrait_candidate", { playerId });
}
export function rejectPortraitCandidate(playerId: string) {
  return invoke<boolean>("reject_portrait_candidate", { playerId });
}
