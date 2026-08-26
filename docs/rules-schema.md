# Webfilter-Regelschema 1.0

Die kanonische Definition liegt in
[`schema/parental-rules.schema.json`](../schema/parental-rules.schema.json).
Eine vollständige Beispielkonfiguration befindet sich in
[`config/rules.example.json`](../config/rules.example.json).

## Auswertung

1. Deaktivierte Blocks werden ignoriert.
2. Ein Block ohne `schedule` ist durchgehend aktiv.
3. Ausnahmen gelten ausschließlich innerhalb ihres eigenen Blocks.
4. Unter allen passenden aktiven Blocks gewinnt die höchste `priority`.
5. Bei gleicher Priorität gewinnt `block` gegenüber `allow`.
6. Passt kein Block, gilt `profile.default_action`.

## Zeitfenster

Zeitfenster verwenden lokale Uhrzeiten und eine eingeschränkte wöchentliche
RFC-5545-Wiederholungsregel. Liegt `end` vor oder gleich `start`, endet das
Fenster am Folgetag. Damit bedeutet `22:00` bis `07:00` eine Sperre über
Mitternacht. Die Laufzeitvalidierung prüft IANA-Zeitzonen und doppelte
Wochentage zusätzlich.

## Ziele

- `domains` enthält kleingeschriebene ASCII-Domains ohne Schema, Port oder Pfad.
  Eine Domain erfasst sich selbst und ihre Subdomains.
- `url_patterns` enthält WebExtension-artige HTTP(S)-Match-Patterns.
- `url_regex` enthält druckbare ASCII-Ausdrücke mit höchstens 512 Zeichen.
  Die Extension validiert sie zusätzlich mit
  `declarativeNetRequest.isRegexSupported()`.

## Benutzerergänzungen

`user_permissions.add_domains` darf nur bei einem Block mit `action: block`
aktiv sein. Alle anderen Benutzeränderungen sind in Version 1.0 verboten.
Benutzerergänzungen werden später append-only außerhalb der geschützten
Basiskonfiguration gespeichert und durch den Daemon mit ihr zusammengeführt.

## Zusätzliche Laufzeitvalidierung

JSON Schema kann nicht alle fachlichen Regeln ausdrücken. Vor dem Aktivieren
prüft die Rule Engine zusätzlich:

- eindeutige Block-IDs,
- existierende IANA-Zeitzonen,
- doppelte Wochentage in RRULEs,
- vollständige WebExtension-Pattern-Semantik,
- RE2-Unterstützung und Regex-Speichergrenzen.

Eine ungültige neue Konfiguration ersetzt niemals die letzte gültige Version.

## Verwaltung und Wiederherstellung

`upcctl` validiert den vollständigen Endzustand vor jeder Änderung und ersetzt
die aktive Datei atomar. Vor dem Ersetzen wird die bisherige gültige Fassung
unter `/var/lib/ubuntu-parental-control/rule-history` mit Modus `0600`
archiviert; das Verzeichnis selbst besitzt Modus `0700`. Beschädigte Fassungen
werden nicht archiviert. Ein Rollback validiert den gewählten Snapshot erneut
und sichert seinerseits zuerst den aktuellen Zustand.

`upcctl apply DATEI --dry-run` und `upcctl rollback VERSION --dry-run` geben ein
Diff aus, ohne die aktive Datei oder den Versionsverlauf zu verändern.

## Validator ausführen

Der Validator benötigt nur Python 3 und keine zusätzlichen Pakete:

```bash
python3 daemon/rule_validator.py config/rules.example.json
```

Für die spätere Anbindung an Daemon und Benutzeroberfläche steht eine
maschinenlesbare Ausgabe zur Verfügung:

```bash
python3 daemon/rule_validator.py --json config/rules.example.json
```

Der lokale Validator prüft die dokumentierte RE2-Teilmenge konservativ. Vor
dem Aktivieren einer Regex muss die Firefox-Erweiterung zusätzlich
`declarativeNetRequest.isRegexSupported()` aufrufen, weil nur Firefox die
endgültige Engine- und Speicherprüfung vornehmen kann.
