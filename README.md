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

### Entfernen

```bash
sudo ./installer/uninstall.sh
```

Das Skript bleibt geöffnet und fordert dazu auf, Firefox in jedem betroffenen
Benutzerkonto einmal zu starten und wieder zu schließen. Firefox verarbeitet
dabei die temporäre `Extensions.Uninstall`-Policy und entfernt die Erweiterung
automatisch. Nach der Rückkehr ins Terminal genügt die Eingabetaste; das gleiche
Skript räumt die temporäre Policy auf und stellt die ursprüngliche Policy wieder
her. Falls das Terminal vorher geschlossen wird, setzt ein erneuter Aufruf von
`uninstall.sh` den Vorgang fort.

### Tests

Die Tests laufen ohne Root-Rechte in einem temporären Installationsziel:

```bash
./tests/test-installer.sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_rule_engine.js
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

Der Daemon veröffentlicht nach erfolgreicher Prüfung denselben kanonischen,
SHA-256-identifizierten Snapshot in beiden Browsern:

- Firefox: `/etc/firefox/policies/policies.json`, unter
  `policies.3rdparty.Extensions.webfilter@ubuntu-parental-control.local`
- Chrome: `/etc/opt/chrome/policies/managed/ubuntu-parental-control.json`

Beide Erweiterungen lesen ausschließlich `storage.managed`, prüfen Snapshot und
Prüfsumme erneut, berechnen Zeitpläne lokal und ersetzen ihre dynamischen
`declarativeNetRequest`-Regeln atomar. Ein statischer, im Extension-Paket
enthaltener Notfall-Regelsatz blockiert HTTP(S)-Navigation, solange kein gültiger
Snapshot aktiv ist.

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
