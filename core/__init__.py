"""Schema Merger deterministic core components.

``core.entity.normalize`` is intentionally not re-exported here: the name would
shadow the :mod:`core.normalize` submodule on the package.  Import it as
``from core.entity import normalize``.
"""

from .entity import (
    UNBLOCKED_KEY,
    BlockedRecord,
    EntityError,
    NormalizationConfig,
    PairDecision,
    SimilarityThresholds,
    all_pairs_count,
    candidate_pairs,
    grey_pairs,
    grey_zone_ratio,
    make_blocks,
    pair_count,
    pending_review,
    resolve_pairs,
    review_grey_zone,
    score_pairs,
)
from .profiler import ProfileError, profile_file
from .types import ColumnProfile, FileProfile, TableProfile
from .writer import WriteError, WriteResult, write, write_merged, write_merge_report

__all__ = [
    "UNBLOCKED_KEY",
    "BlockedRecord",
    "ColumnProfile",
    "EntityError",
    "FileProfile",
    "NormalizationConfig",
    "PairDecision",
    "ProfileError",
    "SimilarityThresholds",
    "TableProfile",
    "all_pairs_count",
    "candidate_pairs",
    "grey_pairs",
    "grey_zone_ratio",
    "make_blocks",
    "pair_count",
    "pending_review",
    "resolve_pairs",
    "review_grey_zone",
    "score_pairs",
    "WriteError",
    "WriteResult",
    "profile_file",
    "write",
    "write_merged",
    "write_merge_report",
]
