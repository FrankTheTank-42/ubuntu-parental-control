# Ubuntu Parental Control

Früher Prototyp einer manipulationsgeschützten Kindersicherung für Ubuntu.

## Firefox- und Chrome-Webfilter

Dieser Stand installiert:

- eine systemweite Firefox-Enterprise-Policy,
- eine verpflichtend installierte und nicht deaktivierbare WebExtension,
- einen mit Firefox-Snap kompatiblen XPI-Ablageort unter
  `/etc/firefox/policies/extensions/`,
- eine geschützte Systemkonfiguration unter `/etc/ubuntu-parental-control`,
- einen minimalen, gehärteten `systemd`-Dienst,
- sowie einen Uninstaller, der eine zuvor vorhandene Firefox-Policy wiederherstellt.

### Erweiterungen bauen und signieren

Firefox Release und Beta akzeptieren nur von Mozilla signierte Erweiterungen.
Das Build-Skript erzeugt zunächst ein **unsigniertes** XPI für Validierung und
Einreichung bei AMO. Nach der AMO-Signierung wird das signierte Paket installiert:

```bash
python3 tools/build_extension.py
```

Das erzeugt:

- `dist/ubuntu-parental-control-webfilter-firefox-unsigned.xpi` zur AMO-Signierung,
- `dist/ubuntu-parental-control-webfilter-chrome.zip` zur Einreichung im Chrome Web Store.

Ausführliche, direkt für die Store-Einreichung nutzbare Versionshinweise stehen
in `RELEASE_NOTES.md`.

Firefox Release und Beta akzeptieren nur ein von Mozilla signiertes XPI. Chrome
benötigt für eine dauerhaft stabile ID und automatische verwaltete Installation
eine veröffentlichte oder selbst gehostete Extension samt HTTPS-Update-URL.

Nur Firefox installieren:

```bash
sudo ./installer/install.sh --xpi /pfad/zur/signierten-datei.xpi
```

Firefox und Google Chrome installieren:

```bash
sudo ./installer/install.sh \
  --xpi /pfad/zur/signierten-datei.xpi \
  --chrome-extension-id abcdefghijklmnopabcdefghijklmnop
```

Für eine selbst gehostete Chrome-Extension zusätzlich
`--chrome-update-url https://…/updates.xml` verwenden. Ohne diese Option wird
die Update-URL des Chrome Web Store verwendet.

Danach Firefox und Chrome vollständig beenden und neu starten. Unter `about:policies`
sollte die Richtlinie aktiv sein; unter `about:addons` darf die Erweiterung
nicht deaktiviert oder entfernt werden können.

Chrome zeigt die geladene Richtlinie unter `chrome://policy`. Die Extension ist
über `ExtensionSettings` als `force_installed` gesetzt und kann vom normalen
Benutzer nicht entfernt werden. Zusätzlich deaktiviert die Projekt-Policy den
Gast- und Inkognitomodus und sperrt Chrome DevTools, damit diese Wege den
verwalteten Filter nicht umgehen beziehungsweise verändern können.

### Status prüfen

```bash
systemctl status ubuntu-parental-control.service
journalctl -u ubuntu-parental-control.service
```

### Regeln sicher verwalten

Der Installer richtet `upcctl` als rootgeschütztes Verwaltungswerkzeug ein.
Lesebefehle zeigen und prüfen die aktive Datei; Schreibbefehle validieren immer
den vollständigen Endzustand und ersetzen die Datei erst danach atomar.

```bash
upcctl list
upcctl show
upcctl validate
sudo upcctl apply /pfad/zu/neuen-regeln.json
sudo upcctl create-block gaming "Spiele" --domain example-game.com
sudo upcctl set-block gaming --priority 50 --disable
sudo upcctl add-domain self-blocked-sites example.com
sudo upcctl remove-domain self-blocked-sites example.com
sudo upcctl delete-block gaming --yes
```

Weitere Blockziele und Domain-Ausnahmen:

```bash
sudo upcctl add-url-pattern gaming '*://example.com/games/*'
sudo upcctl remove-url-pattern gaming '*://example.com/games/*'
sudo upcctl add-url-regex gaming '^https?://example\.com/play'
sudo upcctl remove-url-regex gaming '^https?://example\.com/play'
sudo upcctl add-exception-domain gaming school.example-game.com
sudo upcctl remove-exception-domain gaming school.example-game.com
```

Zeitpläne werden aus einem oder mehreren wöchentlichen Fenstern aufgebaut:

```bash
sudo upcctl add-window gaming \
  --timezone Europe/Berlin \
  --start 18:00 \
  --end 20:00 \
  --days MO,TU,WE,TH,FR
sudo upcctl add-window gaming \
  --timezone Europe/Berlin \
  --start 10:00 \
  --end 12:00 \
  --days SA,SU
upcctl list-windows gaming
sudo upcctl set-schedule-timezone gaming UTC
sudo upcctl remove-window gaming 2
sudo upcctl clear-schedule gaming --yes
```

Ein Zeitfenster, dessen Ende vor oder genau auf dem Start liegt, läuft über
Mitternacht. Für Regex mit Groß-/Kleinschreibung steht bei Hinzufügen und
Entfernen `--case-sensitive` zur Verfügung. Der vollständige Zustand eines
Blocks ist mit `upcctl show-block BLOCK-ID` sichtbar.

Administratoren können außerdem das für eine spätere Benutzeroberfläche
vorgesehene append-only Recht konfigurieren:

```bash
sudo upcctl set-user-add-domains gaming enabled
sudo upcctl set-user-add-domains gaming disabled
```

Dieser Schalter allein gewährt einem normalen Benutzer noch keinen Schreibweg.
Der dafür notwendige privilegierte append-only Dienst ist eine spätere
Ausbaustufe. URL-Pattern- und Regex-Ausnahmen werden bewusst nicht angeboten,
weil sie mit DNR nicht sicher auf genau einen Block begrenzt werden können.

Änderungen aus einer vollständigen JSON-Datei lassen sich vor dem Übernehmen
als vereinheitlichtes Diff prüfen:

```bash
upcctl apply /pfad/zu/neuen-regeln.json --dry-run
sudo upcctl apply /pfad/zu/neuen-regeln.json
```

Vor jeder tatsächlichen Änderung archiviert `upcctl` die bisherige gültige
Regeldatei rootgeschützt. Frühere Versionen lassen sich anzeigen, zunächst als
Vorschau prüfen und anschließend atomar wiederherstellen:

```bash
sudo upcctl history
sudo upcctl rollback VERSION --dry-run
sudo upcctl rollback VERSION --yes
```

Auch vor einem Rollback wird der aktuelle gültige Zustand gesichert. Eine
ungültige oder beschädigte Datei gelangt nie in die Versionshistorie. Die
Historie liegt mit Modus `0700` unter
`/var/lib/ubuntu-parental-control/rule-history`.

Die Profilvoreinstellungen sind ebenfalls validiert änderbar:

```bash
sudo upcctl set-profile --timezone Europe/Berlin
sudo upcctl set-profile --default-action allow
sudo upcctl set-profile --timezone UTC --default-action block
```

Der Daemon erkennt eine erfolgreiche Änderung automatisch. Ein Neustart des
Dienstes ist nicht erforderlich. Firefox kann für die erneuerte Enterprise
Policy weiterhin einen vollständigen Browserneustart benötigen. `upcctl` weist
nach jeder Änderung der Systemregeldatei ausdrücklich darauf hin.

### Entfernen

```bash
sudo ./installer/uninstall.sh
```

Das Skript führt Firefox durch zwei getrennte Neustarts. Beim ersten Start wird
die zuvor erzwungene Erweiterung freigegeben. Danach aktiviert das Skript die
temporäre `Extensions.Uninstall`-Policy; beim zweiten Start entfernt Firefox die
Erweiterung. Nach jedem vollständig beendeten Firefox-Start wird der Ablauf im
Terminal mit der Eingabetaste fortgesetzt. Zum Schluss räumt das Skript die
temporäre Policy auf und stellt die ursprüngliche Policy wieder her. Falls das
Terminal vorher geschlossen wird, setzt ein erneuter Aufruf von `uninstall.sh`
die gespeicherte Phase fort.

### Tests

Die Tests laufen ohne Root-Rechte in einem temporären Installationsziel:

```bash
./tests/test-installer.sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_rule_engine.js
node tests/test_background_start.js
```

## Sicherheitsgrenze

Das Kinderkonto darf weder `sudo`- noch Root-Rechte besitzen. Der Installer
schützt Systemdateien vor normalen Benutzern. Ein Benutzer mit Root-Zugriff
oder der Möglichkeit, ein anderes Betriebssystem zu booten, kann lokale
Kontrollen grundsätzlich umgehen.

## Webfilter-Regeln

Das versionierte Regelschema liegt unter `schema/parental-rules.schema.json`.
`config/rules.example.json` zeigt Domain-Blocks, URL-Patterns, sichere Regex,
Zeitpläne, Prioritäten, Ausnahmen und append-only Benutzerfreigaben.

Die Beispielregeln lassen sich ohne zusätzliche Python-Pakete prüfen:

```bash
python3 daemon/rule_validator.py config/rules.example.json
```

Der Dienst überwacht `/etc/ubuntu-parental-control/rules.json`. Gültige
Änderungen werden automatisch aktiviert und atomar als letzte gültige Version
unter `/var/lib/ubuntu-parental-control/rules.last-known-good.json` gesichert.
Ungültige Änderungen werden protokolliert; die bisherigen Regeln bleiben aktiv.
Diese einzelne Laufzeitsicherung ist vom durch `upcctl` gepflegten
Versionsverlauf unter `/var/lib/ubuntu-parental-control/rule-history` getrennt.

Der Daemon veröffentlicht nach erfolgreicher Prüfung denselben kanonischen,
SHA-256-identifizierten Snapshot in beiden Browsern:

- Firefox: `/etc/firefox/policies/policies.json`, unter
  `policies.3rdparty.Extensions.webfilter@ubuntu-parental-control.local`
- Chrome: `/etc/opt/chrome/policies/managed/ubuntu-parental-control.json`

Beide Erweiterungen lesen ausschließlich `storage.managed`, prüfen Snapshot und
Prüfsumme erneut, berechnen Zeitpläne lokal und ersetzen ihre dynamischen
`declarativeNetRequest`-Regeln atomar. Ein statischer, im Extension-Paket
enthaltener Notfall-Regelsatz blockiert HTTP(S)-Navigation, solange kein gültiger
Snapshot aktiv ist. Geblockte Navigationen werden auf eine lokale Hinweisseite
der Extension umgeleitet; es werden dabei keine URLs gespeichert oder übertragen.

Chrome meldet dynamisch geladene Policy-Änderungen über `storage.onChanged`.
Firefox-Enterprise-Policies können je nach Firefox-Version erst nach einem
Browserneustart neu eingelesen werden; Zeitplanwechsel benötigen keinen Neustart,
weil sie innerhalb der Extension berechnet werden.

### DNR-Grenze für Ausnahmen

Domain-Ausnahmen werden korrekt als `excludedRequestDomains` ausschließlich aus
ihrem eigenen Block herausgenommen. URL-Pattern- und Regex-Ausnahmen lassen sich
mit den DNR-APIs nicht allgemein und verlustfrei auf einen einzelnen Block
begrenzen. Solche Konfigurationen werden deshalb bei der Veröffentlichung sicher
abgelehnt. Die bisher aktiven Regeln bleiben bestehen; bei einer frischen
Installation bleibt der Notfall-Regelsatz aktiv.
