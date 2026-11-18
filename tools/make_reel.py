"""Vertical 1080 x 1920 reel (Instagram Reels / TikTok / Shorts) from a tools/record_demo.py recording.

  listener/.venv/Scripts/python.exe tools/make_reel.py --raw demo/raw_X --out demo/reel.mp4 [--start 0] [--seconds 25]

Layout, top to bottom:
  the whole wall (1080 wide, icon shelf and its Reactive/Ambient toggle included, taskbar cut)
  a big zoom on the centre of the wall (the hero picture), so the reel fills the phone screen
  the KickNet strip, drawn taller for a phone
Sound and picture are lined up exactly like tools/make_demo.py (the wall's hits matched to KickNet's kicks).
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_demo as D  # noqa: E402

OW, OH = 1080, 1920
TOP_H = 608                         # whole wall: 2560 x 1392 scaled to 1080 x 587, padded to 608
STRIP_H = 220
MID_H = OH - TOP_H - STRIP_H        # 1092: zoom on the centre of the wall
ZOOM = (790, 160, 1170, 1183)       # x, y, w, h on the 2560 x 1440 capture: the hero card (ends at its right edge, before the now-playing title)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=float, default=0.3, help="seconds into the recording to start")
    ap.add_argument("--seconds", type=float, default=25.0)
    a = ap.parse_args()
    import soundfile as sf
    audio, sr = sf.read(os.path.join(a.raw, "audio.wav"), dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    video = os.path.join(a.raw, "video.mp4")
    kicks, old = D.kicks_and_old(mono, sr)
    d = D.motion(video)
    offset, score = D.find_offset(d, kicks)
    print(f"{len(kicks)} KickNet kicks; picture lags sound by {offset * 1000:.0f} ms (match {score:.2f})")
    dur = min(a.seconds, len(d) / D.FPS - a.start - 0.2, len(mono) / sr - a.start)
    n = int(dur * D.FPS)
    hop = sr // 200
    env = np.abs(mono[:len(mono) // hop * hop]).reshape(-1, hop).max(1)
    env = np.clip(env / (np.percentile(env, 99.5) + 1e-9), 0, 1)
    i0 = int(round((a.start - offset) * sr))
    seg = np.concatenate([np.zeros((max(0, -i0), audio.shape[1]), np.float32), audio[max(0, i0):]])[:int((dur + 0.5) * sr)]
    aligned = os.path.join(a.raw, "audio_aligned_reel.wav")
    sf.write(aligned, seg, sr)
    sx, sy, sw, shh = D.SHOW
    zx, zy, zw, zh = ZOOM
    fc = (f"[0:v]fps={D.FPS},split=2[a0][a1];"
          f"[a0]crop={sw}:{shh}:{sx}:{sy},scale={OW}:-2:flags=lanczos,pad={OW}:{TOP_H}:0:(oh-ih)/2:color=0x0a0810[top];"
          f"[a1]crop={zw}:{zh}:{zx}:{zy},scale={OW}:{MID_H}:flags=lanczos[mid];"
          f"[top][mid][1:v]vstack=inputs=3,format=yuv420p[v]")
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{a.start:.3f}", "-i", video,
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{STRIP_H}", "-r", str(D.FPS), "-i", "-",
           "-i", aligned, "-filter_complex", fc, "-map", "[v]", "-map", "2:a", "-t", f"{dur:.3f}",
           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", a.out]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fr in D.strip_frames(n, a.start, env, 200, kicks, old, offset, width=OW, height=STRIP_H, span=3.0, legend=False):
        p.stdin.write(fr)
    p.stdin.close(); p.wait()
    print("wrote", a.out)


if __name__ == "__main__":
    main()
