export type SessionStatus = {
  authenticated: boolean;
  tokenExpiresAt: string | number | null;
  remembered: boolean;
};

export type LoginResult = SessionStatus;

export type KickbaseCommandError = {
  code: string;
  message: string;
  status?: number | null;
};
