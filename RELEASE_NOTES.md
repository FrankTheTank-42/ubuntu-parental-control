# Versionshinweise

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
