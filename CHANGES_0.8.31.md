# KickTrack 0.8.31 – Fix-Patch

## Verhalten

- Marktwert-Historien werden beim Öffnen aktualisiert, nach Datum zusammengeführt und ohne Löschen vorhandener Tagesdaten gespeichert.
- 7T/30T/90T/1J und Aktualitätsprüfungen verwenden konsistente Berliner Kalendertage.
- Markt und Player Detail zeigen Mini-Charts nur mit ausreichend aktuellen Daten.
- Formdaten des Transfermarkts werden in einem begrenzten Backend-Batch geladen; einzelne Fehler lassen den Rest der Tabelle nutzbar.
- Marktwert-Historien werden bei fehlenden lokalen API-Daten gebündelt aus der Kickbase-365-Tage-Historie nachgeladen und datumsweise rückwirkend in der Datenbank ergänzt.
- Der Historienparser akzeptiert die von der Live-API gelieferten ganzzahligen Dezimalwerte (z. B. `23154618.0`), statt den gesamten Verlauf zu verwerfen.
- Markt und Kader zeigen MW-Verlauf und Form direkt in ihren Tabellen; die Mini-Charts verwenden ein robustes 90-Tage-Fenster mit Fallback bei lückenhaften Daten.
- Markt- und Kadertabellen passen in die Fensterbreite; die Gegner-Spalte wurde entfernt und horizontales Scrollen vermieden.
- Marktdynamik bleibt parallel zu den neuen Mini-Charts aktiv.
- Optionaler Dauerlogin erneuert wöchentlich ablaufende Tokens mithilfe explizit gespeicherter Zugangsdaten aus dem Windows Credential Manager.

## Plattform, Daten und Sicherheit

- Neue Datenbanken erhalten über Migration 6 alle Tabellen und Indizes für Marktwerte und Dashboard-Snapshots.
- API-Pfadparameter werden validiert, Content Security Policy und Tauri-Berechtigungen sind eingeschränkt.
- Der ungenutzte Opener wurde entfernt; große Seiten werden lazy geladen und der doppelte Player-Detail-Provider wurde beseitigt.
- Ein Logout entfernt Session und gespeicherte Zugangsdaten vollständig.

## Verifikation

Die verbindlichen Prüfungen stehen in `AGENTS.md` und laufen zusätzlich über `.github/workflows/ci.yml`. Ein produktives Windows-Release ist nicht Bestandteil dieses Quellcode-Patches.
