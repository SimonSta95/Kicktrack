# KickTrack V6.0.0


**Private Kickbase Analytics · Preseason + Season Command Center für Windows**

KickTrack ist eine lokale PySide6-Desktop-App zur Analyse und Steuerung einer Kickbase-Liga. KickTrack arbeitet in zwei Modi. Bis zum Saisonstart liegt der Fokus auf **Preseason**: Marktwert-Trading, Startkader-Aufbau, Gebote, Liquidität und Kaderplätze. Ab dem festgelegten Umschaltpunkt wird automatisch der **Saisonmodus** mit Spieltag, Aufstellung, Fixtures und aktueller Saisonleistung freigeschaltet.

KickTrack automatisiert keine Transfers. Schreibende Aktionen wie ein Gebot werden nur nach einer expliziten Nutzereingabe und einem zweiten Bestätigungsdialog an Kickbase gesendet; Analysen und Historien bleiben lokal.

---

## Aktueller Stand

### V6.0.0 – Full Architecture Refactor

- Die frühere UI-Monolith-Datei `app/ui.py` wurde von über 10.000 Zeilen auf rund 1.500 Zeilen reduziert und dient jetzt primär als **Composition Root** für das Hauptfenster. Markt, Intelligence, Coach, Sync, Dashboard/Kader, Liga und Transfer-/Analysefunktionen liegen in klar getrennten Feature-Mixins.
- Wiederverwendbare Qt-Bausteine und Formatierungs-/Statushelfer liegen in `app/ui_components.py`. Dialoge wurden nach Verantwortung in `player_dialogs.py`, `manager_dialogs.py` und `action_dialogs.py` getrennt; `app/dialogs.py` bleibt als kleine stabile Import-Fassade bestehen.
- Der zuvor über 1.300 Zeilen große `KickbaseClient` ist in Transport/Basis sowie die API-Domänen **Market/Transfers**, **Intelligence** und **League/Manager** zerlegt. Die öffentliche `KickbaseClient`-Schnittstelle bleibt dadurch kompatibel.
- Der verifizierte Verkaufsflow bleibt unverändert sicher: Listen, vom Markt nehmen und **an Kickbase verkaufen** sind weiterhin getrennte Aktionen; unbestätigte Manager-Offer-Writes bleiben gesperrt.
- Wildcard-Imports wurden in den refaktorierten UI-Modulen entfernt. Neue Architektur-Regressionstests verhindern, dass `ui.py`, `dialogs.py` oder `kickbase.py` wieder zu Monolithen zurückwachsen.
- Fachliche Berechnungen, Datenbank-Schema, bestehende API-Semantik und Nutzerflows wurden beim Refactor bewusst nicht neu erfunden; Ziel dieser Version ist Struktur, Wartbarkeit und geringeres Änderungsrisiko.
- Vollständige Testsuite bleibt grün. Versionsanzeigen und README auf V6.0.0 angehoben.

### V5.6.0 – Senior-Dev Cleanup & UI-Refactor

- Die zuletzt gewachsene Performance-Balkenansicht wurde aus der über 10.000 Zeilen großen `app/ui.py` in das eigenständige Modul `app/performance_chart.py` ausgelagert. Das Widget ist jetzt UI-agnostischer und erhält Club-Icons sowie Datumsformatierung über Callbacks statt über harte Abhängigkeiten.
- Die Versionsanzeige ist in `app/version.py` zentralisiert. `main.py` und das Hauptfenster verwenden jetzt dieselbe `APP_DISPLAY_NAME`-Konstante; ein Regressionstest hält App- und `pyproject.toml`-Version synchron.
- Generierte Artefakte (`build/`, `dist/`, `KickTrack.zip`, Python-/pytest-/ruff-Caches) werden nicht mehr als Projektquellen behandelt und sind in `.gitignore` sauber ausgeschlossen. Der Release-Build räumt alte Build-Verzeichnisse vor PyInstaller explizit weg.
- Doppelte Imports und zuletzt entstandene UI-Verkettungen wurden bereinigt, ohne fachliche Kickbase-Logik oder API-Endpoints zu verändern.
- Vollständige Testsuite bleibt grün.
- Versionsanzeigen und README auf V5.6.0 angehoben.

### V5.5.2 – Verifizierter Verkauf an Kickbase

- Der mit der offiziellen Android-App verifizierte direkte Kickbase-Verkauf ist jetzt sauber implementiert: `POST /v4/leagues/{leagueId}/market/{playerId}/sell` ohne Request-Body.
- Im Dialog **Verkauf verwalten** gibt es einen klar getrennten Bereich **KICKBASE-ANGEBOT** mit dem Button `AN KICKBASE VERKAUFEN`.
- Vor dem Verkauf erscheint ein ausdrücklicher Bestätigungsdialog; der Text stellt klar, dass damit ausschließlich das aktuelle Kickbase-Angebot angenommen wird und **kein Manager-Gebot** ausgewählt wird.
- Manager-Angebote im Angebots-Center bleiben weiterhin deaktiviert, bis Laden/Annehmen/Ablehnen anhand der offiziellen App verifiziert wurden.
- Regressions-Test ergänzt, der sicherstellt, dass der `/sell`-Request exakt als POST ohne Body gesendet wird.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.5.2 angehoben.

### V5.5.1 – Kickbase-Balken pro Match

- Der Performance-Bereich im Spieler-Dialog zeigt jetzt **konstante Match-Balken** statt einer Linienkurve, angelehnt an die Kickbase-App.
- Jeder Spieltag hat eine feste Breite; **Höhe und Farbe des Balkens** richten sich nach der Punktezahl. Dadurch sind gute, mittlere und schwache Spiele deutlich schneller erfassbar.
- Oberhalb jedes Balkens werden Spieltag, Paarung und – sofern vorhanden – das Ergebnis kompakt dargestellt; unterhalb stehen Punkte und Minuten.
- Ein **Klick auf einen Balken** öffnet weiterhin die echte Kickbase-Punkte-Aufschlüsselung für genau dieses Match.
- Die Ansicht zeigt jetzt auch dann eine verwertbare Historie, wenn die aktuelle Saison noch keine Spiele hat, aber aus der letzten verfügbaren Saison bereits Performance-Daten vorhanden sind.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.5.1 angehoben.

### V5.5.0 – Punkte-Aufschlüsselung pro Spiel

- Der Performance-Chart ist jetzt interaktiv: Ein Klick auf einen Spieltag lädt die echte Kickbase-Punkte-Aufschlüsselung für genau dieses Match.
- Die Match-ID wird aus `/v4/leagues/{leagueId}/players/{playerId}/performance` übernommen und über `/v4/competitions/1/playercenter/{playerId}?leagueId=...&matchId=...` aufgelöst.
- Eventnamen werden dynamisch über `/v4/live/eventtypes` (`i`/`ti`) geladen statt hart codiert oder geraten. Unbekannte IDs bleiben transparent als `Event <ID>` sichtbar.
- Der Detaildialog zeigt Minute, Punktewert und Eventname sowie Gesamtpunkte, Summe der gelieferten Punkte-Events und eine mögliche Differenz. Restpunkte werden bewusst nicht rekonstruiert.
- Playercenter-Antworten werden pro Match 30 Tage und Eventtypen 7 Tage lokal gecacht; das Öffnen des Dialogs läuft im Hintergrund und blockiert die UI nicht.
- Die Performance-Normalisierung behält `match_id`, Saison, Minuten und Ergebnisdaten und bevorzugt die aktuell markierte Saison, damit gleiche Spieltagsnummern aus alten Saisons nicht kollidieren.
- Tests für Match-ID/Saisonauswahl sowie Eventtype- und Playercenter-Normalisierung ergänzt.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.5.0 angehoben.

### V5.4.8 – 22U Cold-Start-/0€-Fix

- 22U-Prognosen nutzen bei Spielern ohne Kickbase-Live-`d1` jetzt den letzten **abgeschlossenen** MW-Refresh aus der vorhandenen 365-Tage-Historie. Ein pre-refresh Tages-Snapshot, der nur den Vortageswert dupliziert, wird nicht mehr fälschlich als `0 €`-Signal verwendet.
- Der tatsächlich verwendete Eingangstrend wird als `baseline_delta` an der Prognose gespeichert. Dadurch sind auch `MANAGER_SQUAD`-Prognosen nachvollziehbar und auswertbar.
- Die Modellgüte berücksichtigt nur Prognosen mit belegtem `baseline_delta`; alte Cold-Start-/Pseudo-0-Prognosen verfälschen die Qualitätskarte damit nicht mehr.
- Historische API-Werte des aktuellen Kalendertags werden nicht mehr als abgeschlossene Historie persistiert; der aktuelle Tag bleibt einer echten Live-Beobachtung vorbehalten.
- Regressions-Tests für Manager-Spieler ohne Live-`d1`, gespeichertes `baseline_delta` und die bereinigte Modellgüte ergänzt.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.4.8 angehoben.

### V5.4.7 – Verifizierter Listing-Flow + sicheres Angebots-Center

- Der offizielle Android-Request zum **Anbieten/Preis setzen** wurde mit HTTP Toolkit verifiziert: `POST /v4/leagues/{leagueId}/market` mit `pi` als String und `prc` als JSON-Float. KickTrack sendet den Listenpreis deshalb jetzt exakt in diesem Typ.
- **Vom Markt nehmen** ist ebenfalls gegen die offizielle App verifiziert: `DELETE /v4/leagues/{leagueId}/market/{playerId}`.
- Der Verkaufsflow enthält bewusst **keinen Sofortverkauf**. KickTrack listet Spieler nur; ein späterer Verkauf soll ausschließlich über ein konkretes Angebot erfolgen.
- Das neue **Angebots-Center** ist bereits im Verwaltungsdialog sichtbar, aber `ANGEBOTE LADEN`, `AUSGEWÄHLTES ANNEHMEN` und `AUSGEWÄHLTES ABLEHNEN` sind solange ausgegraut, bis die Requests der offiziellen App mitgeschnitten und verifiziert wurden.
- Die bisher nur aus inoffiziellen Quellen abgeleiteten Offer-Write-Methoden sind zusätzlich auf API-Ebene gesperrt, damit kein unbestätigter Endpoint versehentlich einen Verkauf auslösen kann.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.4.7 angehoben.

### V5.4.6 – Verkaufs-Endpoint korrigiert

- Der nicht funktionierende `POST /market/{playerId}/sell`-Schritt wurde aus dem Listing-Flow entfernt.
- Spieler werden jetzt direkt über den dokumentierten `POST /v4/leagues/{leagueId}/market` mit `pi` und `prc` angeboten bzw. im Preis aktualisiert.
- Dadurch besteht der Verkaufsstart nur noch aus einer einzigen schreibenden API-Aktion und kann nicht mehr zwischen Listing und Preis-Update in einen inkonsistenten Zustand laufen.
- Fehler des Markt-Writes werden weiterhin unverändert angezeigt; Kickbase bleibt die verbindliche serverseitige Instanz.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.4.6 angehoben.

### V5.4.5 – Robuster Verkaufs-Flow

- Der Verkaufs-Flow behandelt `POST /sell` und das nachgelagerte Setzen des Listenpreises jetzt als zwei getrennte Schreibschritte.
- Nach erfolgreichem Anbieten wird zunächst read-only geprüft, ob der neue Markt-Eintrag bereits sichtbar ist; erst dann wird der gewünschte Listenpreis gesetzt.
- Ein verzögert sichtbarer Markt-Eintrag oder ein `NotFound` beim Preis-Update wird nicht mehr fälschlich als komplett fehlgeschlagener Verkauf dargestellt.
- Bei Teil-Erfolg weist KickTrack ausdrücklich darauf hin, den tatsächlichen Listenpreis nach einem Markt-Refresh über `VERWALTEN` zu prüfen.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.4.5 angehoben.

### V5.4.4 – Exakte Verkaufspreise

- Der `MW`-Quickbutton im Verkaufsdialog übernimmt den aktuellen Marktwert jetzt exakt 1:1, ohne Auf- oder Abrundung.
- Beispiel: `26.913.785 €` bleibt beim Klick auf `MW` exakt `26.913.785 €`.
- Auch `+2 %`, `+5 %` und `+10 %` verwenden keine Tausender-Rundung mehr; der Prozentwert wird lediglich auf einen ganzzahligen Eurobetrag gebracht.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.4.4 angehoben.

### V5.4.3 – Verkaufspreis-Quickbuttons korrigiert

- `MW`, `+2 %`, `+5 %` und `+10 %` im Verkaufsdialog verwenden jetzt korrekt Prozentwerte statt fälschlich Faktoren wie `100.0`.
- Preise werden weiterhin sicher auf den nächsten vollen 1.000-€-Schritt aufgerundet, ohne den Zielwert zu unterschreiten.
- Beispiel: 26.913.785 € → `MW` = 26.914.000 €, nicht 2.691.378.000 €.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.4.3 angehoben.

### V5.4.2 – Verkaufspreise nie unter Zielwert gerundet

- Die Quickbuttons im Verkaufsdialog runden Listenpreise jetzt immer auf den nächsten vollen 1.000-€-Schritt auf.
- `MW` kann dadurch niemals mehr unter dem aktuellen Marktwert landen.
- Auch `+2 %`, `+5 %` und `+10 %` unterschreiten den jeweils berechneten Zielpreis nicht mehr durch kaufmännisches Abrunden.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.4.2 angehoben.

### V5.4.1 – Startup-Fix für Kickbase-Logo

- Der App-Start hängt nicht mehr an einer langsamen Pixel-für-Pixel-Auswertung des hochauflösenden Kickbase-Logos.
- Die sichtbare Logo-Fläche wird jetzt auf einem kleinen Qt-Proxybild erkannt und anschließend auf die Originalauflösung zurückgerechnet.
- Dadurch sinkt die Zahl teurer Python/Qt-Pixelzugriffe von potenziell mehreren hunderttausend auf maximal rund 32.000.
- Die Darstellung des Logos bleibt unverändert; geändert wurde nur die technische Cropping-Strategie.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.4.1 angehoben.

### V5.4.0 – Verkaufssteuerung direkt aus KickTrack

- Eigene Kaderspieler können aus der Spieler-Detailansicht direkt auf den Kickbase-Transfermarkt gesetzt werden.
- Verkaufspreis-Dialog mit Quick-Buttons für `MW`, `+2 %`, `+5 %` und `+10 %` sowie zweiter Bestätigung vor dem echten Write.
- Der Listenpreis kann bei bereits angebotenen Spielern direkt aus KickTrack geändert werden; Spieler können auch wieder vom Markt genommen werden.
- `EIGENE ANGEBOTE` hat jetzt eine `VERWALTEN`-Aktion pro Spieler. Der Verwaltungsdialog lädt die aktuellen Transfer-/Offer-Daten erst auf expliziten Klick.
- Manager-Angebote mit erkannter Offer-ID können nach Bestätigung angenommen oder abgelehnt werden. Kickbase-Systemangebote werden separat behandelt.
- Nach Verkaufsaktionen werden Markt, Budget und eigener Kader gezielt neu synchronisiert. Tabwechsel bleiben frei von versteckten Write-/Offer-Requests.
- Schreib-Endpunkte sind defensiv gekapselt; Kickbase bleibt die verbindliche serverseitige Instanz.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.4.0 angehoben.

### V5.3.7 – Spielerzelle mit mehr Platz für Namen

- Die Spieler-Spalte im Transfermarkt ist breiter und hat eine höhere Mindestbreite, damit längere Namen nicht vom Statussymbol verdrängt werden.
- Avatar und Statussymbol wurden leicht verkleinert; Innenabstände und Spacing sind kompakter.
- Der Spielername bleibt der flexible Hauptbereich der Zelle, während das Statussymbol nur einen kleinen festen Bereich rechts belegt.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.3.7 angehoben.

### V5.3.6 – Spielerzellen ohne Doppelrendering

- Spielerzellen mit Statussymbol wurden technisch bereinigt: der native Tabellen-Text wird bei Custom-Widgets nicht mehr zusätzlich unter dem Widget gerendert.
- Dadurch verschwinden doppelte/übereinanderliegende Spielernamen und Portraits.
- Neues Layout der Spielerzelle: Portrait links, Name mittig/expandierend, Statussymbol sauber am rechten Zellrand.
- Die Statussymbole überlagern weder Portrait noch Namen; Sortier- und Klickdaten bleiben weiterhin im zugrunde liegenden Tabellenitem erhalten.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.3.6 angehoben.

### V5.3.2 – 22U-Evaluation repariert

- Die Auswertung der 22-Uhr-Marktwertprognose matched Ist-Werte nicht mehr nur über das Kalenderdatum. Ein vor 22 Uhr gespeicherter Tageswert kann dadurch nicht mehr fälschlich als Ergebnis desselben 22-Uhr-Refreshs gelten.
- Als Ist-Wert zählt nur noch eine echte Live-Beobachtung **nach** dem Ziel-Refresh und **vor** dem darauffolgenden Refresh. Wird KickTrack erst am nächsten Morgen geöffnet, wird dieser Wert korrekt dem Refresh des Vorabends zugeordnet.
- Bereits vorhandene Auswertungen werden beim nächsten Markt-Load erneut auditiert: fehlerhafte Legacy-Matches werden repariert; fehlt eine belastbare Post-Refresh-Beobachtung, fliegt die Prognose aus der Qualitätsstatistik statt mit einem erfundenen Ist-Wert gewertet zu werden.
- Live-Marktwert-Snapshots werden explizit als `live` markiert und nach Europe/Berlin datiert; importierte historische Werte bleiben davon getrennt.
- Die Detailansicht der Modellgüte zeigt bei den letzten Auswertungen zusätzlich den Zeitpunkt der verwendeten Ist-Beobachtung.
- Das eigentliche Prognosemodell wurde bewusst noch **nicht** neu gewichtet. Erst die reparierte Evaluation soll zeigen, wie gut oder schlecht die Prognose wirklich ist.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.3.2 vereinheitlicht.

### V5.3.1 – Markt-Detail UI-Cleanup

- Die Aktionsleiste im Markt-Detail wurde neu aufgebaut und gequetschte Buttons entfernt.
- `DETAILS` und `BIETEN` stehen jetzt sauber nebeneinander; `FINANZIERUNG` sitzt in einer eigenen zweiten Zeile über die volle Breite.
- `BIETEN` ist optisch als Primäraktion hervorgehoben, während Nebenaktionen bewusst zurückhaltender bleiben.
- Mindesthöhen, Breitenverhalten und Tooltips der Buttons wurden überarbeitet, damit auch `GEBOT ÄNDERN` nicht mehr unschön abgeschnitten wird.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.3.1 vereinheitlicht.

### V5.3.0 – Gebote direkt aus KickTrack

- Im Markt-Detail kann über `BIETEN` bzw. `GEBOT ÄNDERN` ein echtes Kickbase-Gebot abgegeben werden.
- Quick-Buttons für `MW`, `+1 %`, `+2 %` und `+5 %`.
- Lokale Vorprüfung der dokumentierten 33%-Regel mit aktuellem Kaderwert, nach aktiven Geboten verfügbarem Kontostand und bestehendem Gebot auf denselben Spieler.
- Gebote unter aktuellem Marktwert oder oberhalb der lokalen Kreditgrenze werden vor dem Request blockiert.
- Vor jedem POST erscheint ein zweiter expliziter Bestätigungsdialog; Kickbase bleibt die verbindliche serverseitige Instanz.
- Erfolgreiche Gebote lösen anschließend einen Markt-Refresh aus, damit Budget und eigenes Gebot sofort aktualisiert werden.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.3.0 vereinheitlicht.

### V5.2.0 – Punkteverlauf im Spieler-Detail

- Der Performance-Tab im Spieler-Detail zeigt jetzt ein eigenes Diagramm mit den Kickbase-Punkten pro Spieltag der aktuellen Saison.
- Der gesamte Saisonverlauf bleibt in einer kompakten Linie sichtbar; per Hover erscheinen Spieltag, Punkte sowie Datum und Paarung, soweit Kickbase diese Felder liefert.
- Vor dem Saisonstart werden bewusst keine alten Saisonwerte als aktuelle Performance dargestellt.
- Eine Punkte-/Ereignis-Aufschlüsselung wird nicht künstlich rekonstruiert: Der verwendete Kickbase-Performance-Endpunkt liefert derzeit nur verlässliche Gesamtpunkte pro Spieltag, keine belastbare Einzelpunkte-Historie nach Aktionen.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.2.0 vereinheitlicht.

### V5.1.2 – Schneller Markt & Kader

- Markt-Navigation nutzt bereits geladene Daten und startet nicht mehr bei jedem Tab-Klick automatisch einen API-Refresh.
- Der normale Markt-Load erzeugt keine zusätzlichen Player-Detail-Requests mehr, nur um fehlende 24h-MW-Werte nachzuladen; fehlende Werte bleiben bis zu einem expliziten Datenlauf leer.
- `ANBIETER` ist wieder als eigene Transfermarkt-Spalte sichtbar (`Kickbase` oder Managername).
- Der Kader-Tab berechnet das 22U-Modell nicht mehr bei jedem Render neu, sondern verwendet bereits gespeicherte Prognosen.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.1.2 vereinheitlicht.

### V5.1.1 – Kompaktere Trade-Bewertung

- Die Spalte `BEWERTUNG` in den live-bewerteten Trades verwendet jetzt kurze, vollständig lesbare Labels wie `STAMM`, `INVEST`, `VERKAUF`, `TRADE+`, `SOLIDE` und `VERLUST`.
- Die vollständige ursprüngliche Bewertung bleibt im Tooltip erhalten; es gehen keine Bewertungsinformationen verloren.
- Trade-Zeilen wurden von 48 px auf 34 px verdichtet und die Spaltenbreiten für eine kompaktere Tabelle angepasst.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.1.1 vereinheitlicht.

### V5.1.0 – Watchlist & Spieler-Vergleich

- Persistente, liga-spezifische Watchlist in SQLite ergänzt.
- Spieler können direkt im Spieler-Detail per `☆/★ WATCHLIST` hinzugefügt oder entfernt werden.
- Der Transfermarkt hat einen neuen `★ Watchlist`-Filter für aktuell angebotene beobachtete Spieler.
- Neuer Spieler-zu-Spieler-Vergleich direkt aus dem Spieler-Detail.
- Der Vergleich zeigt ausschließlich nachvollziehbare Fakten wie Marktwert, 24H/3T/7T/30T-Trend, Position, Verein, Besitzer und Status; Saisonpunkte werden erst im Saisonmodus eingeblendet.
- Bewusst kein Gesamt-/Gewinner-Score und keine persönlichen Notizen.
- Versionsanzeigen in App, `pyproject.toml` und README auf V5.1.0 vereinheitlicht.

### V5.0.6 – Pitch-Layout & Drag-and-Drop

- Die Startelf-Vorschau nutzt pro Positionsreihe ein eigenes symmetrisches Layout statt eines starren 7-Spalten-Grids.
- Dynamische Kartenbreiten und zusätzliche Außenabstände verhindern, dass 5er-/6er-Reihen am Pitch-Rand kleben, überlappen oder angeschnitten wirken.
- STAMM-Spieler können per Drag & Drop innerhalb ihrer Positionsreihe frei umsortiert bzw. auf einen leeren Slot verschoben werden.
- Die manuelle Slot-Reihenfolge bleibt pro Formation während der laufenden App-Sitzung erhalten und wird bei Kaderänderungen sauber mit neuen/entfernten Spielern abgeglichen.
- Drag & Drop bleibt positionskorrekt: ABW, MF und ST können nur innerhalb ihrer jeweiligen Reihe verschoben werden.
- Versionsanzeigen in App, `pyproject.toml` und README wurden auf V5.0.6 vereinheitlicht.

### V5.0.5 – Startelf-Formationen & UI-Fix

- Die Startelf-Vorschau auf der Kaderseite unterstützt jetzt `AUTO` sowie alle 10 hinterlegten legalen Kickbase-Formationen.
- Auch unvollständige Formationen bleiben beim Startkader-Bau auswählbar; leere Positionsslots werden passend zur gewählten Formation dargestellt.
- Die Pitch-Anordnung nutzt ein symmetrischeres Raster für 3er-, 4er-, 5er- und 6er-Reihen.
- Der Startkader-/Lineup-Optimizer kennt zusätzlich `3-6-1`, `4-2-4` und `5-2-3`.
- Fix: `QSizePolicy` wird in `ui_v4_components.py` korrekt importiert; dadurch startet die App nach dem Pitch-Umbau wieder ohne `NameError`.
- Versionsanzeigen in App, `pyproject.toml` und README wurden auf V5.0.5 vereinheitlicht.

### V5.0.4 – Portraits im Release-Build

- Bereits lokal gecachte Spielerportraits können vor einem Release automatisch nach `assets/portraits/` kopiert werden.
- PyInstaller nimmt sie über das bestehende `--add-data "assets;assets"` mit in den Build.
- Die App bevorzugt einen vorhandenen lokalen Portrait-Cache und verwendet gebündelte Portraits als sofort verfügbaren Fallback.
- Bei einem frischen Empfängerprofil werden gebündelte Portraits beim Spielerpool-Sync automatisch als `CACHED` übernommen.
- Neue oder später aktualisierte Portraits landen weiterhin im schreibbaren lokalen KickTrack-Datenordner; der installierte Build muss dafür nicht verändert werden.
- `build_release.ps1` erledigt Portrait-Vorbereitung, PyInstaller-Build und ZIP-Erstellung in einem Durchlauf.

### V5.0.3 – Startbestand & Exit-Historie

- Ein Spieler, dessen **erster beobachteter eigener Transfer ein Verkauf** ist, wird jetzt als rekonstruierter Startbestand erkannt, wenn bereits Marktwert-Historie auf/vor dem Verkauf existiert.
- Für diese Spieler wird der **früheste gespeicherte Start-MW** als Einstieg verwendet und der tatsächliche Verkaufserlös dagegen gerechnet.
- Dadurch bekommen früh verkaufte Startspieler eine echte Gewinn-/Verlust- und ROI-Bewertung statt `? → Verkauf` / `UNPAIRED_SALE`.
- Verkaufte eigene Spieler erhalten ihre offizielle **365-Tage-MW-Historie** im Hintergrund nachgeladen und lokal gecacht. Dadurch können +3T/+7T-Exit-Bewertungen nachträglich berechnet werden, auch wenn der Spieler längst nicht mehr im eigenen Kader ist.
- Verkäufe ohne beobachteten Kauf **und ohne historische Startbestands-Evidenz** bleiben bewusst ohne erfundenen Einstiegspreis.
- Aktuell gehaltene `STAMM`-/`INVEST`-/`TRANSFERLISTE`-Spieler bleiben Live-Positionen und erhalten weiterhin kein Exit-Timing vor einem echten Verkauf.

### V5.0 – automatischer Saisonmodus

- Automatischer Wechsel **am 21.08.2026 um 22:00 Uhr (Europe/Berlin)**.
- Vorher bleibt die App im `PRESEASON`-Modus.
- Ab dem Umschaltpunkt wird `SAISON` aktiv und die Navigation **Spieltag** freigeschaltet.
- Die Spieltag-Seite nutzt bereits vorhandene Fixtures, Lineup-Optimizer und Liga-Intelligence.
- Kader, Markt und Coach verwenden aktuelle Saisonpunkte erst dann, wenn Kickbase sie als aktuelle Saisonwerte geliefert hat; dadurch werden keine alten Saisonwerte fälschlich verwendet.
- Während die App offen ist, prüft sie den Modus alle 30 Sekunden und aktualisiert beim Wechsel automatisch.
- Unter **Einstellungen → App-Modus** kann `PRESEASON` oder `SAISON` zum Testen erzwungen werden. `AUTOMATISCH` stellt wieder den echten Zeitplan her.

V5.0 verwendet die bestehende Kickbase-CI mit dunklem UI, KB-Pitch-Headlines und KB-Volksans-UI-Schrift, sofern die Fonts lokal vorhanden sind. Der V4-Umbau verschiebt die Oberfläche von einer klassischen KPI-/Tabellen-App zu einem **Manager Command Center**.

Wichtige UI-Prinzipien:

- Spieler stehen visuell im Mittelpunkt, inklusive lokal gecachter Portraits.
- Budget, Kaderbelegung, aktive Gebote und Deadline bleiben global sichtbar.
- Entscheidungen werden als konkrete Aktionen dargestellt statt als immer mehr Kennzahlen.
- Der Transfermarkt arbeitet als **Master/Detail-Ansicht**: links auswählen, rechts analysieren.
- Die Kaderseite zeigt Startelf, Bank/Investments und darunter die vollständige Detailansicht.
- Die Seite scrollt als Ganzes; die Kader-Tabelle besitzt keine eigene vertikale Scrollfläche.
- Die harte Kickbase-Kadergrenze von **18 Spielern** wird zentral berücksichtigt.


### V4.5 – Eigene Angebote & Statusanzeige

- Transfer-Übersicht zeigt **Eigene Angebote** mit Portrait, Verein, Position, Status, Marktwert, 24h-Trend, Listenpreis, aktuell erzielbarem Erlös, Differenz zum Marktwert und Rolle.
- Der aktuell erzielbare Erlös folgt der Kickbase-Regel `max(Listenpreis, aktueller Marktwert)` und wird zusätzlich als Gesamtsumme dargestellt.
- Verfügbarkeitsstatus sind im Redesign wieder sichtbar: ✓ FIT, Verletzung, angeschlagen, Aufbautraining, Sperren und Abwesenheit werden in Kader, Markt, Coach und eigenen Angeboten angezeigt.

### V4.4-Fix

Die Markt-Detailansicht nutzt den **direkt angeklickten Spielerdatensatz** als einzige Datenquelle. Hover-Zustände, Sortierung und Zeilenindizes können den rechten Bereich nicht mehr überschreiben. Die Auswahl wird zusätzlich über die Kickbase-Player-ID gehalten und nach einem Refresh wieder auf den aktuellen Datensatz gemappt. Für das rechte Marktpanel wird bewusst kein Opacity-/Fade-Effekt mehr verwendet.

---

## Funktionen

### Übersicht / Command Center

- globaler Liga- und Manager-Kontext
- aktuelles Budget
- Kaderbelegung `x / 18`
- offene Gebote
- relevante Deadline
- Tagesfokus und priorisierte Aktionen
- globale Spielersuche über den lokalen Player-Master

### Kader

- Rollen wie `STAMM`, `INVEST` und `TRANSFERLISTE`
- Startelf-Vorschau mit Portraits
- Bank-/Investment-Strip
- Marktwert- und P/L-Entwicklung
- Startkader-/Trade-Einordnung
- Spielerstatus
- vollständige Detailtabelle
- zentrale Prüfung der 18er-Kadergrenze

### Transfermarkt

- Marktspieler inkl. eigenem Gebot
- 24h-Marktwertänderung
- Prognose für den nächsten 22-Uhr-Refresh
- Value Score
- Startkader- und Trade-Fit
- Empfehlungen: `KADERZIEL`, `INVEST`, `BEOBACHTEN`, `PASS`
- Max-Bid
- Liga-Lernmodell
- MW-Scanner
- Startkader-Optimizer
- Finanzierung
- Master/Detail-Ansicht mit Portrait, Preisen, Score-Bars, Trends und Entscheidungsgründen

### Transfers

Transfers werden als **Trade-Zyklen** betrachtet. Ein zugehöriger Kauf und Verkauf werden zu einem Trade zusammengeführt.

Bewertet werden unter anderem:

- Kaufpreis
- Verkaufspreis
- realisierter Gewinn/Verlust
- ROI
- Haltedauer
- Marktwertentwicklung nach dem Verkauf
- Exit-Timing nach 3 und 7 Tagen

Ein offener Spieler wird nicht allein wegen eines negativen Marktwertverlaufs als `FEHLKAUF` bezeichnet. Eine echte kombinierte sportlich/finanzielle Kaufbewertung ist für den Saisonbetrieb vorgesehen, sobald belastbare Punkte während der jeweiligen Besitzdauer vorliegen.

### Coach

Der Coach ist eine priorisierte Action Queue und keine zweite Analyseseite.

Marktaktionen:

- `KADERZIEL`
- `INVEST`
- `BEOBACHTEN`
- `PASS`

Eigener Kader:

- `HALTEN`
- `INVEST HALTEN`
- `VERKAUF WARTEN`
- `VERKAUFEN`

Bei `18 / 18` wird ein neuer Spieler nicht mehr als isolierter Kauf empfohlen. Ein Zugang muss dann als **Upgrade mit notwendigem Abgang** betrachtet werden.

---

## Saisonmodus

Der UI-Modus und die Verfügbarkeit echter Saisonpunkte sind bewusst getrennt.

- **UI-Modus:** schaltet zeitgesteuert am 21.08.2026 um 22:00 Uhr Europe/Berlin auf Saison.
- **Saisonstats:** werden nur verwendet, wenn der Liga-Sync bestätigt, dass aktuelle Saisonpunkte vorliegen.

Dadurch wird die Saisonoberfläche pünktlich freigeschaltet, ohne dass alte Vorjahreswerte versehentlich in sportliche Entscheidungen einfließen. Im Saisonmodus wird die bisherige Analyse-Navigation als **Spieltag** sichtbar. Dort liegen Aufstellung/Lineup-Optimizer, nächste Gegner, Fixture-Einordnung und Liga-Intelligence. Dashboard, Kader und Coach wechseln gleichzeitig auf saisonale Texte und Prioritäten.

## Preseason-Logik

Die Preseason-Version vermeidet bewusst scheinpräzise Saisonprognosen ohne aktuelle Saisonbasis.

Grundregeln:

- Vorjahrespunkte treiben keine aktuellen Kaufentscheidungen.
- Marktwertentwicklung und tatsächliche Ligadaten haben Vorrang.
- Der Max-Bid bleibt wirtschaftlich begrenzt; ein historisch hoher Liga-Zuschlag erhöht ihn nicht automatisch.
- `Cash - offene Gebote` ist die relevante Liquidität nach möglichen Zuschlägen.
- Spieler auf der Transferliste sind potenzielles Verkaufskapital, aber kein bereits vorhandenes Cash.
- Andere Manager-Budgets werden **nicht geschätzt**.
- Die Kadergrenze beträgt global `18`.

Die zentrale Regel liegt in `app/squad_rules.py`.

---

## Player-Master & Portraits

KickTrack führt einen lokalen Player-Master auf Basis des aktuellen Kickbase-Bundesliga-Spielerpools.

Gespeichert werden unter anderem:

- Kickbase-Player-ID
- Kurz-/Vollname
- Verein
- Position
- Aktivitätsstatus
- `first_seen` / `last_seen`
- FotMob-Mapping
- Match-Sicherheit
- lokaler Portrait-Cache

Spieler werden nicht gelöscht, nur weil sie bei einem Sync fehlen. Der Status durchläuft sinngemäß:

- `ACTIVE`
- `UNKNOWN`
- `LEFT_LEAGUE`

Neue Kickbase-Spieler können dadurch automatisch erkannt und in die Portrait-Queue aufgenommen werden.

### Portrait-Matching

Portraits werden lokal gecacht. Unsichere Zuordnungen landen in `NEEDS_REVIEW` und können unter **Einstellungen → Portraits prüfen** kontrolliert werden.

Die Review-Ansicht zeigt, soweit vorhanden:

- Kickbase-Spieler
- Verein
- Position
- Marktwert
- Kickbase-ID
- FotMob-Kandidat
- FotMob-ID
- Match-Sicherheit
- Match-Begründung
- Portrait-Vorschau

Ein Kandidat kann übernommen oder dauerhaft abgelehnt werden. Abgelehnte Zuordnungen lassen sich später zurücksetzen.

Für ungelöste Kurz-/Nachnamen versucht KickTrack gezielt, den vollständigen Namen aus dem Kickbase-Spielerdetail nachzuladen, bevor weitere Heuristiken verwendet werden.

> FotMob ist keine offizielle Datenquelle dieses Projekts. Deren Nutzungsbedingungen können automatisierte/systematische Nutzung einschränken. Das Portrait-Modul ist deshalb technisch vom Player-Master getrennt und kann später gegen einen anderen Provider ausgetauscht werden.

---

## Marktwert-Historie & Modell

KickTrack speichert Marktwert-Snapshots in SQLite und verwendet sie für:

- 24h / 3T / 7T / 14T / 30T-Verläufe
- Momentum und Beschleunigung
- historische Trade-Auswertung
- Exit-Timing
- 22-Uhr-MW-Prognosen
- Modellgüte / Backtesting

22-Uhr-Prognosen werden gespeichert und nach dem Ziel-Refresh gegen den tatsächlichen Wert ausgewertet. Dadurch kann die Modellgüte über die Zeit gemessen werden.

---

## Projektstruktur

```text
KickTrack/
├─ app/
│  ├─ ui.py                    # Hauptfenster, Pages, Dialog-Orchestrierung
│  ├─ ui_v4_components.py      # wiederverwendbare V4-Komponenten
│  ├─ theme.py                 # konsolidiertes KickTrack/Kickbase-CI Theme
│  ├─ kickbase.py              # Kickbase-API-Client und Parsing
│  ├─ storage.py               # SQLite, Cache, Historien, Settings
│  ├─ player_master.py         # Player-Master und Portrait-Resolver
│  ├─ market_analysis.py       # Marktanalyse
│  ├─ coach_analysis.py        # Coach-Entscheidungen
│  ├─ preseason_tools.py       # Preseason-Optimizer / Value-Logik
│  ├─ transfer_evaluation.py   # Trade-Zyklen und Timing
│  ├─ squad_rules.py           # zentrale Kaderregeln, MAX_SQUAD_SIZE = 18
│  ├─ mv_prediction.py         # Marktwert-Prognose
│  ├─ league_learning.py       # historische Liga-Lernwerte
│  └─ services/                # Sync-/League-/Transfer-Services
├─ assets/
│  ├─ clubs/                   # Vereinslogos
│  └─ clubs_png/
├─ tests/
├─ tools/
│  └─ install_kickbase_fonts.py
├─ main.py
├─ requirements.txt
├─ pyproject.toml
└─ README.md
```

`app/ui.py` ist historisch noch groß. Neue V4-Präsentationskomponenten liegen bereits separat in `app/ui_v4_components.py`. Weitere UI-Seiten können künftig schrittweise ausgelagert werden, ohne API- oder Storage-Logik neu zu schreiben.

---

## Voraussetzungen

- Windows 10/11
- Python **3.11 oder neuer**
- Internetzugriff für Kickbase-Sync und optionale externe Portrait-Auflösung

Python-Abhängigkeiten:

- PySide6
- httpx
- keyring
- tzdata

---

## Installation

### Schnellstart unter Windows

Im Projektordner:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Alternativ können `setup.bat` und `start.bat` verwendet werden.

### Entwicklungsinstallation

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

---

## Lokale Daten

Die produktive SQLite-Datenbank liegt standardmäßig unter:

```text
%APPDATA%\KickTrack\kicktrack.db
```

Darin befinden sich unter anderem:

- Liga-/Manager-Einstellungen
- aktuelle Spielerzustände
- Marktwert-Historien
- Transferhistorie
- Modellprognosen und deren Auswertung
- Player-Master
- Portrait-Mappings

Portraitdateien werden separat im lokalen KickTrack-Datenbereich gecacht.

Die Datenbank sollte bei Updates der App **nicht** durch eine leere Projekt-DB ersetzt werden.

---

## Kickbase-CI Fonts

KickTrack enthält **keine** Kickbase-Fontdateien.

Wenn die offiziellen Pakete `KB_Volksans.zip` und `KB_Pitch.zip` lokal vorhanden sind, können sie in folgenden Ordner gelegt werden:

```text
assets/fonts/packages/
```

KickTrack registriert die Fonts dann beim App-Start nur für den laufenden Prozess. Eine systemweite Windows-Installation ist nicht erforderlich.

Alternativ:

```powershell
python tools/install_kickbase_fonts.py "C:\Pfad\KB_Volksans.zip" "C:\Pfad\KB_Pitch.zip"
```

Ohne KB-Fonts verwendet die App definierte Fallback-Schriften.

---

## Tests & Qualität

Testlauf:

```powershell
pytest
```

Syntax-/Import-Check:

```powershell
python -m compileall app
```

Der V4.4-Stand läuft aktuell vollständig durch die vorhandene Testsuite.

Optional mit Ruff:

```powershell
ruff check .
```

---

## Build als Windows-App

### Empfohlener Release-Build

Der einfachste Weg ist das mitgelieferte PowerShell-Skript:

```powershell
.\build_release.ps1
```

Es führt nacheinander aus:

1. `tools/prepare_build_portraits.py` kopiert deinen lokalen Portrait-Cache aus `%APPDATA%\KickTrack\player_portraits` nach `assets\portraits`.
2. PyInstaller baut KickTrack inklusive des kompletten `assets`-Ordners.
3. `dist\KickTrack` wird als `KickTrack.zip` gepackt.

Damit sind vorhandene Portraits direkt beim Empfänger sichtbar. Neue Portraits werden später weiterhin lokal gecacht.

Manuell entspricht das im Wesentlichen:

```powershell
python .\tools\prepare_build_portraits.py

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --noupx `
  --name "KickTrack" `
  --icon "assets\kickbase_icon.ico" `
  --add-data "assets;assets" `
  main.py

Compress-Archive `
  -Path .\dist\KickTrack\* `
  -DestinationPath .\KickTrack.zip `
  -Force
```

### Fonts

Wenn deine lokalen KB-Fontpakete unter `assets\fonts\packages` liegen, werden sie durch `--add-data "assets;assets"` ebenfalls in den Build aufgenommen. Sie werden von KickTrack nur für die App registriert und nicht systemweit unter Windows installiert.

### Portraits

Die Build-Kopien liegen unter `assets\portraits`. Der normale Laufzeitcache bleibt unter `%APPDATA%\KickTrack\player_portraits`. Die App bevorzugt den Laufzeitcache; fehlt dort ein Bild, wird die gebündelte Version verwendet.

Vor einem Build sollte geprüft werden, welche externen Assets du tatsächlich weitergeben darfst. Private Datenbanken und Zugangsdaten gehören nicht in das Distributionspaket.

---

## API-Hinweis

KickTrack verwendet eine **nicht offiziell dokumentierte öffentliche Drittanbieter-Schnittstelle** von Kickbase. Endpunkte oder Payload-Strukturen können sich ändern.

Deshalb gilt im Projekt:

- API-spezifisches Parsing bleibt möglichst in `app/kickbase.py`.
- Daten werden lokal gecacht, um unnötige Requests zu reduzieren.
- vollständige Liga-/Team-Syncs werden nur dort eingesetzt, wo sie fachlich nötig sind.
- bei unklaren API-Feldern werden keine Fantasiewerte erzeugt.

KickTrack ist ein privates Analyseprojekt und nicht mit Kickbase bzw. der DFL verbunden.

---

## Aktuelle Navigation

Die sichtbare Preseason-Navigation besteht aus:

1. **Übersicht**
2. **Kader**
3. **Markt**
4. **Transfers**
5. **Coach**
6. **Einstellungen**

Saisonmodule können später wieder eingeblendet bzw. erweitert werden, ohne die Preseason-Datenhistorie zu verlieren.

---

## Entwicklungsrichtung

Die nächsten größeren technischen Refactorings sollten vor allem Wartbarkeit verbessern, nicht die fachliche Logik erneut umwerfen:

- `ui.py` schrittweise in Pages/Dialogs/Controller zerlegen
- `storage.py` langfristig in klar getrennte Repositories/Migrationsmodule aufteilen
- Player-Master als zentrale Identitätsschicht weiterverwenden
- Season-Betrieb auf tatsächlichen Punkten während der Besitzdauer aufbauen
- bestehende Preseason-Modelle weiter über gespeicherte Outcomes evaluieren

Die Leitlinie bleibt: **echte Daten und echte Kickbase-Regeln vor zusätzlichen Fantasie-Kennzahlen.**


## Änderungen in V5.0.1

- Startkader-Verkäufe ohne beobachteten BUY werden mit dem gespeicherten Start-Marktwert bewertet.
- Realisierter Gewinn/Verlust und ROI nutzen damit `Start-MW → Verkaufserlös`.
- Normale Verkäufe ohne bekannten Kauf bleiben weiterhin ohne erfundenen Einstiegspreis.
