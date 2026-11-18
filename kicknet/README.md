# KickNet

A tiny, causal neural **kick-drum detector** for full music mixes. numpy only, ~0.15 ms per 10 ms of audio,
so it runs live. It's the detector behind the Pin Wall music-reactive wallpaper.

- **Input:** any mono audio (any sample rate; trained on 44.1 / 48 kHz).
- **Output:** the time of each kick's attack and a 0-1 confidence.
- **Latency:** a kick triggers ~30 ms after its attack and is reported 20 ms later with its peak confidence
  (`peak_frames=2`; set 0 to report at the trigger). Its time is stamped at the attack itself (median error
  ~1 ms against the drum stem).

## Use it

```bash
pip install numpy            # soundfile for non-WAV files, soundcard for --live (both optional)
python -m kicknet song.wav                     # prints: time (s)  confidence
python -m kicknet song.wav --json kicks.json   # or --csv kicks.csv
python -m kicknet --live                       # kicks in whatever the PC is playing (loopback)
```

Run these from the folder that contains `kicknet/` (or put that folder on your `PYTHONPATH`).

From Python, streaming (feed blocks of any size, exactly like the live wallpaper does):

```python
from kicknet import KickDetector
det = KickDetector(sample_rate=48000)          # threshold=0.5, min_gap=0.09
for block in blocks:                           # mono float32, -1..1
    for k in det.process(block):
        print(k["time"], k["confidence"])
```

or a whole file: `from kicknet import detect_file; kicks, sr, duration = detect_file("song.wav")`.

## How it works

Every 10 ms, a 2048-point spectrum is folded into 40 log-spaced bands (40 Hz-14 kHz). Each band gives its level
(relative to a slowly decaying peak of the whole mix, so loudness doesn't matter) and its change over 10 and
20 ms. The last 12 frames (120 ms, 1440 numbers) go through a small MLP (1440 → 128 → 64 → 1) that answers
"was there a kick attack 30 ms ago?". A kick fires when that confidence reaches 0.5 while still rising, at most
once per 90 ms; it is reported 20 ms later with the peak confidence over those frames (real kicks keep
climbing to ~0.82, stray hits stall around 0.66, so confidence separates them well). Optional: `min_peak` (e.g. 0.65)
drops kicks whose peak stays low, which halves extras such as bass notes but also misses softer kicks. (An optional stricter first-hit-after-a-pause rule, `idle_threshold`, is off: it blocked the
first kicks of drops.)

It was trained on full mixes, with answers taken from demucs-separated **drum stems** of the same songs, so
vocals, bass, arps and pads are in what it hears but never in its answers. The stem kick labels were built and
checked by ear (a loud, fast low-end attack with the track's own click, not a pure sub note, layered attacks
merged). Training details and tools: `bench/` in the Pin Wall repo.

## How good is it (and on what)

Scored with 5-fold cross-validation by song: each song is scored by a model that never trained on it.

| | Kick P / R / F | Hits with no kick under them |
|---|---|---|
| rule-based trigger it replaced (low-band flux + gates) | 0.48 / 0.63 / 0.54 | 65 / min |
| **KickNet v7** | **0.85 / 0.80 / 0.83** | **~12 / min** |

Against a person's hand-tapped kicks on one track: 96% of its kicks land on a tap, 96% of taps are caught.

**Caveat:** the training and test songs (31) are all one listener's taste: trance, hardstyle, neurofunk,
breakcore, ethereal/EDM. Other genres (rock, jazz, orchestral, acoustic drums) are untested. The `--threshold`
option trades misses for false hits (0.6-0.7: fewer false hits, more misses).

## Files

`kicknet.py` (features + network, numpy), `kicknet.npz` (weights, ~0.8 MB), `detector.py` (streaming trigger,
file reader), `__main__.py` (command line). In the Pin Wall repo, `listener/kicknet.*` is the source of truth;
`tools/build_kicknet.py` copies it here and builds `dist/KickNet.zip`.
