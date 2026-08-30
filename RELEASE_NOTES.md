# Versionshinweise

## 0.3.9

### Firefox/AMO

- Liefert bei einer Neuinstallation die aktive Standard-Blockierliste
  „Webseiten sperren“ mit aus. Dadurch stehen dem Kinderkonto die
  Domain-Eingabe und beide Kontextmenüs sofort zur Verfügung, auch wenn noch
  keine Elternregeln angelegt wurden.
- Erlaubt vorbereitete Blocks mit einer leeren Zielmenge im Regelschema und im
  Validator. Der Browser erzeugt dafür keine DNR-Regel, bis die erste Domain,
  das erste URL-Pattern oder die erste Regex ergänzt wird.
- Erkennt bei der Installation interaktive Ubuntu-Konten ohne
  Administratorrechte automatisch als eingeschränkte Konten. Der Name des
  Kinderkontos muss nicht mehr zwingend mit `--restricted-user` angegeben
  werden; die Option bleibt als expliziter Override für besondere
  Mehrbenutzerkonfigurationen erhalten.

- Erkennt doppelt zugestellte Native Snapshots anhand ihrer bereits geprüften
  Revision. Die direkte Antwort einer Domain-Ergänzung und das unmittelbar
  folgende Live-Event bestätigen nun denselben Stand, ohne identische
  DNR-Regel-IDs ein zweites Mal zu registrieren.
- Markiert der Native Host eine bereits direkt beantwortete Snapshot-Revision
  pro Browser-Verbindung als zugestellt. Sein Dateiwächter unterdrückt nur das
  identische Folge-Event; wirklich neuere Revisionen und andere
  Browser-Verbindungen werden weiterhin benachrichtigt.
- Verhindert dadurch die rote Firefox-Fehlermeldung „Doppelte ID“, wenn über
  das Kontextmenü nacheinander weitere Domains ergänzt werden.
- Ergänzt im Drei-Punkte-Menü des Erweiterungssymbols den Eintrag „Webseite zu
  Block hinzufügen“. Ein Untermenü zeigt die verfügbaren Blockierlisten an.
- Übernimmt nach der Blockauswahl ausschließlich den Hostnamen des aktuellen
  HTTP(S)-Tabs und verwendet denselben bestätigten Speicherweg wie das
  bestehende Seiten-Kontextmenü und die manuelle Domain-Eingabe.

## 0.3.8

### Firefox/AMO

- Verhindert, dass ein verspätetes Firefox-`storage.managed`-Ereignis einen
  bereits verifizierten Native-Live-Snapshot wieder durch den älteren
  Policy-Cache ersetzt. Eine neu ergänzte Domain bleibt dadurch in der
  Regelverwaltung sichtbar und dauerhaft aktiv.
- Serialisiert direkte Speicherantworten, Native-Live-Ereignisse und
  Zeitplanauswertungen über dieselbe Aktivierungswarteschlange. Parallel
  eintreffende Snapshots können die zuletzt bestätigte Änderung nicht mehr
  überholen.
- Lädt passende offene Tabs nach der Aktivierung unter Umgehung des
  Firefox-Caches neu.

## 0.3.7

### Firefox/AMO

- Lädt bereits geöffnete HTTP- und HTTPS-Tabs der neu ergänzten Domain nach
  der bestätigten DNR-Aktivierung gezielt neu. Die Sperrseite erscheint damit
  bei Ergänzungen über die Kinderansicht und das Seiten-Kontextmenü sofort,
  ohne Firefox neu zu starten.
- Zeigt das Ubuntu-Parental-Control-Symbol am Erweiterungseintrag und in den
  Firefox-Kontextmenüs an.
- Öffnet die Regelverwaltung sowohl mit einem Klick auf das
  Erweiterungssymbol als auch über den neuen Eintrag „Regelverwaltung öffnen“
  in dessen Drei-Punkte-Menü.

## 0.3.6

### Firefox/AMO

- Zeigt die Domain-Eingabe in jedem bestätigten Kinderkonto für jede
  Blockierliste zuverlässig an und markiert eigene Ergänzungen als „Von dir
  ergänzt“. Die Oberfläche erklärt, dass diese manipulationsgeschützt getrennt
  von den Elternregeln in `user-domains.json` gespeichert werden.
- Meldet das Hinzufügen erst als erfolgreich, nachdem der Native Host einen
  neuen signierten Snapshot geliefert hat, die Domain darin enthalten ist und
  der Browser diesen Snapshot als aktiven Filter übernommen hat.

## 0.3.5

### Firefox/AMO

- Zeigt einen nicht erreichbaren Native Host jetzt deutlich als Ursache des
  Nur-Lesen-Modus an, statt die Eingabe zum Ergänzen von Domains kommentarlos
  auszublenden.
- Unterscheidet zwischen einer fehlenden Host-Verbindung und einem nicht
  bestätigten Kontostatus. Bekannte Fehler wie eine fehlende Registrierung,
  eine verweigerte Portalberechtigung, eine Zeitüberschreitung oder ein
  unerwarteter Verbindungsabbruch erhalten verständliche Hinweise.
- Blendet an betroffenen Blockierlisten ein eigenes Fehlerfeld ein und zeigt
  das unveränderte technische Detail zusätzlich in der globalen Statusbox an.
  Die aktiven Filterregeln bleiben währenddessen weiterhin wirksam.
- Baut die Native-Messaging-Verbindung nicht mehr beim Browserstart auf. Die
  Firefox-Snap-Einwilligung erscheint erst, wenn die Regelverwaltung oder eine
  konkrete Kontextmenü-Aktion den lokalen Verwaltungsdienst benötigt.
- Ergänzt auf HTTP- und HTTPS-Seiten das Kontextmenü „Aktuelle Website
  zusätzlich blockieren“. Die gewünschte Blockierliste wird als Untermenü
  gewählt; anschließend zeigt die Regelverwaltung Erfolg oder Fehler an.
- Installiert „Ubuntu Parental Control – Firefox verbinden“ in der
  Ubuntu-Anwendungsübersicht. Ein Kinderkonto kann damit eine zuvor
  verweigerte Firefox-Snap-Einwilligung verständlich und ohne Elternpasswort
  wieder erteilen; die UID-basierten append-only Rechte bleiben unverändert.
- Verknüpft den Sitzungshelfer direkt aus der Fehlerbox der Regelverwaltung.
  Der feste lokale URL-Handler akzeptiert nur die vorgesehene Reparaturaktion
  und erteilt ohne die anschließende ausdrückliche Bestätigung keine Freigabe.
## 0.3.4

### Firefox/AMO

- Führt klar unterscheidbare Eltern- und Kinderansichten in der grafischen
  Regelverwaltung ein. Im Kinderkonto bleiben geschützte Einstellungen
  sichtbar, sind aber ausgegraut und technisch deaktiviert.
- Zeigt beim Anlegen, Bearbeiten, Löschen und Ergänzen von Domains eine
  Warteanimation, bis der Verwaltungsdienst die Speicherung und den neuen
  Browser-Snapshot bestätigt hat.
- Entfernt den Schalter „Kind darf Domains ergänzen“. Registrierte
  Kinderkonten dürfen nun immer Domains zu Blockierlisten ergänzen, während
  Erlaubnislisten sowie alle löschenden oder lockernden Änderungen geschützt
  bleiben.
- Akzeptiert beim Update bereits vorhandene Blocks mit demselben sichtbaren
  Namen wieder. Ihre eindeutigen technischen IDs bleiben maßgeblich, sodass
  keine Regel verloren geht; nur das neue Anlegen oder Umbenennen auf einen
  bereits verwendeten Namen wird verhindert.

## 0.3.3

### Firefox/AMO

- Verhindert, dass die minütliche Zeitplanauswertung einen neueren
  Native-Live-Snapshot wieder durch den unter Firefox noch älteren
  `storage.managed`-Stand ersetzt. Gleichnamige Blocks mit unterschiedlichen
  technischen IDs bleiben dadurch nach dem Löschen eines Blocks korrekt aktiv.
- Lehnt identische sichtbare Blocknamen bereits vor der Domainabfrage ab und
  validiert diese Eindeutigkeit zusätzlich im Root-Helfer. Verschiedene Namen
  bleiben weiterhin über ihre dauerhaften technischen IDs getrennt.
- Der Firefox-Uninstaller kombiniert nun die dauerhaft durchgesetzte
  `ExtensionSettings: blocked`-Entfernung mit `Extensions.Uninstall`. Er stellt
  die ursprüngliche Policy erst wieder her, wenn die Extension aus allen
  gefundenen normalen, Snap- und Flatpak-Profilen verschwunden ist.

## 0.3.2

### Firefox/AMO

- Behebt, dass ein administrativ angelegter oder bearbeiteter Block in der
  laufenden Optionsseite wieder verschwinden konnte und erst nach einem
  Firefox-Neustart aktiv wurde.
- Der Native Host wartet nach einer Polkit-Änderung nun auf die bestätigte
  Veröffentlichung durch den Root-Daemon und liefert den neuen signierten
  Snapshot direkt in derselben Antwort an Firefox zurück.
- Die Oberfläche meldet eine Änderung erst dann als erfolgreich, wenn der neue
  Snapshot auch als dynamischer DNR-Regelsatz im laufenden Browser aktiviert
  wurde.

## 0.3.1

### Firefox/AMO

- Behebt irreführende Native-Host-Zeitüberschreitungen während einer laufenden
  Polkit-Passworteingabe. Administrative Anfragen warten nun bis zum Ende des
  erlaubten Polkit-Zeitfensters.
- Verhindert parallele oder wiederholte Administrator-Anfragen aus der
  Optionsseite. Beim Anlegen, Speichern oder Löschen ist dadurch nur noch eine
  Passwortabfrage pro Änderung vorgesehen.
- Erzeugt die technische Block-ID beim Anlegen automatisch aus dem
  verständlichen Blocknamen. Validierungsfehler erklären das erlaubte Format
  jetzt ohne den ungeklärten Fachbegriff „Kebab Case“.
- Normale Native-Messaging-Anfragen erhalten eine robustere Zeitgrenze; die
  Fehlermeldung nennt künftig den betroffenen Befehl. Nach erfolgreicher
  Wiederverbindung verschwindet eine veraltete Fehlermeldung automatisch.

## 0.3.0

### Firefox/AMO

- Ergänzt eine direkt über die Add-on-Einstellungen erreichbare grafische
  Regelverwaltung mit Blockübersicht, Zeitplan- und Zielbearbeitung.
- Verwendet Native Messaging als optionalen lokalen Livekanal. Neue validierte
  Regeln werden dadurch sofort in Firefox aktiviert, ohne auf ein erneutes
  Einlesen der Enterprise Policy oder einen Browserneustart zu warten.
- `storage.managed` bleibt die verbindliche Start- und Rückfallebene. Bei nicht
  verfügbarem Native Host bleibt der Filter aktiv und der Editor arbeitet im
  Nur-Lesen-Modus.
- Live-Snapshots und der UID-basierte Kontostatus werden mit einem
  rootgeschützten ECDSA-P-256-Schlüssel signiert. Die Erweiterung lehnt
  gefälschte Native-Nachrichten und einen nicht bestätigten Elternmodus ab.
- Die neue Berechtigung `nativeMessaging` dient ausschließlich dem lokalen
  Austausch mit dem rootinstallierten Ubuntu-Parental-Control-Host. Es werden
  keine Daten an externe Server übertragen.

### Sichere Regelverwaltung

- Eingeschränkte Ubuntu-Konten können ausschließlich Domains zu ausdrücklich
  freigegebenen Blocklisten hinzufügen. Entfernen, Ausnahmen und jede Lockerung
  sind für diese Konten technisch nicht als Dienstoperation verfügbar.
- Kinderergänzungen werden pro Linux-UID getrennt und rootgeschützt gespeichert
  und erst nach erneuter Gesamtvalidierung in den Browser-Snapshot übernommen.
- Administrative Änderungen aus der Extension benötigen bei jedem Speichern
  eine Polkit-Administratoranmeldung und verwenden weiterhin atomare Writes,
  Validierung und Versionshistorie.
- Firefox und Chrome verwenden dieselbe Optionsseite, denselben Native Host und
  denselben SHA-256-identifizierten Regelsnapshot.

## 0.2.2

### Firefox/AMO

- Zeigt bei blockierten HTTP(S)-Webseiten nun eine eigene, verständliche
  Hinweisseite anstelle einer allgemeinen Browser-Fehlermeldung.
- Die Hinweisseite erklärt, dass Ubuntu Parental Control den Zugriff durch eine
  verwaltete Webfilter-Regel verhindert hat und verweist an die verwaltende
  Person.
- Der Fail-safe verwendet dieselbe lokale Hinweisseite und bleibt weiterhin
  geschlossen, wenn keine gültige Regelkonfiguration aktiviert werden kann.
- Neu hinzugekommen sind Host-Berechtigungen ausschließlich für HTTP- und
  HTTPS-Seiten. Sie sind technisch erforderlich, um eine blockierte Navigation
  auf die lokale Erweiterungsseite umzuleiten. Es werden weiterhin keine
  besuchten URLs oder personenbezogenen Daten gespeichert oder übertragen.
- Die Blockseite enthält keinen externen Inhalt und keinen ausführbaren Code.

### Chrome

- Die gleiche Blockseite und Redirect-Logik wird auch für Chrome paketiert und
  mit denselben zentral verwalteten Regeln verwendet.

### Regelverwaltung

- Fügt mit `upcctl` ein erstes sicheres Kommandozeilenwerkzeug zum Anzeigen,
  Validieren und atomaren Übernehmen von Regeln hinzu.
- Administratoren können Domains gezielt zu bestehenden Blocks hinzufügen oder
  daraus entfernen. Jede Änderung wird vor dem Schreiben vollständig validiert.
- Blocks lassen sich mit sicheren Einzelbefehlen erstellen, umbenennen,
  aktivieren, deaktivieren, priorisieren, in ihrer Aktion ändern und nach einer
  ausdrücklichen Bestätigung löschen.
- Domain-Ausnahmen, URL-Patterns, URL-Regex und mehrere wöchentliche Zeitfenster
  samt IANA-Zeitzone sind über eigene validierte Befehle verwaltbar.
- Das vorbereitende Blockrecht `add_domains` lässt sich administrativ setzen;
  ein unprivilegierter append-only Schreibweg ist noch nicht enthalten.
- `apply --dry-run` zeigt geplante Änderungen als Diff, ohne Regeln oder
  Versionsverlauf zu verändern.
- Vor jeder tatsächlichen Änderung sichert `upcctl` die bisherige gültige
  Konfiguration rootgeschützt. `history` und `rollback` ermöglichen die
  kontrollierte, erneut validierte Wiederherstellung; auch Rollbacks können
  zunächst als Diff geprüft werden.
- Standardaktion und Profilzeitzone lassen sich mit `set-profile` verwalten.

## 0.2.1

### Firefox/AMO

- Behebt den Start des Hintergrundskripts unter Firefox Manifest V3. Die
  gemeinsame Regelengine wird nun über `background.scripts` vor dem
  browserspezifischen Hintergrundcode geladen.
- Verhindert dadurch, dass Firefox wegen des dort nicht verfügbaren
  `importScripts()` in den Fail-safe-Zustand gerät und sämtliche Webseiten
  blockiert.
- Berechtigungen, verwaltetes Regelprotokoll und Datenerhebung sind gegenüber
  0.2.0 unverändert. Die Erweiterung erhebt und überträgt weiterhin keine Daten.

### Chrome und Installation

- Chrome lädt dieselbe Regelengine weiterhin im Manifest-V3-Service-Worker.
  Der Startpfad wird nun explizit je Browser gewählt und automatisch getestet.
- Der Installer lehnt die fehlerhafte Firefox-Version 0.2.0 künftig ab.
- Der Firefox-Uninstaller arbeitet in zwei Neustartphasen: Zuerst wird die
  erzwungene Installation aufgehoben, danach entfernt eine separate
  `Extensions.Uninstall`-Policy die Erweiterung.

## 0.2.0

- Führt den gemeinsamen Firefox- und Chrome-Webfilter auf Basis derselben
  rootgeschützten Regeln ein.
- Verteilt validierte Regelsnapshots über `storage.managed` und aktiviert sie
  mit `declarativeNetRequest`.
- Enthält einen standardmäßig aktiven Fail-safe-Regelsatz, der bei fehlender
  oder ungültiger Policy HTTP(S)-Navigation blockiert.
