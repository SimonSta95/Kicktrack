const teamLogoModules = import.meta.glob("../assets/teams/*.png", {
  eager: true,
  query: "?url",
  import: "default",
}) as Record<string, string>;

export function getBundledTeamLogo(teamId: string | null): string | null {
  if (!teamId) return null;
  return teamLogoModules[`../assets/teams/${teamId}.png`] ?? null;
}
