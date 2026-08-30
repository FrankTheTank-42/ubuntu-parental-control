# Sicherheitsrichtlinie

Ubuntu Parental Control ist ein früher Prototyp für einen sicherheitsrelevanten
Anwendungsfall. Es gab noch kein unabhängiges Audit. Bitte behandle das Projekt
nicht als alleinige Schutzschicht für ein Gerät oder Netzwerk.

## Unterstützter Stand

Sicherheitskorrekturen werden derzeit ausschließlich für den neuesten Stand
des `main`-Branches und die neueste veröffentlichte Browsererweiterung
betrachtet. Für ältere Versionen gibt es keine eigene Supportzusage.

Die dokumentierten Garantien und bekannten Restrisiken stehen im
[Threat Model](docs/threat-model.md). Rootzugriff, ein alternatives
Bootmedium, nicht verwaltete Browser und Netzwerkverkehr anderer Programme
liegen außerhalb der Sicherheitsgrenze.

## Sicherheitsproblem melden

Bitte veröffentliche keine Exploitdetails, privaten Regeldaten, Benutzernamen
oder realen Browserverlauf in einem öffentlichen Issue.

Falls GitHub im Bereich **Security** des Repositorys die private Meldung einer
Schwachstelle anbietet, verwende diesen Kanal. Solange kein privater Kanal
angeboten wird, öffne nur ein minimales öffentliches Issue mit dem Titel
„Private security contact requested“ und ohne technische Details. Der
Maintainer stimmt anschließend einen nicht öffentlichen Übermittlungsweg ab.

Eine hilfreiche Meldung enthält:

- betroffene Projekt- und Browserversion,
- Ubuntu-, Firefox- beziehungsweise Chrome-Version,
- erforderliche Angreiferrolle und Voraussetzungen,
- reproduzierbare Schritte mit ausschließlich synthetischen Testdaten,
- erwartetes und beobachtetes Verhalten sowie
- eine Einschätzung der Auswirkung auf Integrität, Vertraulichkeit oder
  Verfügbarkeit.

## Umgang mit Meldungen

Der Maintainer bestätigt Meldungen nach Möglichkeit zeitnah, reproduziert sie
zunächst in einer isolierten Testumgebung und veröffentlicht technische Details
erst zusammen mit einer Korrektur oder nach abgestimmter Offenlegung. Für den
Prototyp kann derzeit keine feste Reaktions- oder Behebungsfrist zugesichert
werden.

Bei einer bestätigten Umgehung der Filterregeln haben eine fail-safe
Zwischenmaßnahme, ein Regressionstest und eine verständliche Warnung für
Betroffene Vorrang vor neuen Funktionen.
