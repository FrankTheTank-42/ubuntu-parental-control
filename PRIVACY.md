# Datenschutzerklärung für Ubuntu Parental Control Webfilter

Stand: 28. August 2026

## Verantwortlicher und Kontakt

Frank Winkler, E-Mail: frankwinkler42@posteo.de

## Geltungsbereich und Zweck

Diese Datenschutzerklärung gilt für die Browser-Erweiterung „Ubuntu Parental
Control Webfilter“ für Google Chrome und Mozilla Firefox. Ihr einziger Zweck
ist, lokal administrierte Webfilter-Regeln im Browser umzusetzen und
eingeschränkten Linux-Konten ausschließlich zusätzliche Verschärfungen von
Blockierlisten zu ermöglichen.

## Lokal verarbeitete Daten

Die Erweiterung und der zugehörige lokale Ubuntu-Dienst verarbeiten nur die
für diesen Zweck erforderlichen Daten:

- die numerische Linux-Benutzer-ID (UID), um zwischen administrativen und
  eingeschränkten lokalen Konten zu unterscheiden;
- vom Administrator konfigurierte Domains, URL-Patterns, reguläre Ausdrücke,
  Ausnahmen, Prioritäten und Zeitpläne;
- Domains, die ein eingeschränktes Konto bewusst zu einer Blockierliste
  hinzufügt;
- technische Prüfsummen, Revisionsnummern, Signaturen und zufällige Nonces zur
  Integritäts- und Authentizitätsprüfung lokaler Regelnachrichten.

Die Erweiterung liest, protokolliert oder speichert insbesondere keine
tatsächlich besuchten URLs, keine Browserhistorie, keine Seiteninhalte, keine
Formulareingaben, keine Passwörter, keine Cookies und keine persönlichen
Kommunikationsinhalte. Chrome führt den Abgleich einer Navigation mit den
Filterregeln intern über `declarativeNetRequest` aus; die aufgerufene URL wird
der Erweiterung dabei nicht als Browserverlauf übermittelt.

## Verarbeitung und Speicherung

Die Verarbeitung findet ausschließlich auf dem lokalen Ubuntu-System statt.
Die zentrale Konfiguration wird über die schreibgeschützte Browser-Schnittstelle
`storage.managed` bereitgestellt. Live-Aktualisierungen und Verwaltungsanfragen
werden ausschließlich zwischen der Erweiterung und dem lokal installierten
Native-Messaging-Host ausgetauscht.

Regeln und Benutzerergänzungen werden in rootgeschützten lokalen Systemdateien
gespeichert. Es gibt keine Cloud-Synchronisierung, keine Analyse- oder
Telemetriedienste, keine Werbung und kein Nutzertracking.

## Übermittlung und Weitergabe

Die Erweiterung übermittelt keine Nutzer-, Browser- oder Konfigurationsdaten an
den Entwickler, an Google oder an sonstige externe Server oder Dritte. Der
lokale Native-Messaging-Host ist Bestandteil derselben installierten Anwendung
und kommuniziert nur über lokale Betriebssystem-Schnittstellen.

Die Nutzung der verarbeiteten Informationen ist auf den beschriebenen einzigen
Zweck beschränkt und entspricht den Limited-Use-Anforderungen der Chrome Web
Store User Data Policy. Daten werden weder verkauft noch für Werbung,
Profilbildung, Kreditwürdigkeitsprüfungen oder andere sachfremde Zwecke
verwendet.

## Speicherdauer und Löschung

Konfigurierte Regeln bleiben gespeichert, bis sie von einem Administrator
geändert oder gelöscht werden. Von eingeschränkten Konten hinzugefügte Domains
können durch einen Administrator entfernt werden. Der mitgelieferte
Uninstaller löscht die Regeln, Benutzerergänzungen, Revisionshistorie und
lokalen Signaturschlüssel des Projekts.

Da keine Daten an den Entwickler übertragen werden, besitzt der Entwickler
keine serverseitige Kopie, die eingesehen, berichtigt oder gelöscht werden
könnte. Fragen zur lokalen Verarbeitung können an die oben angegebene
Kontaktadresse gerichtet werden.

## Änderungen

Diese Datenschutzerklärung wird angepasst, wenn sich die Datenverarbeitung der
Erweiterung ändert. Die jeweils aktuelle Fassung wird in diesem Repository
veröffentlicht.
