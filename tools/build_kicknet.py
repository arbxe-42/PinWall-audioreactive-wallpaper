"""Sync the standalone KickNet package (kicknet/) with the live listener's model and zip it.

The listener's copy (listener/kicknet.py + listener/kicknet.npz) is the source of truth; this copies both
into kicknet/ and builds dist/KickNet.zip (a `kicknet/` folder: unzip, then `python -m kicknet song.wav`).

  listener/.venv/Scripts/python.exe tools/build_kicknet.py
"""
import os
import shutil
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "kicknet")
OUT = os.path.join(ROOT, "dist", "KickNet.zip")


def main():
    for f in ("kicknet.py", "kicknet.npz"):
        shutil.copy2(os.path.join(ROOT, "listener", f), os.path.join(PKG, f))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    files = ["__init__.py", "__main__.py", "detector.py", "kicknet.py", "kicknet.npz", "README.md", "requirements.txt"]
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(os.path.join(PKG, f), "kicknet/" + f)
    print(f"synced kicknet/ from listener/ and wrote {OUT} ({os.path.getsize(OUT) // 1024} KB)")


if __name__ == "__main__":
    main()
