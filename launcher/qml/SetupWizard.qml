import QtQuick
import QtQuick.Controls

// First-time setup: one checklist page. Every check shows its state and its fix inline, so
// nothing is hidden behind a step the player has to guess their way to.
Item {
    id: setup
    objectName: "setupWizard"
    property int startStep: 0
    property var checks: launcher.readiness
    // The start-up route can point at game files (1) or saves (2): accent that row.
    property int focusSection: startStep === 1 ? 0 : startStep === 2 ? 2 : -1
    signal exitRequested(string page)
    onVisibleChanged: {
        if (visible) {
            launcher.refreshReadiness()
            launcher.debugPage("setup visible focus=" + focusSection)
        }
    }

    function checkAt(index) {
        return index >= 0 && index < checks.length ? checks[index] : null
    }
    function levelAt(index) {
        const check = checkAt(index)
        return check ? check.level : "warning"
    }
    function detailAt(index) {
        const check = checkAt(index)
        return check ? check.detail : ""
    }
    function levelColor(level) {
        return level === "ready" ? Theme.good : level === "error" ? Theme.accent : Theme.warn
    }
    function gameValid() {
        return levelAt(0) !== "error"
    }
    function savesValid() {
        return levelAt(2) !== "error" && launcher.savesWritable
    }
    function readyCount() {
        let count = 0
        if (gameValid()) count++
        if (levelAt(1) === "ready") count++
        if (savesValid()) count++
        return count
    }
    function summary() {
        return gameValid() && savesValid() ? "Ready to play" : readyCount() + " of 3 checks ready"
    }
    function skip() {
        if (!launcher.confirm("Skip setup?",
                "Missing game files or an unwritable saves folder will still block Play. You can finish setup later in Game & saves.\n\nSkip setup anyway?"))
            return
        launcher.skipSetup()
        setup.exitRequested("Home")
    }
    function finish(play) {
        if (!gameValid() || !savesValid()) {
            launcher.skipSetup()
            setup.exitRequested("Home")
            return
        }
        launcher.completeSetup()
        setup.exitRequested("Home")
        if (play) launcher.play()
    }

    Rectangle { anchors.fill: parent; color: Theme.base }

    Column {
        id: header
        x: 0; y: 0; width: parent.width; spacing: 0
        Item { width: 1; height: 10 }
        Item {
            x: 4; width: parent.width - 8; height: 40
            Row {
                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                spacing: 11
                Image {
                    width: 28; height: 28; anchors.verticalCenter: parent.verticalCenter
                    source: Qt.resolvedUrl("../assets/hunter-icon.png")
                    fillMode: Image.PreserveAspectCrop; smooth: true; mipmap: true
                }
                Column {
                    anchors.verticalCenter: parent.verticalCenter; spacing: 1
                    Text {
                        text: "BLOODBORNE"; color: Theme.text; font.family: Theme.serif
                        font.pixelSize: 14; font.letterSpacing: 1.8
                    }
                    Text {
                        text: "FIRST-TIME SETUP"; color: Theme.textFaint; font.family: Theme.sans
                        font.pixelSize: 10; font.letterSpacing: 1.3
                    }
                }
            }
            Row {
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                spacing: 12
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: setup.summary(); color: setup.gameValid() && setup.savesValid()
                                                 ? Theme.good : Theme.textDim
                    font.family: Theme.sans; font.pixelSize: 11
                }
                GlassButton {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Check again"; width: 96; height: 28
                    onClicked: launcher.refreshReadiness()
                }
            }
        }
        Item { width: 1; height: 6 }
        Rectangle { width: parent.width; height: 1; color: Theme.line }
    }

    Rectangle {
        id: footer
        anchors.bottom: parent.bottom
        width: parent.width; height: 48
        color: Theme.base
        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.line }
        Row {
            anchors.left: parent.left; anchors.leftMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            spacing: 10
            GlassButton { text: "Skip setup"; width: 96; height: 30; onClicked: setup.skip() }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                visible: !setup.gameValid() || !setup.savesValid()
                text: "Finish the checks above to play."; color: Theme.textDim
                font.family: Theme.sans; font.pixelSize: 10
            }
        }
        Row {
            anchors.right: parent.right; anchors.rightMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            GlassButton {
                text: "Open launcher"; width: 118; height: 30
                enabled: !launcher.setupRunning
                onClicked: setup.finish(false)
            }
            GlassButton {
                text: "Play"; width: 88; height: 30; highlighted: true
                enabled: setup.gameValid() && setup.savesValid() && !launcher.running && !launcher.setupRunning
                onClicked: setup.finish(true)
            }
        }
    }

    Flickable {
        id: body
        anchors.top: header.bottom
        anchors.bottom: footer.top
        width: parent.width
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: width
        contentHeight: stepColumn.implicitHeight + 24
        ScrollBar.vertical: AppScrollBar {}

        Column {
            id: stepColumn
            x: 4; width: body.width - 8
            spacing: 12

            Item { width: 1; height: 4 }
            Text {
                width: parent.width; text: "Set up your hunt"
                color: Theme.text; font.family: Theme.sans
                font.pixelSize: 24; font.weight: Font.DemiBold
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap; color: Theme.textDim
                font.family: Theme.sans; font.pixelSize: 12; lineHeight: 1.4
                text: "Point the launcher at your own decrypted CUSA03173 game dump (version 1.09), check your saves and optional trophy key, then pick a graphics preset. You can skip setup and change everything later in Settings."
            }

            Text {
                text: "CHECKLIST"; color: Theme.textFaint
                font.family: Theme.sans; font.pixelSize: 10; font.letterSpacing: 1.3
            }

            // Game files
            Rectangle {
                width: stepColumn.width
                height: gameRow.implicitHeight + 28
                color: Theme.panel; radius: 4
                border.width: setup.focusSection === 0 ? 1 : 0
                border.color: Theme.accent
                Column {
                    id: gameRow
                    x: 14; y: 14; width: parent.width - 28; spacing: 8
                    Row {
                        spacing: 8
                        Rectangle {
                            width: 7; height: 7; radius: 3.5; y: 5
                            color: setup.levelColor(setup.levelAt(0))
                        }
                        Text {
                            text: "Game files"; color: Theme.text
                            font.family: Theme.sans; font.pixelSize: 13; font.weight: Font.DemiBold
                        }
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: setup.detailAt(0); color: Theme.textDim
                        font.family: Theme.sans; font.pixelSize: 12
                    }
                    Flow {
                        width: parent.width; spacing: 8
                        GlassButton {
                            text: launcher.setupRunning ? "Installing…" : "Install from ZIP / PKG"
                            width: 190; height: 30; highlighted: true
                            enabled: !launcher.setupRunning && !launcher.running
                            onClicked: launcher.installFromArchive()
                        }
                        GlassButton {
                            text: "Choose a game folder"; height: 30
                            enabled: !launcher.setupRunning
                            onClicked: launcher.browse("game_dir")
                        }
                    }
                }
            }

            // Trophy keys
            Rectangle {
                width: stepColumn.width
                height: trophyRow.implicitHeight + 28
                color: Theme.panel; radius: 4
                Column {
                    id: trophyRow
                    x: 14; y: 14; width: parent.width - 28; spacing: 8
                    Row {
                        spacing: 8
                        Rectangle {
                            width: 7; height: 7; radius: 3.5; y: 5
                            color: setup.levelColor(setup.levelAt(1))
                        }
                        Text {
                            text: "Trophy keys"; color: Theme.text
                            font.family: Theme.sans; font.pixelSize: 13; font.weight: Font.DemiBold
                        }
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: setup.detailAt(1); color: Theme.textDim
                        font.family: Theme.sans; font.pixelSize: 12
                    }
                    GlassButton {
                        text: "Import trophy keys"; height: 30
                        onClicked: launcher.importTrophyKeys()
                    }
                }
            }

            // Saves
            Rectangle {
                width: stepColumn.width
                height: savesRow.implicitHeight + 28
                color: Theme.panel; radius: 4
                border.width: setup.focusSection === 2 ? 1 : 0
                border.color: Theme.accent
                Column {
                    id: savesRow
                    x: 14; y: 14; width: parent.width - 28; spacing: 8
                    Row {
                        spacing: 8
                        Rectangle {
                            width: 7; height: 7; radius: 3.5; y: 5
                            color: setup.levelColor(setup.savesValid() ? setup.levelAt(2) : "error")
                        }
                        Text {
                            text: "Saves"; color: Theme.text
                            font.family: Theme.sans; font.pixelSize: 13; font.weight: Font.DemiBold
                        }
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: setup.savesValid() ? setup.detailAt(2)
                                                 : "Choose a folder the game can write saves to."
                        color: Theme.textDim
                        font.family: Theme.sans; font.pixelSize: 12
                    }
                    GlassButton {
                        text: "Choose a saves folder"; height: 30
                        onClicked: launcher.browse("user_dir")
                    }
                }
            }

            Text {
                text: "GRAPHICS"; color: Theme.textFaint
                font.family: Theme.sans; font.pixelSize: 10; font.letterSpacing: 1.3
            }
            Flow {
                width: parent.width; spacing: 8
                Repeater {
                    model: ["low", "balanced", "high", "ultra"]
                    delegate: GlassButton {
                        width: 96; height: 30
                        text: launcher.presetLabel(modelData) + (launcher.recommendedPreset === modelData ? "  *" : "")
                        highlighted: launcher.graphicsPreset === modelData
                        onClicked: launcher.applyGraphicsPreset(modelData)
                    }
                }
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap; color: Theme.textDim
                font.family: Theme.sans; font.pixelSize: 11; lineHeight: 1.3
                text: launcher.presetDescription(launcher.graphicsPreset) +
                      (launcher.recommendedPreset !== "" ? "  * Suggested for the detected card." : "")
            }
            GlassSwitch {
                text: "Start the game directly next time"
                checked: launcher.launchDirectly
                onToggled: launcher.setValue("launchDirectly", checked)
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap; color: Theme.textDim
                font.family: Theme.sans; font.pixelSize: 11; lineHeight: 1.35
                text: "Hold Shift while starting to open the launcher instead. In the game, Insert or L3+R3 opens the guide. Setup can be reopened from Game & saves."
            }
            Item { width: 1; height: 8 }
        }
    }
}
