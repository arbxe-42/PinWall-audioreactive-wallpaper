# Pin Wall: this install (the author's machine)

Notes on how Pin Wall is set up on the author's own PC (their Pinterest board, Bluetooth K3 speakers,
icon shelf, demo video). The public overview is the [README](../README.md); developer notes are in
[HANDOFF.md](../HANDOFF.md).

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
- **What fires (2026-11-18):** the pictures hit on every **kick the listener hears**, detected by **KickNet**, a tiny neural detector (`listener/kicknet.py`) trained on your own 31 tracks: the full mix goes in, and the answers come from each track's separated drum stem (kicks only), so vocals, bass, arps and pads don't count. How hard a hit lands follows KickNet's confidence (your idea): sure kicks punch, borderline ones only nudge. Each hit is stamped with the moment you will hear it: on the K3s (250 ms Bluetooth delay) it lands on time; on laptop speakers it fires ~50 ms after the sound.
- **How it was checked:** each song scored by a model that never saw it, against the kick labels you checked by ear: hits with no kick under them went from 65 a minute (the old rules) to about 12; kick accuracy F 0.54 → 0.83. Your Dark Arm taps (human): 96% of hits land on a tap, 96% of taps get a hit. All your songs are trance/EDM-ish, so other genres are untested; to go back to the old rules set `nn=0` in `listener/detect.py`.
- **Drops:** the wall shatters (the next wall is loaded ahead, so the break is instant and smooth) only on a jump of at least 8 dB in loudness and bass after a quieter stretch, then waits 30 s. It catches about a quarter of labelled drops plus other big "drums in" moments, and misses rather than faking.
- **Kick/snare labels are not used to trigger anything:** in a full mix they were right only 70% (kicks) / 28% (snares) of the time, which is exactly the phantom-hit problem you worried about.
- **New track (from Spotify's now-playing via Lively):** the wall rebuilds from pins whose colours match the album cover; accents take the cover's colours pushed to neon; the title is stamped in big, then shrinks to a small strip.

## The full algorithm

### Live: from your speakers to the wall

1. **Capture** (`listener/server.py`). The listener records what Windows plays (WASAPI loopback, 48 kHz,
   mixed to mono) in 10 ms blocks. It knows the output device and its delay (K3 Bluetooth 250 ms, laptop
   speakers 0) and re-checks the device every 2 s.
2. **A spectrum every 10 ms** (`listener/detect.py`). The last 2048 samples (~43 ms) get a Hann window and an
   FFT: 1025 frequency magnitudes, a snapshot of the sound right now.
3. **KickNet features** (`listener/kicknet.py`). The spectrum is folded into 40 log-spaced bands from 40 Hz to
   14 kHz (fine detail in the bass, coarse up high). Each band gives three numbers:
   - **level**: its loudness in dB relative to a running peak of the whole mix (the peak falls 3 dB per
     second, so the volume knob doesn't matter);
   - **change over 10 ms** and **change over 20 ms**: how fast the band is jumping (what an attack looks like).

   The last 12 frames (120 ms) are kept: 40 × 3 × 12 = 1440 numbers.
4. **The network.** A small MLP (normalised input → 128 → 64 → output, ~0.15 ms per frame) answers: *"was
   there a kick attack 3 frames (30 ms) ago?"* as a confidence from 0 to 1. Looking back 30 ms lets it see the
   start of the kick's tail before deciding.
5. **Trigger.** Fire when the confidence is ≥ 0.5 and still rising; at most one hit per 90 ms. The hit is
   stamped at the attack, 30 ms before the decision; the decision comes ~30 ms after the kick. (A stricter
   "first hit after a pause needs 0.8" rule was tried and dropped: it held back the first kicks of drops.)
6. **Send** (websocket `ws://127.0.0.1:4360`). Each hit becomes `{hit, at, z}`: `at` is the moment you will
   *hear* it (when the sound left Windows + ~15 ms output buffer + the speaker delay), `z` the confidence.
7. **Wallpaper** (`wallpaper/src/audio.js` → `main.js`).
   - Timing: the hit is scheduled for `at − 45 ms` so the visual peak lands on the sound. On the K3s there is
     250 ms of slack (exactly on time); on laptop speakers that moment has passed, so it fires at once (~50 ms
     late).
   - Strength: the listener sends each hit 20 ms after it triggers, with the *peak* confidence over those
     20 ms (real kicks keep climbing to ~0.82, stray hits stall around 0.66). The wall maps it straight:
     0.6 or less is a light nudge, 0.75 or more hits full. Strength drives the punch-zoom, shake, picture
     bounce, RGB split and flash; only confident hits step the sunburst rays or trigger a glitch.

**Alongside the hits:**
- **Beat clock**: tempo from autocorrelation of the last 6 s of onsets, phase by comb search, then a
  phase-locked loop that predicts every next beat. It drives the bar count, picture swaps, the clock HUD and
  the barcode, not the hits.
- **Drops**: a jump of at least 8 dB in loudness and bass after a quieter stretch → the wall shatters, then
  waits 30 s before another can. The next wall is built and its pictures loaded ahead of time, so the break is
  instant and stays at 60 fps.

### How KickNet was made (offline, `bench/`)

- **Data.** Your 31 full tracks went through demucs (`bench/make_full_stems.py`), which separates the drum
  stem. The model's input is the **full mix**; its answers come only from the **drum stem**. Vocals, bass and
  arps are in what it hears but never in the answers, so it learns to ignore them.
- **Kick labels from the drum stem** (`bench/stem_labels.py`, tuned with your ears in Kick Check). A kick is:
  1. a loud, fast low-end attack: 30-150 Hz rises 15 dB within 40 ms, to within 14 dB of the track's real kicks;
  2. with the track's own click: the 2-10 kHz part at the attack is like the track's typical kick, in level and
     in how sharply it rises (kills bass/lead bleed and clickless thumps; relative per track, so soft-kick
     tracks keep their kicks);
  3. not a pure sub note: if 110-250 Hz sits more than 12 dB under the 30-70 Hz sub, it's a bass or arp note
     (the 825 hp case);
  4. one kick, not two: attacks within 70 ms are one layered kick (the neurotransmission case); 70-100 ms apart
     only count twice if the low end dips 12 dB between them;
  5. big hits near the stem's loudest also count, when the low end carries them.
- **Training** (`bench/kn_train.py --kick-only`). Each kick becomes a 1 at its attack frame + 3 (soft 0.3 / 0.6
  on the neighbouring frames), everything else 0. Loss: cross-entropy with kicks weighted ×4 (they're rare).
  Augmentation: random gain and EQ tilt of ±6 dB, so it can't lean on loudness or tone colour. AdamW, 6 passes
  over ~700k frames.
- **Testing.** The songs are split into 5 groups and each song is scored by a model that never saw it
  (Adrenaline is never trained on). The live model is then trained on all 30 songs. Results against the kick
  labels you checked: kick F 0.83 (old rules 0.54), hits with no kick under them about 12 per minute (old rules 65);
  your Dark Arm taps 96% / 96%.

### Why it beats the old rules

The old trigger asked one question: *"did the bass band jump?"* Sidechain swells, bass notes, vocals with low
end and sub arps all answer yes. KickNet sees all 40 bands over 120 ms at once (the broadband click, the shape
of the low-end rise, what comes right after) and learned the kick's whole fingerprint from your own songs. The
biggest single win wasn't the network, though: it was getting the labels right with your ears (the first
version learned from labels that put kicks under hi-hats).

To go back to the old rules: set `nn=0` in `listener/detect.py` and restart the listener.

### KickNet on its own

KickNet is also a standalone download: the `kicknet/` folder (or `KickNet.zip` from the repo's Releases page).
numpy only. `python -m kicknet song.wav` lists every kick, `python -m kicknet --live` shows kicks in whatever the
PC plays, and `from kicknet import KickDetector` streams it in your own code. See `kicknet/README.md`. After
retraining, `tools/build_kicknet.py` syncs it from the listener and rebuilds the zip.

## Demo video

- **Record a clean clip:** `listener/.venv/Scripts/python.exe tools/record_demo.py --seconds 25`, then press
  play on a song (from a local file you own, never a stream). It switches the wall to Reactive, shows the
  desktop, hides the icons, waits for the music, records the main monitor (no mouse pointer) and the PC's
  sound, then puts everything back. Files land in `demo/raw/` (ignored by git: they hold the sound).
- **Cut it:** `listener/.venv/Scripts/python.exe tools/make_demo.py --raw demo/raw --out demo/clip.mp4 --loop`.
  It crops off the taskbar, keeps the icon shelf with its Reactive/Ambient toggle (`--blur-icons` blurs the desktop icons), runs KickNet and the old loudness trigger on the sound, lines
  the sound up with the picture by matching the wall's hits to the kicks (the wall shows hits when you
  HEAR them, so a Bluetooth delay shows up as an offset), draws the strip and writes a 1920x1080 mp4
  plus a 6 s WebP loop (`--loop`). A screen recording of your own works too: put it in a folder as `video.mp4` with its
  sound as `audio.wav` and a `meta.json` of `{"seconds": <length - 1>}`.
- The 2026-11-18 demo is two of the user's own screen recordings, cut this way and joined with a 0.6 s
  crossfade; the full clip is on the `demo-v1` release, the loop in `docs/demo.webp`.

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
