import { invoke } from "@tauri-apps/api/core";
import type { KickbaseCommandError, LoginResult, SessionStatus } from "./types";

function normalizeCommandError(error: unknown): Error {
  if (typeof error === "string") {
    return new Error(error);
  }

  if (error && typeof error === "object") {
    const candidate = error as Partial<KickbaseCommandError>;
    if (candidate.message) {
      return new Error(candidate.message);
    }
  }

  return new Error("Kickbase ist gerade nicht erreichbar. Bitte versuche es erneut.");
}

export async function login(
  email: string,
  password: string,
  remember: boolean,
): Promise<LoginResult> {
  try {
    return await invoke<LoginResult>("login", { email, password, remember });
  } catch (error) {
    throw normalizeCommandError(error);
  }
}

export async function getSessionStatus(): Promise<SessionStatus> {
  try {
    return await invoke<SessionStatus>("session_status");
  } catch (error) {
    throw normalizeCommandError(error);
  }
}

export async function logout(): Promise<void> {
  try {
    await invoke("logout");
  } catch (error) {
    throw normalizeCommandError(error);
  }
}
