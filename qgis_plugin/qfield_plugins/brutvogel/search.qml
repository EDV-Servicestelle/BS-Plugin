/**
 * search.qml – Brutvogel Artsuche v3 (Hintergrundthread)
 * Korrekt: LayerUtils.createFeatureIteratorFromExpression + it.close()
 */
import QtQuick
import org.qfield

Item {
    signal prepareResult(var details)
    signal fetchResultsEnded()

    function fetchResults(searchString, context, parameters) {
        var layers = qgisProject.mapLayersByName("Referenzliste_Arten")
        if (layers.length === 0) { fetchResultsEnded(); return }

        var layer = layers[0]
        var term  = searchString.toLowerCase().trim()
        var count = 0

        try {
            // LIKE-Filter direkt in der Expression (performanter als JS-Filter über alle Features)
            var expression = term.length > 0
                ? "lower(\"name\") LIKE '%" + term + "%' OR lower(\"wiss_name\") LIKE '%" + term + "%' OR lower(\"kuerzel\") LIKE '%" + term + "%'"
                : "1=1"

            var it = LayerUtils.createFeatureIteratorFromExpression(layer, expression)
            while (it.hasNext() && count < 50) {
                var feat    = it.next()
                var name    = feat.attribute("name")      || ""
                var wiss    = feat.attribute("wiss_name") || ""
                var kuerzel = feat.attribute("kuerzel")   || ""

                var score = 0.5
                if (name.toLowerCase().indexOf(term) === 0)    score = 1.0
                else if (kuerzel.toLowerCase() === term)        score = 0.95
                else if (wiss.toLowerCase().indexOf(term) === 0) score = 0.8

                prepareResult({
                    "displayString": name,
                    "description":   wiss + (kuerzel ? "  [" + kuerzel + "]" : ""),
                    "score":         score,
                    "group":         "Brutvögel NRW",
                    "groupScore":    1,
                    "userData":      { "name": name, "wiss": wiss }
                })
                count++
            }
            it.close()   // CRITICAL
        } catch(e) {}
        fetchResultsEnded()
    }
}
