"""After deleting pictures from wallpaper/pins by hand: drop them from wallpaper/pins/manifest.json.

  listener/.venv/Scripts/python.exe tools/prune_pins.py

The wallpaper picks pins from the manifest, so a deleted file would otherwise leave a blank card.
The originals (aesthetic-worlds/references/_moodboard/pinterest-board) are not touched.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PINS = os.path.join(ROOT, "wallpaper", "pins")
MAN = os.path.join(PINS, "manifest.json")


def main():
    data = json.load(open(MAN, encoding="utf-8"))
    pins = data if isinstance(data, list) else data["pins"]
    keep = [p for p in pins if os.path.exists(os.path.join(PINS, p["file"]))]
    gone = [p["file"] for p in pins if p not in keep]
    if isinstance(data, list):
        data = keep
    else:
        data["pins"] = keep
    tmp = MAN + ".tmp"
    json.dump(data, open(tmp, "w", encoding="utf-8"), indent=1)
    os.replace(tmp, MAN)
    print(f"{len(keep)} pins kept, {len(gone)} removed from the manifest: {', '.join(gone) or '-'}")


if __name__ == "__main__":
    main()
