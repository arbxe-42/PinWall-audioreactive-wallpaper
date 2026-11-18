"""KickNet: a tiny causal neural kick-drum detector (numpy only). See README.md."""
from .detector import KickDetector, detect_file, read_audio  # noqa: F401
from .kicknet import Net, Stream, offline_features, WEIGHTS  # noqa: F401

__version__ = "7.0"
