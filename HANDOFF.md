# Pin Wall: handoff for the next agent

Written 2026-11-17, end of the build session; updated 2026-11-18 (KickNet, stem labels, shatter perf, vivid colours). Read this first, then `README.md` (user-facing guide
for this install) and `share/README.md` (guide for other people). The root `CLAUDE.md` describes the
user and their taste.

## What it is

The user's actual Windows desktop wallpaper: a living collage of their 255 Pinterest pins
("Sick images" board) that floats, reacts to the mouse and **hits on the kicks** of whatever music the
PC plays. It runs on both screens:
- **Monitor:** 2560x1440, primary. Lively `--monitor 2`.
- **Laptop panel:** 1536x960 scaled, 3840x2400 physical. Lively `--monitor 1`.

**Two pieces:**
- **The wallpaper**, `wallpaper/`: a web page with WebGL2. Lively Wallpaper (Microsoft Store
  version 20262.5.6.0) plays it from a directory junction in its library, so edits go live on reload.
- **The listener**, `listener/server.py`: Python 3.12, starts with Windows from a Startup-folder
  shortcut, tray icon is a starburst. It captures loopback audio, runs `detect.py`, and sends events
  to the wallpaper over `ws://127.0.0.1:4360`.

**Status:** live and working on the user's machine. A shareable package is built in
`dist/PinWall.zip` (code only, no images) but **not published**. The user was asked whether they want
a public GitHub repo (from their logged-in `gh` account) or just the zip. No answer yet: **don't
publish without their explicit yes.**

## The user's taste and feedback for this project (all of it was said out loud)

- **The sketch was loved:** `sketch/frames/calm.png`. Composition "A" (clock top left, big
  now-playing bottom right) is the one they prefer; `layout.js` always uses it.
- **No cringe text:** no "SICK IMAGES", issue numbers or decorative kanji blocks (memory
  `no-slogan-text`). Functional text is fine (clock, date, BPM, track, "NOW PLAYING"); manga stamps
  like the yellow ドン starburst are fine as art.
- **They asked for more stuff:**
  - the clock cluster (pink level meter, white barcode, long info bar)
  - a border (crop marks, registration marks, ruler ticks, edge halftone)
  - big outlined type in the background (the artist name, or the weekday)
  - the album cover
  - a back layer of extra pins. Then "too many pins": it's now 6x3 with 18% skipped, about 14 pins.
- **The pins must always move** (float, sway, drift), and in reactive mode bounce on the music.
- **Their biggest worry:** hits firing when there's no kick, and hits off the beat. Their rule:
  **assume the BPM is constant within a song; only fire on real kicks** (snares too: in their music
  snares carry a kick underneath).
- **There's a desktop button** to switch reactive / ambient. Ambient keeps all the movement but
  nothing follows the music.
- **They called out a self-graded check.** I scored detection against onsets *I* found on separated
  drum stems. The only human ground truth is their hand-marked Adrenaline lanes. Report both, and
  say which is which.

## How the music part works now (after many iterations; why it is this way)

1. **Beat clock** (`detect.py`):
   - tempo by autocorrelation, phase by comb search, then a phase-locked loop
   - locks onto the kick's **click** (the full-range attack), not its low-end peak
   - while locked it ignores harmonic tempo jumps (2x, 1/2, 2/3...)
   - lock hysteresis
   - it drives the bar count, picture swaps, the HUD beat squares and the barcode scan
2. **Hits = KickNet** (since 2026-11-18; `listener/kicknet.py` + `listener/kicknet.npz`, wired in
   `detect.py` `_nn_frame`, `nn=1`):
   - a tiny causal MLP (numpy only, 0.15 ms per frame): 40 log bands x (level vs a running peak,
     1- and 2-frame change) x the last 12 frames -> P(kick attack 3 frames ago)
   - **v7 (live since 2026-11-18 ~02:09) is KICK-ONLY**: the user found snare labels unreliable ("a lot of
     kicks are snares too ... train kicknet to just get the kicks"); the snare head is untrained and off
     (`nn_snare=2.0`). Trained with `bench/kn_train.py --kick-only`.
   - fires when the kick activation crosses 0.5 while rising (`nn_kick`), at most one hit per 90 ms;
     stamped at the attack (frame - 3); event type `kick_fast`. The quiet-stretch guard (`nn_idle_thr`:
     after 1.5 s without a hit the next needs 0.8) is OFF since the user said hits sometimes "don't even
     start on the drop": with it, the first hit after a pause came > 4 s late after 13 of 75 pauses (6 of
     75 without it); it bought only 3 points of precision (0.88 -> 0.85)
   - **Peak filter (04:35, turned OFF 04:40: the user found it "missing too much now"; `nn_bar=0.0`):** at
     0.65 a hit whose 20 ms peak stays under the bar is dropped (the user: "picking
     up a lot of extra stuff, especially bass hits"): extras 12.9 -> 6.7/min, hits on a kick 85% -> 91%,
     stem-label kicks caught 80% -> 70% (softer ones), the user's Dark Arm taps still 96%. Keeps real kicks'
     timing (a higher trigger bar gives the same numbers but fires later). KickNet standalone: `min_peak`.
   - the hit is sent 20 ms after it triggers (`nn_peak=2` frames) carrying the PEAK confidence over those
     frames; its timestamp stays on the attack. At the crossing real kicks and strays look alike (median
     0.69 vs 0.61); at the peak real kicks reach 0.82 and strays 0.66.
   - **Strength (audio.js `_hit`, 2026-11-18 03:08):** full contrast, kick or no kick. The full point is the
     70th percentile of the last 30 s of hits' peak confidences (clamped 0.7-0.9; 0.8 until 8 hits are in,
     so a drop is strong from its first kick); 0.2 below it maps to ~0; curve ^1.5, floor 0.05. In
     main.js every effect of a KickNet hit scales with that strength, base amounts included (they used to
     fire a fixed minimum on every hit, so "no kick" was never 0). Over 30 songs: real kicks median 0.89,
     strays 0.16; first 8 s after a pause, real kicks 0.96. History: the 200-hit window (median 0.59 /
     strays 0.34, ~1 min warm-up: the user liked its contrast once settled but not its first 20 s), an
     absolute 0.6-0.75 ramp, a guarded 20 s ramp (1.00 / 0.53: real kicks great, too little contrast).
     KickNet hits are not damped off the beat-clock grid; downbeat accents only when the clock agrees.
     On wired/laptop speakers hits show ~50 ms after the sound.
   - **Crossfade to the "settled" feel (03:20):** the user found the 30 s curve better at the START of a
     drop but the old 200-hit version better once a drop runs (~20 s in). So `audio.js` computes both
     (old = trigger confidence `z0` vs the 80th percentile of the last 200 hits, ^1.5, floor 0.12, plus
     main.js's old beat-grid damping/accents and base motion) and `settle` = 0 for the first 10 s of a
     section (after >= 3 s without hits, or a drop), ramping to 1 by 25 s; main.js mixes every effect.
     The listener sends `z0` (trigger) next to `z` (20 ms peak). **Pinned to the settled (200-hit) feel since
     03:25** at the user's request ("just stay with the full first version for a bit"): `PIN_SETTLE = 1` at
     the top of `audio.js` (0 = start-of-drop curve always, null = the crossfade).
   - **04:07, settled feel tuned** (the user: fun, the extras are kind of nice, but it "doesn't hit on the
     kicks enough", and "200 hits is probably too long"): it now scales the 20 ms PEAK confidence
     (`SETTLED_USES_PEAK`; real kicks 0.59 -> 0.83, extras 0.34 -> 0.39) against the last 40 hits (was
     200; same kick/extra gap, stronger right after pauses, cleared on silence). Measured over 30 songs:
     | formulation | real kicks | extras | gap |
     |---|---|---|---|
     | 200-hit, trigger conf (03:25) | 0.59 | 0.34 | 0.25 |
     | fixed 0.6-0.75 ramp, peak | 1.00 | 0.46 | 0.54 |
     | guarded 20 s ramp | 1.00 | 0.53 | 0.47 |
     | 30 s p70 contrast curve | 0.89 | 0.16 | 0.73 |
     | **40-hit, peak conf (live)** | **0.84** | **0.39** | **0.45** |
   - the old rule trigger (low-band flux + rise + 180 ms hold + loudness gate) is still in
     `detect.py` behind `nn=0` (also the fallback if `kicknet.npz` is missing)
   - `server.py` sends `{type: 'hit', at: <epoch ms when YOU will hear it>}`; `audio.js` `_hit()`
     schedules it for `at - LEAD(45 ms)`, or fires at once if that moment has passed
   - why reactive and not predicted: the user's drops are syncopated and don't repeat per bar
     (pattern-guessing caught 11-15% of their marks)
   - **Stem labels** (`bench/stem_labels.py`, v6, built with the user's ears on 2026-11-18 in the Kick
     Check page): kick = a fast loud low-end (30-150 Hz) attack (within 14 dB of the track's real
     kicks, rising 15 dB in 40 ms) whose 2-10 kHz click is like the track's own kicks (level within
     28 dB, rise within 15 dB of the typical kick: kills bass/lead bleed and clickless thumps, keeps
     soft clickless kicks on tracks where all kicks are soft); attacks within 70 ms are one layered
     kick; 70-100 ms apart only if the low end dips 12 dB between. Snare = snap rising 22 dB in 40 ms
     + body, ringing >= 8 ms, not on a kick. Big broadband hits near the stem's loudest also count.
     v7: a pure sub note is not a kick (110-250 Hz more than 12 dB under the 30-70 Hz sub at the
     attack): removed all 29 of the user's wrong-marks on 825 hp (a sub arp left in the stem) and 101 of
     106 on Adrenaline, without losing their Dark Arm taps.
     The user's verdict: "way better", Dark Arm "spot on", Adrenaline "about right". Old labels
     (`bench.drum_hits`) put kicks under hi-hats and are no longer used for training.
   - **Timing gotcha:** 44.1 kHz audio in "1 ms" blocks of `sr // 1000` = 44 samples drifts 0.23%
     (0.4 s by 3 minutes). Always convert block indexes with the real block length.
3. **Speaker delay** (`listener/devices.json`):
   - Their **K3 speakers are Bluetooth, about 250 ms late**, which gives time to land every hit on
     time.
   - On laptop speakers (no delay) KickNet hits are sent ~30 ms after the drum hit (the old rules:
     50-60 ms). They were asked earlier whether 50-60 ms was acceptable; no answer.
   - The listener re-checks the output device every 2 s.
   - (History) **Tuned 2026-11-17 night (the user said it reacted too much to vocals and best to clicky kicks
     like tek/hardstyle):** after a hit, a 180 ms hold ignores the bass swelling back after
     sidechain ducking (that was most of the "vocal" hits), unless the new jump is 3 dB bigger. A
     loudness gate (`gate_db` 30) blocks hits when the low end is more than 30 dB under the last 8 s,
     so pure vocal or pad breakdowns stay still. A tighter 14 dB gate cost 11 points on the user's
     Adrenaline marks, and a sub-bass-dominance rule (`sub_margin`) cut real hits as much as bad
     ones, so both are off. Tools: `bench/vocal_study.py` (labels each trigger from the
     drum/vocal stems), `bench/hand_fast.py` (settings against the user's marks).
4. **Drops:** a jump of 8 dB or more in loudness and bass after a quieter stretch of *music*, then a
   30 s cooldown. Music starting after silence doesn't count. On a drop the wall shatters (no stamp:
   the user removed the yellow ドン from the break on 2026-11-18). The next wall is prepared ahead
   (`prepNext`) and pictures are decoded off-thread and uploaded one per frame, so the break starts
   at once and holds 60 fps (it used to stall up to 150 ms per frame and start 160-860 ms late).

**Numbers (keep this separation when reporting):**
- **Human truth:**
  - the user's kick taps on Dark Arm (01, 54-96 s, Kick Check page; tapped on the K3s, so matched at the
    best constant shift): KickNet v6 92% of hits on a tap, 97% of taps caught (KickNet v1: 76% / 97%)
  - Adrenaline cue-page lanes (63-127 s, kick + snare, ±100 ms, `tools/e2e_hand.py` full chain):
    82% of hits on a mark, 58% of marks get a hit. The user says these marks "aren't perfect" (cue
    grid at 129.59 BPM vs ~130.2, drifts 54 ms over the drop): treat as rough.
  - `bench/annotations/` (Kick Check): taps, wrong-marks and notes for 01, 02, 04, 14; read its README
    (which tracks were tapped on the K3s).
- **Machine truth** (stem kick labels v7, derived from the drum stems but checked by the user by eye/ear;
  `bench/kn_train.py` 5-fold cross-validation by track, 30 songs, each scored by a model that never saw it;
  `bench/kn_compare.py`; final comparison 2026-11-18):
  | trigger | kick P / R / F | hits on no kick | Dark Arm taps (HUMAN) P / R |
  |---|---|---|---|
  | old rules (`nn=0`) | 0.48 / 0.63 / 0.54 | 65 /min | 0.92 / 0.91 |
  | KickNet v1 (kick+snare, old labels) | 0.52 / 0.77 / 0.62 | 68 /min | 0.76 / 0.97 |
  | KickNet v6 (kick+snare) | 0.66 / 0.80 / 0.72 | 39 /min | 0.92 / 0.97 |
  | **KickNet v7 kick-only (live, no quiet guard)** | **0.85 / 0.80 / 0.83** | **~12 /min** | **0.96 / 0.96** |
  | (v7 with the 0.8 quiet guard, live 02:09-02:40) | 0.88 / 0.77 / 0.83 | 9.5 /min | 0.96 / 0.96 |
  Full chain on Adrenaline (`tools/e2e_hand.py`): 88% of hits on the user's marked kicks, timing -1 ms.
  Worst tracks for v7 (hits on no kick): Glass Ocean (20) 28/min, 47, 45, 39.
  Caveat (the user's): every song is from their own taste (trance/EDM-ish); held-out scores say nothing
  about other genres. A true test set would be a few songs in other genres (the user declined for now:
  "worst case I'll have you go back to not using KickNet" = set `nn=0`).
- Beat clock (`bench/bench.py` + `report.html`, older stem labels): about 88% of locked beats on a
  drum hit; tempo exact 77%, within a factor of 2 94%.

## Files

```
wallpaper/                 the Lively wallpaper (junction: %LOCALAPPDATA%\Packages\12030rocksdanister.LivelyWallpaper_97hta09mmv6hy\
                           LocalCache\Local\Lively Wallpaper\Library\wallpapers\pinwall -> here)
  index.html               import map version-stamps every module (otherwise Lively's browser serves stale JS)
  src/main.js              world state, effects, input, toggle button, HUD, frame loop, debug hooks (window.__pw)
  src/audio.js             Music: WebSocket client, beat clock extrapolation (+step-back fix), hit scheduling, Lively fallback
  src/layout.js            composition templates (A is used), pin choice, back layer, print marks
  src/shaders.js           card treatments, background (rays, rings, halftone), post (punch, glitch, shatter, shelf, edge halftone)
  src/overlay.js           2D canvas: clock cluster, border, now-playing block, empty-state text, stamps, background type
  src/textures.js          pin texture cache, animated GIFs via ImageDecoder
  src/gl.js                WebGL helpers copied from channel-surf/src/gl.js
  shelf.json               the user's icon-row plates (2560x1440 measured; laptop-alone not measured)
  pins/                    the user's 255 imported pins + manifest.json (private: never publish)
listener/
  server.py                capture, Analyzer (sound time -> heard wall time), websocket, tray, Ctrl+Alt+W, replay mode for tests
  detect.py                the detector (beat clock, kick_fast, kick_raw, groove memory, drops)
  devices.json             per-device delays (K3 = 0.25)
  calibrate.html           tap-along speaker-delay page (saves through the websocket)
  state.json / config.json / listener.log   runtime state, remembered image folder, log (wallpaper stats every 10 s)
tools/
  annotate/                Kick Check page (server.py, port 4353, launch.json "kick-check"): play mix or drum
                           stem, see stem labels / detector hits, mark wrong labels, tap kicks -> bench/annotations
  drop_test.py             triggers a test shatter on every wallpaper and prints its frame-time report
  prep_pins.py             import any image folder -> wallpaper/pins (+ manifest); remembers the folder
  package.py               builds dist/PinWall + zip; refuses if personal strings appear
  e2e_run.py, e2e_beats.mjs  full-chain test: silent replay -> listener on a test port -> audio.js in Node -> scored on stems
  e2e_hand.py              the same chain scored on the user's Adrenaline marks
  desktop_check.py         shows the desktop (Win+D), captures screens, real mouse input, toggles mode, restores
  serve.py, shot.py        local static server (port 4351, POST /save) and headless-Edge screenshots (no WebGL there)
bench/                     detector bench. KickNet: make_full_stems.py (demucs drums of full tracks -> analysis/full/NN/),
                           stem_labels.py (labels), label_human.py (labels vs every human mark), kn_train.py (train,
                           pipeline venv with torch), kn_score.py, kn_baseline.py. Older: 31 drop clips in analysis/drop/
share/                     README, LICENSE, generic devices.json and shelf.json for the package
setup.ps1, Setup.bat, uninstall.ps1, Uninstall.bat    installer for other people (has -Images -NoLively -NoStartup -NoListener -NoPrompt)
dist/                      built package (rebuild: listener/.venv/Scripts/python.exe tools/package.py)
probe/FINDINGS.md          what Lively gives a web wallpaper (APIs, CLI, monitor numbering)
sketch/, test/, MORNING.html   original look sketch, stills and captures (contain the user's pins: private)
```

## How to work on it

- **Reload the wallpaper after editing** (both screens):
  ```
  & 'C:\Program Files\WindowsApps\12030rocksdanister.LivelyWallpaper_20262.5.6.0_x64__97hta09mmv6hy\Build\Lively.exe' setwp --file 'C:\Users\arbxe\AppData\Local\Lively Wallpaper\Library\wallpapers\pinwall' --monitor 2
  ```
  Then the same with `--monitor 1`.
- **Restart the listener:** kill the python processes whose command line contains
  `listener\server.py`, then start `listener\.venv\Scripts\pythonw.exe listener\server.py` from
  `listener\`. Only one instance runs (mutex), except in `--replay` mode.
- **See what's happening live:** `listener/listener.log`. Every 10 s each wallpaper logs `w, h, fps,
  paused, beats, hits, clock{locked, active, bpm, ahead}, err`. This is how to debug "it stopped
  reacting".
- **Screenshot what Lively renders:** `Lively.exe screenshot --file <path> --monitor N`. It times out
  on a paused screen.
- **Test without sound** (never play audio out loud; the user may be asleep or working):
  - `listener/server.py --replay <wav> --start S --duration D --port P [--delay d] [--switch-at s --delay2 d2] --info f.json`
  - `tools/e2e_run.py 08,21,40`
  - `tools/e2e_hand.py`
  - `bench/bench.py` then `bench/report.py`
  - `bench/fast_eval.py` (kick-trigger latency and accuracy)
- **The browser pane only renders while it's visible** (rAF stops when it's hidden). The test server
  is `tools/serve.py`; the page takes test params (`?test&seed=&tmpl=&fx=shatter&ft=&hover=x,y&stamp=x,y&track=&artist=&cover=&ws=&icons=`)
  and `__pw.snap(name)`.
- **Headless Edge can't do WebGL here:** the collage comes out black. Use Lively screenshots or the
  visible pane.

## Picture rotation (2026-11-18, the user: "seeing the same images over and over", "especially the big one")

- `layout.js` `choosePin` picks among the 14 best-fitting pins (weighted by fit) instead of always the single
  best; `pinCost` adds a freshness penalty (3.0, fading over ~30 min) from `S.shown` (id -> last shown ms,
  saved in localStorage `pinwall_shown`, merged between the two screens). Colour coding to the album cover
  is kept: colour distance of shown pins 0.36 (old 0.32, random 0.50).
- Simulated hour with one cover: 250 of 255 pins shown (old 140); the hero spot 40 different pictures
  (old 20), none more than 5 times (old 9).
- The hero now also swaps mid-wall: at bar 16 of every 32 during music, and every other ambient swap.

## Demo video (2026-11-18)

- `tools/record_demo.py` (clean capture: Reactive mode, Win+D, desktop icons hidden, waits for music,
  ddagrab GPU capture of monitor 0 + soundcard loopback, restores everything) and `tools/make_demo.py`
  (KickNet + old trigger on the sound, sync by matching frame-to-frame motion to kicks, strip, libx264).
  NVENC fails on this NVIDIA driver (needs 610+), so both encode with libx264. README "Demo video" has the
  commands.
- The published demo: the user's own recordings (INZO - Overthinker first, "looks cooler with purple",
  then JPEGMAFIA - 1539 N. Calvert), measured sound offsets 385 / 340 ms. Full clip (88 MB) and web clip
  (21 MB) on the `demo-v1` release; `docs/demo.gif` (6 s loop) at the top of the README. Work files stay
  in `demo/` (git-ignored; the raw folders hold audio).
- The songs are copyrighted and the pins are other artists' work: anything public is the user's call.

## Gotchas learned the hard way

- **Lively pauses** a screen's wallpaper when a maximised or full-screen window covers it (logged as
  `paused: True, fps 0`). On the monitor that's most of the time. It isn't a bug.
- **Lively's own audio feed** is only 128 bands at about 16 Hz, too coarse for beats. It's used only
  as a fallback for smooth levels.
- **Mouse forwarding** needs real input events. `SetCursorPos` alone is invisible to Lively's hooks;
  `mouse_event` works.
- **Lively serves wallpapers** from `https://<hash>.localhost/`: modules, fetch, WebGL textures and
  `ws://127.0.0.1` all work.
- **Clock messages:** with Bluetooth delay, the listener's "next beat" can be one beyond a beat not
  yet heard. `audio.js` `_clock` steps back to the earliest unplayed beat; without that, beats never
  fire.
- **Kick detection pitfalls:**
  - In house/trance, kick and clap land together on 2 and 4: a kick with a strong low jump counts
    even with a big click.
  - The clock locked to hi-hats on some tracks: the half-beat "flip" corrects it.
- **PowerShell `Add-Type` fails** here (temp-folder access denied). Use Python ctypes for desktop
  automation.

## Open items

0. **KickNet v7 (kick-only) went live 2026-11-18 ~02:09** (v6 at ~01:40) after the user asked to "make the audio reactive algorithm
   better". Not yet heard by the user on music: ask how it feels (vocals, soft kicks, breakcore).
   Next idea: drive the beat clock from KickNet's kicks instead of the flux envelope (cleaner onsets ->
   faster, truer lock after changes; it still drives swaps, downbeat accents and the HUD). Ideas not tried: train on more tracks (any new song: `bench/make_full_stems.py`, labels are
   automatic), an ensemble of the 5 fold models (+5x 0.15 ms), a small GRU instead of the MLP.
   The packaged build (`dist/`, `tools/package.py`) must ship `kicknet.py` + `kicknet.npz`
   (weights are learned from the user's music: harmless numbers, but check before publishing).
1. **Publishing:** the GitHub repo exists since 2026-11-18 (the user asked, pins included):
   https://github.com/arbxe-42/pinwall-audioreactive-wallpaper (the user's PERSONAL account; transferred
   from the work account andres-r-blanco on 2026-11-18, where it was `pin-wall`, then
   `pinwall-audioreactive-wallpaper`). `gh` here is logged in as andres-r-blanco, which still has push
   and release access after the transfer. (`git push` from `live-wallpaper/`, HTTPS via `gh`;
   SSH has no key here). `.gitignore` keeps out the venv, caches, `test/` desktop captures, `dist/` and
   all audio. **The repo is PUBLIC, pins included: the user's explicit choice on 2026-11-18 ("keep it public")
   after being told it holds their 247 pins (other artists' work).** The demo video is on the `demo-v1`
   release. `dist/PinWall.zip` stays the code-only package for other people.
2. **Laptop-speaker lag**: now ~30 ms with KickNet (was 50-60 ms). Probably fine; not asked again.
3. **Laptop-alone icon shelf** is unmeasured (`shelf.json` has no `1536x960` entry). Ask for a
   screenshot.
4. **The Lively step of `setup.ps1`** (junction + setwp on every screen) hasn't been run end to end
   from the package: it would have redirected the user's own wallpaper. Test it on a separate account
   or after backing up the `pinwall` junction.
5. **Planned but not built:** double-click "cover moment", login boot animation.
6. **More human ground truth:** the Kick Check page (`tools/annotate`) makes it quick; it learns the
   tap delay and snaps taps to the stem attack. Its saves are refused from a page loaded before the
   labels changed (it says to reload).
7. **Perf probe:** `tools/drop_test.py [--fxonly]` triggers a test shatter via the listener
   (`test_drop`) and prints each wallpaper's frame-time report from `listener.log`.
8. **Colours:** the canvas is tagged Display P3 on wide-gamut screens (both of the user's report P3),
   because the user preferred the unmanaged, more vivid look of the browser pane. Lively panel
   "Vivid colours" turns it off.
