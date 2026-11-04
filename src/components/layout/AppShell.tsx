import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeEuro, BarChart3, ChevronDown, LogOut, ShoppingBag, Trophy, UsersRound } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { BrandLogo } from "@/components/branding/BrandLogo";
import { Button } from "@/components/ui/button";
import { getAccountBootstrap, getLeagueAccountContext } from "@/features/account/api";
import { logout } from "@/features/auth/api";
import { getLeagueSquad } from "@/features/squad/api";
import { getLeagueOverview } from "@/features/league/api";
import { getLeagueMarket } from "@/features/market/api";
import "./app-shell.css";

const AccountOverviewPage = lazy(() => import("@/features/account/AccountOverviewPage").then((module) => ({ default: module.AccountOverviewPage })));
const LeaguePage = lazy(() => import("@/features/league/LeaguePage").then((module) => ({ default: module.LeaguePage })));
const SquadPage = lazy(() => import("@/features/squad/SquadPage").then((module) => ({ default: module.SquadPage })));
const MarketPage = lazy(() => import("@/features/market/MarketPage").then((module) => ({ default: module.MarketPage })));
const PlayerDetailPage = lazy(() => import("@/features/player-detail/PlayerDetailDrawer").then((module) => ({ default: module.PlayerDetailPage })));
const FairValuePage = lazy(() => import("@/features/fair-value/FairValuePage").then((module) => ({ default: module.FairValuePage })));

const ACTIVE_LEAGUE_KEY = "kicktrack.activeLeagueId";

type Section = "overview" | "squad" | "league" | "market" | "fair-value" | "player";

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [selectedLeagueId, setSelectedLeagueId] = useState<string | null>(null);
  const [appVersion, setAppVersion] = useState<string | null>(null);
  const playerRouteMatch = location.pathname.match(/^\/players\/([^/]+)$/);
  const section: Section = playerRouteMatch ? "player" : location.pathname === "/squad" ? "squad" : location.pathname === "/league" ? "league" : location.pathname === "/market" ? "market" : location.pathname === "/fair-value" ? "fair-value" : "overview";
  const playerId = playerRouteMatch ? decodeURIComponent(playerRouteMatch[1]) : null;
  const playerLeagueId = section === "player" ? new URLSearchParams(location.search).get("leagueId") : null;

  useEffect(() => {
    let active = true;
    void getVersion()
      .then((version) => {
        if (active) setAppVersion(version);
      })
      .catch(() => {
        if (active && import.meta.env.DEV) setAppVersion("dev");
      });
    return () => {
      active = false;
    };
  }, []);

  const bootstrapQuery = useQuery({
    queryKey: ["account", "bootstrap"],
    queryFn: getAccountBootstrap,
  });

  useEffect(() => {
    if (!bootstrapQuery.data || selectedLeagueId) return;

    const rememberedLeague = localStorage.getItem(ACTIVE_LEAGUE_KEY);
    const usableRouteLeague = playerLeagueId != null && bootstrapQuery.data.leagues.some(
      (league) => league.id === playerLeagueId,
    );
    const usableRememberedLeague = bootstrapQuery.data.leagues.some(
      (league) => league.id === rememberedLeague,
    );

    setSelectedLeagueId(
      usableRouteLeague ? playerLeagueId : usableRememberedLeague ? rememberedLeague : bootstrapQuery.data.leagues[0]?.id ?? null,
    );
  }, [bootstrapQuery.data, playerLeagueId, selectedLeagueId]);

  const leagueQuery = useQuery({
    queryKey: ["account", "league", selectedLeagueId],
    queryFn: () => getLeagueAccountContext(selectedLeagueId!),
    enabled: Boolean(selectedLeagueId) && section === "overview",
  });

  const squadQuery = useQuery({
    queryKey: ["squad", selectedLeagueId],
    queryFn: () => getLeagueSquad(selectedLeagueId!),
    enabled: Boolean(selectedLeagueId) && section === "squad",
  });

  const leagueOverviewQuery = useQuery({
    queryKey: ["league", "overview", selectedLeagueId],
    queryFn: () => getLeagueOverview(selectedLeagueId!),
    enabled: Boolean(selectedLeagueId) && section === "league",
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });

  const marketQuery = useQuery({
    queryKey: ["market", selectedLeagueId],
    queryFn: () => getLeagueMarket(selectedLeagueId!),
    enabled: Boolean(selectedLeagueId) && section === "market",
    refetchInterval: section === "market" ? 60_000 : false,
  });

  function changeLeague(leagueId: string) {
    localStorage.setItem(ACTIVE_LEAGUE_KEY, leagueId);
    setSelectedLeagueId(leagueId);
    if (section === "player" && playerId) {
      const query = new URLSearchParams({ leagueId });
      navigate(`/players/${encodeURIComponent(playerId)}?${query.toString()}`, {
        replace: true,
        state: location.state,
      });
    }
  }

  async function handleLogout() {
    await logout();
    localStorage.removeItem(ACTIVE_LEAGUE_KEY);
    queryClient.clear();
    queryClient.setQueryData(["auth", "session"], {
      authenticated: false,
      tokenExpiresAt: null,
      remembered: false,
    });
    navigate("/login", { replace: true });
  }

  if (bootstrapQuery.isLoading) {
    return <ShellLoading label="Account und Ligen werden geladen …" />;
  }

  if (bootstrapQuery.isError) {
    return (
      <ShellError
        title="Account konnte nicht geladen werden"
        message={errorMessage(bootstrapQuery.error)}
        retry={() => bootstrapQuery.refetch()}
        logout={handleLogout}
      />
    );
  }

  const bootstrap = bootstrapQuery.data;
  if (!bootstrap) {
    return <ShellLoading label="Account und Ligen werden geladen …" />;
  }

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-sidebar__brand">
          <BrandLogo />
          <span className="app-sidebar__product">KICKTRACK</span>
        </div>

        <nav className="app-nav" aria-label="Hauptnavigation">
          <NavItem
            icon={<BarChart3 size={18} />}
            label="Übersicht"
            active={section === "overview"}
            onClick={() => navigate("/")}
          />
          <NavItem
            icon={<UsersRound size={18} />}
            label="Kader"
            active={section === "squad"}
            onClick={() => navigate("/squad")}
          />
          <NavItem
            icon={<Trophy size={18} />}
            label="Liga"
            active={section === "league"}
            onClick={() => navigate("/league")}
          />
          <NavItem icon={<ShoppingBag size={18} />} label="Markt" active={section === "market"} onClick={() => navigate("/market")} />
          <NavItem icon={<BadgeEuro size={18} />} label="Fair Value" active={section === "fair-value"} onClick={() => navigate("/fair-value")} />
        </nav>

        <div className="app-sidebar__footer">
          <div className="account-mini">
            <span className="account-mini__avatar">
              {(bootstrap.user.username ?? bootstrap.user.email ?? "K")
                .slice(0, 1)
                .toUpperCase()}
            </span>
            <div className="account-mini__text">
              <strong>{bootstrap.user.username ?? "Kickbase"}</strong>
              <span>{bootstrap.user.email ?? "Account verbunden"}</span>
            </div>
          </div>
          <Button variant="ghost" className="app-sidebar__logout" onClick={handleLogout}>
            <LogOut size={16} /> Abmelden
          </Button>
          <span className="app-sidebar__version" aria-label={appVersion ? `KickTrack Version ${appVersion}` : "KickTrack Version wird geladen"}>
            Version {appVersion ?? "…"}
          </span>
        </div>
      </aside>

      <div className="app-workspace">
        <header className="app-topbar">
          <div className="league-switcher-wrap">
            <span className="league-switcher-label">Aktive Liga</span>
            <div className="league-switcher">
              <select
                aria-label="Aktive Liga auswählen"
                value={selectedLeagueId ?? ""}
                onChange={(event) => changeLeague(event.target.value)}
              >
                {bootstrap.leagues.map((league) => (
                  <option key={league.id} value={league.id}>
                    {league.name}
                  </option>
                ))}
              </select>
              <ChevronDown size={15} aria-hidden />
            </div>
          </div>
        </header>

        <main className="app-content">
          <Suspense fallback={<ContentLoading />}>
          {section === "overview" ? (
            leagueQuery.isLoading || !leagueQuery.data ? (
              leagueQuery.isError ? (
                <InlineError message={errorMessage(leagueQuery.error)} retry={() => leagueQuery.refetch()} />
              ) : (
                <ContentLoading />
              )
            ) : (
              <AccountOverviewPage league={leagueQuery.data} />
            )
          ) : section === "squad" ? (
            squadQuery.isLoading || !squadQuery.data ? (
              squadQuery.isError ? (
                <InlineError message={errorMessage(squadQuery.error)} retry={() => squadQuery.refetch()} />
              ) : (
                <TableLoading />
              )
            ) : (
              <SquadPage players={squadQuery.data.players} leagueId={selectedLeagueId!} />
            )
          ) : section === "league" ? (
            leagueOverviewQuery.isLoading || !leagueOverviewQuery.data ? (
              leagueOverviewQuery.isError ? (
                <InlineError message={errorMessage(leagueOverviewQuery.error)} retry={() => leagueOverviewQuery.refetch()} />
              ) : (
                <TableLoading />
              )
            ) : (
              <LeaguePage
                managers={leagueOverviewQuery.data.managers}
                leagueId={selectedLeagueId!}
              />
            )
          ) : section === "fair-value" && selectedLeagueId ? (
            <FairValuePage leagueId={selectedLeagueId} />
          ) : section === "player" && playerId && (playerLeagueId ?? selectedLeagueId) ? (
            <PlayerDetailPage
              request={{
                playerId,
                leagueId: playerLeagueId ?? selectedLeagueId!,
                context: (location.state as { playerDetailContext?: import("@/features/player-detail/types").PlayerDetailContext } | null)?.playerDetailContext,
              }}
              onClose={() => {
                const returnTo = (location.state as { playerDetailReturnTo?: string } | null)?.playerDetailReturnTo;
                navigate(returnTo ?? "/");
              }}
            />
          ) : marketQuery.isLoading || !marketQuery.data ? (
            marketQuery.isError ? (
              <InlineError message={errorMessage(marketQuery.error)} retry={() => marketQuery.refetch()} />
            ) : (
              <TableLoading />
            )
          ) : (
            <MarketPage
              entries={marketQuery.data.entries}
              leagueId={selectedLeagueId!}
            />
          )}
          </Suspense>
        </main>
      </div>
    </div>
  );
}

function NavItem({
  icon,
  label,
  active,
  disabled,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      className={`app-nav__item${active ? " is-active" : ""}`}
      disabled={disabled}
      onClick={onClick}
    >
      <span className="app-nav__icon">{icon}</span>
      <span>{label}</span>
    </button>
  );
}

function ShellLoading({ label }: { label: string }) {
  return (
    <div className="shell-state">
      <BrandLogo />
      <div className="shell-state__loader" />
      <p>{label}</p>
    </div>
  );
}

function ContentLoading() {
  return (
    <div className="content-loading">
      <div className="skeleton skeleton-title" />
      <div className="skeleton-grid">
        {Array.from({ length: 3 }, (_, index) => (
          <div key={index} className="skeleton skeleton-card" />
        ))}
      </div>
    </div>
  );
}

function TableLoading() {
  return (
    <div className="content-loading">
      <div className="skeleton skeleton-title" />
      <div className="skeleton skeleton-toolbar" />
      <div className="skeleton skeleton-table" />
    </div>
  );
}

function InlineError({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div className="inline-error">
      <strong>Daten konnten nicht geladen werden.</strong>
      <p>{message}</p>
      <Button onClick={retry}>Erneut versuchen</Button>
    </div>
  );
}

function ShellError({
  title,
  message,
  retry,
  logout,
}: {
  title: string;
  message: string;
  retry: () => void;
  logout: () => void;
}) {
  return (
    <div className="shell-error-screen">
      <BrandLogo />
      <p className="eyebrow">Verbindung fehlgeschlagen</p>
      <h1>{title}</h1>
      <p>{message}</p>
      <div>
        <Button onClick={retry}>Erneut versuchen</Button>
        <Button variant="ghost" onClick={logout}>Abmelden</Button>
      </div>
    </div>
  );
}

function errorMessage(error: unknown) {
  if (typeof error === "object" && error !== null && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  return "Kickbase hat die Anfrage nicht wie erwartet beantwortet.";
}
