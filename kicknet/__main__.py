"""KickNet command line.

  python -m kicknet song.wav                    print every kick (time in seconds, confidence)
  python -m kicknet song.wav --json kicks.json  ... or save them (--csv kicks.csv works too)
  python -m kicknet --live                      kicks in whatever the PC is playing right now (needs soundcard)
  options: --threshold 0.5  --min-gap 0.09
"""
import argparse
import json
import sys
import time

import numpy as np

from .detector import KickDetector, detect_file


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kicknet", description="Find kick drums in music with KickNet.")
    ap.add_argument("audio", nargs="?", help="audio file (WAV; any format soundfile reads if it is installed)")
    ap.add_argument("--live", action="store_true", help="listen to what the PC plays (loopback; needs `soundcard`)")
    ap.add_argument("--json", help="write kicks to this JSON file")
    ap.add_argument("--csv", help="write kicks to this CSV file")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--min-gap", type=float, default=0.09)
    ap.add_argument("--no-idle", action="store_true", help=argparse.SUPPRESS)   # the rule is off by default now
    a = ap.parse_args(argv)
    kw = dict(threshold=a.threshold, min_gap=a.min_gap)
    if a.no_idle:
        kw["idle"] = 1e9
    if a.live:
        return live(kw)
    if not a.audio:
        ap.print_help()
        return 2
    t0 = time.time()
    kicks, sr, dur = detect_file(a.audio, **kw)
    took = time.time() - t0
    if a.json:
        json.dump({"file": a.audio, "sample_rate": sr, "duration": round(dur, 3), "kicks": kicks}, open(a.json, "w"), indent=1)
    if a.csv:
        with open(a.csv, "w") as f:
            f.write("time,confidence\n")
            for k in kicks:
                f.write(f"{k['time']:.3f},{k['confidence']}\n")
    if not (a.json or a.csv):
        for k in kicks:
            print(f"{k['time']:9.3f}  {k['confidence']:.2f}")
    print(f"{len(kicks)} kicks in {dur:.1f} s of audio ({took:.1f} s to analyse)", file=sys.stderr)
    return 0


def live(kw):
    try:
        import soundcard as sc
    except ImportError:
        print("live mode needs the soundcard package: pip install soundcard", file=sys.stderr)
        return 1
    sr, block = 48000, 480
    spk = sc.default_speaker()
    mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
    det = KickDetector(sr, **kw)
    print(f"listening to {spk.name} (Ctrl+C to stop)", file=sys.stderr)
    t0 = time.time()
    try:
        with mic.recorder(samplerate=sr, channels=2, blocksize=block) as rec:
            while True:
                data = rec.record(numframes=block)
                for k in det.process(data.mean(axis=1).astype(np.float32)):
                    bar = "#" * int(round(k["confidence"] * 20))
                    print(f"{time.time() - t0:8.2f}s  kick  {k['confidence']:.2f}  {bar}", flush=True)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
