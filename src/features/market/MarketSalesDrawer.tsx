import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleDollarSign, Store, Trash2, X, XCircle } from "lucide-react";
import { getBundledTeamLogo } from "@/lib/team-assets";
import { getLeagueSquad } from "@/features/squad/api";
import type { SquadPlayer } from "@/features/squad/types";
import { PositionBadge } from "@/components/position-badge/PositionBadge";
import {
  acceptKickbaseSellOffer,
  acceptMarketOffer,
  declineMarketOffer,
  listMarketPlayer,
  unlistMarketPlayer,
} from "./api";
import type { MarketEntry, MarketOffer } from "./types";

type Props = {
  entries: MarketEntry[];
  leagueId: string;
  initialPlayerId: string | null;
  onClose: () => void;
  onChanged: () => Promise<void>;
};

export function MarketSalesDrawer({ entries, leagueId, initialPlayerId, onClose, onChanged }: Props) {
  const queryClient = useQueryClient();
  const squadQuery = useQuery({ queryKey: ["squad", leagueId], queryFn: () => getLeagueSquad(leagueId) });
  const listingByPlayerId = useMemo(() => new Map(entries.map((entry) => [entry.playerId, entry])), [entries]);
  const [selectedId, setSelectedId] = useState<string | null>(initialPlayerId);

  useEffect(() => {
    if (initialPlayerId) setSelectedId(initialPlayerId);
  }, [initialPlayerId]);

  useEffect(() => {
    if (selectedId || !squadQuery.data?.players.length) return;
    const firstListed = squadQuery.data.players.find((player) => listingByPlayerId.has(player.id));
    setSelectedId(firstListed?.id ?? squadQuery.data.players[0]?.id ?? null);
  }, [listingByPlayerId, selectedId, squadQuery.data]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const selectedPlayer = squadQuery.data?.players.find((player) => player.id === selectedId) ?? null;
  const selectedListing = selectedPlayer ? listingByPlayerId.get(selectedPlayer.id) ?? null : null;
  const listedCount = squadQuery.data?.players.filter((player) => listingByPlayerId.has(player.id)).length ?? 0;

  const refreshAll = async () => {
    await onChanged();
    await queryClient.invalidateQueries({ queryKey: ["squad", leagueId] });
  };

  return (
    <div className="market-sales-layer" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}>
      <aside className="market-sales-drawer" role="dialog" aria-modal="true" aria-label="Meine Verkäufe">
        <header className="market-sales-drawer__header">
          <div>
            <span className="market-sales-drawer__eyebrow">TRANSFERMARKT</span>
            <h2>MEINE VERKÄUFE</h2>
            <p>{listedCount} von {squadQuery.data?.players.length ?? 0} Spielern gelistet</p>
          </div>
          <button type="button" className="market-action-close" onClick={onClose} aria-label="Schließen"><X size={19}/></button>
        </header>

        <div className="market-sales-layout">
          <div className="market-sales-roster">
            {squadQuery.isLoading ? <div className="market-sales-state">Kader wird geladen …</div> : null}
            {squadQuery.isError ? <div className="market-sales-state is-error">Kader konnte nicht geladen werden.</div> : null}
            {squadQuery.data?.players.map((player) => {
              const listing = listingByPlayerId.get(player.id);
              return <SalePlayerRow key={player.id} player={player} listing={listing} active={player.id === selectedId} onClick={() => setSelectedId(player.id)} />;
            })}
          </div>

          <div className="market-sales-detail">
            {selectedPlayer ? (
              <SaleEditor
                key={`${selectedPlayer.id}:${selectedListing?.price ?? "unlisted"}`}
                player={selectedPlayer}
                listing={selectedListing}
                leagueId={leagueId}
                refreshAll={refreshAll}
              />
            ) : (
              <div className="market-sales-state">Wähle einen Spieler aus.</div>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}

function SalePlayerRow({ player, listing, active, onClick }: { player: SquadPlayer; listing?: MarketEntry; active: boolean; onClick: () => void }) {
  const logo = getBundledTeamLogo(player.teamId);
  return (
    <button type="button" className={`market-sales-player${active ? " is-active" : ""}`} onClick={onClick}>
      <span className="market-sales-player__portrait">{player.portraitDataUrl ? <img src={player.portraitDataUrl} alt=""/> : player.name.slice(0, 1)}</span>
      {logo ? <img className="market-sales-player__team" src={logo} alt="" aria-hidden/> : null}
      <span className="market-sales-player__name">
        {player.firstName ? <small>{player.firstName}</small> : null}
        <strong>{player.name}</strong>
      </span>
      <PositionBadge position={player.position}/>
      <span className={`market-sales-player__state${listing ? " is-listed" : ""}`}>{listing ? "Gelistet" : "Kader"}</span>
      {listing?.offerCount ? <span className="market-sales-player__offers">{listing.offerCount}</span> : null}
    </button>
  );
}

function SaleEditor({ player, listing, leagueId, refreshAll }: { player: SquadPlayer; listing: MarketEntry | null; leagueId: string; refreshAll: () => Promise<void> }) {
  const [priceText, setPriceText] = useState(() => String(listing?.price ?? player.marketValue ?? ""));
  const [message, setMessage] = useState<string | null>(null);
  const [confirmOffer, setConfirmOffer] = useState<string | null>(null);
  const price = parseEuroInput(priceText);
  const logo = getBundledTeamLogo(player.teamId);

  const listMutation = useMutation({
    mutationFn: () => listMarketPlayer(leagueId, player.id, price!),
    onSuccess: async () => { setMessage(listing ? "Verkaufspreis aktualisiert." : "Spieler auf den Markt gestellt."); await refreshAll(); },
    onError: (error) => setMessage(errorMessage(error)),
  });
  const unlistMutation = useMutation({
    mutationFn: () => unlistMarketPlayer(leagueId, player.id),
    onSuccess: async () => { setMessage("Spieler vom Markt genommen."); await refreshAll(); },
    onError: (error) => setMessage(errorMessage(error)),
  });
  const acceptMutation = useMutation({
    mutationFn: (offer: MarketOffer) => offer.isKickbase
      ? acceptKickbaseSellOffer(leagueId, player.id)
      : acceptMarketOffer(leagueId, player.id, offer.id!),
    onSuccess: async () => { setMessage("Angebot angenommen."); setConfirmOffer(null); await refreshAll(); },
    onError: (error) => setMessage(errorMessage(error)),
  });
  const declineMutation = useMutation({
    mutationFn: (offer: MarketOffer) => declineMarketOffer(leagueId, player.id, offer.id!),
    onSuccess: async () => { setMessage("Angebot abgelehnt."); await refreshAll(); },
    onError: (error) => setMessage(errorMessage(error)),
  });

  const busy = listMutation.isPending || unlistMutation.isPending || acceptMutation.isPending || declineMutation.isPending;
  const offers = listing?.offers ?? [];

  return (
    <div className="market-sale-editor">
      <div className="market-sale-editor__player">
        <span className="market-sale-editor__portrait">{player.portraitDataUrl ? <img src={player.portraitDataUrl} alt=""/> : player.name.slice(0, 1)}</span>
        <div>
          <div className="market-sale-editor__name">{logo ? <img src={logo} alt="" aria-hidden/> : null}<strong>{displayPlayerName(player.firstName, player.name)}</strong></div>
          <span>{player.marketValue == null ? "Marktwert unbekannt" : `Marktwert ${formatCurrency(player.marketValue)}`}</span>
        </div>
      </div>

      <section className="market-sale-card">
        <div className="market-sale-card__title"><Store size={16}/><div><strong>{listing ? "Verkauf verwalten" : "Auf den Markt stellen"}</strong><span>{listing ? "Preis ändern oder Listing entfernen" : "Lege deinen Verkaufspreis fest"}</span></div></div>
        <label className="market-sale-price">
          <span>Verkaufspreis</span>
          <div><input inputMode="numeric" value={priceText} onChange={(event) => { setPriceText(event.target.value); setMessage(null); }}/><span>€</span></div>
        </label>
        <div className="market-sale-actions" style={{ display: "grid", gridTemplateColumns: listing ? "1fr 1fr" : "1fr", gap: 10, marginTop: 14, minHeight: 42, visibility: "visible", opacity: 1 }}>
          {listing ? <button type="button" className="market-sale-remove" disabled={busy} onClick={() => unlistMutation.mutate()} style={{ minHeight: 42, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6, borderRadius: 6 }}><Trash2 size={15}/> Vom Markt nehmen</button> : null}
          <button type="button" disabled={busy || price == null || price <= 0} onClick={() => listMutation.mutate()} style={{ minHeight: 42, width: "100%", display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6, padding: "0 12px", border: "1px solid #ff4600", borderRadius: 6, background: "#ff4600", color: "#111214", font: "inherit", fontSize: 11, fontWeight: 800, opacity: busy || price == null || price <= 0 ? 0.45 : 1, cursor: busy || price == null || price <= 0 ? "not-allowed" : "pointer", visibility: "visible" }}><Store size={15}/>{listMutation.isPending ? "Wird gesendet …" : listing ? "Preis aktualisieren" : "Auf Markt stellen"}</button>
        </div>
        {player.marketValue != null ? <button type="button" className="market-sale-mv-shortcut" onClick={() => setPriceText(String(player.marketValue))}>Marktwert · {formatCurrency(player.marketValue)}</button> : null}
      </section>

      {listing ? (
        <section className="market-sale-card market-sale-offers">
          <div className="market-sale-card__title"><CircleDollarSign size={16}/><div><strong>Angebote</strong><span>{offers.length} verfügbar{(listing.offerCount ?? 0) > 0 ? ` · ${listing.offerCount} von Managern` : ""}</span></div></div>
          {offers.length ? offers.map((offer, index) => {
            const key = offer.id ?? `kickbase-${index}`;
            const canDecline = !offer.isKickbase && Boolean(offer.id);
            const canAccept = offer.isKickbase || Boolean(offer.id);
            const confirming = confirmOffer === key;
            return (
              <div className="market-sale-offer" key={key}>
                <div className="market-sale-offer__main">
                  <span className={`market-sale-offer__avatar${offer.isKickbase ? " is-kickbase" : ""}`}>{offer.isKickbase ? "K" : (offer.userName ?? "M").slice(0, 1).toUpperCase()}</span>
                  <div><strong>{offer.isKickbase ? "Kickbase" : offer.userName ?? "Manager"}</strong><span>{offer.price == null ? "Preis nicht lesbar" : formatCurrency(offer.price)}{offer.price != null && player.marketValue != null ? ` · ${formatDelta(offer.price - player.marketValue)} zum MW` : ""}</span></div>
                </div>
                <div className="market-sale-offer__actions">
                  {canDecline ? <button type="button" className="market-offer-decline" disabled={busy} onClick={() => declineMutation.mutate(offer)}><XCircle size={14}/> Ablehnen</button> : null}
                  {canAccept ? <button type="button" className={`market-offer-accept${confirming ? " is-confirm" : ""}`} disabled={busy} onClick={() => { if (!confirming) { setConfirmOffer(key); return; } acceptMutation.mutate(offer); }}><Check size={14}/>{confirming ? "Verkauf bestätigen" : "Annehmen"}</button> : null}
                </div>
              </div>
            );
          }) : <div className="market-sales-state is-compact">Noch keine sichtbaren Angebote.</div>}
          {(listing.offerCount ?? 0) > offers.filter((offer) => !offer.isKickbase).length ? <p className="market-offer-note">Kickbase meldet mehr Managerangebote als die API aktuell im Detail sichtbar macht.</p> : null}
        </section>
      ) : null}

      {message ? <p className={`market-sale-message${listMutation.isError || unlistMutation.isError || acceptMutation.isError || declineMutation.isError ? " is-error" : ""}`}>{message}</p> : null}
    </div>
  );
}

function parseEuroInput(value: string) {
  const normalized = value.replace(/[^0-9]/g, "");
  if (!normalized) return null;
  const number = Number(normalized);
  return Number.isSafeInteger(number) ? number : null;
}

function displayPlayerName(firstName: string | null, name: string) {
  const first = firstName?.trim();
  const display = name.trim();
  if (!first || display.toLocaleLowerCase("de-DE").startsWith(`${first.toLocaleLowerCase("de-DE")} `) || display.localeCompare(first, "de-DE", { sensitivity: "base" }) === 0) {
    return display;
  }
  return `${first} ${display}`;
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value);
}

function formatDelta(value: number) {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${formatCurrency(Math.abs(value))}`;
}

function errorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    const candidate = error as { message?: unknown; status?: unknown; code?: unknown };
    if (typeof candidate.message === "string" && candidate.message.trim()) {
      const suffix = typeof candidate.status === "number" ? ` (HTTP ${candidate.status})` : "";
      return `${candidate.message}${suffix}`;
    }
  }
  return "Kickbase hat die Aktion abgelehnt.";
}
