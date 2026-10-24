import QtQuick

// A page under the top bar. The outgoing page fades and settles while the incoming one rises
// into place; disabled immediately so a hidden page never takes input. The first binding is
// applied without motion, so startup does not animate every page at once.
Item {
    id: slot
    property bool active: false
    property bool ready: false

    anchors.fill: parent
    enabled: active
    z: active ? 1 : 0
    opacity: active ? 1 : 0
    visible: opacity > 0.01

    Component.onCompleted: Qt.callLater(function () { slot.ready = true })

    Behavior on opacity {
        enabled: slot.ready
        NumberAnimation { duration: Theme.motionBase; easing.type: Easing.OutCubic }
    }
    transform: Translate {
        y: slot.active ? 0 : 10
        Behavior on y {
            enabled: slot.ready
            NumberAnimation { duration: Theme.motionSlow; easing.type: Easing.OutCubic }
        }
    }
}
