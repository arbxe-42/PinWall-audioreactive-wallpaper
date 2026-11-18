"""Separate the drum stem of every full track in the music folder (htdemucs, CPU), for training and
scoring the kick detector on whole songs (breakdowns with vocals included), not only drop windows.

Run with the music pipeline venv (has torch + demucs):
  aesthetic-worlds/references/_music/pipeline/.venv/Scripts/python.exe live-wallpaper/bench/make_full_stems.py
Writes analysis/full/<NN>/drums.flac (local only; derived from the user's own files). Skips done tracks.
"""
import glob
import os
import sys
import time

import numpy as np
import soundfile as sf
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
VIBE = os.path.dirname(os.path.dirname(HERE))
MUSIC = os.path.join(VIBE, "aesthetic-worlds", "references", "_music", "ultra_ethereal_worlds")
OUT = os.path.join(MUSIC, "analysis", "full")


def main():
    from demucs.apply import apply_model
    from demucs.audio import convert_audio
    from demucs.pretrained import get_model
    torch.set_num_threads(max(1, os.cpu_count() - 4))
    model = get_model("htdemucs").eval()
    files = sorted(glob.glob(os.path.join(MUSIC, "*.wav")))
    only = set(sys.argv[1].split(",")) if len(sys.argv) > 1 else None
    for f in files:
        num = os.path.basename(f)[:2]
        if only and num not in only:
            continue
        dst = os.path.join(OUT, num, "drums.flac")
        if os.path.exists(dst):
            continue
        t0 = time.time()
        x, sr = sf.read(f, dtype="float32", always_2d=True)
        wav = torch.from_numpy(x.T)
        wav = convert_audio(wav, sr, model.samplerate, model.audio_channels)
        ref = wav.mean(0)
        mu, sd = ref.mean(), ref.std() + 1e-8
        with torch.no_grad():
            st = apply_model(model, ((wav - mu) / sd)[None], device="cpu", split=True, overlap=0.25, progress=False)[0]
        st = st * sd + mu
        di = model.sources.index("drums")
        drums = st[di].mean(0).numpy()
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        sf.write(dst, drums, model.samplerate, format="FLAC")
        print(num, f"{len(x) / sr:.0f}s audio in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
