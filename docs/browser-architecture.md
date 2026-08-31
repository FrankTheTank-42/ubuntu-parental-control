# Browserübergreifende Regelverteilung

Die Sicherheitsziele, Angreiferrollen und bekannten Restrisiken dieser
Architektur sind im [Threat Model](threat-model.md) festgehalten. Dieses
Dokument beschreibt den technischen Soll-Datenfluss; das Threat Model bewertet
zusätzlich seine Vertrauensgrenzen und offenen Härtungsaufgaben.

## Vertrauensgrenze

`/etc/ubuntu-parental-control/rules.json` enthält die rootgeschützten
Administratorregeln. Append-only Ergänzungen eingeschränkter Konten liegen
getrennt unter `/var/lib/ubuntu-parental-control/user-domains.json`. Der als
root laufende Daemon validiert und vereinigt beide Ebenen und veröffentlicht
erst danach einen kompakten Snapshot.

Firefox und Chrome erhalten denselben Snapshot weiterhin über die
schreibgeschützte WebExtension-API `storage.managed`. Zusätzlich schreibt der
Daemon den aktiven Snapshot rootkontrolliert nach
`/run/ubuntu-parental-control/live-snapshot.json`. Ein Native-Messaging-Host
liest diese Datei und übermittelt Änderungen an die laufende Extension. Der
Livekanal ist optional; sein Ausfall verändert die aktiven Regeln nicht und
`storage.managed` bleibt Start- und Fallbackquelle.

Für Firefox Snap wird der Native Host über das WebExtensions-XDG-Portal
gestartet. Eine verweigerte oder fehlende Portalberechtigung schaltet nur
Liveaktualisierung und Editor ab, nicht den verwalteten Filter.
Die Extension startet diese Verbindung nicht beim Browserstart, sondern erst
beim Öffnen der Regelverwaltung oder nach einer konkreten Kontextmenü-Aktion.
Die Portalabfrage steht dadurch in einem verständlichen Zusammenhang mit der
gewünschten lokalen Änderung.
Eine zuvor verweigerte Entscheidung kann das betroffene Konto über den
installierten Sitzungshelfer `upc-firefox-consent` wieder erlauben oder
zurücksetzen. Der Helfer ändert nur den Eintrag
`webextensions/ubuntu_parental_control/snap.firefox` im XDG PermissionStore und
benötigt keine Rootrechte. Die eigentlichen Schreibrechte bleiben unabhängig
davon durch Peer-UID, Rollenprüfung und Signaturen begrenzt.
Die Regelverwaltung erreicht den Helfer auch ohne Native Messaging über den
systemweit registrierten URI-Handler
`ubuntu-parental-control://firefox-consent/allow`. Der Helfer akzeptiert nur
diese exakte URI und verlangt interaktiv eine Bestätigung. Dadurch kann eine
Website höchstens den Dialog öffnen, aber niemals die Einwilligung selbst
erteilen.

## Veröffentlichte Daten

Der Managed Snapshot enthält:

- `protocol_version`: Version des Extension-/Daemon-Protokolls,
- `revision`: SHA-256 über das kanonische Regelobjekt,
- `snapshot_json`: kanonisches JSON aus Protokollversion, Revision und Regeln.
- `live_public_key_spki`: öffentlicher ECDSA-P-256-Vertrauensanker für den
  lokalen Livekanal.

Der Live-Snapshot ergänzt `live_signature`, eine Signatur über die exakten
UTF-8-Bytes von `snapshot_json`. Der private Schlüssel liegt ausschließlich
rootlesbar unter `/var/lib/ubuntu-parental-control/live-signing-key.pem`.

Die doppelte Revision erkennt abgeschnittene, gemischte oder anderweitig
beschädigte Policy-Daten. Für Managed Storage beruht die Authentizität auf den
rootgeschützten Enterprise-Policy-Dateien. Live-Nachrichten werden zusätzlich
gegen den daraus gelesenen öffentlichen Schlüssel geprüft. Damit kann auch ein
vom Kinderkonto in dessen Benutzerprofil platzierter Native Host keine
abweichenden Filterregeln aktivieren.

## Browseradapter

Firefox liest die Daten aus `policies.3rdparty.Extensions` in der bereits für
Firefox Snap funktionierenden Datei `/etc/firefox/policies/policies.json`.
Chrome liest denselben Inhalt aus `3rdparty.extensions` in
`/etc/opt/chrome/policies/managed/ubuntu-parental-control.json`.
Die Chrome-Projekt-Policy setzt außerdem `IncognitoModeAvailability: 1`,
`BrowserGuestModeEnabled: false` und `DeveloperToolsAvailability: 2`.

Die gemeinsame Extension-Regelengine:

1. liest und prüft Managed Storage,
2. prüft die SHA-256-Revision,
3. wertet die Wochenzeitpläne in der jeweiligen IANA-Zeitzone aus,
4. übersetzt aktive Blocks in dynamische DNR-Regeln,
5. prüft jeden Regex mit `declarativeNetRequest.isRegexSupported()`,
6. ersetzt den dynamischen Regelsatz atomar.

Native Snapshots durchlaufen dieselbe Protokoll-, Schema-, SHA-256-, Regex- und
DNR-Prüfung wie Managed Storage und zusätzlich die ECDSA-Prüfung. Ein
ungültiger Native Snapshot fällt zuerst auf Managed Storage zurück und öffnet
den Filter niemals.

## Lokale Verwaltung

Der Native Host läuft mit der UID des Browserkontos. Schreibanfragen gehen über
einen Unix-Socket an den Root-Daemon, der die echte Peer-UID mit `SO_PEERCRED`
ermittelt. Angaben zur Benutzerrolle aus der Extension werden nicht vertraut.
Der Daemon signiert seinen UID-basierten Status zusammen mit einer frischen
Zufallskennung der Extension. So kann ein ersetzter Native Host weder eine
Elternrolle erfinden noch einen alten Status aus einer anderen Anfrage
wiederverwenden.

Registrierte Kinder-UIDs dürfen ausschließlich `add_domain` für Regeln mit
`action: block` ausführen. Diese append-only Berechtigung gilt immer und kann
nicht versehentlich über einen UI-Schalter abgeschaltet werden. Der Socket
bietet keine Lösch- oder Lockerungsoperation für diese Rolle.
Die Kinderansicht darf zusätzlich ausschließlich die eigenen, bereits
gespeicherten Ergänzungen abfragen, um sie kenntlich zu machen; Ergänzungen
anderer UIDs und die unveränderten Basisregeln werden dabei nicht offengelegt.
Administratoreingriffe laufen separat über einen rootinstallierten Helper und
Polkit mit `auth_admin` für jede einzelne Speicherung. Der Helper akzeptiert
nur vollständig validierte Regelobjekte oder das gezielte Entfernen einer
append-only Ergänzung.

Das Kontextmenü entsteht ausschließlich aus dem bereits geprüften aktiven
Snapshot und benötigt keinen Native Host. Nach Auswahl einer Blockierliste
extrahiert die Extension den Hostnamen aus der ausdrücklich ausgewählten
HTTP(S)-Seite, öffnet die Regelverwaltung und verwendet anschließend denselben
UID-authentifizierten Schreibweg wie die manuelle Domain-Eingabe. Pfad und
Suchparameter werden nicht in die Regel übernommen.

Nach der bestätigten Aktivierung einer Kinderergänzung fragt die Extension nur
nach offenen HTTP(S)-Tabs, die genau zur ergänzten Domain oder einer ihrer
Subdomains gehören, und lädt diese neu. Bereits gerenderte Seiten werden so
erst nach installierter DNR-Regel erneut angefordert und unmittelbar auf die
lokale Blockseite umgeleitet. Ein Fehler beim Neuladen eines einzelnen Tabs
macht die zuvor erfolgreich gespeicherte und aktivierte Regel nicht rückgängig.

Das Manifest definiert außerdem ein gemeinsames Erweiterungssymbol für Firefox
und Chrome. Ein Klick auf die Browseraktion sowie der Eintrag
„Regelverwaltung öffnen“ in ihrem Kontextmenü führen zur Optionsseite. Das
Seiten-Kontextmenü verwendet dasselbe Symbol; Firefox zeigt es zusätzlich an
den Blockierlisten-Untermenüs.

Das Kontextmenü der Browseraktion enthält zusätzlich „Webseite zu Block
hinzufügen“. Dessen Untermenü wird aus denselben aktiven Blockierlisten wie das
Seiten-Kontextmenü erzeugt. Nach der Auswahl liefert das Menüereignis den
zugehörigen aktuellen Tab; die Extension extrahiert ausschließlich dessen
HTTP(S)-Hostnamen und öffnet den vorhandenen bestätigten Ergänzungsablauf.

Nach einer erfolgreichen Polkit-Änderung wartet der Native Host auf eine neue
Veröffentlichungsnummer des Daemons und die passende Basis- beziehungsweise
Benutzerregel-Revision. Den dabei erzeugten signierten Snapshot liefert er
direkt als Teil der Adminantwort an die Extension. Eine Speicherung gilt in
der Oberfläche deshalb erst als abgeschlossen, nachdem Firefox diesen
Snapshot geprüft und als DNR-Regelsatz aktiviert hat.

Höhere Blockprioritäten erzeugen höhere DNR-Prioritäten. Bei derselben
Blockpriorität erhält `block` eine um eins höhere DNR-Priorität als `allow`.

## Blockseite und Fail-safe

Explizite Blockregeln leiten HTTP(S)-Navigation auf die paketierte Seite
`/blocked/blocked.html` um. Beide Manifeste deklarieren dafür ausschließlich
HTTP(S)-Hostberechtigungen und veröffentlichen die HTML-Datei als
`web_accessible_resources`. Der Redirect übergibt ausschließlich die technische
ID des auslösenden Blocks. Ein lokales Skript fragt dazu den Namen aus dem
bereits aktiven, verifizierten Snapshot ab und zeigt ihn auf der Blockseite an.
Unbekannte oder manipulierte IDs werden ignoriert. Die ursprünglich besuchte
URL wird weder gelesen noch gespeichert oder übertragen; externe Ressourcen
werden nicht geladen.

Das signierte Extension-Paket enthält einen standardmäßig aktiven statischen
Regelsatz, der HTTP(S)-Navigation in Haupt- und Unterframes auf dieselbe lokale
Blockseite umleitet. Bei einer Konfiguration mit `default_action: allow` wird er
erst nach erfolgreicher Installation aller dynamischen Regeln deaktiviert. Bei
`default_action: block` bleibt er als Default-Deny-Regel aktiv; höher
priorisierte dynamische Allow-Regeln bilden die Freigaben.

Schlägt Lesen, Prüfsummenprüfung, Regex-Prüfung oder DNR-Aktivierung fehl, wird
der statische Regelsatz aktiviert und werden dynamische Regeln entfernt. Damit
können alte Allow-Regeln den Fail-safe nicht überstimmen.

## Aktualisierung

Die Engine reagiert auf Browserstart, Service-Worker-Start,
`storage.onChanged`, Native Snapshots und einen minütlichen Alarm. Der Alarm
wertet insbesondere Zeitpläne neu aus. Der Native Host beobachtet die aktive
Snapshot-Datei und übermittelt eine neue Revision an den laufenden Browser;
bei verfügbarem Native Host ist für gültige Regeländerungen deshalb kein
Firefox-Neustart mehr erforderlich.

Alle Aktivierungswege teilen sich eine serielle Warteschlange. Sobald ein
signierter Native Snapshot aktiv ist, darf ein verspätetes
`storage.onChanged`-Ereignis ihn nicht durch den unter Firefox möglicherweise
noch älteren Managed-Storage-Cache ersetzen. Managed Storage bleibt beim
Browserstart und als expliziter Fallback nach einem abgelehnten Native Snapshot
weiterhin die Vertrauensbasis.

Die direkte Antwort einer erfolgreichen Schreiboperation und das nachfolgende
Datei-Live-Event können denselben signierten Snapshot enthalten. Nach
Signatur-, Schema- und Revisionsprüfung erkennt die Extension eine bereits
aktive Revision und behandelt die zweite Zustellung nur als Bestätigung. Der
identische DNR-Regelsatz wird nicht erneut mit denselben IDs registriert.

Der Native Host verhindert die doppelte Zustellung zusätzlich an der Quelle:
Enthält eine erfolgreiche Befehlsantwort bereits einen Snapshot, merkt sich
dieser Host-Prozess dessen kryptografische Revision als zugestellt. Erkennt
der Dateiwächter anschließend dieselbe Revision, aktualisiert er nur seine
Dateisignatur. Eine abweichende neuere Revision wird weiterhin gesendet. Da
jede Browser-Verbindung einen eigenen Native-Host-Prozess besitzt, erhalten
andere laufende Browser die Änderung unabhängig davon als Live-Event.

## Bewusste DNR-Einschränkung

Domain-Ausnahmen sind über `excludedRequestDomains` exakt darstellbar. Für eine
beliebige Pattern- oder Regex-Ausnahme bietet DNR keine allgemeine
blocklokale Negation. Eine globale Allow-Regel wäre falsch, weil sie Regeln
anderer Blocks überstimmen könnte. Der Publisher lehnt solche Snapshots deshalb
ab, statt ihre Bedeutung abzuschwächen.
