"""Import images for the Pin Wall wallpaper.

Takes every image in a folder (jpg, jpeg, jfif, png, webp, gif, bmp; sub-folders too) and writes:
  * wallpaper/pins/<n>.webp  resized copies (longest side <= 1400 px); GIFs stay animated as <n>.gif
  * wallpaper/pins/manifest.json  size, a 5-colour palette, brightness, saturation for each image
Old imported images are replaced. The source folder is remembered (listener/config.json), so
"Change images" in the tray menu can re-run it.

Run:  listener/.venv/Scripts/python.exe tools/prep_pins.py --src "C:/path/to/your/images"
      listener/.venv/Scripts/python.exe tools/prep_pins.py            (re-import the remembered folder)
"""
import argparse
import json
import os
import re
import sys

import numpy as np
from PIL import Image, ImageOps, ImageSequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "wallpaper", "pins")
CONFIG = os.path.join(ROOT, "listener", "config.json")
EXTS = {".jpg", ".jpeg", ".jfif", ".png", ".webp", ".gif", ".bmp"}
MAXSIDE = 1400


def families(src):
    """Optional: a families.js next to the images (optional grouping file) groups them; otherwise 'misc'."""
    fam = {}
    p = os.path.join(src, "..", "families.js")
    if os.path.exists(p):
        txt = open(p, encoding="utf-8").read()
        for m in re.finditer(r'id:\s*"(\w+)".*?ids:\s*"([\d ]+)"', txt, re.S):
            for i in m.group(2).split():
                fam.setdefault(i, m.group(1))
    return fam


def palette(im, k=5, iters=12):
    a = np.asarray(im.convert("RGB").resize((64, 64), Image.BILINEAR), float).reshape(-1, 3) / 255
    mx, mn = a.max(1), a.min(1)
    sat = (mx - mn) / (mx + 1e-6)
    w = 0.35 + sat * 1.5 + 0.2 * mx
    rng = np.random.default_rng(1)
    c = a[rng.choice(len(a), k, replace=False, p=w / w.sum())]
    for _ in range(iters):
        lab = np.argmin(((a[:, None, :] - c[None]) ** 2).sum(-1), 1)
        for j in range(k):
            m = lab == j
            if m.any():
                c[j] = (a[m] * w[m, None]).sum(0) / w[m].sum()
    lab = np.argmin(((a[:, None, :] - c[None]) ** 2).sum(-1), 1)
    share = np.array([w[lab == j].sum() for j in range(k)]) / w.sum()
    order = np.argsort(-share)
    lum = float((a @ np.array([0.2126, 0.7152, 0.0722])).mean())
    return [[int(round(v * 255)) for v in c[j]] + [round(float(share[j]), 3)] for j in order], lum, float(sat.mean())


def find_images(src):
    out = []
    for dp, _, files in os.walk(src):
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in EXTS:
                out.append(os.path.join(dp, f))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="folder with your images")
    ap.add_argument("--limit", type=int, default=400, help="at most this many images")
    a = ap.parse_args()
    cfg = {}
    if os.path.exists(CONFIG):
        try:
            cfg = json.load(open(CONFIG, encoding="utf-8"))
        except Exception:
            cfg = {}
    src = a.src or cfg.get("images")
    if not src or not os.path.isdir(src):
        print("No image folder given. Use --src \"C:/path/to/images\"")
        sys.exit(1)
    files = find_images(src)[:a.limit]
    if not files:
        print("No images found in", src)
        sys.exit(1)
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):                       # replace the previous import
        if f.endswith((".webp", ".gif")) or f == "manifest.json":
            os.remove(os.path.join(OUT, f))
    fam = families(src)
    manifest = []
    for n, path in enumerate(files, 1):
        pid = f"{n:03d}"
        try:
            im = Image.open(path)
            anim = getattr(im, "is_animated", False) and getattr(im, "n_frames", 1) > 1
            if not anim:
                im = ImageOps.exif_transpose(im)
            w, h = im.size
            pal, lum, sat = palette(im.copy())
            if anim:
                name = pid + ".gif"
                scale = min(1.0, 900 / max(w, h))
                frames, durs = [], []
                for fr in ImageSequence.Iterator(im):
                    durs.append(fr.info.get("duration", 80))
                    fr = fr.convert("RGBA")
                    if scale < 1.0:
                        fr = fr.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
                    frames.append(fr)
                frames[0].save(os.path.join(OUT, name), save_all=True, append_images=frames[1:], duration=durs, loop=0, disposal=2)
                w, h = frames[0].size
            else:
                im = im.convert("RGB")
                scale = min(1.0, MAXSIDE / max(w, h))
                if scale < 1.0:
                    im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
                w, h = im.size
                name = pid + ".webp"
                im.save(os.path.join(OUT, name), "WEBP", quality=88, method=5)
        except Exception as e:
            print("skipped", os.path.basename(path), "-", e)
            continue
        orig = os.path.splitext(os.path.basename(path))[0][:3]
        manifest.append(dict(id=pid, file=name, w=w, h=h, aspect=round(w / h, 4), lum=round(lum, 3), sat=round(sat, 3),
                             palette=pal, family=fam.get(orig, "misc"), anim=bool(anim)))
        print(f"{n}/{len(files)} {os.path.basename(path)}", flush=True)
    json.dump(manifest, open(os.path.join(OUT, "manifest.json"), "w"), indent=0)
    cfg["images"] = os.path.abspath(src)
    json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), indent=1)
    print(f"done: {len(manifest)} images imported from {src}")


if __name__ == "__main__":
    main()
