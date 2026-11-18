# Pin Wall

> For agents picking this up: read `HANDOFF.md` first.

Your desktop wallpaper as a living collage of your 255 Pinterest pins ("Sick images" board), cut,
taped, torn and printed out of register like the sketch you loved. It moves with whatever music the PC
plays (Spotify, YouTube, anything) and with your mouse. Built overnight 2026-11-16/17 from the approved
plan (`C:\Users\arbxe\.claude\plans\ok-this-is-great-enchanted-squirrel.md`).

**Private:** the pins are other people's art from your board. Everything here stays on this machine;
never publish the wallpaper or its screenshots.

## What's running

| Piece | Where | What it does |
|---|---|---|
| Wallpaper | `wallpaper/` (linked into Lively's library as **Pin Wall**) | WebGL2 collage. Lively plays it on both screens, each at its own size |
| Listener | `listener/server.py`, starts with Windows (Startup folder shortcut "Pin Wall listener") | Hears what the PC plays, finds the beat, tells the wallpaper. Tray icon (a starburst), log in `listener/listener.log`. Audio is analysed in memory only, never saved |

## Controls

- **Ctrl+Alt+W**: switch **Reactive** (music-driven) / **Ambient** (calm background: slow drift, one picture melts into another about once a minute, a new wall every few minutes, no hits). Remembered across restarts.
- **Tray icon**: left-click toggles the mode; right-click shows the mode and the output device, and has Quit.
- **Mouse** (on the bare desktop): pictures sit at different depths and slide with the cursor; the picture under the cursor lifts with a holo-foil sheen; a click slams a starburst with a shockwave; dragging across a picture rips it to reveal another. The icon shelf at the top never reacts to clicks.
- **Lively's panel** (Pin Wall → customise): mode, reaction intensity, clock on/off, battery mode, icon-shelf outlines (calibration).

## How the music drives it (and why it won't fire phantom hits)

Measured on 31 of your tracks (`bench/report.html`, full mixes, scored against each track's isolated drum stem):

- **The beat clock** locks onto the tempo and predicts every next beat. 90% of locked beats land on a real drum hit, median timing +5 ms. Tempo exact on 81% of tracks (94% counting double/half time). Hits only ever fire on predicted beats, so a hit can't land off the beat. When the clock isn't sure (breakcore breaks, ambient, talking) it goes loose and hard hits stop.
- **What fires (2026-11-18):** the pictures hit on every **kick the listener hears**, detected by **KickNet**, a tiny neural detector (`listener/kicknet.py`) trained on your own 31 tracks: the full mix goes in, and the answers come from each track's separated drum stem (kicks only), so vocals, bass, arps and pads don't count. How hard a hit lands follows KickNet's confidence (your idea): sure kicks punch, borderline ones only nudge. Each hit is stamped with the moment you will hear it: on the K3s (250 ms Bluetooth delay) it lands on time; on laptop speakers it fires ~30 ms after the sound.
- **How it was checked:** each song scored by a model that never saw it, against the kick labels you checked by ear: hits with no kick under them went from 65 a minute (the old rules) to 9.5; kick accuracy F 0.54 → 0.83. Your Dark Arm taps (human): 96% of hits land on a tap, 96% of taps get a hit. All your songs are trance/EDM-ish, so other genres are untested; to go back to the old rules set `nn=0` in `listener/detect.py`.
- **Drops:** the wall shatters (the next wall is loaded ahead, so the break is instant and smooth) only on a jump of at least 8 dB in loudness and bass after a quieter stretch, then waits 30 s. It catches about a quarter of labelled drops plus other big "drums in" moments, and misses rather than faking.
- **Kick/snare labels are not used to trigger anything:** in a full mix they were right only 70% (kicks) / 28% (snares) of the time, which is exactly the phantom-hit problem you worried about.
- **New track (from Spotify's now-playing via Lively):** the wall rebuilds from pins whose colours match the album cover; accents take the cover's colours pushed to neon; the title is stamped in big, then shrinks to a small strip.

## Kick Check (checking the labels by ear)

`tools/annotate/server.py` (or "kick-check" in the app's preview list) opens http://127.0.0.1:4353: play any of your
tracks as the full mix or the drum stem, see the kick / snare / hat labels and the detector hits, mark labels wrong,
tap missed kicks (it learns your tap delay and snaps taps onto the real attack). Saves to `bench/annotations/`.

## Speaker delay (your K3s)

Bluetooth plays sound late. Your hand-fixed Adrenaline kicks sit +242 ms after the drum stem (48 of 56
line up), so the K3s get **250 ms** (`listener/devices.json`); laptop speakers and wired outputs get none.
The listener checks the output device every 2 s and switches the delay when you switch speakers.

**Fine-tune it:** open `calibrate.html` (double-click) with the listener running and the speakers you want
selected, press start and tap along to the clicks. It saves the measured delay for that exact device.

## Icon shelf

`wallpaper/shelf.json` holds, per screen size, a calm 112 px band at the top with a plate behind each of
your four icon groups (measured from your monitor screenshot), plus 48 px kept clear for the taskbar.
The collage never goes under the band, and glitches and the shatter stop at its edge.

- **Laptop alone:** when you unplug the monitor, Windows moves the icons onto the laptop screen, whose
  shelf isn't measured yet (it has no band). Turn on "Show icon shelf outlines" in Lively's panel, take a
  screenshot, and I'll add the laptop's plates (or edit `shelf.json`: key `"1536x960"`).

## Switching back

Lively → Library → pick any other wallpaper (your old ones are still there: Matrix Rain, etc.).
To stop the listener: tray icon → Quit; to stop it starting with Windows, delete "Pin Wall listener" from
the Startup folder (`Win+R` → `shell:startup`).

## Files

```
wallpaper/            the Lively wallpaper (index.html, src/*.js, shelf.json, pins/ = your 255 pins + manifest)
listener/             server.py (live), detect.py (beat/drop detector), devices.json, .venv (Python 3.12)
bench/                bench.py + report.py -> report.html (detection scores on your tracks); scratch/ = dev plots
tools/                prep_pins.py (rebuild pins/ after re-grabbing the board), shot.py, serve.py, desktop_check.py
probe/                Phase 0 findings about Lively (FINDINGS.md)
sketch/               the original look sketch
test/                 stills and real-desktop captures from the overnight checks
calibrate.html        tap-along speaker delay
```

## Overnight verification (what was checked, and how)

- Detection: offline bench on 31 tracks (numbers above), plus a silent real-time replay through the listener (locked 130 BPM on Adrenaline within 4.5 s, beats sent ~600 ms ahead including the K3 delay).
- Look: stills of every template at 2560x1440 with your real icon row pasted over the shelf, the laptop shape, the shatter, a beat peak, hover + click (`test/v1_*.png`).
- Real desktop: Pin Wall loaded in Lively on both screens; with the desktop shown, the wallpaper reported 60 fps on the laptop, received real mouse moves (hover lift confirmed), and Ctrl+Alt+W toggled the mode (`test/desk_*.png`, `listener/listener.log`).
- Not checked: anything with sound (nothing was played overnight, on purpose). First thing to try: play a track on the K3s and watch.

## Known limits / next ideas

- Layout templates: 3 compositions × mirrored = 6. More can be added in `wallpaper/src/layout.js`.
- The laptop panel renders at up to 2x pixel density (3072x1920) for sharpness; battery mode drops to 70% resolution and 30 fps.
- Double-click "cover moment" and a login boot animation were planned for v2 and aren't built.
