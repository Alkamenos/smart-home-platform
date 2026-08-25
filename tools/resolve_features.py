import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from features.lighting.schema import resolve_group, _feats_of  # noqa: F401
