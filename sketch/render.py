"""Render the sketch frames to PNG with headless Edge. Usage: python render.py [frame ...]"""
import os, subprocess, sys, time
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HERE, "index.html").replace("\\", "/").replace(" ", "%20")
PROFILE = os.path.join(os.environ.get("TEMP", HERE), "pinwall-edge")
for f in sys.argv[1:] or ["calm", "touch", "drop"]:
    out = os.path.join(HERE, "frames", f + ".png")
    if os.path.exists(out): os.remove(out)
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={PROFILE}-{f}",
                    "--allow-file-access-from-files", "--window-size=1920,1080", "--virtual-time-budget=8000",
                    f"--screenshot={out}", f"{URL}?f={f}&shot=1"], capture_output=True)
    for _ in range(60):
        if os.path.exists(out) and os.path.getsize(out) > 0: break
        time.sleep(0.5)
    time.sleep(1)
    print(f, os.path.getsize(out) if os.path.exists(out) else "MISSING")
