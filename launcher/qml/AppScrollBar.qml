import QtQuick
import QtQuick.Controls

// Slim scrollbar in the launcher palette. The handle stays quiet until the pointer is near it
// or the bar is dragged, and disappears when the content fits.
ScrollBar {
    id: bar
    policy: ScrollBar.AsNeeded
    minimumSize: 0.08
    contentItem: Rectangle {
        visible: bar.size < 1
        implicitWidth: 4
        implicitHeight: 4
        radius: 2
        color: bar.pressed ? Theme.textDim : bar.hovered ? Theme.textFaint : Theme.lineStrong
        opacity: bar.active || bar.hovered ? 1 : 0.45
        Behavior on opacity { NumberAnimation { duration: Theme.motionFast } }
        Behavior on color { ColorAnimation { duration: Theme.motionFast } }
    }
    background: Rectangle { color: "transparent" }
}
