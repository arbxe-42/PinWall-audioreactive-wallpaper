"""KickDetector: streaming kick detection with KickNet, the same trigger the Pin Wall listener uses live.

    from kicknet import KickDetector
    det = KickDetector(sample_rate=48000)
    for block in audio_blocks:            # mono float32 numpy arrays, any length
        for kick in det.process(block):
            print(kick["time"], kick["confidence"])

`time` is the kick's attack in seconds from the first sample fed (not the moment it was detected, which is
~30 ms later). `confidence` is KickNet's 0..1 activation at the trigger.
"""
import numpy as np

from .kicknet import Net, Stream, WEIGHTS


class KickDetector:
    def __init__(self, sample_rate, weights=WEIGHTS, threshold=0.5, min_gap=0.09, idle=1.5, idle_threshold=0.8,
                 nfft=2048):
        """
        threshold       fire when the kick confidence reaches this while still rising (live: 0.5)
        min_gap         at most one kick per this many seconds (live: 0.09)
        idle            after this many seconds without a kick ...
        idle_threshold  ... the next one needs this confidence (live: 1.5 s / 0.8; cuts lone false hits in
                        breakdowns). Set idle=1e9 to turn it off.
        """
        self.sr = sample_rate
        self.hop = int(round(sample_rate / 100.0))     # 10 ms frames
        self.nfft = nfft
        self.win = np.hanning(nfft).astype(np.float32)
        self.wsum = float(self.win.sum())
        self.buf = np.zeros(nfft, np.float32)
        self.pending = np.zeros(0, np.float32)
        self.net = Net(weights)
        self.stream = Stream(sample_rate, nfft, self.net)
        self.threshold, self.min_gap, self.idle, self.idle_threshold = threshold, min_gap, idle, idle_threshold
        self.n = 0
        self.prev = 0.0
        self.last = -10 ** 9

    def process(self, block):
        """Feed mono float samples (-1..1). Returns a list of {"time", "confidence"} for kicks confirmed so far."""
        out = []
        x = np.concatenate([self.pending, np.asarray(block, np.float32).ravel()])
        i = 0
        while len(x) - i >= self.hop:
            self.buf = np.roll(self.buf, -self.hop)
            self.buf[-self.hop:] = x[i:i + self.hop]
            i += self.hop
            out.extend(self._frame())
        self.pending = x[i:]
        return out

    def _frame(self):
        n = self.n
        self.n += 1
        spec = np.abs(np.fft.rfft(self.buf * self.win)) / self.wsum
        k, _ = self.stream.push(spec)
        prev, self.prev = self.prev, k
        if (n - self.last) * self.hop / self.sr < self.min_gap:
            return []
        quiet = (n - self.last) * self.hop / self.sr > self.idle
        thr = max(self.threshold, self.idle_threshold) if quiet else self.threshold
        if k >= thr and k >= prev:
            self.last = n
            return [{"time": (n - self.net.lag + 1) * self.hop / self.sr, "confidence": round(float(k), 3)}]
        return []


def detect_file(path, **kw):
    """All kicks in an audio file: list of {"time", "confidence"}. Reads with soundfile if installed, else WAV
    via the standard library."""
    x, sr = read_audio(path)
    det = KickDetector(sr, **kw)
    out = []
    for i in range(0, len(x), sr):          # 1 s blocks; the result is the same for any block size
        out.extend(det.process(x[i:i + sr]))
    return out, sr, len(x) / sr


def read_audio(path):
    try:
        import soundfile as sf
        x, sr = sf.read(path, dtype="float32", always_2d=True)
        return x.mean(axis=1), sr
    except ImportError:
        pass
    import wave
    with wave.open(str(path), "rb") as w:
        sr, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        v = np.where(v >= 1 << 23, v - (1 << 24), v)
        x = v.astype(np.float32) / float(1 << 23)
    elif width == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / float(1 << 31)
    else:
        raise ValueError(f"unsupported WAV sample width {width} bytes (install soundfile for other formats)")
    return x.reshape(-1, ch).mean(axis=1), sr
