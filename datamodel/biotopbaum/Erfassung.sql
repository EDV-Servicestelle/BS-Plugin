-- Erzeugt aus Erfassung.gpkg
-- Nicht von Hand aendern: tools/export_from_gpkg.py

CREATE TABLE "Baueme" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "geom" POINT, "bhd" INTEGER, "hoehe" MEDIUMINT, "posi_Lage" TEXT, "akkumulat" TEXT, "K_Datum" DATE, "sonderstruk" TEXT, "bem_sonderstruk" TEXT, "foerderung" TEXT, "markierung" TEXT, "besitzart" TEXT, "baumart" TEXT, "baumtyp" TEXT, "Aenderungsdatum" DATETIME, "Objektid" TEXT, "markierung_bem
" TEXT, "standort
" TEXT, "Besonnung" TEXT, "vitalitaet" TEXT, "baumhoehlen" TEXT, "anz_baumhoehlen" MEDIUMINT, "zersetzung" TEXT, "allg_bem
" TEXT, "x" TEXT, "y" TEXT, "adrolle" TEXT, "bearbeiter" TEXT, "terminart" TEXT, "Verkehrssicherungspflicht" TEXT, "Baumpilze" TEXT, "Kartierer" TEXT, "Institution" TEXT);

CREATE TABLE "Hoehlen" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "Baumhoehlen_Typ" MEDIUMINT, "Anzahl" MEDIUMINT, "Baum_ObjektID" TEXT, "Eintragungsdatum" DATE);
