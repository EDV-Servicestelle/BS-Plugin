/**
 * panel.qml – Brutvogel Artsuche Panel (v1.86)
 * Wird von main.qml via Loader geladen – genau wie im Vegetation-Demo
 */
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.qfield
import org.qgis
import Theme

Rectangle {
    id: panelFrame
    anchors.fill: parent
    color: "#CC000000"

    signal closed()

    // Daten kommen vom Elternelement (main.qml) via Loader-Properties
    property var  allSpecies:      []
    property var  filteredSpecies: []
    property string activeGroup:   ""
    property var  gruppen:         []

    // Klick auf Hintergrund schließt Panel
    MouseArea {
        anchors.fill: parent
        onClicked: panelFrame.closed()
    }

    // Eigentliches weißes Fenster
    Rectangle {
        anchors.centerIn: parent
        width:  Math.min(480, parent.width  - 32)
        height: Math.min(640, parent.height - 80)
        color:  Theme.mainBackgroundColor
        radius: 10
        border.color: Theme.mainColor
        border.width: 1
        clip: true

        MouseArea { anchors.fill: parent; onClicked: {} }

        ColumnLayout {
            anchors { fill: parent; margins: 12 }
            spacing: 8

            // Titelzeile
            RowLayout {
                Layout.fillWidth: true
                Text { text: "Vogelart wählen"; font.pixelSize: 18; font.weight: Font.Medium; color: Theme.mainTextColor; Layout.fillWidth: true }
                Button {
                    text: "✕"; flat: true; padding: 6
                    onClicked: panelFrame.closed()
                    contentItem: Text { text: parent.text; font.pixelSize: 18; color: Theme.mainTextColor; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                }
            }

            // Suchfeld
            TextField {
                id: searchField
                Layout.fillWidth: true
                placeholderText: "Deutsch / Wissenschaftlich / Kürzel …"
                font.pixelSize: 15
                onTextChanged: filterLocal(text)
                Component.onCompleted: forceActiveFocus()
                background: Rectangle {
                    color: Theme.controlBackgroundColor
                    border.color: Theme.mainColor
                    border.width: searchField.activeFocus ? 2 : 1
                    radius: 6
                }
            }

            // Gruppenfilter-Buttons
            ScrollView {
                Layout.fillWidth: true
                height: 40
                ScrollBar.vertical.policy: ScrollBar.AlwaysOff
                Row {
                    spacing: 4
                    Repeater {
                        model: panelFrame.gruppen
                        Button {
                            text: modelData.label; height: 34; padding: 6; font.pixelSize: 12
                            highlighted: panelFrame.activeGroup === modelData.filter
                            onClicked: {
                                panelFrame.activeGroup = modelData.filter
                                filterLocal(searchField.text)
                            }
                            background: Rectangle {
                                color: parent.highlighted ? Theme.mainColor : Theme.controlBackgroundColor
                                radius: 17; border.color: Theme.mainColor; border.width: 1
                            }
                            contentItem: Text {
                                text: parent.text; color: parent.highlighted ? "white" : Theme.mainTextColor
                                font: parent.font; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                }
            }

            Text { text: panelFrame.filteredSpecies.length + " Arten"; font.pixelSize: 11; color: Theme.secondaryTextColor; Layout.alignment: Qt.AlignRight }

            // Artenliste
            ListView {
                id: list
                Layout.fillWidth: true; Layout.fillHeight: true
                model: panelFrame.filteredSpecies; clip: true
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: ItemDelegate {
                    width: list.width; height: 52
                    onClicked: {
                        setSpecies(modelData.name)
                        panelFrame.closed()
                    }
                    ColumnLayout {
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 10; rightMargin: 10 }
                        spacing: 1
                        Text { text: modelData.name; font.pixelSize: 14; font.weight: Font.Medium; color: Theme.mainTextColor; Layout.fillWidth: true; elide: Text.ElideRight }
                        Text { text: modelData.wiss_name; font.pixelSize: 11; font.italic: true; color: Theme.secondaryTextColor; Layout.fillWidth: true; elide: Text.ElideRight }
                    }
                    Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom }; height: 1; color: Theme.controlBorderColor; opacity: 0.3 }
                }
                Text { anchors.centerIn: parent; visible: list.count === 0; text: panelFrame.allSpecies.length === 0 ? "Lade …" : "Keine Treffer"; color: Theme.secondaryTextColor; font.pixelSize: 13 }
            }
        }
    }

    function filterLocal(term) {
        var t = term.toLowerCase().trim()
        var g = panelFrame.activeGroup
        var rx = g ? new RegExp(g, "i") : null
        panelFrame.filteredSpecies = panelFrame.allSpecies.filter(function(sp) {
            if (rx && !rx.test(sp.name)) return false
            if (!t) return true
            return sp.name.toLowerCase().indexOf(t) >= 0
                || sp.wiss_name.toLowerCase().indexOf(t) >= 0
                || sp.kuerzel.toLowerCase().indexOf(t) >= 0
        })
    }

    function setSpecies(artName) {
        var drawer = iface.findItemByObjectName("overlayFeatureFormDrawer")
        if (drawer && drawer.featureModel) {
            try {
                var feat = drawer.featureModel.feature
                var idx  = feat.fields.indexOf("Vogel_Art")
                if (idx >= 0) { feat.setAttribute(idx, artName); drawer.featureModel.feature = feat }
                iface.mainWindow().displayToast("✓ " + artName)
            } catch(e) { iface.mainWindow().displayToast("Fehler: " + e) }
        } else { iface.mainWindow().displayToast("Kein Formular offen") }
    }
}
