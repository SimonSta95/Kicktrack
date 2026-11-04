import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, CircleAlert, Clock3, RefreshCw, Trophy, UserRound } from "lucide-react";
import { usePlayerDetail } from "@/features/player-detail/PlayerDetailProvider";
import { getLiveMatchday } from "./api";
import "./live-matchday.css";

export function LiveMatchdayPage({ leagueId }: { leagueId: string }) {
  const { openPlayerDetail } = usePlayerDetail();
  const query = useQuery({
    queryKey: ["live-matchday", leagueId],
    queryFn: () => getLiveMatchday(leagueId),
    refetchInterval: 30_000,
    staleTime: 10_000,
    refetchOnWindowFocus: true,
  });

  if (query.isLoading) return <LiveState>Live-Spieltag wird geladen …</LiveState>;
  if (query.isError || !query.data) return <LiveState error retry={() => query.refetch()}>Live-Daten konnten nicht geladen werden.</LiveState>;

  const data = query.data;
  const own = data.managers.find((manager) => manager.isSelf);
  const leader = data.managers[0];
  const activeManagers = data.managers.filter((manager) => manager.currentMatchdayPoints != null);
  const ownLineupTotal = data.ownLineup.reduce((sum, player) => sum + player.points, 0);

  return (
    <section className="live-page">
      <header className="live-header">
        <div><span><i/> Live Center</span><h1>SPIELTAG {data.dayNumber ?? "LIVE"}</h1><p>Aktuelle Managerpunkte und Beiträge deiner aufgestellten Spieler. Automatische Aktualisierung alle 30 Sekunden.</p></div>
        <button type="button" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw className={query.isFetching ? "is-spinning" : ""} size={15}/>Jetzt aktualisieren</button>
      </header>

      <div className="live-summary">
        <Summary icon={<Trophy size={16}/>} label="Live-Führung" value={leader?.name ?? "–"} hint={points(leader?.currentMatchdayPoints)} />
        <Summary icon={<UserRound size={16}/>} label="Dein Spieltag" value={points(own?.currentMatchdayPoints)} hint={own ? `Live-Rang ${data.managers.indexOf(own) + 1}` : "Eigener Manager nicht erkannt"} />
        <Summary icon={<Activity size={16}/>} label="Eigene Elf" value={points(ownLineupTotal)} hint={`${data.ownLineup.length} Beiträge erkannt`} />
        <Summary icon={<Clock3 size={16}/>} label="Letztes Update" value={time(data.updatedAtUnix)} hint={`${activeManagers.length}/${data.managers.length} Manager mit Live-Wert`} />
      </div>

      <div className="live-grid">
        <section className="live-card">
          <header><div><Trophy size={15}/><span>Live-Ranking</span></div><small>Kickbase-Punkte</small></header>
          <div className="live-ranking">
            {data.managers.map((manager, index) => <div className={`live-manager${manager.isSelf ? " is-self" : ""}`} key={manager.id}>
              <strong className="live-rank">{index + 1}</strong>
              <span className="live-avatar">{manager.name.slice(0, 1).toUpperCase()}</span>
              <div><strong>{manager.name}</strong><small>Saisonrang {manager.place ?? "–"} · {manager.points?.toLocaleString("de-DE") ?? "–"} Gesamtpunkte</small></div>
              <b>{points(manager.currentMatchdayPoints)}</b>
            </div>)}
          </div>
        </section>

        <section className="live-card">
          <header><div><Activity size={15}/><span>Deine Spieler</span></div><small>Aufstellung</small></header>
          {data.ownLineup.length ? <div className="live-players">
            {[...data.ownLineup].sort((a, b) => b.points - a.points).map((player) => <button type="button" key={player.playerId} onClick={() => openPlayerDetail({ playerId: player.playerId, leagueId, context: { source: "other", label: "Live-Spieltag" } })}>
              <span className="live-player-position">{position(player.position)}</span>
              <div><strong>{player.name}</strong><small>{player.status && player.status > 0 ? "Status-Hinweis" : "Aufgestellt"}</small></div>
              <b className={player.points < 0 ? "is-negative" : ""}>{points(player.points)}</b>
            </button>)}
          </div> : <div className="live-empty"><CircleAlert size={20}/><strong>{data.ownLineupAvailable ? "Noch keine Spielerpunkte" : "Aufstellung nicht verfügbar"}</strong><p>{data.ownLineupAvailable ? "Kickbase liefert für die aktuelle Aufstellung noch keine einzelnen Live-Beiträge." : "Das Live-Ranking bleibt verfügbar; die optionale Aufstellungsabfrage ist fehlgeschlagen."}</p></div>}
        </section>
      </div>
    </section>
  );
}

function Summary({ icon, label, value, hint }: { icon: ReactNode; label: string; value: string; hint: string }) {
  return <div className="live-summary__item"><div>{icon}<span>{label}</span></div><strong>{value}</strong><small>{hint}</small></div>;
}

function LiveState({ children, error = false, retry }: { children: string; error?: boolean; retry?: () => void }) {
  return <div className={`live-state${error ? " is-error" : ""}`}>{error ? <CircleAlert size={20}/> : <RefreshCw className="is-spinning" size={20}/>}<span>{children}</span>{retry ? <button type="button" onClick={retry}>Erneut versuchen</button> : null}</div>;
}

function points(value: number | null | undefined) { return value == null ? "–" : `${value.toLocaleString("de-DE")} P`; }
function time(unix: number) { return unix ? new Date(unix * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "–"; }
function position(value: number | null) { return value === 1 ? "TW" : value === 2 ? "ABW" : value === 3 ? "MF" : value === 4 ? "ST" : "–"; }
