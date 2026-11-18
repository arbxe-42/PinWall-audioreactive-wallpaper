# Phase 0 findings: what Lively gives a web wallpaper (2026-11-17)

Lively Wallpaper 20262.5.6.0 (Microsoft Store), WebView2 player (Edge/Chromium 157).

## Loading wallpapers without the UI

- `Build\Lively.exe` (inside the WindowsApps package folder) accepts commands and forwards
  them to the running Lively: `setwp --file <path> --monitor <n>`, `closewp`, `screenshot
  --file <out> --monitor <n>`.
- `setwp` with a bare `index.html` fails ("Unsupported command import file"). It works with a
  folder inside Lively's library. Our folders are linked into the library with a directory
  junction, so Lively plays the files straight from the project (edits show on reload):
  `%LOCALAPPDATA%\Packages\12030rocksdanister.LivelyWallpaper_97hta09mmv6hy\LocalCache\Local\Lively Wallpaper\Library\wallpapers\pinwall-probe`
  -> `live-wallpaper\probe`. Lively itself sees that path as
  `C:\Users\arbxe\AppData\Local\Lively Wallpaper\Library\wallpapers\...`.
- `screenshot` writes a JPEG of the wallpaper only (no windows or icons over it): good for
  checking builds while the desktop is covered.
- Monitor numbering: `--monitor 2` = the 2560x1440 monitor (`\\.\DISPLAY6`, primary);
  `--monitor 1` = the laptop panel (3840x2400 physical, 1536x960 logical at 250%).

## Audio feed (`--audio`)

- `livelyAudioListener(array)`: 128 values, called every ~62 ms (about 16 per second), even
  in silence (all zeros). That is far too coarse for beat timing (a 62 ms grid is wider than
  the whole ±20 ms timing target). Lively's feed is good only for the smooth fallback
  (bass/high levels) when the listener is not running. Scaling with real music: not measured
  (nothing played overnight, on purpose).

## Now playing (`--system-nowplaying`)

- `livelyCurrentTrack(json)` delivers: `Title, Artist, AlbumTitle, AlbumArtist,
  AlbumTrackCount, TrackNumber, Genres, PlaybackType, Subtitle, Thumbnail` (cover art as
  base64 PNG, ~260 KB). Fires on start and on track change. Spotify works (it reported the
  last-played Miss Jay track).
- So the album-cover colours come from Lively directly; the listener does not need to read
  Windows' media controls.

## Screen and rendering

- On the monitor: `innerWidth x innerHeight` = 2560x1440, `devicePixelRatio` 1.
  `screen.width/height` is wrong (reports 3840x2400); use the window size.
- WebGL2 works on the RTX 4060 (ANGLE D3D11), float render targets available, max texture
  16384. 60 fps.

## Mouse

- Lively settings already have input forwarding on (`InputForward = 1`,
  `MouseInputMovAlways = True`). Moving the cursor while application windows covered the
  desktop produced no events in the wallpaper; forwarding needs the desktop itself under
  the cursor. Re-test with the real wallpaper when the desktop is visible.

## Pause events (`--pause-event true`)

- `livelyWallpaperPlaybackChanged(json)` with `IsPaused`. Lively pauses wallpapers when an
  app is focused full screen or on battery (`BatteryPause = 1`).
