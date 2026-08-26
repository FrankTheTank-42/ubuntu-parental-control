# Browserübergreifende Regelverteilung

## Vertrauensgrenze

`/etc/ubuntu-parental-control/rules.json` ist die einzige fachliche Regelquelle.
Nur root darf sie ändern. Der als root laufende Daemon validiert die Datei und
veröffentlicht erst danach einen kompakten Snapshot. Firefox und Chrome erhalten
denselben Snapshot und lesen ihn ausschließlich über die schreibgeschützte
WebExtension-API `storage.managed`.

Es gibt keinen Native-Messaging-Host und keinen lokalen Netzwerkdienst. Damit
hängt Firefox Snap weder vom Native-Messaging-Portal noch von einer durch den
eingeschränkten Benutzer erteilbaren Portalberechtigung ab.

## Veröffentlichte Daten

Der Snapshot enthält:

- `protocol_version`: Version des Extension-/Daemon-Protokolls,
- `revision`: SHA-256 über das kanonische Regelobjekt,
- `snapshot_json`: kanonisches JSON aus Protokollversion, Revision und Regeln.

Die doppelte Revision erkennt abgeschnittene, gemischte oder anderweitig
beschädigte Policy-Daten. Sie ist keine Signatur: Die Authentizität beruht auf
den rootgeschützten Enterprise-Policy-Dateien.

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

Höhere Blockprioritäten erzeugen höhere DNR-Prioritäten. Bei derselben
Blockpriorität erhält `block` eine um eins höhere DNR-Priorität als `allow`.

## Fail-safe

Das signierte Extension-Paket enthält einen standardmäßig aktiven statischen
Regelsatz, der HTTP(S)-Navigation in Haupt- und Unterframes blockiert. Bei einer
Konfiguration mit `default_action: allow` wird er erst nach erfolgreicher
Installation aller dynamischen Regeln deaktiviert. Bei `default_action: block`
bleibt er als Default-Deny-Regel aktiv; höher priorisierte dynamische
Allow-Regeln bilden die Freigaben.

Schlägt Lesen, Prüfsummenprüfung, Regex-Prüfung oder DNR-Aktivierung fehl, wird
der statische Regelsatz aktiviert und werden dynamische Regeln entfernt. Damit
können alte Allow-Regeln den Fail-safe nicht überstimmen.

## Aktualisierung

Die Engine reagiert auf Browserstart, Service-Worker-Start,
`storage.onChanged` und einen minütlichen Alarm. Der Alarm wertet insbesondere
Zeitpläne neu aus. Er kann nur Policy-Daten sehen, die der jeweilige Browser
bereits neu eingelesen hat. Chrome unterstützt dynamisches Policy-Refresh;
Firefox kann für geänderte Enterprise-Policies einen Browserneustart benötigen.

## Bewusste DNR-Einschränkung

Domain-Ausnahmen sind über `excludedRequestDomains` exakt darstellbar. Für eine
beliebige Pattern- oder Regex-Ausnahme bietet DNR keine allgemeine
blocklokale Negation. Eine globale Allow-Regel wäre falsch, weil sie Regeln
anderer Blocks überstimmen könnte. Der Publisher lehnt solche Snapshots deshalb
ab, statt ihre Bedeutung abzuschwächen.
