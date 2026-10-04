on run argv
    set volumeName to item 1 of argv
    set mountPath to item 2 of argv
    tell application "Finder"
        tell disk volumeName
            open
            tell container window
                set current view to icon view
                set toolbar visible to false
                set statusbar visible to false
                set bounds to {120, 120, 840, 560}
                set viewOptions to icon view options
                tell viewOptions
                    set icon size to 128
                    set text size to 14
                    set arrangement to not arranged
                end tell
                set background picture of viewOptions to file ".background:background.png"
            end tell
            set position of every item to {900, 100}
            set position of item "iOpenPod.app" to {190, 210}
            set extension hidden of item "iOpenPod.app" to true
            set position of item "Applications" to {530, 210}
            close
            open
            delay 1
        end tell
    end tell
    repeat 20 times
        if (do shell script "test -s " & quoted form of (mountPath & "/.DS_Store") & "; echo $?") is "0" then return
        delay 1
    end repeat
    error "Finder did not save the DMG layout"
end run
