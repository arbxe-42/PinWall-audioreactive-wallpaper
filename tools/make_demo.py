"""Turn a tools/record_demo.py recording into the demo clip: the wall on top, a KickNet strip underneath.

  listener/.venv/Scripts/python.exe tools/make_demo.py [--raw demo/raw] [--out demo/pinwall-demo.mp4] [--gif]

1. KickNet (the live detector, kicknet/) and the old rule trigger (listener/detect.py, nn=0) run on the
   recorded sound.
2. Sync: the wall shows each hit when YOU hear it (Bluetooth delay included), so picture and captured sound
   are offset. The offset is measured, not assumed: frame-to-frame change in the video (hits punch the
   whole wall) is matched against KickNet's kicks, and the sound is shifted to land on the picture.
3. The wall (icon shelf band and taskbar cropped off) is scaled to 1920 x 960 and a 1920 x 120 strip is drawn
   under it: the sound's waveform scrolling past a playhead, KickNet's kicks (taller = more sure), and the
   old loudness trigger's hits (red where it fired on no kick).
4. Writes the mp4 (H.264 + AAC) and, with --loop, a 6 s animated WebP loop for the README.
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.append(os.path.join(ROOT, "listener"))   # after ROOT: listener/kicknet.py must not shadow the kicknet package
W, H_WALL, H_STRIP, FPS = 1920, 1044, 120, 30
CROP = (0, 112, 2560, 1280)          # the collage only (below the icon shelf, above the taskbar): used for sync
# what the clip shows: everything but the taskbar. The icon shelf stays because its Reactive/Ambient toggle
# (top right) shows the mode switching (the user: "the top is important"). The desktop icons are shown as
# they are (the user's choice); --blur-icons blurs the inside of the shelf's plates, the toggle stays sharp.
SHOW = (0, 0, 2560, 1392)


def icon_blur(icons_visible):
    """ffmpeg filter (on the 2560 x 1440 capture) that blurs the inside of each icon plate."""
    if icons_visible:
        return "null"
    sh = json.load(open(os.path.join(ROOT, "wallpaper", "shelf.json"), encoding="utf-8")).get("2560x1440", {})
    y0, y1 = sh.get("plateY", [3, 100])
    plates = sh.get("plates", [])
    if not plates:
        return "null"
    n = len(plates)
    f = f"split={n + 1}" + "".join(f"[s{i}]" for i in range(n + 1)) + ";"
    for i, (x0, x1) in enumerate(plates):
        ins = 8
        f += f"[s{i + 1}]crop={x1 - x0 - 2 * ins}:{y1 - y0 - 2 * ins}:{x0 + ins}:{y0 + ins},boxblur=14:3[b{i}];"
    cur = "s0"
    for i, (x0, x1) in enumerate(plates):
        f += f"[{cur}][b{i}]overlay={x0 + 8}:{y0 + 8}[o{i}];"
        cur = f"o{i}"
    return f[:-len(f"[o{n - 1}];")]   # the last overlay's output becomes the chain's output


def kicks_and_old(mono, sr):
    from kicknet import KickDetector
    from detect import Detector
    k = KickDetector(sr)
    kicks = []
    for i in range(0, len(mono), sr):
        kicks += k.process(mono[i:i + sr])
    d = Detector(sr, params={"nn": 0})
    old = []
    for i in range(0, len(mono), 480):
        for e in d.process(mono[i:i + 480]):
            if e["type"] == "kick_fast":
                old.append(e["t"])
    return kicks, np.array(old)


def motion(video):
    """Per-frame change of the wall (mean abs difference of tiny grey frames), 30 per second."""
    x, y, w, h = CROP
    cmd = ["ffmpeg", "-v", "error", "-i", video, "-vf", f"crop={w}:{h}:{x}:{y},scale=160:80,format=gray",
           "-r", str(FPS), "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, 80, 160).astype(np.float32)
    d = np.zeros(len(f))
    d[1:] = np.abs(f[1:] - f[:-1]).mean(axis=(1, 2))
    return d


def find_offset(d, kicks, max_s=1.2):
    """Seconds the picture lags the captured sound: best match of motion peaks to kick times."""
    if not kicks:
        return 0.0, 0.0
    t = np.arange(len(d)) / FPS
    dz = (d - np.median(d)) / (np.std(d) + 1e-9)
    best = (-1e9, 0.0)
    for off in np.arange(-0.3, max_s, 0.005):
        s = 0.0
        for k in kicks:
            i = int(round((k["time"] + off) * FPS))
            if 1 <= i < len(dz) - 1:
                s += max(dz[i - 1:i + 2]) * k["confidence"]
        if s > best[0]:
            best = (s, off)
    return best[1], best[0] / max(1, len(kicks))


def font(size):
    from PIL import ImageFont
    for f in ("C:/Windows/Fonts/bahnschrift.ttf", "C:/Windows/Fonts/segoeui.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except Exception:
            pass
    return ImageFont.load_default()


def strip_frames(n, start, env, env_rate, kicks, old, offset, width=None, height=None, span=4.0, legend=True):
    """Yield n strip frames (height x width RGB bytes); frame i shows sound time start + i/FPS - offset.
    Drawn for 1920 x 120; other sizes scale every mark with the height (the vertical reel uses a taller strip)."""
    from PIL import Image, ImageDraw
    Wd = width or W; Hd = height or H_STRIP
    k = Hd / 120.0
    S = lambda v: int(round(v * k))
    f_lab, f_small, f_big = font(S(17)), font(S(15)), font(S(22))
    play = 0.72
    kt = np.array([k_["time"] for k_ in kicks]); kc = np.array([k_["confidence"] for k_ in kicks])
    phantom = np.array([len(kt) == 0 or np.min(np.abs(kt - o)) > 0.05 for o in old], bool)
    PINK, RED, WAVE = (255, 63, 184), (255, 86, 86), (104, 86, 150)
    for i in range(n):
        ts = start + i / FPS - offset                      # sound time at the playhead
        a = ts - span * play; b = a + span
        X = lambda tt: int((tt - a) / (b - a) * Wd)
        im = Image.new("RGB", (Wd, Hd), (10, 8, 16)); d = ImageDraw.Draw(im)
        i0, i1 = max(0, int(a * env_rate)), min(len(env), int(b * env_rate))
        px = X(ts)
        for j in range(i0, i1, 2):
            v = env[j] * S(24); x = X(j / env_rate)
            d.line([(x, S(30) - v), (x, S(30) + v)], fill=WAVE if x < px else (64, 54, 90))   # played part brighter
        # how long ago the last kick crossed the playhead (drives the flash)
        past = kt[kt <= ts]
        since = ts - past[-1] if len(past) else 9.0
        glow = max(0.0, 1.0 - since / 0.18)
        if glow > 0:   # the playhead blooms on each kick
            gw = S(6 + 20 * glow)
            col = tuple(int(10 + (c - 10) * glow * 0.45) for c in PINK)
            d.rectangle([px - gw, 0, px + gw, Hd], fill=col)
        m = (kt >= a) & (kt <= b)
        for t, c in zip(kt[m], kc[m]):
            x = X(t); hh = S(14 + 30 * c); near = abs(t - ts) < 0.1
            d.rectangle([x - S(5), S(78) - hh // 2, x + S(5), S(78) + hh // 2], fill=(255, 170, 225) if near else PINK)
            d.rectangle([x - S(2), S(78) - hh // 2 + S(3), x + S(2), S(78) + hh // 2 - S(3)], fill=(255, 215, 240))
        mo = (old >= a) & (old <= b)
        for t, ph in zip(old[mo], phantom[mo]):
            x = X(t); d.rectangle([x - S(2), S(103), x + S(2), S(117)], fill=RED if ph else (120, 120, 132))
        d.line([(px, 0), (px, Hd)], fill=(255, 255, 255), width=max(2, S(2)))
        # labels on a dark plate so the scrolling marks never run under them; a light flashes on each kick
        d.rectangle([0, S(52), S(235), Hd], fill=(10, 8, 16))
        lit = tuple(int(70 + (c - 70) * glow) for c in PINK) if glow > 0 else (70, 30, 60)
        d.ellipse([S(18), S(68), S(38), S(88)], fill=lit)
        d.text((S(48), S(64)), "KICKNET", font=f_big, fill=(255, 170, 225) if glow > 0.3 else PINK)
        d.text((S(48), S(100)), "loudness trigger", font=f_small, fill=(130, 130, 142))
        if legend:
            d.rectangle([Wd - S(500), S(2), Wd, S(26)], fill=(10, 8, 16))
            d.text((Wd - S(490), S(4)), "pink = kicks KickNet hears    red = old trigger firing on no kick", font=f_small, fill=(176, 170, 190))
        yield im.tobytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=os.path.join(ROOT, "demo", "raw"))
    ap.add_argument("--out", default=os.path.join(ROOT, "demo", "pinwall-demo.mp4"))
    ap.add_argument("--skip", type=float, default=0.6, help="seconds trimmed off the start")
    ap.add_argument("--gif", "--loop", dest="gif", action="store_true", help="also write a 6 s animated WebP loop")
    ap.add_argument("--blur-icons", action="store_true", help="blur the desktop icons inside the shelf plates (shown by default)")
    a = ap.parse_args()
    import soundfile as sf
    audio, sr = sf.read(os.path.join(a.raw, "audio.wav"), dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    video = os.path.join(a.raw, "video.mp4")
    meta = json.load(open(os.path.join(a.raw, "meta.json")))
    kicks, old = kicks_and_old(mono, sr)
    d = motion(video)
    offset, score = find_offset(d, kicks)
    print(f"{len(kicks)} KickNet kicks, {len(old)} old-trigger hits; picture lags sound by {offset * 1000:.0f} ms (match {score:.2f})")
    dur = min(meta["seconds"], len(d) / FPS - a.skip - 0.2, len(mono) / sr - a.skip)
    n = int(dur * FPS)
    hop = sr // 200
    env = np.abs(mono[:len(mono) // hop * hop]).reshape(-1, hop).max(1)
    env = np.clip(env / (np.percentile(env, 99.5) + 1e-9), 0, 1)
    x, y, w, h = CROP
    # the sound for video time skip.. is sound time (skip - offset)..: cut it here (silence-padded if needed)
    i0 = int(round((a.skip - offset) * sr))
    pad = np.zeros((max(0, -i0), audio.shape[1]), np.float32)
    seg = np.concatenate([pad, audio[max(0, i0):]])[:int((dur + 0.5) * sr)]
    aligned = os.path.join(a.raw, "audio_aligned.wav")
    sf.write(aligned, seg, sr)
    a_in = ["-i", aligned]
    cmd = (["ffmpeg", "-v", "error", "-y", "-ss", f"{a.skip:.3f}", "-i", video,
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H_STRIP}", "-r", str(FPS), "-i", "-"] + a_in +
           ["-filter_complex", f"[0:v]{icon_blur(not a.blur_icons)}[cl];[cl]crop={SHOW[2]}:{SHOW[3]}:{SHOW[0]}:{SHOW[1]},"
            f"scale={W}:{H_WALL}:flags=lanczos,fps={FPS}[wall];[wall][1:v]vstack[v];"
            "[2:a]anull[a]",
            "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", a.out])
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fr in strip_frames(n, a.skip, env, 200, kicks, old, offset):
        p.stdin.write(fr)
    p.stdin.close(); p.wait()
    print("wrote", a.out)
    if a.gif:
        # README loop: an animated WebP (full colour; a GIF's 256-colour palette looked muddy): 6 s, 1000 px,
        # 15 fps, quality 75 (~8-9 MB; GitHub shows it like a GIF)
        loop = os.path.splitext(a.out)[0] + "-loop.webp"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "4", "-t", "6", "-i", a.out, "-vf", "fps=15,scale=1000:-1:flags=lanczos",
                        "-c:v", "libwebp_anim", "-q:v", "75", "-preset", "picture", "-compression_level", "5", "-loop", "0", "-an", loop], check=True)
        print("wrote", loop, f"({os.path.getsize(loop) // 1024} KB)")


if __name__ == "__main__":
    main()
