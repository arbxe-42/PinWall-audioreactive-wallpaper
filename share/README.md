# Pin Wall

A live Windows wallpaper: a collage of **your own images**, cut, taped, torn and printed out of
register, that floats around on its own and **hits on the kicks of whatever music you play**
(Spotify, YouTube, games, anything). It shows the time, the track that's playing with its album
cover, and reacts to your mouse.

- Runs inside [Lively Wallpaper](https://www.rocksdanister.com/lively/) (free).
- A small background listener hears your PC's sound and finds the beat. Audio is analysed in memory
  only: never recorded, saved or sent anywhere.
- Your images stay on your PC.

## What you need

- Windows 10 or 11
- **Lively Wallpaper**: free in the Microsoft Store. Open it once after installing.
- **Python 3.10 or newer**: [python.org/downloads](https://www.python.org/downloads/). In the
  installer, tick **"Add python.exe to PATH"**.
- About 300 MB of disk space.

## Install

1. Unzip the `PinWall` folder somewhere it can stay, for example `Documents\PinWall`, not inside
   Downloads. The wallpaper runs from this folder.
2. Double-click **`Setup.bat`**. It will:
   - install the music listener (a minute or two the first time),
   - ask for the folder with your images,
   - add Pin Wall to Lively and set it on every screen,
   - ask whether it should start with Windows,
   - ask whether you use Bluetooth speakers or headphones and, if so, open the speaker-delay check.
3. Play some music and look at your desktop.

Run `Setup.bat` again at any time to repair or update the install.

## Your images

**Change them any time:** right-click the Pin Wall icon in the tray (a starburst) → **Change images…**
→ pick a folder. The wallpaper reloads with the new set.

Or from a terminal, inside the PinWall folder:

```
listener\.venv\Scripts\python.exe tools\prep_pins.py --src "C:\path\to\your\images"
```

Tips:
- **Formats:** jpg, png, webp, gif and bmp, sub-folders included. GIFs stay animated.
- **How many:** 60 to 300 images gives the best variety. Up to 400 are used.
- **What works best:** a mix of tall and wide pictures, and bold, saturated art. The big picture in
  the middle is chosen from your brighter, more colourful images.
- **They're copies:** images are copied and resized into `wallpaper\pins\`. Your originals are never
  touched.
- **Pinterest:** to use a board, save its images into a folder first, then import that folder. Only
  use art you're allowed to use, and don't share other people's art without permission.

## Controls

| What | How |
|---|---|
| Music on / off | The **REACTIVE / AMBIENT** button on the desktop (top right), **Ctrl+Alt+W**, or left-click the tray icon |
| Change images | Tray icon → right-click → *Change images…* |
| Speaker delay | Tray icon → right-click → *Calibrate speaker delay…* |
| Settings | Lively → Pin Wall → *Customise*: reaction intensity, clock on/off, battery mode, icon-shelf outlines |
| Mouse | Pictures slide with the cursor; hovering lifts a picture with a holo-foil shine; click for a stamp and shockwave; drag across a picture to rip it and reveal another |

**Reactive** mode: pictures hit on the kicks, the sunburst steps round, a picture swaps every bar,
heavier tears every 8 bars, and the wall shatters on big drops.
**Ambient** mode: everything still floats, drifts and slowly swaps pictures, but nothing follows the
music. The choice is remembered.

## Speaker delay (Bluetooth)

Bluetooth speakers and headphones play sound late, often 150 to 300 ms. The listener hears the sound
before your speakers do, so it can wait and land each hit exactly when you hear it, but it needs to
know the delay.

1. Make the speakers you want to measure your Windows output, with the listener running.
2. Tray icon → *Calibrate speaker delay…* (or open `listener\calibrate.html`).
3. Press **Start**, then tap the space bar on every click you hear.

It saves the delay for that exact device in `listener\devices.json`. The listener checks your output
every 2 seconds and switches delays when you change speakers. Wired speakers and laptop speakers need
nothing. On them, hits show about 50 ms after the sound, since there's no delay to hide the detection
time in.

You can also edit `listener\devices.json` by hand. Each entry matches part of the device name; the
first match wins:

```json
{"devices": [{"match": "My Speaker Name", "delay": 0.25}, {"match": "Bluetooth", "delay": 0.2}, {"match": "", "delay": 0.0}]}
```

## Icon shelf (optional)

If you keep desktop icons in a row along the top of a screen, Pin Wall can put a calm strip behind
them, with a plate behind each group of icons, so the collage never covers your icons. Set it in
`wallpaper\shelf.json`, one entry per screen size (in Windows "scaled" pixels):

```json
{
  "2560x1440": { "band": 112, "plateY": [3, 100], "plates": [[444, 610], [668, 982]], "bottom": 48 },
  "default":   { "band": 0, "plates": [], "bottom": 48 }
}
```

- `band`: height of the strip at the top (0 = none).
- `plates`: `[left, right]` of each icon group.
- `plateY`: their top and bottom.
- `bottom`: room left for the taskbar.

Turn on *Show icon shelf outlines* in Lively's settings to see the plates while you adjust them, and
take a screenshot to measure where your icons are.

## Troubleshooting

- **Nothing moves with the music.**
  - Is the tray icon there? If not, start *Pin Wall listener* from the Start menu's Startup folder, or
    run `Setup.bat` again.
  - Is the button set to REACTIVE?
  - Look in `listener\listener.log`: it should say `capturing <your speakers>` and `lock bpm …` while
    music plays.
- **It stops moving when a window covers the screen.** That's Lively saving power: it pauses the
  wallpaper on a screen covered by a maximised or full-screen window, and it plays again as soon as
  you see the desktop. To change it: Lively → Settings → Performance.
- **Hits feel early or late.** Calibrate the speaker delay (see above).
- **"ADD YOUR IMAGES" on screen.** Import a folder: tray → *Change images…*.
- **The clock font looks plain.** The fonts load from Google Fonts. Without internet, system fonts
  are used instead.

## Uninstall

Double-click `Uninstall.bat`. It stops the listener, removes the autostart and takes Pin Wall out of
Lively. Then delete the folder.

## How it works (short version)

`listener\server.py` captures what Windows plays (WASAPI loopback). `listener\detect.py` finds the
tempo and beat phase, and detects kicks in real time from sudden low-end jumps. Each kick is sent to
the wallpaper over `ws://127.0.0.1:4360`, stamped with the moment you'll hear it. The wallpaper
(`wallpaper\`, WebGL2 in Lively's browser) draws the collage, the clock and the effects. Everything
stays on your machine.

## License

The code is MIT licensed (see `LICENSE`). No images are included: the images you import are yours,
and you're responsible for having the right to use them.
