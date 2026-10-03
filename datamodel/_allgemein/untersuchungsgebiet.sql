-- Erzeugt aus untersuchungsgebiet.gpkg
-- Nicht von Hand aendern: tools/export_from_gpkg.py

CREATE TABLE Untersuchungsgebiet (
    fid INTEGER PRIMARY KEY AUTOINCREMENT,
    geom MULTIPOLYGON,
    KENNUNG TEXT);
