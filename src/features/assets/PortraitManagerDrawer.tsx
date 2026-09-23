import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ImageDown, RefreshCw, X, XCircle } from "lucide-react";
import { acceptPortraitCandidate, getPortraitManagerState, rejectPortraitCandidate, syncMissingPortraits } from "./api";
import "./portrait-manager.css";

export function PortraitManagerDrawer({ leagueId, onClose }: { leagueId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [lastMessage, setLastMessage] = useState<string | null>(null);
  const stateQuery = useQuery({ queryKey: ["assets", "portraits"], queryFn: getPortraitManagerState, staleTime: 0 });
  const syncMutation = useMutation({
    mutationFn: (retryFailed: boolean) => syncMissingPortraits(leagueId, retryFailed),
    onSuccess: async (summary) => {
      setLastMessage(`${summary.cached} geladen · ${summary.review} prüfen · ${summary.failed} fehlgeschlagen`);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["assets", "portraits"] }),
        queryClient.invalidateQueries({ queryKey: ["squad", leagueId] }),
        queryClient.invalidateQueries({ queryKey: ["market", leagueId] }),
      ]);
    },
  });
  const acceptMutation = useMutation({
    mutationFn: acceptPortraitCandidate,
    onSuccess: async () => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["assets", "portraits"] }), queryClient.invalidateQueries({ queryKey: ["squad", leagueId] })]);
    },
  });
  const rejectMutation = useMutation({
    mutationFn: rejectPortraitCandidate,
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["assets", "portraits"] }),
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const state = stateQuery.data;
  return <div className="portrait-manager-layer" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}>
    <aside className="portrait-manager-drawer" role="dialog" aria-modal="true" aria-label="Spielerbilder verwalten">
      <header className="portrait-manager-header">
        <div><span>ASSETS</span><h2>SPIELERBILDER</h2><p>Legacy-Mappings zuerst, FotMob nur für fehlende Zuordnungen.</p></div>
        <button type="button" onClick={onClose} aria-label="Schließen"><X size={19}/></button>
      </header>

      <div className="portrait-manager-content">
        <div className="portrait-manager-metrics">
          <Metric label="Gecached" value={state?.cached ?? 0}/><Metric label="Fehlen" value={state?.missing ?? 0}/><Metric label="Prüfen" value={state?.review ?? 0}/><Metric label="Fehler" value={state?.failed ?? 0}/>
        </div>

        <div className="portrait-manager-actions">
          <button type="button" className="is-primary" disabled={syncMutation.isPending} onClick={() => syncMutation.mutate(false)}><ImageDown size={16}/>{syncMutation.isPending ? "Wird abgeglichen …" : "Fehlende Bilder laden"}</button>
          <button type="button" disabled={syncMutation.isPending} onClick={() => syncMutation.mutate(true)}><RefreshCw size={15}/> Fehlgeschlagene erneut</button>
        </div>
        {lastMessage ? <p className="portrait-manager-message">{lastMessage}</p> : null}
        {syncMutation.isError ? <p className="portrait-manager-message is-error">{errorMessage(syncMutation.error)}</p> : null}

        <section className="portrait-review">
          <div className="portrait-review__title"><strong>Unsichere Zuordnungen</strong><span>{state?.reviewItems.length ?? 0}</span></div>
          {stateQuery.isLoading ? <p className="portrait-review-empty">Mappings werden geladen …</p> : state?.reviewItems.length ? state.reviewItems.map((item) => <article className="portrait-review-row" key={item.playerId}>
            <div className="portrait-review-names"><span>Kickbase</span><strong>{item.playerName}</strong><small>{item.clubName ?? "Verein unbekannt"}</small></div>
            <div className="portrait-review-arrow">→</div>
            <div className="portrait-review-candidate">{item.portraitUrl ? <img src={item.portraitUrl} alt="" aria-hidden /> : <div className="portrait-review-candidate__empty">?</div>}<div className="portrait-review-names"><span>FotMob</span><strong>{item.candidateName ?? "Unbekannt"}</strong><small>{item.candidateTeam ?? "Team unbekannt"}</small></div></div>
            <div className="portrait-review-confidence"><strong>{item.confidence ?? 0}%</strong><span>{item.reason ?? "Manuelle Prüfung erforderlich"}</span></div>
            <div className="portrait-review-actions"><button type="button" className="is-accept" disabled={acceptMutation.isPending || rejectMutation.isPending} onClick={() => acceptMutation.mutate(item.playerId)}><Check size={15}/> Übernehmen</button><button type="button" disabled={acceptMutation.isPending || rejectMutation.isPending} onClick={() => rejectMutation.mutate(item.playerId)}><XCircle size={15}/> Ablehnen</button></div>
          </article>) : <p className="portrait-review-empty">Keine offenen Prüffälle.</p>}
        </section>
      </div>
    </aside>
  </div>;
}

function Metric({ label, value }: { label: string; value: number }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
function errorMessage(error: unknown) { return error instanceof Error ? error.message : typeof error === "string" ? error : "Spielerbilder konnten nicht aktualisiert werden."; }
