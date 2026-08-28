"""Schema Merger deterministic core components.

``core.entity.normalize`` is intentionally not re-exported here: the name would
shadow the :mod:`core.normalize` submodule on the package.  Import it as
``from core.entity import normalize``.
"""

from .contracts import ClusterContract, canonical_map, pending_clusters
from .entity import (
    UNBLOCKED_KEY,
    BlockedRecord,
    ClusterResult,
    EntityCluster,
    EntityError,
    NormalizationConfig,
    PairDecision,
    SimilarityThresholds,
    all_pairs_count,
    candidate_pairs,
    cluster,
    grey_pairs,
    grey_zone_ratio,
    make_blocks,
    pair_count,
    pending_review,
    resolve_pairs,
    review_grey_zone,
    score_pairs,
    to_cluster_plans,
)
from .profiler import ProfileError, profile_file
from .transformer import DeduplicationResult, deduplicate
from .types import (
    ClusterCandidate,
    ClusterMember,
    ColumnProfile,
    EntityClusterPlan,
    FileProfile,
    TableProfile,
)
from .writer import EntitySummary, WriteError, WriteResult, write, write_merged, write_merge_report

__all__ = [
    "UNBLOCKED_KEY",
    "BlockedRecord",
    "ClusterCandidate",
    "ClusterContract",
    "ClusterMember",
    "ClusterResult",
    "ColumnProfile",
    "DeduplicationResult",
    "EntityCluster",
    "EntityClusterPlan",
    "EntityError",
    "EntitySummary",
    "FileProfile",
    "NormalizationConfig",
    "PairDecision",
    "ProfileError",
    "SimilarityThresholds",
    "TableProfile",
    "all_pairs_count",
    "canonical_map",
    "candidate_pairs",
    "cluster",
    "deduplicate",
    "grey_pairs",
    "grey_zone_ratio",
    "make_blocks",
    "pair_count",
    "pending_clusters",
    "pending_review",
    "resolve_pairs",
    "review_grey_zone",
    "score_pairs",
    "to_cluster_plans",
    "WriteError",
    "WriteResult",
    "profile_file",
    "write",
    "write_merged",
    "write_merge_report",
]
