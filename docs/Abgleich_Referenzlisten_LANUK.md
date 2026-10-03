# Abgleich der überarbeiteten LANUK-Referenzlisten

**Fachschale „Fundpunkte Tiere“ · Stand der Prüfung: 25.09.2026**

Grundlage sind zwei Lieferungen:

| Datei | Inhalt |
| --- | --- |
| `Refliste_FT_Entwicklung_2027.ods` | Überarbeitete Referenzlisten, **ENTWURF Arbeitsstand 18.09.2026, FB24 / FB21** |
| `Referenzen_2026-08-30.gpkg` | Bisheriger Projektstand der Referenzlisten |

---

# 1. Zusammenfassung

Die Arbeitsmappe bringt **neun Listen**, davon drei fachlich neu
(Erfassungsmethode, Häufigkeit, geografische Genauigkeit) und sechs
überarbeitet. Insgesamt kommen 165 Einträge hinzu, 32 entfallen.

Zwei Punkte sind vor der Umsetzung zu klären, weil sie die Kaskade
bzw. bestehende Daten betreffen (Abschnitte 4.1 und 4.2).

**Zur „neuen Artenliste“:** Die Tabelle `Arten` im gelieferten GeoPackage ist
mit dem bisherigen Stand **inhaltlich identisch** (13.291 Einträge, alle
Spalten übereinstimmend). Neu enthalten ist die Tabelle `Arten_Synonyme`
(120 Einträge, ausschließlich Typ „Synonym“). Eine überarbeitete Artenliste
ist in den beiden Dateien somit nicht enthalten — bitte prüfen, ob sie
separat nachgeliefert wird.

---

# 2. Listen im Überblick

| LANUK-Blatt | Zieltabelle | bisher | neu | Kaskade |
| --- | --- | --- | --- | --- |
| ft_zähleinheit | Einheit | 13 | 4 | – |
| ft_Status_Tier | Status | 66 | 101 | ja (3 Gruppen) |
| 0_ft_stadium | Stadium | 19 | 18 | – |
| ft_geschlecht | Geschlecht | 4 | 4 | – |
| ft_genauigkeit_Bestandsangabe | Genauigkeit_Bestandsangabe | 3 (als „Unschaerfe“) | 3 | – |
| ft_geogenau | **Geogenauigkeit (neu)** | – | 6 | – |
| ft_haeufigkeit | **Haeufigkeit (neu)** | – | 28 | unklar |
| ft_ErfassMethode | **Erfassungsmethode (neu)** | – | 128 | ja (14 Gruppen) |
| ft_adressrolle | Adressrolle | 94 (als „Institution“) | 87 | – |

---

# 3. Fachlich neue Listen — Auswirkung auf das Datenmodell

Drei Listen haben im bisherigen Datenmodell **kein zugehöriges Feld**. Sollen
sie genutzt werden, sind Anlage A (Tabelle `Fund`) und die
Leistungsbeschreibung zu erweitern:

- **Erfassungsmethode** (128 Werte, nach Artengruppe kaskadiert) — fachlich
  ein zentrales Feld für die LANUK-Auswertung.
- **Häufigkeit** (28 Werte) — Schätzklassen als Alternative bzw. Ergänzung zur
  exakten `Anzahl`.
- **Geogenauigkeit** (6 Werte: punkt-/flächengenau bis „im Bezugsraum nicht
  präzise verortet“) — betrifft die Lagegenauigkeit des Fundpunktes.

Da bei mobiler Erfassung die Koordinate stets GPS-genau ermittelt wird, ist zu
entscheiden, ob `Geogenauigkeit` im QField-Formular überhaupt erscheinen oder
mit einem festen Standardwert vorbelegt werden soll.

---

# 4. Zu klärende Punkte

## 4.1 Artengruppen-Kaskade passt nicht auf unsere Artengruppen (blockierend)

`ft_ErfassMethode` und `ft_Status_Tier` sind über Gruppenkopfzeilen nach
Artengruppe gegliedert. Diese Gruppenköpfe verwenden jedoch ein **anderes
Gruppierungsschema** als unsere Referenzliste `Artengruppen` (41 Einträge).

Von 14 Gruppenköpfen der Erfassungsmethode finden sich nur **drei** in unserer
Artengruppen-Liste wieder:

| LANUK-Gruppe | entityid | in unserer Liste `Artengruppen` |
| --- | --- | --- |
| Vögel | 102937 | ja |
| Geradflügler | 6909 | ja |
| Libellen | 6827 | ja |
| Fledermäuse | 153231 | **nein** |
| Fische | 153237 | **nein** |
| Hautflügler | 151909 | **nein** |
| Käfer | 151910 | **nein** |
| Kriechtiere | 154059 | **nein** |
| Lurche | 154065 | **nein** |
| Schmetterlinge | 154153 | **nein** |
| sonstige Säugetiere | 153236 | **nein** |
| Spinnen | 153299 | **nein** |
| Weichtiere | 153256 | **nein** |

Die Schemata sind nicht nur unterschiedlich benannt, sondern schneiden die
Gruppen anders zu: Unsere Liste führt „Amph-Reptilien“ zusammen, das LANUK
trennt „Kriechtiere“ und „Lurche“; unsere Liste kennt „Säugetiere“, das LANUK
unterscheidet „Fledermäuse“ und „sonstige Säugetiere“; „Schnecken, Muscheln“
entspricht dem LANUK-Begriff „Weichtiere“.

Teilweise handelt es sich um die **Elternebene** unserer Liste: Ameisen,
Bienen, Gall-/Schlupfwespen, Pflanzenwespen und Weitere Stechimmen tragen
`parentid = 158741`, was inhaltlich den „Hautflüglern“ entspricht — diese
Elternebene ist in unserer Liste jedoch nicht als eigene Zeile enthalten.

**Ohne Zuordnungstabelle zwischen beiden Schemata lässt sich die Kaskade für
Status und Erfassungsmethode nicht an das Feld `Artengruppe` binden.**
Benötigt wird vom LANUK entweder (a) eine Crosswalk-Tabelle
41 Artengruppen → 14 Gruppen, oder (b) die Gruppenzuordnung direkt in den
Listen auf Basis unserer `listitemid`.

## 4.2 Zähleinheit: Reduktion von 13 auf 4 Werte

Die neue Liste enthält nur noch *Individuen / Einzeltiere*, *Brutpaare*,
*Paare* und *keine Angabe*. Es entfallen unter anderem sämtliche
Bezugsflächen- und Streckenangaben:

`auf 1 qm`, `auf 10 qm`, `auf 100 qm`, `auf 1 ha`, `auf 1 m`, `auf 10 m`,
`auf 100 m`, `auf 500 m`, `Fläche in qm`, `Individuen gesamt`.

Zusätzlich ändert sich die ID für *keine Angabe* von `139716` auf `42734`.

Bestehende Datensätze mit diesen Einheiten verlieren damit ihren
Referenzbezug. Vor dem Austausch ist zu klären, ob diese Werte in den
Altdaten der Biologischen Stationen vorkommen und wie sie überführt werden
sollen.

## 4.3 Häufigkeit: Skalenzuordnung nicht auswertbar

Das Blatt enthält vier mit „neue Gruppenskala“ überschriebene Blöcke, von
denen **nur der erste eine entityid** (192952) trägt. Der Wert „1“ (192940)
kommt in drei Blöcken identisch vor. Damit lässt sich maschinell nicht
bestimmen, welche Skala wann gilt und wie die Blöcke zu unterscheiden sind.
Hier ist eine eindeutige Kennzeichnung der Skalen erforderlich — vermutlich
abhängig von Artengruppe oder Zähleinheit.

## 4.4 Institution → Adressrolle: Begriffswechsel

Die bisherige Liste `Institution` wird durch `ft_adressrolle` abgelöst. Das ist
nicht nur eine Umbenennung, sondern ein Konzeptwechsel von der *Institution*
zur *Rolle* der erfassenden Stelle. Es entfallen unter anderem `LANUV`,
`LOEBF`, `Eigene BS`, `Kartierung / Bearbeitung` und
`Mitarbeiter(-in) der LOEBF`; neu sind `Mitarbeiter(in) des LANUK` und
`Flurbereinigungsbehörde`.

Für die Biologischen Stationen ist relevant, dass ein Eintrag „Eigene BS“
entfällt. Zu klären: Welche Rolle sollen die Stationen künftig wählen
(`Naturschutzverband`, `ehrenamtliche Mitarbeit`, …), und bleibt daneben ein
Freitextfeld für die konkrete Station erhalten?

## 4.5 Stadium: Wert „unbestimmt“ entfällt

Die neue Stadium-Liste enthält kein „unbestimmt“ mehr (bisher `153225`).
Dieser Wert existiert nur noch in der Liste `Geschlecht`. Falls „unbestimmt“
auch für das Stadium wählbar bleiben soll, ist er beim LANUK nachzufordern.

## 4.6 Zwei unterschiedliche Genauigkeits-Begriffe

Die bisherige Tabelle `Unschaerfe` entspricht inhaltlich
`ft_genauigkeit_Bestandsangabe` (exakte Angabe / Minimum / Schätzung) und
bezieht sich auf die **Bestandszahl**. Das neue Blatt `ft_geogenau` beschreibt
dagegen die **Lagegenauigkeit**. Beide Begriffe sind künftig sauber zu
trennen; die Tabelle `Unschaerfe` sollte in `Genauigkeit_Bestandsangabe`
umbenannt werden, um Verwechslungen zu vermeiden.

---

# 5. Umschlüsselung bisher synthetischer IDs

Bei der Trennung Stadium/Geschlecht wurden übergangsweise eigene IDs vergeben,
weil noch keine LANUK-Schlüssel vorlagen. Diese werden jetzt durch die
offiziellen entityids ersetzt:

| Liste | Wert | bisher | neu |
| --- | --- | --- | --- |
| Stadium | subadult | 900101 | 193000 |
| Stadium | Pullus / nicht-flügge | 900102 | 193001 |
| Stadium | 1. KJ / diesjährig | 900103 | 193002 |
| Stadium | 2. KJ / vorjährig | 900104 | 193003 |
| Stadium | 3. KJ | 900105 | 193004 |
| Stadium | 4. KJ | 900106 | 193005 |
| Stadium | 5. KJ | 900107 | 193006 |
| Stadium | immatur | 900108 | 192999 |
| Geschlecht | weibchenfarbig | 900001 | 192924 |

Damit verschwinden alle Behelfs-IDs — die Übergangslösung aus der
Stadium/Geschlecht-Trennung ist abgelöst. Bereits erfasste Datensätze mit
diesen Werten sind entsprechend umzuschlüsseln; die vollständige Zuordnung
liegt als `id_umschluesselung.csv` bei.

---

# 6. Mitgelieferte Arbeitsergebnisse

| Datei | Zweck |
| --- | --- |
| `build_reflisten_from_ods.py` | Wiederholbarer Konverter: liest die LANUK-Arbeitsmappe und schreibt die Listen in eine Kopie des GeoPackages. Bei einer neuen Fassung der Mappe ohne Codeänderung erneut ausführbar. |
| `Referenzen_LANUK_ENTWURF.gpkg` | Ergebnis des Laufs — zur fachlichen Sichtung, **noch nicht** für den Produktivbetrieb. |
| `migration_bericht.csv` | Je Eintrag: neu / unverändert / entfällt. |
| `id_umschluesselung.csv` | Zuordnung alter zu neuer entityid für die Datenmigration. |

Die bisherigen Tabellen `Institution` und `Unschaerfe` bleiben im
Entwurfs-GeoPackage vorerst erhalten, damit bis zur Klärung der Punkte in
Abschnitt 4 nichts verloren geht.

---

# 7. Vorschlag zum weiteren Vorgehen

1. Punkte 4.1 (Artengruppen-Zuordnung) und 4.3 (Häufigkeitsskalen) mit FB24
   klären — beide blockieren die Kaskade.
2. Klären, ob eine überarbeitete Artenliste noch nachgeliefert wird.
3. Entscheidung über die drei neuen Felder (Erfassungsmethode, Häufigkeit,
   Geogenauigkeit) im Datenmodell; danach Anlage A und Leistungsbeschreibung
   fortschreiben.
4. Altdatenbestand der Stationen auf die entfallenden Zähleinheiten und
   Institutionen prüfen.
5. Erst danach Referenzlisten austauschen, Formulare und Wizard anpassen und
   die Umschlüsselung auf die Bestandsdaten anwenden.

Solange die Mappe den Status **ENTWURF** trägt, sollte der Austausch im
Produktivprojekt unterbleiben.
