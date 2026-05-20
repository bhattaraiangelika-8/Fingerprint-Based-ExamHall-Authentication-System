"""
minutiae_core.py — DEPRECATED
──────────────────────────────
This module has been replaced by the v4 pipeline integrated into pipeline.py.

All algorithmic functions (normalize, segmentation, orientation, gabor,
skeletonize, crossing number, Poincaré) are now implemented via the proven
pipeline_v4.py approach in pipeline.py.

Importing anything from this module will raise ImportError to surface
any stale references immediately.
"""

raise ImportError(
    "minutiae_core is deprecated. Use preprocessing.pipeline functions directly. "
    "See pipeline.py for the v4 implementation."
)
