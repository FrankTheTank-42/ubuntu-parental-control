# Chrome Web Store – Einreichungstexte

## Datenschutzerklärung

Nach Veröffentlichung des aktuellen Repository-Stands:

`https://github.com/FrankTheTank-42/ubuntu-parental-control/blob/main/PRIVACY.md`

## Händlersymbol

`store-icon-128.png` ist eine PNG-Datei mit 128 × 128 Pixeln und transparentem
Hintergrund. Das Motiv belegt mittig 96 × 96 Pixel; der vorgeschriebene
transparente Innenabstand beträgt damit 16 Pixel pro Seite. Dasselbe Symbol ist
unter `icons/icon-128.png` im Chrome-Extension-ZIP enthalten.

## Screenshot

`screenshot-parent-1280x800.png` zeigt die Elternansicht der grafischen
Regelverwaltung mit einem zeitgesteuerten Block und besitzt das vom Chrome Web
Store erwartete Format von 1280 × 800 Pixeln.

## Beschreibung des allgemeinen Zwecks

Ubuntu Parental Control setzt die zentral verwalteten Webfilter-Regeln eines
lokalen Ubuntu-Systems in Chrome um. Die Erweiterung blockiert konfigurierte
Domains und URLs, berücksichtigt Zeitpläne und zeigt bei einer Sperre eine
lokale Hinweisseite an. Eltern können Regeln über die Erweiterungsoberfläche
verwalten; eingeschränkte Konten dürfen Blockierlisten ausschließlich durch
weitere Domains verschärfen. Firefox und Chrome verwenden dabei denselben
lokalen, rootgeschützten Regelsatz. Die Erweiterung überträgt keine Browserdaten
an externe Server.

## Begründung für `storage`

Die Erweiterung liest mit `storage.managed` die durch Ubuntu Enterprise Policy
bereitgestellte, schreibgeschützte Startkonfiguration. Sie enthält den
validierten Regelsnapshot, seine Prüfsumme und den öffentlichen Schlüssel zur
Prüfung lokaler Live-Aktualisierungen. Die Erweiterung speichert damit keine
Browserhistorie und liest keine sonstigen Nutzerdaten.

## Begründung für `alarms`

Ein minütlicher Alarm weckt den Extension-Service-Worker, damit zeitabhängige
Blockregeln zuverlässig neu ausgewertet werden. Dadurch werden Beginn und Ende
konfigurierter Zeitfenster auch dann wirksam, wenn keine Policy-Änderung oder
Browsernavigation den Service-Worker anderweitig aktiviert.

## Begründung für `contextMenus`

Die Erweiterung bietet auf HTTP- und HTTPS-Seiten den ausdrücklich ausgelösten
Menüeintrag „Aktuelle Website zusätzlich blockieren“ an. Nach Auswahl einer
Blockierliste wird die aktuelle Adresse einmalig im Arbeitsspeicher verarbeitet
und ausschließlich ihr Hostname als neue lokale Filterregel übernommen. Pfad,
Suchparameter und Seiteninhalt werden nicht gespeichert oder übertragen. Ohne
diese Benutzeraktion liest die Erweiterung die aktuelle Seitenadresse nicht.

## Begründung für `declarativeNetRequest`

Die Berechtigung setzt die validierten Filterregeln als deklarative,
browserseitig ausgeführte Netzwerkregeln um. Die Erweiterung ersetzt den
dynamischen Regelsatz atomar und leitet gesperrte Hauptseiten-Navigationen auf
eine lokale Hinweisseite um. Seiteninhalte werden dabei weder gelesen noch an
die Erweiterung oder externe Dienste übertragen.

## Begründung für `nativeMessaging`

Native Messaging verbindet die Erweiterung ausschließlich mit dem lokal
installierten Ubuntu-Parental-Control-Dienst. Der Dienst liefert signierte
Regelaktualisierungen ohne Browserneustart und bestätigt anhand der Linux-UID,
ob die Eltern- oder Kinderansicht angezeigt werden darf. Administrative
Änderungen werden lokal über Polkit autorisiert. Es findet keine Kommunikation
mit externen Servern statt; bei Ausfall des Native Hosts bleibt die verwaltete
Startkonfiguration als sicherer Nur-Lesen-Fallback aktiv.

## Begründung für die Hostberechtigungen

Die Berechtigungen für `http://*/*` und `https://*/*` sind erforderlich, damit
`declarativeNetRequest` konfigurierte Websites unabhängig von ihrer Domain
blockieren und gesperrte Hauptseiten auf die lokale Hinweisseite umleiten kann.
Die Erweiterung liest keine Seiteninhalte, Formulareingaben oder
Browserhistorie. Die Zugriffsentscheidung erfolgt ausschließlich anhand der
lokalen, administrativ verwalteten Filterregeln.
