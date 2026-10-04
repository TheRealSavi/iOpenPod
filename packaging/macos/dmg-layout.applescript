on run argv
    set mountPath to item 1 of argv
    set mountFolder to POSIX file mountPath as alias
    tell application "Finder"
        -- Finder can name a custom-mounted volume after its mount directory.
        tell folder mountFolder
            open
            tell container window
                set current view to icon view
                set toolbar visible to false
                set statusbar visible to false
                -- 800 x 500 artwork points, with room for the native title bar.
                set bounds to {120, 120, 920, 642}
            end tell
            set viewOptions to icon view options of container window
            tell viewOptions
                set icon size to 160
                set text size to 14
                set arrangement to not arranged
                set label position to bottom
            end tell
            set background picture of viewOptions to file ".background:background.png"
            set position of every item to {1000, 100}
            -- Match the SVG's logical coordinates, not its 2x raster pixels.
            set position of item "iOpenPod.app" to {200, 232}
            set extension hidden of item "iOpenPod.app" to true
            set position of item "Applications" to {600, 232}
            close
            open
            delay 1
            close
        end tell
    end tell
    repeat 20 times
        if (do shell script "test -s " & quoted form of (mountPath & "/.DS_Store") & "; echo $?") is "0" then return
        delay 1
    end repeat
    error "Finder did not save the DMG layout"
end run
