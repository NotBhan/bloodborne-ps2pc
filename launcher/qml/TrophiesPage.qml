import QtQuick
import QtQuick.Controls

// Local trophy progress, grouped into unlocked and locked sections. Read-only: the game's
// trophy cache and unlock history are the only sources, so unavailable data stays unavailable.
Item {
    id: page
    signal openSettings(string category, string section)
    property var summary: launcher.trophySummary
    property var entries: launcher.trophyEntries
    property string filterMode: "all"
    property string sortMode: "default"
    property var filtered: {
        let list = entries.slice()
        if (filterMode === "earned") list = list.filter(function (entry) { return entry.earned })
        else if (filterMode === "locked") list = list.filter(function (entry) { return !entry.earned })
        const order = { "P": 0, "G": 1, "S": 2, "B": 3, "?": 4 }
        if (sortMode === "grade")
            list.sort(function (a, b) { return (order[a.grade] - order[b.grade]) || (a.id - b.id) })
        else if (sortMode === "recent")
            list.sort(function (a, b) {
                return (a.earned === b.earned ? 0 : a.earned ? -1 : 1) ||
                       (b.unlocked > a.unlocked ? 1 : b.unlocked < a.unlocked ? -1 : 0) ||
                       (a.id - b.id)
            })
        return list
    }
    property var earned: filtered.filter(function (entry) { return entry.earned })
    property var locked: filtered.filter(function (entry) { return !entry.earned })

    Rectangle { anchors.fill: parent; color: Theme.base }
    Image {
        anchors.fill: parent
        source: Qt.resolvedUrl("../art/strip.png")
        fillMode: Image.PreserveAspectCrop
        smooth: true; mipmap: true
        opacity: 0.9
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#990b0c10" }
            GradientStop { position: 0.55; color: "#cc0b0c10" }
            GradientStop { position: 1.0; color: "#f20b0c10" }
        }
    }

    Flickable {
        anchors.fill: parent
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: width
        contentHeight: content.implicitHeight + 56
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
            id: content
            x: 28; y: 22
            width: Math.min(Theme.pageMaxWidth, page.width - 56)
            spacing: 0

            // Identity and summary.
            Item {
                width: parent.width; height: 48
                Row {
                    id: identityRow
                    anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                    spacing: 13
                    Image {
                        width: 42; height: 42; anchors.verticalCenter: parent.verticalCenter
                        source: Qt.resolvedUrl("../assets/hunter-icon.png")
                        fillMode: Image.PreserveAspectCrop; smooth: true; mipmap: true
                    }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter; spacing: 2
                        Text {
                            text: "Bloodborne"; color: Theme.text; font.family: Theme.sans
                            font.pixelSize: 22; font.weight: Font.DemiBold
                        }
                        Text {
                            text: "Trophies"; color: Theme.textDim
                            font.family: Theme.sans; font.pixelSize: 11; font.letterSpacing: 0.8
                        }
                    }
                }
                Row {
                    id: summaryRow
                    width: childrenRect.width
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 22
                    Column {
                        spacing: 1
                        Text { text: "PROGRESS"; color: Theme.textFaint; font.family: Theme.sans; font.pixelSize: 10; font.letterSpacing: 1.2 }
                        Text {
                            text: page.summary.available ? page.summary.completion + "%" : "—"
                            color: Theme.text; font.family: Theme.sans; font.pixelSize: 22
                        }
                    }
                    Column {
                        spacing: 1
                        Text { text: "EARNED"; color: Theme.textFaint; font.family: Theme.sans; font.pixelSize: 10; font.letterSpacing: 1.2 }
                        Text {
                            text: page.summary.available
                                  ? page.summary.earned + "/" + page.summary.total : "—"
                            color: Theme.text; font.family: Theme.sans; font.pixelSize: 22
                        }
                    }
                    Row {
                        width: childrenRect.width
                        spacing: 12
                        Repeater {
                            model: page.summary.grades
                            delegate: Row {
                                spacing: 5
                                Rectangle {
                                    width: 19; height: 19; radius: 9.5
                                    color: "transparent"; border.width: 1
                                    border.color: modelData.letter === "P" ? "#d8d2c6" :
                                                  modelData.letter === "G" ? "#c6a45c" :
                                                  modelData.letter === "S" ? "#a2a9ae" : "#a87a56"
                                    Text {
                                        anchors.centerIn: parent; text: modelData.letter
                                        color: Theme.textDim; font.family: Theme.sans
                                        font.pixelSize: 9; font.weight: Font.DemiBold
                                    }
                                }
                                Text {
                                    text: modelData.count; color: Theme.textDim
                                    font.family: Theme.sans; font.pixelSize: 12
                                }
                            }
                        }
                    }
                }
            }
            Item { width: 1; height: 12 }
            Rectangle {
                width: parent.width; height: 3; color: Theme.line
                Rectangle {
                    width: parent.width * (page.summary.available ? page.summary.completion / 100 : 0)
                    height: parent.height; color: Theme.text
                }
            }
            Item { width: 1; height: 8 }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: page.summary.available
                      ? "Local records from this port. Not synced to PlayStation Network."
                      : page.summary.localUnlocks + " local unlocks recorded."
                color: Theme.textFaint; font.family: Theme.sans; font.pixelSize: 11
            }
            Text {
                visible: page.summary.stale
                width: parent.width; wrapMode: Text.WordWrap
                text: "Cached trophy data is older than the current trophy pack."
                color: Theme.warn; font.family: Theme.sans; font.pixelSize: 11
            }
            Item { width: 1; height: 20 }

            // Unavailable state.
            Column {
                visible: !page.summary.available
                width: parent.width
                spacing: 8
                Text {
                    text: page.summary.complete ? "Trophy details are not available yet"
                                                : "No trophy data yet"
                    color: Theme.text; font.family: Theme.sans
                    font.pixelSize: 18; font.weight: Font.DemiBold
                }
                Text {
                    width: Math.min(parent.width, 640); wrapMode: Text.WordWrap
                    text: page.summary.reason !== ""
                          ? page.summary.reason
                          : "Import keys.json in Game & saves, launch the game once, then return."
                    color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 12
                    lineHeight: 1.35
                }
                GlassButton {
                    text: "Import trophy keys"; width: 150; height: 30
                    onClicked: launcher.importTrophyKeys()
                }
            }

            // Unlocked and locked lists.
            Column {
                visible: page.summary.available
                width: parent.width
                spacing: 0

                Item {
                    width: parent.width; height: 34
                    Text {
                        anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                        text: "All trophies: " + page.summary.total; color: Theme.textDim
                        font.family: Theme.sans; font.pixelSize: 11
                    }
                    Row {
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        spacing: 8
                        GlassComboBox {
                            width: 108; height: 28
                            model: [{value: "all", text: "All"}, {value: "earned", text: "Earned"},
                                    {value: "locked", text: "Locked"}]
                            textRole: "text"; valueRole: "value"
                            Component.onCompleted: currentIndex = indexOfValue(page.filterMode)
                            onActivated: page.filterMode = currentValue
                        }
                        GlassComboBox {
                            width: 164; height: 28
                            model: [{value: "default", text: "Game default"},
                                    {value: "grade", text: "Grade"},
                                    {value: "recent", text: "Recently earned"}]
                            textRole: "text"; valueRole: "value"
                            Component.onCompleted: currentIndex = indexOfValue(page.sortMode)
                            onActivated: page.sortMode = currentValue
                        }
                    }
                }
                Item { width: 1; height: 2 }
                Rectangle { width: parent.width; height: 1; color: Theme.line }

                Text {
                    visible: page.earned.length > 0
                    text: "UNLOCKED (" + page.earned.length + ")"
                    color: Theme.textFaint; font.family: Theme.sans
                    font.pixelSize: 10; font.letterSpacing: 1.3
                    topPadding: 14
                }
                Item { visible: page.earned.length > 0; width: 1; height: 4 }
                Repeater {
                    model: page.earned
                    delegate: trophyRow
                }
                Item { visible: page.locked.length > 0; width: 1; height: 18 }
                Text {
                    visible: page.locked.length > 0
                    text: "LOCKED (" + page.locked.length + ")"
                    color: Theme.textFaint; font.family: Theme.sans
                    font.pixelSize: 10; font.letterSpacing: 1.3
                }
                Item { visible: page.locked.length > 0; width: 1; height: 4 }
                Repeater {
                    model: page.locked
                    delegate: trophyRow
                }
                Text {
                    visible: page.filtered.length === 0
                    text: "No trophies match this filter."; color: Theme.textDim
                    font.family: Theme.sans; font.pixelSize: 11
                    topPadding: 14
                }
            }
        }
    }

    Component {
        id: trophyRow
        Rectangle {
            id: row
            width: content.width; height: 66
            color: "transparent"
            opacity: modelData.earned ? 1.0 : 0.78
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }

            Row {
                anchors.fill: parent
                spacing: 13
                Rectangle {
                    width: 40; height: 40; anchors.verticalCenter: parent.verticalCenter
                    radius: 3; color: Theme.surface; border.width: 1
                    border.color: modelData.grade === "P" ? "#d8d2c6" :
                                  modelData.grade === "G" ? "#c6a45c" :
                                  modelData.grade === "S" ? "#a2a9ae" : "#a87a56"
                    Image {
                        visible: modelData.icon !== ""
                        anchors.fill: parent; anchors.margins: 1
                        source: modelData.icon; fillMode: Image.PreserveAspectCrop
                        smooth: true; mipmap: true
                    }
                    Text {
                        visible: modelData.icon === ""
                        anchors.centerIn: parent
                        text: modelData.grade
                        color: Theme.textDim; font.family: Theme.sans
                        font.pixelSize: 12; font.weight: Font.DemiBold
                    }
                }
                Column {
                    width: parent.width - 53
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 3
                    Text {
                        width: parent.width
                        text: (modelData.hidden && !modelData.earned) ? "Secret trophy" : modelData.name
                        color: Theme.text; font.family: Theme.sans; font.pixelSize: 13
                        elide: Text.ElideRight
                    }
                    Row {
                        spacing: 7
                        Text {
                            text: modelData.grade
                            color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 10
                        }
                        Text {
                            text: modelData.earned
                                  ? (modelData.unlocked !== "" ? "Unlocked " + modelData.unlocked : "Earned locally")
                                  : "Not earned locally"
                            color: modelData.earned ? Theme.good : Theme.textFaint
                            font.family: Theme.sans; font.pixelSize: 10
                        }
                    }
                    Text {
                        width: parent.width
                        visible: !(modelData.hidden && !modelData.earned) && modelData.description !== ""
                        text: modelData.description
                        color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11
                        wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight
                    }
                }
            }
        }
    }
}
