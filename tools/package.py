"""Build the shareable package: dist/PinWall/ and dist/PinWall.zip.

Only code, the generic settings and the instructions go in. Nothing personal: no images (each person
imports their own), no logs, no measured speaker delays, no icon-shelf layout, no test captures.
"""
import json
import os
import re
import shutil
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
OUT = os.path.join(DIST, "PinWall")

FILES = [
    ("Setup.bat", "Setup.bat"), ("Uninstall.bat", "Uninstall.bat"), ("setup.ps1", "setup.ps1"), ("uninstall.ps1", "uninstall.ps1"),
    ("share/README.md", "README.md"), ("share/LICENSE", "LICENSE"),
    ("wallpaper/index.html", "wallpaper/index.html"), ("wallpaper/LivelyInfo.json", "wallpaper/LivelyInfo.json"),
    ("wallpaper/LivelyProperties.json", "wallpaper/LivelyProperties.json"), ("share/shelf.json", "wallpaper/shelf.json"),
    ("listener/server.py", "listener/server.py"), ("listener/detect.py", "listener/detect.py"),
    ("listener/kicknet.py", "listener/kicknet.py"), ("listener/kicknet.npz", "listener/kicknet.npz"),
    ("listener/requirements.txt", "listener/requirements.txt"), ("listener/calibrate.html", "listener/calibrate.html"),
    ("share/devices.json", "listener/devices.json"), ("tools/prep_pins.py", "tools/prep_pins.py"),
]
SRC_DIR = ("wallpaper/src", "wallpaper/src")
PERSONAL = re.compile(r"arbxe|andres|blanco|K3|Adrenaline|moodboard|Vibecode|Sick images|Miss Jay|PRXZM|idiap", re.I)


def thumbnail(path):
    """A pin-free preview for Lively's library: sunburst, halftone, a clock and plates."""
    from PIL import Image, ImageDraw
    import math
    W, H = 640, 360
    im = Image.new("RGB", (W, H), (7, 4, 11))
    d = ImageDraw.Draw(im)
    cx, cy = 400, 190
    for i in range(30):
        if i % 3:
            continue
        a0, a1 = i / 30 * 2 * math.pi, (i + 1) / 30 * 2 * math.pi
        d.polygon([(cx, cy), (cx + 900 * math.cos(a0), cy + 900 * math.sin(a0)), (cx + 900 * math.cos(a1), cy + 900 * math.sin(a1))], fill=(60, 14, 58))
    for y in range(0, H, 9):
        for x in range(0, 250, 9):
            r = max(0, 3.2 - x / 80)
            if r > 0.4:
                d.ellipse([x - r, y - r, x + r, y + r], fill=(30, 120, 140))
    cards = [(330, 70, 170, 220, (123, 44, 255)), (470, 40, 140, 110, (34, 230, 255)), (480, 170, 130, 150, (255, 43, 214)), (240, 210, 120, 110, (182, 255, 46))]
    for x, y, w, h, c in cards:
        d.rectangle([x + 6, y + 6, x + w + 6, y + h + 6], fill=(0, 0, 0))
        d.rectangle([x, y, x + w, y + h], fill=c)
        d.rectangle([x + 10, y + 10, x + w - 10, y + h - 10], outline=(255, 255, 255), width=2)
    try:
        from PIL import ImageFont
        f = ImageFont.truetype("impact.ttf", 92)
    except Exception:
        f = None
    d.text((28, 22), "22:47", fill=(255, 43, 214), font=f)
    d.text((22, 18), "22:47", fill=(182, 255, 46), font=f)
    d.rectangle([22, 128, 230, 150], fill=(0, 0, 0))
    im.save(path, quality=90)


def main():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    for a, b in FILES:
        dst = os.path.join(OUT, b)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, a), dst)
    shutil.copytree(os.path.join(ROOT, SRC_DIR[0]), os.path.join(OUT, SRC_DIR[1]))
    os.makedirs(os.path.join(OUT, "wallpaper", "pins"), exist_ok=True)
    json.dump([], open(os.path.join(OUT, "wallpaper", "pins", "manifest.json"), "w"))
    info = json.load(open(os.path.join(OUT, "wallpaper", "LivelyInfo.json"), encoding="utf-8"))
    info["License"] = "MIT (code). The images are your own."
    info["Desc"] = "A living collage of your own images that floats around and hits on the kicks of your music."
    json.dump(info, open(os.path.join(OUT, "wallpaper", "LivelyInfo.json"), "w", encoding="utf-8"), indent=1)
    thumbnail(os.path.join(OUT, "wallpaper", "thumbnail.jpg"))
    # nothing personal may leave
    hits = []
    for dp, _, fs in os.walk(OUT):
        for f in fs:
            if f.endswith((".py", ".js", ".html", ".json", ".md", ".ps1", ".bat", ".txt")):
                for n, line in enumerate(open(os.path.join(dp, f), encoding="utf-8", errors="ignore"), 1):
                    if PERSONAL.search(line):
                        hits.append(f"{os.path.relpath(os.path.join(dp, f), OUT)}:{n}: {line.strip()[:90]}")
    if hits:
        print("PERSONAL CONTENT FOUND, package not zipped:")
        print("\n".join(hits))
        raise SystemExit(1)
    z = os.path.join(DIST, "PinWall.zip")
    if os.path.exists(z):
        os.remove(z)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for dp, _, fs in os.walk(OUT):
            for f in fs:
                p = os.path.join(dp, f)
                zf.write(p, os.path.join("PinWall", os.path.relpath(p, OUT)))
    n = sum(len(fs) for _, _, fs in os.walk(OUT))
    print(f"package: {OUT} ({n} files), zip: {z} ({os.path.getsize(z) // 1024} KB), personal-content check passed")


if __name__ == "__main__":
    main()
