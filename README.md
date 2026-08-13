# KickTrack — Preseason Build

KickTrack ist in dieser Version bewusst auf die **Preseason** fokussiert. Das Ziel ist nicht, schon vor dem ersten Spieltag eine vermeintlich perfekte Saisonanalyse zu liefern, sondern zwei konkrete Aufgaben gut zu lösen:

1. **Kapital aufbauen** durch kurzfristige Marktwert-Trades.
2. **Einen brauchbaren Startkader bauen**, ohne die Freitag-20:00-Solvenz zu gefährden.

## Sichtbare Kernlogik

Die Standardansicht reduziert Spielerentscheidungen auf wenige Begriffe:

- **STARTKADER** — wie sinnvoll ist der Spieler aktuell als Teil des geplanten Startkaders?
- **TRADE** — wie attraktiv ist die kurzfristige Marktwertchance?
- **MAX-BID** — wirtschaftliche Preisobergrenze, am aktuellen Marktwert verankert.
- **AKTION** — konkrete nächste Handlung.

Marktaktionen sind bewusst auf `KADERZIEL`, `INVEST`, `BEOBACHTEN` und `PASS` begrenzt. Eigene Spieler erhalten im Alltag nur `HALTEN`, `INVEST HALTEN`, `VERKAUF WARTEN` oder `VERKAUFEN`.

## Preseason-Regeln

- Alte Saisonpunkte treiben keine Kauf-, Kader- oder Coach-Entscheidungen.
- Fixture Difficulty und Lineup Optimizer sind in der Preseason-Navigation nicht Teil des Workflows.
- `CAN'T MISS` wird vor Saisonstart nicht als harte Kategorie verwendet. Gute langfristige Kandidaten heißen neutraler **KADERZIEL**.
- Die nächste Freitag-20:00-Deadline bleibt eine harte Finanz-Constraint.
- Für die Deadline zählt echter Cash-Saldo minus offene Gebote. Spieler werden nicht pauschal als imaginäre Liquidität eingerechnet.
- Spieler auf `TRANSFERLISTE` werden separat als potenzielles Verkaufskapital betrachtet, aber nicht als bereits vorhandenes Cash.

## Trading-Daten

Intern nutzt KickTrack weiterhin:

- 24h / 3T / 7T / 14T Marktwertentwicklung
- nicht überlappende Momentum-Fenster und Trendbeschleunigung
- historische Liga-Zuschläge
- tatsächlich gezahlte Premiums
- 3T-/7T-Outcomes vergangener Transfers
- historische Performance ähnlicher Momentum-Profile

Diese Größen bleiben überwiegend **Inputs**. Die UI zeigt sie nur dort prominent, wo sie eine konkrete Entscheidung erklären.

## Liga-Lernmodell

Historische Liga-Daten werden weiterhin rückwirkend genutzt, insbesondere für:

- typisches Zuschlagspremium je Preisband
- geschätzten Winning Price
- Premium-Risiko anhand späterer Käufer-Returns
- historische 7-Tage-Performance ähnlicher Momentum-Profile

Der erwartete Winning Price erhöht niemals automatisch den Max-Bid. Wenn die Liga typischerweise mehr zahlt als wirtschaftlich sinnvoll ist, lautet die Konsequenz: nicht hinterherbieten.

## Navigation

Die sichtbare Preseason-Navigation besteht aus:

- **Übersicht**
- **Kader**
- **Markt**
- **Transfers**
- **Coach**
- **Einstellungen**

Liga-/Saisonanalyse-Code bleibt für einen späteren Season-Build erhalten, ist aber im Preseason-Workflow ausgeblendet.

## Lokaler Start unter Windows

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Tests:

```powershell
pip install -e ".[dev]"
pytest
```

## Daten

Die SQLite-Datenbank liegt unter:

```text
%APPDATA%\KickTrack\kicktrack.db
```

Marktwert-Snapshots und Transferhistorie bleiben erhalten und können im späteren Season-Build weiterverwendet werden.

## Hinweis zur API

Die verwendete Kickbase-API ist keine offiziell dokumentierte öffentliche Drittanbieter-API. API-spezifisches Parsing bleibt deshalb in `app/kickbase.py` gekapselt.
