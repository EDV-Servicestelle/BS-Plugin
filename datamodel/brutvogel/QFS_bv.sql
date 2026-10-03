-- Erzeugt aus QFS_bv.gpkg
-- Nicht von Hand aendern: tools/export_from_gpkg.py

CREATE TABLE "Abundanzliste" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "Vogel_Art" TEXT(100), "Brutreviere" MEDIUMINT, "davon_Randbrueter" MEDIUMINT, "Abundanz_pro_100ha" REAL, "Nahrungsgast_zur_Brutzeit" TEXT, "Durchzuegler" TEXT);

CREATE TABLE "Begehungsliste" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "Kartiergang" TEXT, "Erfasser" TEXT, "Witterung" TEXT, "uuid" TEXT, "anzeigename" TEXT, "Datum" DATE, "Zeitstempel_Start" DATETIME, "Zeitstempel_Ende" DATETIME, "zeit_plausi" BOOLEAN, "Kartierer" TEXT, "Institution" TEXT);

CREATE TABLE "Ortsbewegungen" ("fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "geom" LINESTRING, "vb_uuid" TEXT, "Bemerkung" TEXT, "ob_uuid" TEXT, "Zeitstempel_Digitalisierung" DATETIME, "Vogel_Art_1" TEXT, "Zeitstempel_Beobachtung" DATETIME, "Bewegung_Art" TEXT);

CREATE TABLE "Papierreviere" ("fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "geom" POLYGON, "Vogel_Art" TEXT, "Lage" TEXT, "Anzahl" MEDIUMINT, "flaeche" REAL, "overlap" REAL, "overlap_rel" REAL, "Bemerkung" TEXT, "bzc_count_a" MEDIUMINT, "bzc_count_b" MEDIUMINT, "bzc_count_c" MEDIUMINT, "bzc_plausi" BOOLEAN, "Hinweis" TEXT, "Bemerkung_plausi" TEXT, "KENNUNG" TEXT, "ATOM_ID" TEXT, "geometry_valid" BOOLEAN, "geometry_duplicate" BOOLEAN, "Vogelbeobachtungen" TEXT, "uuid" TEXT);

CREATE TABLE "Referenzliste_Arten" ("fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "name" TEXT, "kuerzel" TEXT, "Atom_ID" MEDIUMINT, "info" TEXT, "info_mobile" TEXT, "wiss_name" TEXT, "uuid" TEXT);

CREATE TABLE "Referenzliste_Brutzeitcodes" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "BrutzeitcodeID = ID in ornitho.de" MEDIUMINT, "Brutzeitcode" TEXT, "Brutzeitcode-Status" TEXT, "Bedeutung" TEXT, "anzeigename" TEXT);

CREATE TABLE "Referenzliste_Kartiergaenge" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "kartiergang_nr" TEXT, "kartiergang_name" TEXT, "kartiergang_farbe" TEXT, "Witterung" TEXT, "Erfasser" TEXT);

CREATE TABLE "Referenzliste_Mitarbeiter" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "uuid" TEXT, "Vorname" TEXT, "Nachname" TEXT, "Email" TEXT, "Telefon" TEXT);

CREATE TABLE "Simultanmarker" ("fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "geom" POINT, "sim_uuid" TEXT, "vb_uuid" TEXT, "vb2_uuid" TEXT, "Vogel_Art_1" TEXT, "vb2_Vogel_Art" TEXT, "Bemerkung" TEXT, "Zeitstempel_Digitalisierung" DATETIME, "Zeitstempel_Beobachtung" DATETIME, "Simultan_Art" TEXT);

CREATE TABLE "Vogelbeobachtungen" ("fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "geom" POINT, "Zeitstempel_Beobachtung" DATETIME, "Anzahl" MEDIUMINT, "Zeitstempel_Digitalisierung" DATETIME, "nachtraeglich_erfasst" BOOLEAN, "vb_uuid" TEXT, "Zeitstempel_letzteAenderung" DATETIME, "BearbeiterIn_letzteAenderung" TEXT, "kartiergang" TEXT, "anzeigename" TEXT, "geometry_type" TEXT, "Genauigkeit" TEXT, "Brutzeitcode" TEXT, "Stadium_Geschlecht" TEXT, "Verhalten" TEXT, "Bemerkung" TEXT, "Vogel_Art" TEXT, "Brutstatus" TEXT);

CREATE TABLE "layer_styles" ( "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "f_table_catalog" TEXT(256), "f_table_schema" TEXT(256), "f_table_name" TEXT(256), "f_geometry_column" TEXT(256), "styleName" TEXT(30), "styleQML" TEXT, "styleSLD" TEXT, "useAsDefault" BOOLEAN, "description" TEXT, "owner" TEXT(30), "ui" TEXT(30), "update_time" DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
