# Testprotokoll Ubuntu Parental Control 0.5.3

Dieses Protokoll ist für einen manuellen Abnahmetest auf einem realen
Ubuntu-System vorgesehen. Es prüft Installation, Eltern- und Kinderrollen,
Live-Updates, Regelverwaltung, Zeitfenster, Fehlerverhalten und Deinstallation.

## Testkopf

- Datum: ____________________
- Tester: ____________________
- Rechner/VM: ____________________
- Ubuntu-Version: ____________________
- Firefox-Version: ____________________
- Chrome-Version: ____________________
- Elternkonto: ____________________  UID: __________
- Kinderkonto: ____________________  UID: __________
- Optionales unregistriertes Konto: ____________________  UID: __________
- Signiertes Firefox-XPI: ____________________
- Chrome-Web-Store-Version: ____________________
- Getestetes Release: `v0.5.3`
- Erwartete Extension-Version: `0.5.3`

Gesamtergebnis:

- [ ] Bestanden
- [ ] Bestanden mit Einschränkungen
- [ ] Nicht bestanden

Wichtige Beobachtungen:

________________________________________________________________________

________________________________________________________________________

## Abbruchkriterien

Den Test anhalten und zunächst die Logs sichern, wenn eines davon eintritt:

- Firefox blockiert nach korrekter Installation ohne konfigurierte
  Whitelist-Regel sämtliche Seiten.
- Eine Änderung des Kinderkontos lockert oder löscht eine Elternregel.
- Ein unregistriertes Konto erhält die Eltern- oder Kinderverwaltung.
- `rules.json`, `user-domains.json` oder eine Browser-Policy wird ungültig.
- Der Dienst startet wiederholt neu oder verliert die letzte gültige Regel.
- Firefox oder Chrome verwendet noch Extension 0.5.2 zusammen mit dem
  0.5.3-Daemon. Protokoll 1 und 2 sind nicht kompatibel.

Bei einem Abbruch erfassen:

```bash
sudo systemctl status ubuntu-parental-control.service --no-pager
sudo journalctl -u ubuntu-parental-control.service -b --no-pager -n 200
sudo cp -a /etc/ubuntu-parental-control /tmp/upc-test-etc
sudo cp -a /var/lib/ubuntu-parental-control /tmp/upc-test-state
```

## 1. Release und Voraussetzungen

### 1.1 Release-Dateien

- [ ] `ubuntu-parental-control-installer-m2.zip` heruntergeladen.
- [ ] `ubuntu-parental-control-webfilter-firefox-unsigned.xpi` heruntergeladen.
- [ ] `ubuntu-parental-control-webfilter-chrome.zip` heruntergeladen.
- [ ] Die Prüfsummendatei aus dem Release heruntergeladen.

Im Downloadverzeichnis prüfen:

```bash
sha256sum --check ubuntu-parental-control-0.5.3-SHA256SUMS
```

Soll:

- [ ] Alle drei Zeilen melden `OK`.
- [ ] Keine Datei meldet `FAILED`.

Ergebnis/Notiz: _________________________________________________________

### 1.2 Firefox-Signatur

Das Release-XPI ist absichtlich unsigniert. Firefox Stable benötigt eine über
Mozilla AMO signierte 0.5.3-Datei.

- [ ] Das unsignierte 0.5.3-XPI bei AMO hochgeladen.
- [ ] Das von AMO signierte XPI heruntergeladen.
- [ ] Dateiname und Speicherort des signierten XPI oben im Testkopf notiert.
- [ ] Das signierte XPI lässt sich in Firefox installieren.

SHA-256 des signierten XPI dokumentieren:

```bash
sha256sum /PFAD/ZUR/SIGNIERTEN-0.5.3.xpi
```

Signierte XPI-Prüfsumme: ________________________________________________

### 1.3 Chrome-Sperre

- [ ] Im Chrome Web Store ist tatsächlich Version 0.5.3 freigegeben.

Falls nein:

- [ ] Den Chrome-Abschnitt dieses Protokolls überspringen.
- [ ] Chrome nicht mit der verwalteten Store-Version 0.5.2 gegen den
  0.5.3-Daemon testen.

## 2. Ausgangszustand und Sicherung

### 2.1 Vorhandenen Zustand erfassen

```bash
systemctl status ubuntu-parental-control.service --no-pager
upcctl list
sudo upcctl list-user-domains
```

- Installierte Ausgangsversion: ____________________
- Anzahl Blocks vorher: ____________________
- Anzahl Kinder-Domains vorher: ____________________

### 2.2 Sicherung anlegen

Falls bereits eine Installation vorhanden ist:

```bash
sudo mkdir -p /var/backups/ubuntu-parental-control-test
sudo cp -a /etc/ubuntu-parental-control \
  /var/backups/ubuntu-parental-control-test/etc-before-0.5.3
sudo cp -a /var/lib/ubuntu-parental-control \
  /var/backups/ubuntu-parental-control-test/state-before-0.5.3
```

- [ ] Sicherung ohne Fehler erstellt.
- [ ] Firefox und Chrome vollständig beendet.

## 3. Installation oder Upgrade

Installer entpacken:

```bash
unzip ubuntu-parental-control-installer-m2.zip
cd ubuntu-parental-control
```

Mit dem signierten Firefox-XPI installieren. Das aufrufende `sudo`-Konto wird
automatisch als Administrator registriert. Weitere Elternkonten können mit
`--administrator-user` ergänzt werden.

```bash
sudo ./installer/install.sh \
  --xpi /PFAD/ZUR/SIGNIERTEN-0.5.3.xpi
```

Bei bewusst manueller Kontozuordnung beispielsweise:

```bash
sudo ./installer/install.sh \
  --xpi /PFAD/ZUR/SIGNIERTEN-0.5.3.xpi \
  --administrator-user ELTERNKONTO \
  --restricted-user KINDERKONTO
```

Soll:

- [ ] Installer endet ohne Fehler.
- [ ] Elternkonto wurde als Administrator erkannt.
- [ ] Kinderkonto wurde automatisch oder explizit als eingeschränkt erkannt.
- [ ] Mindestens der leere Standard-Block zum Sperren wurde angelegt, falls
  vorher keine Regeln existierten.
- [ ] Vorhandene gültige Regeln und Kinder-Domains blieben beim Upgrade erhalten.

Notiz: __________________________________________________________________

## 4. Dienst, Dateien und Rollen

### 4.1 Dienstzustand

```bash
sudo systemctl status ubuntu-parental-control.service --no-pager
sudo journalctl -u ubuntu-parental-control.service -b --no-pager -n 100
```

- [ ] Dienst ist `active (running)`.
- [ ] Kein wiederholter Neustart.
- [ ] Keine Validierungs-, Signatur- oder Publikationsfehler.

### 4.2 Konfiguration

```bash
sudo python3 -m json.tool /etc/ubuntu-parental-control/config.json
```

- [ ] `administrator_users` enthält die UID des Elternkontos.
- [ ] `restricted_users` enthält die UID des Kinderkontos.
- [ ] Keine UID steht in beiden Listen.
- [ ] Nicht registrierte Konten stehen in keiner Liste.

### 4.3 Dateirechte

```bash
sudo stat -c '%a %U:%G %n' \
  /etc/ubuntu-parental-control/rules.json \
  /var/lib/ubuntu-parental-control/user-domains.json \
  /var/lib/ubuntu-parental-control/live-signing-key.pem \
  /var/lib/ubuntu-parental-control/snapshot-generation
```

- [ ] `rules.json` ist nicht durch normale Benutzer schreibbar.
- [ ] Benutzerzustand, privater Schlüssel und Generation sind nur für root
  schreibbar und nicht öffentlich lesbar.

### 4.4 Policy und Live-Snapshot stimmen überein

```bash
sudo python3 - <<'PY'
import json
from pathlib import Path

extension_id = "webfilter@ubuntu-parental-control.local"
policy = json.loads(Path("/etc/firefox/policies/policies.json").read_text())
managed = policy["policies"]["3rdparty"]["Extensions"][extension_id]
live = json.loads(Path("/run/ubuntu-parental-control/live-snapshot.json").read_text())

assert managed["protocol_version"] == 2
assert live["protocol_version"] == 2
assert managed["generation"] == live["generation"]
assert managed["revision"] == live["revision"]
assert isinstance(live["live_signature"], str) and live["live_signature"]
print("OK", managed["generation"], managed["revision"])
PY
```

- [ ] Ausgabe beginnt mit `OK`.

## 5. Firefox-Grundtest im Elternkonto

Firefox als echtes Elternkonto starten.

- [ ] Extension ist erzwungen installiert und nicht deaktivierbar.
- [ ] Erweiterungssymbol zeigt das Projekt-Icon.
- [ ] Die Drei-Punkte-Aktionen enthalten „Regelverwaltung öffnen“.
- [ ] Die Drei-Punkte-Aktionen enthalten „Webseite zu Block hinzufügen“.
- [ ] Die Regelverwaltung meldet „Administrator“ beziehungsweise Elternansicht.
- [ ] Keine unerwartete Native-Messaging-Einwilligungsaufforderung direkt beim
  Firefox-Start. Die Verbindung wird erst bei einer Verwaltungsaktion benötigt.

In der Erweiterungs-Debug-Konsole:

```javascript
browser.runtime.getManifest().version
```

Soll: `"0.5.3"`

- [ ] Version stimmt.

Hinweis: Ein angehaltenes MV3-Hintergrundskript im Firefox-Debugger ist allein
noch kein Fehler. Entscheidend sind Regelaktivierung und erneutes Aufwachen bei
Ereignissen.

## 6. Eltern-Regelverwaltung

### 6.1 Übersicht und Detailansicht

- [ ] Übersicht zeigt Name, Aktion und Reihenfolge der Blocks.
- [ ] Priorität lässt sich per Drag-and-drop ändern.
- [ ] Auf-/Ab-Schaltflächen funktionieren.
- [ ] `Alt` plus Pfeiltasten funktioniert für die Reihenfolge.
- [ ] Zahlenfeld für Priorität fehlt in der Detailansicht.
- [ ] Klick auf einen Block öffnet Domains, Ausnahmen und Zeitfenster.
- [ ] Abschlussregel „Alles erlauben“ oder „Alles blockieren“ steht am Ende.

### 6.2 Gemeinsamer Entwurf und Polkit

- [ ] Zwei oder mehr Änderungen vornehmen, ohne sofort zu speichern.
- [ ] Warteanimation erscheint während des abschließenden Speicherns.
- [ ] Beim abschließenden „Alles speichern“ erscheint genau eine
  Polkit-Passwortabfrage.
- [ ] Nach Erfolg bleiben alle Änderungen sichtbar.
- [ ] „Aktualisieren“ verwirft keine erfolgreich gespeicherte Änderung.

### 6.3 Leerer Block und eindeutige IDs

- [ ] Neuen Block ohne Domain anlegen.
- [ ] Speichern ist trotz leerer Domainliste möglich.
- [ ] Zwei ähnlich benannte Blocks erzeugen unterschiedliche technische IDs.
- [ ] Löschen eines Blocks löscht nicht den anderen.

Test-Block-ID/Name: _____________________________________________________

## 7. Gleichzeitige Elternänderungen

Die Regelverwaltung in zwei Firefox-Fenstern oder zwei Tabs öffnen und in
beiden zuerst denselben Ausgangsstand laden.

1. In Fenster A eine Änderung speichern.
2. In Fenster B ohne vorheriges Aktualisieren eine andere Änderung speichern.

Soll:

- [ ] Fenster A speichert erfolgreich.
- [ ] Fenster B meldet verständlich, dass die Basisregeln zwischenzeitlich
  geändert wurden.
- [ ] Änderung A wird nicht überschrieben.
- [ ] Nach Aktualisieren kann Änderung B erneut angewendet werden.

Notiz: __________________________________________________________________

## 8. Blockierung und Blockseite

Einen aktiven Block für `example.com` anlegen oder ergänzen.

- [ ] `https://example.com/` wird blockiert.
- [ ] Die lokale Blockseite erscheint.
- [ ] Die Blockseite nennt den auslösenden Block verständlich.
- [ ] Eine andere, nicht konfigurierte Seite bleibt erreichbar.
- [ ] Ein neu geöffneter Tab wird ebenfalls blockiert.
- [ ] Nach Firefox-Neustart bleibt die Sperre aktiv.

In der Erweiterungs-Debug-Konsole:

```javascript
(await browser.declarativeNetRequest.getDynamicRules())
  .filter(rule => rule.condition.requestDomains?.includes("example.com"))
```

- [ ] Mindestens eine passende dynamische Regel vorhanden.

## 9. Kinderkonto und Live-Update

Diese Tests in einer echten grafischen Sitzung des Kinderkontos durchführen,
nicht mit `sudo -u`, weil Firefox-Snap, D-Bus und Portalberechtigungen zur
Benutzersitzung gehören.

### 9.1 Kinderansicht

- [ ] Regelverwaltung zeigt die Kinderansicht.
- [ ] Elternfelder sind sichtbar, aber deaktiviert.
- [ ] Löschen, Lockern, Priorisieren und Allow-Regeln ändern ist nicht möglich.
- [ ] Domain-Eingabe ist für jeden Block mit Aktion `block` vorhanden.
- [ ] Es gibt keine Checkbox „Kind darf Domains ergänzen“.

### 9.2 Domain über die Regelverwaltung

`example.org` zu einem Blockier-Block hinzufügen.

- [ ] UI zeigt erst nach bestätigter Rückmeldung Erfolg.
- [ ] Warteanimation erscheint während des Speicherns.
- [ ] `https://example.org/` wird ohne Firefox-Neustart blockiert.
- [ ] Die neue Domain bleibt nach Firefox-Neustart gesperrt.

Im Elternkonto prüfen:

```bash
sudo upcctl list-user-domains
```

- [ ] Domain steht mit der UID des Kinderkontos in der Ausgabe.
- [ ] Domain wurde nicht in die Basisregeldatei geschrieben.

```bash
sudo python3 - <<'PY'
import json
from pathlib import Path

domain = "example.org"
base = json.loads(Path("/etc/ubuntu-parental-control/rules.json").read_text())
user = json.loads(Path("/var/lib/ubuntu-parental-control/user-domains.json").read_text())
assert domain not in json.dumps(base)
assert domain in json.dumps(user)
print("OK: getrennte Speicherung")
PY
```

### 9.3 Domain über Kontextmenüs

Eine noch erlaubte Website öffnen.

- [ ] Seiten-Rechtsklick bietet das Hinzufügen zum gewünschten Block an.
- [ ] Das Kontextmenü trägt das Projekt-Icon, soweit Firefox dies anzeigt.
- [ ] Erweiterungssymbol → Drei-Punkte-Menü bietet ebenfalls
  „Webseite zu Block hinzufügen“.
- [ ] Nach Auswahl wird die aktuelle Seite ohne Browserneustart blockiert.
- [ ] Es entsteht keine doppelte DNR-ID und keine Meldung „Doppelte ID“.

Getestete Domain: _______________________________________________________

### 9.4 Eltern entfernen Kinder-Domain

Im Elternkonto die zuvor ergänzte Kinder-Domain entfernen.

- [ ] Entfernen erfordert administrative Bestätigung.
- [ ] Nur der ausgewählte Eintrag wird entfernt.
- [ ] Andere Kinder-Domains bleiben erhalten.
- [ ] Die Website wird nach erfolgreicher Aktualisierung wieder erreichbar,
  sofern keine andere Regel sie blockiert.

## 10. Firefox-Native-Messaging-Einwilligung

Im Kinderkonto ohne `sudo`:

```bash
upc-firefox-consent status
upc-firefox-consent reset
```

- [ ] `reset` entfernt nur die Firefox-Hostentscheidung.
- [ ] Normales Browsen funktioniert weiterhin gemäß bereits aktiven Regeln.
- [ ] Eine Verwaltungsaktion meldet verständlich, dass der Native Host nicht
  erreichbar beziehungsweise nicht erlaubt ist.
- [ ] „Firefox-Verbindung reparieren“ ist in der UI vorhanden.
- [ ] Der Helfer erklärt die lokale Verbindung verständlich.
- [ ] Nach Zustimmung funktioniert das Hinzufügen einer Domain wieder.

Alternativ im Kinderkonto:

```bash
upc-firefox-consent allow
upc-firefox-consent status
```

- [ ] Status meldet anschließend „erlaubt“.

## 11. Zeitfenster

Einen eigenen Block mit einer Testdomain verwenden, damit andere Regeln das
Ergebnis nicht verdecken.

### 11.1 Aktives Fenster

- [ ] Zeitzone `Europe/Berlin` einstellen.
- [ ] Fenster wählen, das die aktuelle Uhrzeit einschließt.
- [ ] Testdomain wird innerhalb des Fensters blockiert.
- [ ] UI zeigt Wochentage, Start, Ende und Zeitzone korrekt.

### 11.2 Inaktives Fenster

- [ ] Fenster so ändern, dass die aktuelle Uhrzeit außerhalb liegt.
- [ ] Spätestens nach der nächsten Minutenauswertung wird die Domain erreichbar.
- [ ] Kein Firefox-Neustart erforderlich.

### 11.3 Mitternacht

- [ ] Fenster mit Ende vor oder gleich Start anlegen.
- [ ] UI erklärt beziehungsweise zeigt den Lauf über Mitternacht korrekt.

Testdomain und Zeiten: __________________________________________________

## 12. Priorität und Abschlussregel

### 12.1 Konflikt zweier Blocks

Eine Domain gleichzeitig in einer Allow- und einer Block-Regel verwenden.

- [ ] Die weiter oben priorisierte Regel gewinnt.
- [ ] Nach Drag-and-drop und Speichern ändert sich das Ergebnis ohne Neustart.

### 12.2 Whitelist-Modus

Vor diesem Test das Protokoll lokal geöffnet lassen.

- [ ] Abschlussregel auf „Alles blockieren“ setzen.
- [ ] Eine ausdrücklich erlaubte Domain bleibt erreichbar.
- [ ] Eine nicht erlaubte Domain wird blockiert.
- [ ] Anschließend Abschlussregel wieder auf den gewünschten Dauerzustand setzen.

## 13. Snapshot-Generation und Neustart

Generation vor dem Neustart erfassen:

```bash
sudo cat /var/lib/ubuntu-parental-control/snapshot-generation
```

Wert vorher: ____________________

```bash
sudo systemctl restart ubuntu-parental-control.service
sudo systemctl is-active ubuntu-parental-control.service
sudo cat /var/lib/ubuntu-parental-control/snapshot-generation
```

Wert nachher: ____________________

- [ ] Dienst ist wieder `active`.
- [ ] Generation nachher ist größer als vorher.
- [ ] Aktive Regeln wurden nicht zurückgesetzt.
- [ ] Blockierte Testdomain bleibt blockiert.

## 14. Managed-Fallback bei nicht erreichbarem Dienst

Nur durchführen, wenn ein Terminal mit `sudo` bereitsteht.

```bash
sudo systemctl stop ubuntu-parental-control.service
```

- [ ] Bereits veröffentlichte Regeln bleiben in Firefox aktiv.
- [ ] Regelverwaltung zeigt einen verständlichen Verbindungsfehler.
- [ ] Es wird kein Speichern fälschlich als erfolgreich gemeldet.

Dienst sofort wieder starten:

```bash
sudo systemctl start ubuntu-parental-control.service
sudo systemctl is-active ubuntu-parental-control.service
```

- [ ] Dienst ist `active`.
- [ ] Regelverwaltung funktioniert anschließend wieder.

## 15. Validierung und Historie

```bash
upcctl validate
sudo upcctl history
```

- [ ] Aktive Regeln sind gültig.
- [ ] Nach Elternänderungen existieren Historieneinträge.

Eine ungültige Testdatei darf nur gegen einen temporären Pfad geprüft werden:

```bash
cp /etc/ubuntu-parental-control/rules.json /tmp/upc-invalid-rules.json
python3 -c 'import json; p="/tmp/upc-invalid-rules.json"; d=json.load(open(p)); d["blocks"][0]["priority"]="falsch"; open(p,"w").write(json.dumps(d))'
upcctl --rules /tmp/upc-invalid-rules.json validate
```

Soll:

- [ ] Validierung schlägt verständlich fehl.
- [ ] Aktive `/etc/ubuntu-parental-control/rules.json` bleibt unverändert.
- [ ] Browserregeln bleiben aktiv.

## 16. Protokollierung und Datenschutz

Nach dem Besuch einer blockierten Testdomain:

```bash
sudo journalctl -u ubuntu-parental-control.service -b --no-pager -n 300
```

- [ ] Keine vollständige besuchte URL im Dienstprotokoll.
- [ ] Keine Browserhistorie oder Seiteninhalte im Dienstprotokoll.
- [ ] Fehler enthalten genug technische Information, aber keine Passwörter,
  privaten Schlüssel oder Signaturen.

## 17. Optional: unregistriertes Konto

Nur durchführen, wenn ein drittes normales Ubuntu-Konto vorhanden ist.

- [ ] Firefox in der echten Sitzung dieses Kontos starten.
- [ ] Native-Status ergibt Rolle `unauthorized`.
- [ ] Keine Basisregeln oder vollständigen Kinderzustände einsehbar.
- [ ] Keine Domain als Kind ergänzbar.
- [ ] Keine Elternbearbeitung verfügbar.

## 18. Chrome-Test nach Freigabe von 0.5.3

Diesen Abschnitt erst durchführen, wenn der Chrome Web Store dieselbe
Extension-ID tatsächlich als Version 0.5.3 ausliefert.

- [ ] `chrome://policy` öffnen und Policies neu laden.
- [ ] Extension ist erzwungen installiert und nicht deaktivierbar.
- [ ] `chrome://extensions` zeigt Version 0.5.3.
- [ ] Regelverwaltung zeigt im Elternkonto die Elternansicht.
- [ ] Regelverwaltung zeigt im Kinderkonto die Kinderansicht.
- [ ] Domain-Ergänzung über UI wirkt ohne Chrome-Neustart.
- [ ] Domain-Ergänzung über Seiten-Kontextmenü wirkt ohne Chrome-Neustart.
- [ ] Blockseite nennt den auslösenden Block.
- [ ] Zeitfenster werden wie in Firefox ausgewertet.
- [ ] `chrome://policy` zeigt Protokoll 2 und eine positive Generation.

Chrome-Notiz: ___________________________________________________________

## 19. Optionale Deinstallation

Erst nach Abschluss aller Funktionstests durchführen.

```bash
sudo ./installer/uninstall.sh
```

Den Anweisungen für die zwei vollständigen Firefox-Neustarts folgen.

- [ ] Dienst und systemd-Unit wurden entfernt.
- [ ] Firefox-Policy wurde entfernt beziehungsweise auf den Zustand vor der
  Installation zurückgesetzt.
- [ ] Chrome-Policy wurde entfernt beziehungsweise wiederhergestellt.
- [ ] Extension ist aus allen erkannten Firefox-Profilen entfernt.
- [ ] Native-Messaging-Manifeste wurden entfernt.
- [ ] Polkit-Policy und Firefox-Einwilligungshelfer wurden entfernt.
- [ ] `snapshot-generation` und zugehörige Lockdatei wurden entfernt.
- [ ] Andere, nicht zum Projekt gehörende Firefox-Policies blieben erhalten.

## 20. Abschluss

### Pflichtfälle

- [ ] Installation/Upgrade erfolgreich
- [ ] Dienst stabil
- [ ] Firefox 0.5.3 aktiv
- [ ] Elternrolle korrekt
- [ ] Kinderrolle korrekt
- [ ] Unregistrierte Rolle korrekt oder als nicht getestet markiert
- [ ] Sofortige Domain-Aktivierung ohne Neustart
- [ ] Kontextmenüs funktionieren
- [ ] Zeitfenster funktionieren
- [ ] Gleichzeitige Elternänderung wird erkannt
- [ ] Snapshot-Generation bleibt monoton
- [ ] Managed-Fallback funktioniert
- [ ] Keine URL-Lecks im Dienstprotokoll
- [ ] Chrome korrekt getestet oder bewusst bis Store-Freigabe ausgenommen

Nicht getestete Punkte:

________________________________________________________________________

Fehler mit Reproduktionsschritten:

________________________________________________________________________

________________________________________________________________________

Abschlussentscheidung:

- [ ] 0.5.3 für den persönlichen Einsatz freigegeben
- [ ] Nach Korrektur einzelner Befunde erneut testen
- [ ] Installation zurückrollen/deinstallieren
