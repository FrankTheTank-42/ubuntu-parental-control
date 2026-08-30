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
- eine gemeinsame Firefox-/Chrome-Optionsseite mit Native-Livekanal,
- append-only Domain-Ergänzungen für registrierte Kinderkonten,
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

Ohne weitere Benutzeroption erkennt der Installer automatisch alle
interaktiven Konten im normalen Ubuntu-UID-Bereich, die weder Mitglied der
Administratorgruppen `sudo`/`admin` noch das aufrufende `sudo`-Konto sind. Sie
werden als Kinderkonten registriert und dürfen Blockierlisten ausschließlich
append-only erweitern. Dienstkonten mit `nologin` oder `false` werden
ausgeschlossen.

Falls nur bestimmte normale Konten eingeschränkt werden sollen, kann die
automatische Auswahl explizit überschrieben werden:

```bash
sudo ./installer/install.sh \
  --xpi /pfad/zur/signierten-datei.xpi \
  --restricted-user KINDERKONTO
```

`--restricted-user` kann für mehrere Konten wiederholt werden. Bei einer
erneuten Installation ohne diese Option wird die sichere automatische
Erkennung wiederholt. Ein vorhandener Stand bleibt erhalten, falls dabei kein
passendes Konto gefunden wird.

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

### Grafische Regelverwaltung

Die Einstellungen der Extension öffnen eine zweistufige Regelverwaltung. Die
erste Ansicht zeigt Name, Aktion, Status und Priorität jedes Blocks; die höchste
Priorität steht oben. Eltern können die Reihenfolge per Drag-and-drop, über
Auf/Ab-Schaltflächen oder mit `Alt`+`Pfeil hoch/runter` ändern. Ein Klick öffnet
die Detailansicht für Ziele, Ausnahmen und Zeitfenster. Die Profilwahl erklärt
zusätzlich den Blocklisten-Betrieb (`default_action: allow`) und den
Whitelist-Betrieb (`default_action: block`). Die Elternansicht bietet den
vollständigen Editor. In der Kinderansicht bleiben die geschützten Einstellungen
sichtbar, sind aber klar
ausgegraut und technisch deaktiviert. Das Kind kann jede Blockierliste um eine
Domain ergänzen, aber weder eigene noch vorgegebene Domains entfernen und keine
Regel lockern. Diese Ergänzungen verändern die Elternkonfiguration
`/etc/ubuntu-parental-control/rules.json` bewusst nicht. Sie werden je UID
getrennt und rootgeschützt in
`/var/lib/ubuntu-parental-control/user-domains.json` gespeichert und erst im
signierten effektiven Browser-Snapshot mit den Elternregeln vereinigt.

Eine Neuinstallation enthält bereits die dauerhaft aktive Blockierliste
„Webseiten sperren“. Sie darf zunächst eine leere Zielmenge besitzen, sodass
keine Website unbeabsichtigt vorgegeben wird. Das Kinderkonto kann sie sofort
über die Regelverwaltung und die Kontextmenüs um Domains ergänzen.
Beim Aktualisieren ergänzt der Installer diesen neutralen Standard-Block auch
in einer bereits vorhandenen, aber vollständig leeren Blockliste. Bestehende
Blocks und Profileinstellungen werden nicht verändert.

In einem nicht als eingeschränkt registrierten Konto lassen sich Blocks
anlegen, bearbeiten und löschen. Jede Speicherung öffnet eine neue
Polkit-Administratoranmeldung; es wird bewusst keine Autorisierung für spätere
Änderungen zwischengespeichert. Die Oberfläche kann Name, Aktivierung, Aktion,
Priorität, Domainziele, URL-Patterns, URL-Regex und Domain-Ausnahmen bearbeiten.
Zeitpläne werden ohne JSON-Eingabe über einen Wocheneditor verwaltet: Für jeden
Block lassen sich mehrere Kombinationen aus Wochentagen, Start- und Endzeit
sowie eine gemeinsame IANA-Zeitzone festlegen. Liegt die Endzeit vor oder
gleich der Startzeit, läuft das Fenster bis zum Folgetag. Ohne Zeitfenster ist
der Block durchgehend aktiv. Während einer Speicherung zeigt die Oberfläche
eine Warteanzeige, bis der Verwaltungsdienst den neuen Browser-Snapshot
bestätigt hat.

Native Messaging transportiert nur lokale Regelsnapshots und
Verwaltungsanfragen. Die verbindliche Start- und Rückfallebene bleibt
`storage.managed`. Ist der Native Host nicht erreichbar, bleibt der Filter
aktiv und die Oberfläche wechselt in den Nur-Lesen-Modus. Live-Snapshots und
Kontoberechtigungen sind mit einem bei der Installation erzeugten,
rootgeschützten ECDSA-Schlüssel signiert. Die Extension übernimmt den
öffentlichen Vertrauensanker ausschließlich aus `storage.managed`; ein vom
Kinderkonto überschriebener Native Host kann daher weder Regeln einschleusen
noch den Elternmodus freischalten.

Die Native-Messaging-Verbindung wird bewusst erst aufgebaut, wenn die
Regelverwaltung geöffnet oder das Kontextmenü zum Ergänzen der aktuellen
Website verwendet wird. Das Kontextmenü wird ohne Native Host aus dem bereits
aktiven Regelsnapshot erzeugt. Nach Auswahl einer Blockierliste öffnet sich die
Regelverwaltung, zeigt die lokale Einwilligung gegebenenfalls im unmittelbaren
Zusammenhang mit der Aktion an und meldet anschließend Erfolg oder Fehler.

Administrative Bearbeitung ist für ein separates, nicht eingeschränktes
Ubuntu-Elternkonto vorgesehen. Im Kinderkonto sollte auch eine betreuende
Person keine Polkit-Anmeldung für eine unerwartet angebotene Verwaltung
bestätigen.

### Status prüfen

```bash
systemctl status ubuntu-parental-control.service
journalctl -u ubuntu-parental-control.service
```

Hat ein eingeschränktes Konto die einmalige Firefox-Snap-Einwilligung bereits
verneint, steht in seiner Ubuntu-Anwendungsübersicht der Eintrag
„Ubuntu Parental Control – Firefox verbinden“ bereit. Er erklärt die lokale
Verbindung und setzt die Portalberechtigung nach einer ausdrücklichen
Bestätigung wieder auf „erlaubt“. Dafür ist weder `sudo` noch ein
Elternpasswort erforderlich, weil die Berechtigung ausschließlich zur
betroffenen Benutzersitzung gehört und der Native Host die Kinderrechte
weiterhin anhand der echten UID begrenzt.

Bei einer fehlenden Firefox-Verbindung bietet auch die Regelverwaltung den
Knopf „Firefox-Verbindung reparieren“ an. Er öffnet denselben lokalen Helfer
über den fest registrierten Handler
`ubuntu-parental-control://firefox-consent/allow`. Die Einwilligung wird erst
nach der Bestätigung im Helfer gesetzt; ein bloßes Öffnen des Links reicht
nicht aus.

Alternativ lässt sich dasselbe Werkzeug im Terminal des betroffenen Kontos
verwenden:

```bash
upc-firefox-consent status
upc-firefox-consent allow
upc-firefox-consent reset
```

`allow` erteilt die Einwilligung direkt. `reset` löscht den Portalentscheid,
sodass Firefox beim nächsten Öffnen der Regelverwaltung oder Verwenden des
Kontextmenüs erneut fragt. Das Werkzeug muss als betroffenes Konto und bewusst
ohne `sudo` ausgeführt werden.

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

Ein automatisch erkanntes oder explizit mit `--restricted-user` registriertes
Konto darf Domains append-only ergänzen. Die Berechtigung gilt automatisch
für alle Regeln mit `action: block`; `action: allow` bleibt ausgeschlossen.
Ergänzungen werden getrennt unter
`/var/lib/ubuntu-parental-control/user-domains.json` gespeichert. Eltern können
sie in der Extension oder per CLI anzeigen und entfernen:

```bash
sudo upcctl list-user-domains
sudo upcctl remove-user-domain UID BLOCK-ID DOMAIN --yes
```

URL-Pattern- und Regex-Ausnahmen werden bewusst nicht angeboten, weil sie mit
DNR nicht sicher auf genau einen Block begrenzt werden können.

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
Dienstes ist nicht erforderlich. Bei verbundenem Native Host aktualisiert
Firefox die DNR-Regeln sofort. Ist der Host nicht verfügbar, kann für den
Managed-Storage-Fallback weiterhin ein vollständiger Browserneustart nötig sein.
`upcctl` weist nach jeder Änderung der Systemregeldatei darauf hin.

Nach einer Domain-Ergänzung aus einem Kinderkonto aktiviert die Extension
zuerst den bestätigten signierten Snapshot und lädt danach bereits geöffnete
Tabs dieser Domain unter Umgehung des Browsercaches gezielt neu. Dadurch erscheint die Blockseite sowohl bei
manueller Eingabe als auch beim Hinzufügen über das Seiten-Kontextmenü ohne
Firefox-Neustart. Das Erweiterungssymbol und dessen Drei-Punkte-Menü öffnen die
Regelverwaltung direkt. Im selben Drei-Punkte-Menü steht „Webseite zu Block
hinzufügen“ mit den vorhandenen Blockierlisten als Untermenü zur Verfügung.

Ein bereits aktiver Native-Live-Snapshot wird nicht durch ein verspätetes
`storage.onChanged`-Ereignis auf den älteren Firefox-Policy-Cache
zurückgesetzt. Sämtliche Snapshot-Aktivierungen und Zeitplanauswertungen laufen
in einer gemeinsamen Reihenfolge ab.

### Entfernen

```bash
sudo ./installer/uninstall.sh
```

Das Skript führt Firefox durch zwei getrennte Neustarts. Beim ersten Start wird
die zuvor erzwungene Erweiterung freigegeben. Danach aktiviert das Skript die
temporäre `ExtensionSettings: blocked`- und `Extensions.Uninstall`-Policy; beim
zweiten Start entfernt Firefox die Erweiterung. Nach jedem vollständig
beendeten Firefox-Start wird der Ablauf im Terminal mit der Eingabetaste
fortgesetzt. Vor dem Aufräumen prüft das Skript alle gefundenen normalen,
Snap- und Flatpak-Firefox-Profile. Solange die Extension noch in einem Profil
registriert ist, bleibt die Uninstall-Policy aktiv und der Ablauf kann nach
einem weiteren Firefox-Neustart erneut ausgeführt werden. Erst nach der
bestätigten Entfernung stellt das Skript die ursprüngliche Policy wieder her.

### Tests

Die Tests laufen ohne Root-Rechte in einem temporären Installationsziel:

```bash
./tests/test-installer.sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_rule_engine.js
node tests/test_schedule_model.js
node tests/test_background_start.js
node tests/test_native_live_update.js
```

## Sicherheit und Review

Das [Threat Model](docs/threat-model.md) beschreibt Schutzversprechen,
Angreiferrollen, Vertrauensgrenzen und die priorisierten offenen Risiken. Die
[Browserarchitektur](docs/browser-architecture.md) dokumentiert den technischen
Datenfluss. Hinweise für eine vertrauliche Schwachstellenmeldung stehen in der
[Sicherheitsrichtlinie](SECURITY.md).

Das Threat Model ist ein entwicklerinternes Review und kein unabhängiges Audit.
Sicherheitsrelevante Änderungen sollen die betroffene Invariante benennen und
einen negativen Regressionstest ergänzen.

### Sicherheitsgrenze

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

Beide Erweiterungen lesen beim Start `storage.managed`, prüfen Snapshot und
Prüfsumme erneut, berechnen Zeitpläne lokal und ersetzen ihre dynamischen
`declarativeNetRequest`-Regeln atomar. Ein statischer, im Extension-Paket
enthaltener Notfall-Regelsatz blockiert HTTP(S)-Navigation, solange kein gültiger
Snapshot aktiv ist. Geblockte Navigationen werden auf eine lokale Hinweisseite
der Extension umgeleitet; es werden dabei keine URLs gespeichert oder übertragen.

Zusätzlich liefert der rootgeschützte Dienst neue validierte Snapshots über den
lokalen Native Host. Dadurch aktualisieren Firefox und Chrome die aktiven
DNR-Regeln sofort, ohne dass Firefox seine Enterprise Policy neu laden muss.
Jeder Live-Snapshot besitzt eine ECDSA-P-256-Signatur über das exakte
Snapshot-JSON. Der öffentliche Schlüssel wird über die Enterprise Policy
verankert; ungültige oder mit einem fremden Schlüssel signierte Nachrichten
werden verworfen.
Chrome meldet Policy-Änderungen ergänzend über `storage.onChanged`. Fällt der
Native Kanal aus, bleibt `storage.managed` der verbindliche Fallback.

### DNR-Grenze für Ausnahmen

Domain-Ausnahmen werden korrekt als `excludedRequestDomains` ausschließlich aus
ihrem eigenen Block herausgenommen. URL-Pattern- und Regex-Ausnahmen lassen sich
mit den DNR-APIs nicht allgemein und verlustfrei auf einen einzelnen Block
begrenzen. Solche Konfigurationen werden deshalb bei der Veröffentlichung sicher
abgelehnt. Die bisher aktiven Regeln bleiben bestehen; bei einer frischen
Installation bleibt der Notfall-Regelsatz aktiv.
