"""Request and response models for the web backend.

These models are a transport shell around the dataclasses in :mod:`core`: they
convert to and from ``SourceMatch``/``MappingEntry``/``EntityClusterPlan`` and
add nothing the core does not already know.  No business rule lives here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.contracts import ClusterContract, MappingContract
from core.types import (
    ClusterCandidate,
    ClusterMember,
    ColumnProfile,
    EntityClusterPlan,
    FileProfile,
    MappingEntry,
    SourceMatch,
    TargetColumn,
)
from core.validator import ValidationFinding, ValidationReport
from core.writer import EntitySummary, WriteResult


MappingStatus = Literal["auto", "review", "unmatched"]
ClusterStatus = Literal["auto", "review", "rejected"]
Artifact = Literal["merged", "report"]
SessionState = Literal["uploaded", "analyzed", "applied"]


class SourceModel(BaseModel):
    """One proposed source column for a target column."""

    model_config = ConfigDict(extra="forbid")

    file: str
    column: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    status: MappingStatus
    reason: str | None = None
    samples: list[object] | None = None

    @classmethod
    def from_core(cls, source: SourceMatch) -> "SourceModel":
        return cls(
            file=source.file,
            column=source.column,
            confidence=source.confidence,
            status=source.status,
            reason=source.reason,
            samples=list(source.samples) if source.samples is not None else None,
        )

    def to_core(self) -> SourceMatch:
        return SourceMatch(
            file=self.file,
            column=self.column,
            confidence=self.confidence,
            status=self.status,
            reason=self.reason,
            samples=list(self.samples) if self.samples is not None else None,
        )


class MappingEntryModel(BaseModel):
    """All source proposals made for one target column."""

    model_config = ConfigDict(extra="forbid")

    target_column: str
    sources: list[SourceModel]

    @classmethod
    def from_core(cls, entry: MappingEntry) -> "MappingEntryModel":
        return cls(
            target_column=entry.target_column,
            sources=[SourceModel.from_core(source) for source in entry.sources],
        )

    def to_core(self) -> MappingEntry:
        return MappingEntry(
            target_column=self.target_column,
            sources=[source.to_core() for source in self.sources],
        )


class StatusCounts(BaseModel):
    """How many matches sit in each status; ``review`` blocks ``apply``."""

    auto: int = 0
    review: int = 0
    unmatched: int = 0

    @classmethod
    def from_core(cls, mapping: MappingContract) -> "StatusCounts":
        counts = {"auto": 0, "review": 0, "unmatched": 0}
        for entry in mapping.entries:
            for source in entry.sources:
                counts[source.status] += 1
        return cls(**counts)


class MappingModel(BaseModel):
    """A whole Phase 1 plan plus the counts a review screen needs."""

    model_config = ConfigDict(extra="forbid")

    entries: list[MappingEntryModel]
    counts: StatusCounts = Field(default_factory=StatusCounts)

    @classmethod
    def from_core(cls, mapping: MappingContract) -> "MappingModel":
        return cls(
            entries=[MappingEntryModel.from_core(entry) for entry in mapping.entries],
            counts=StatusCounts.from_core(mapping),
        )

    def to_core(self) -> MappingContract:
        return MappingContract(entries=[entry.to_core() for entry in self.entries])


class MappingUpdate(BaseModel):
    """PUT body: the plan as the user edited it (counts are recomputed)."""

    model_config = ConfigDict(extra="forbid")

    entries: list[MappingEntryModel]

    def to_core(self) -> MappingContract:
        return MappingContract(entries=[entry.to_core() for entry in self.entries])


class ClusterMemberModel(BaseModel):
    """One spelling that belongs to a cluster."""

    model_config = ConfigDict(extra="forbid")

    value: str
    normalized: str = ""
    row_count: int = 0

    @classmethod
    def from_core(cls, member: ClusterMember) -> "ClusterMemberModel":
        return cls(value=member.value, normalized=member.normalized, row_count=member.row_count)

    def to_core(self) -> ClusterMember:
        return ClusterMember(value=self.value, normalized=self.normalized, row_count=self.row_count)


class ClusterCandidateModel(BaseModel):
    """A proposed spelling that no one has moved into the cluster yet."""

    model_config = ConfigDict(extra="forbid")

    value: str
    similarity: float
    suggestion: Literal["same", "different", "undecided"]
    source: str
    confidence: float | None = None
    reason: str | None = None

    @classmethod
    def from_core(cls, candidate: ClusterCandidate) -> "ClusterCandidateModel":
        return cls(
            value=candidate.value,
            similarity=candidate.similarity,
            suggestion=candidate.suggestion,
            source=candidate.source,
            confidence=candidate.confidence,
            reason=candidate.reason,
        )

    def to_core(self) -> ClusterCandidate:
        return ClusterCandidate(
            value=self.value,
            similarity=self.similarity,
            suggestion=self.suggestion,
            source=self.source,
            confidence=self.confidence,
            reason=self.reason,
        )


class ClusterModel(BaseModel):
    """One reviewable entity cluster; only ``auto`` ones are merged."""

    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    target_column: str
    canonical: str
    status: ClusterStatus
    members: list[ClusterMemberModel]
    candidates: list[ClusterCandidateModel] = Field(default_factory=list)
    reason: str | None = None

    @classmethod
    def from_core(cls, plan: EntityClusterPlan) -> "ClusterModel":
        return cls(
            cluster_id=plan.cluster_id,
            target_column=plan.target_column,
            canonical=plan.canonical,
            status=plan.status,
            members=[ClusterMemberModel.from_core(member) for member in plan.members],
            candidates=[ClusterCandidateModel.from_core(item) for item in plan.candidates],
            reason=plan.reason,
        )

    def to_core(self) -> EntityClusterPlan:
        return EntityClusterPlan(
            cluster_id=self.cluster_id,
            target_column=self.target_column,
            canonical=self.canonical,
            status=self.status,
            members=[member.to_core() for member in self.members],
            candidates=[candidate.to_core() for candidate in self.candidates],
            reason=self.reason,
        )


class ClustersModel(BaseModel):
    """Every cluster proposed for one target column."""

    model_config = ConfigDict(extra="forbid")

    target_column: str | None = None
    clusters: list[ClusterModel] = Field(default_factory=list)
    approved_count: int = 0
    pending_count: int = 0

    @classmethod
    def from_core(cls, contract: ClusterContract) -> "ClustersModel":
        return cls(
            target_column=contract.target_column,
            clusters=[ClusterModel.from_core(plan) for plan in contract.clusters],
            approved_count=len(contract.approved),
            pending_count=len(contract.pending),
        )

    def to_core(self) -> ClusterContract:
        return ClusterContract(clusters=[item.to_core() for item in self.clusters])


class ClustersUpdate(BaseModel):
    """PUT body: clusters as the user approved or rejected them."""

    model_config = ConfigDict(extra="forbid")

    clusters: list[ClusterModel]

    def to_core(self) -> ClusterContract:
        return ClusterContract(clusters=[item.to_core() for item in self.clusters])


class UploadResponse(BaseModel):
    """The workspace a session works in; every later call names its id."""

    session_id: str
    inputs: list[str]
    target_schema: str
    state: SessionState


class AnalyzeRequest(BaseModel):
    """Phase 1 options; ``sheet`` narrows every workbook to one worksheet."""

    model_config = ConfigDict(extra="forbid")

    sheet: str | None = None


class ClusterRequest(BaseModel):
    """Phase 1 entity proposal for one target column."""

    model_config = ConfigDict(extra="forbid")

    column: str
    sheet: str | None = None
    strategy: list[str] | None = None
    high: float | None = None
    low: float | None = None
    use_llm: bool = True


class ApplyRequest(BaseModel):
    """Phase 2 options; no LLM is ever built for this call."""

    model_config = ConfigDict(extra="forbid")

    output_format: Literal["xlsx", "csv", "sql"] | None = None
    sheet: str | None = None
    null_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    use_clusters: bool = True


class FindingModel(BaseModel):
    """One validator finding, already rendered for a human."""

    check: str
    severity: Literal["info", "warning", "error"]
    target_column: str
    message: str
    source_file: str | None = None
    source_column: str | None = None
    description: str

    @classmethod
    def from_core(cls, finding: ValidationFinding) -> "FindingModel":
        return cls(
            check=finding.check,
            severity=finding.severity,
            target_column=finding.target_column,
            message=finding.message,
            source_file=finding.source_file,
            source_column=finding.source_column,
            description=finding.describe(),
        )


class EntityResultModel(BaseModel):
    """What approved clusters did to this merge."""

    target_column: str
    merged_cluster_count: int
    canonicalized_row_count: int
    duplicate_row_count: int
    pending_cluster_count: int

    @classmethod
    def from_core(cls, entity: EntitySummary) -> "EntityResultModel":
        return cls(
            target_column=entity.target_column,
            merged_cluster_count=entity.merged_cluster_count,
            canonicalized_row_count=entity.canonicalized_row_count,
            duplicate_row_count=entity.duplicate_row_count,
            pending_cluster_count=len(entity.pending_clusters),
        )


class ApplyResponse(BaseModel):
    """Phase 2 outcome; the files themselves are fetched from ``/download``."""

    row_count: int
    null_cell_count: int
    conversion_error_count: int
    output_format: str
    merged_file: str
    report_file: str
    skipped_sheets: list[str] = Field(default_factory=list)
    warnings: list[FindingModel] = Field(default_factory=list)
    entity: EntityResultModel | None = None

    @classmethod
    def from_core(
        cls,
        written: WriteResult,
        validation: ValidationReport,
        *,
        skipped_sheets: list[str],
        entity: EntitySummary | None,
    ) -> "ApplyResponse":
        return cls(
            row_count=written.row_count,
            null_cell_count=written.null_cell_count,
            conversion_error_count=written.conversion_error_count,
            output_format=written.output_format,
            merged_file=written.merged_path.name,
            report_file=written.report_path.name,
            skipped_sheets=list(skipped_sheets),
            warnings=[FindingModel.from_core(item) for item in validation.warnings],
            entity=None if entity is None else EntityResultModel.from_core(entity),
        )


class PendingMatch(BaseModel):
    """One match that still blocks ``apply``."""

    target_column: str
    file: str
    column: str | None
    confidence: float
    reason: str | None = None


class ReviewGuardDetail(BaseModel):
    """4xx body of a refused ``apply``: what to fix, and that nothing ran."""

    error: Literal["review_pending", "validation_failed"]
    message: str
    pending: list[PendingMatch] = Field(default_factory=list)
    findings: list[FindingModel] = Field(default_factory=list)
    written: bool = False


class SessionStatus(BaseModel):
    """Enough progress for a UI to know which step is next (MVP)."""

    session_id: str
    state: SessionState
    inputs: list[str]
    target_schema: str
    counts: StatusCounts | None = None
    has_mapping: bool = False
    has_clusters: bool = False
    artifacts: list[Artifact] = Field(default_factory=list)


class ProviderInfo(BaseModel):
    """Which provider this user configured -- never the key itself."""

    provider: str
    embedding_provider: str
    model: str
    embedding_model: str = ""
    configured: bool
    detail: str | None = None


class SourceColumnModel(BaseModel):
    """One column that exists in an uploaded source file.

    The review screen needs these to offer a dropdown: correcting a match is a
    choice among the columns that are really there, never a free-text guess
    columns that really exist, never a free-text guess.
    """

    name: str
    inferred_type: str
    samples: list[str] = Field(default_factory=list)
    unique_count: int = 0
    null_ratio: float = 0.0

    @classmethod
    def from_core(cls, column: ColumnProfile) -> "SourceColumnModel":
        return cls(
            name=column.name,
            inferred_type=column.inferred_type,
            samples=[str(value) for value in column.samples],
            unique_count=column.unique_count,
            null_ratio=column.null_ratio,
        )


class FileColumnsModel(BaseModel):
    """Every column one uploaded file offers, across its worksheets."""

    file: str
    row_count: int = 0
    columns: list[SourceColumnModel] = Field(default_factory=list)

    @classmethod
    def from_core(cls, profile: FileProfile) -> "FileColumnsModel":
        seen: dict[str, SourceColumnModel] = {}
        row_count = 0
        for table in profile.tables:
            row_count += table.row_count
            for column in table.columns:
                seen.setdefault(column.name, SourceColumnModel.from_core(column))
        return cls(file=profile.path.name, row_count=row_count, columns=list(seen.values()))


class TargetColumnModel(BaseModel):
    """One target column as the schema declares it."""

    name: str
    type: str
    required: bool = False

    @classmethod
    def from_core(cls, column: TargetColumn) -> "TargetColumnModel":
        return cls(name=column.name, type=column.type, required=column.required)


class ColumnsModel(BaseModel):
    """What a review screen may choose from: sources on one side, target on the other."""

    files: list[FileColumnsModel] = Field(default_factory=list)
    target_columns: list[TargetColumnModel] = Field(default_factory=list)


class RegisterRequest(BaseModel):
    """Sign-up body; the password is never stored or echoed in clear."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class LoginRequest(BaseModel):
    """Sign-in body."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class UserModel(BaseModel):
    """The account as a browser may see it -- never a key, never a hash."""

    id: int
    email: str
    provider: str
    model: str
    embedding_model: str = ""
    key_configured: bool = False


class SessionToken(BaseModel):
    """What a successful sign-in returns; send it as ``Authorization: Bearer``."""

    token: str
    user: UserModel


class ProviderUpdate(BaseModel):
    """The user's own provider settings.

    ``api_key`` is held in server memory for this process only: it is never
    written to disk and never comes back in a response.  Omit it to keep the
    key already held, send an empty string to forget it.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai", "anthropic", "ollama"]
    model: str | None = None
    embedding_model: str | None = None
    api_key: str | None = None
