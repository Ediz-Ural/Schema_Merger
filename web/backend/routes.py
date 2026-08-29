"""HTTP endpoints that drive the two-phase flow over the deterministic core.

Every route is orchestration only: it loads a session's files, calls the same
``core`` functions the CLI calls, and shapes the result for a browser.  The
invariants live in the core and are enforced here as HTTP status codes -- most
importantly the review guard, which turns an unreviewed plan into ``409`` so no
blind merge can be started from a UI either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
import tempfile
import uuid

from fastapi import APIRouter, Body, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from core.contracts import (
    ClusterContract,
    ContractValidationError,
    MappingContract,
    SchemaContract,
    dump_clusters,
    dump_mapping,
    load_clusters,
    load_mapping,
    load_schema,
    pending_reviews,
)
from core.entity import (
    BLOCKING_STRATEGIES,
    DEFAULT_HIGH_THRESHOLD,
    DEFAULT_LOW_THRESHOLD,
    EntityError,
    SimilarityThresholds,
    make_blocks,
    resolve_pairs,
    to_cluster_plans,
)
from core.entity import cluster as build_clusters
from core.llm import (
    EmbeddingClient,
    LLMClient,
    LLMConfig,
    LLMConfigurationError,
    create_embedding_client,
    create_llm_client,
)
from core.matcher import match_profiles
from core.profiler import ProfileError, profile_file
from core.transformer import TransformError, deduplicate, transform
from core.validator import ValidationError, ValidationSettings, validate
from core.writer import DEFAULT_REPORT_NAME, EntitySummary, WriteError, write

from .auth import (
    DEFAULT_EMBEDDING_MODELS,
    DEFAULT_MODELS,
    AuthError,
    ProviderCredentials,
    User,
    UserStore,
)
from .schemas import (
    AnalyzeRequest,
    ColumnsModel,
    ApplyRequest,
    ApplyResponse,
    ClusterRequest,
    ClustersModel,
    ClustersUpdate,
    FileColumnsModel,
    LoginRequest,
    FindingModel,
    MappingModel,
    MappingUpdate,
    PendingMatch,
    ProviderInfo,
    ProviderUpdate,
    RegisterRequest,
    ReviewGuardDetail,
    SessionStatus,
    SessionToken,
    StatusCounts,
    TargetColumnModel,
    UploadResponse,
    UserModel,
)


#: Refusal used by both guards; nothing is written when it is returned.
REVIEW_GUARD_STATUS = 409

#: Input extensions the profiler understands.
SUPPORTED_INPUT_SUFFIXES = frozenset({".csv", ".xlsx"})

SCHEMA_NAME = "schema.yaml"
MAPPING_NAME = "mapping.yaml"
CLUSTERS_NAME = "clusters.yaml"

router = APIRouter()


@dataclass
class Session:
    """One user's workspace on disk: uploads, plan, and outputs.

    A session is a folder and nothing more; every artifact is a real file, so a
    session can be inspected -- or finished with the CLI -- exactly as if the
    user had run ``merger`` in that folder.
    """

    session_id: str
    workspace: Path
    user_id: int
    inputs: list[str] = field(default_factory=list)
    schema_file: str = SCHEMA_NAME
    state: str = "uploaded"
    merged_name: str | None = None
    report_name: str | None = None

    @property
    def schema_path(self) -> Path:
        return self.workspace / self.schema_file

    @property
    def mapping_path(self) -> Path:
        return self.workspace / MAPPING_NAME

    @property
    def clusters_path(self) -> Path:
        return self.workspace / CLUSTERS_NAME

    @property
    def input_paths(self) -> list[Path]:
        return [self.workspace / name for name in self.inputs]

    def artifact_path(self, artifact: str) -> Path | None:
        name = self.merged_name if artifact == "merged" else self.report_name
        if name is None:
            return None
        candidate = self.workspace / name
        return candidate if candidate.is_file() else None


class SessionStore:
    """In-memory registry of workspaces (MVP: one process, no database)."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else Path(tempfile.mkdtemp(prefix="schema-merger-web-"))
        self._root.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, Session] = {}

    @property
    def root(self) -> Path:
        return self._root

    def create(self, user: User) -> Session:
        session_id = uuid.uuid4().hex
        workspace = self._root / session_id
        workspace.mkdir(parents=True, exist_ok=False)
        session = Session(session_id=session_id, workspace=workspace, user_id=user.id)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str, user: User) -> Session:
        """One user's own session.

        Someone else's session is reported as missing rather than forbidden, so
        the API never confirms that an id exists to a user who may not see it.
        """

        session = self._sessions.get(session_id)
        if session is None or session.user_id != user.id:
            raise HTTPException(status_code=404, detail=f"Oturum bulunamadı: {session_id}")
        return session

    def discard(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            shutil.rmtree(session.workspace, ignore_errors=True)


def get_sessions(request: Request) -> SessionStore:
    """The store the app was built with; tests can point it at ``tmp_path``."""

    return request.app.state.sessions


def get_users(request: Request) -> UserStore:
    """The account store the app was built with."""

    return request.app.state.users


def current_user(
    authorization: str | None = Header(default=None),
    users: UserStore = Depends(get_users),
) -> User:
    """The signed-in account behind ``Authorization: Bearer <token>``."""

    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    user = users.user_for_token(token) if token else None
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Giriş gerekli ya da oturumun süresi doldu.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_credentials(
    user: User = Depends(current_user), users: UserStore = Depends(get_users)
) -> ProviderCredentials:
    """This user's own provider settings, key included from memory."""

    return users.credentials(user)


def get_llm_client(credentials: ProviderCredentials = Depends(get_credentials)) -> LLMClient:
    """Build the chat client from the *user's own* key and model.

    The key lives only in this process's memory (see :mod:`web.backend.auth`);
    it never travels back in a response and is never written to disk.  Tests
    override this dependency with a fake so no provider is contacted.
    """

    if not credentials.configured:
        raise LLMConfigurationError(
            "Sağlayıcı anahtarın tanımlı değil. Ayarlar ekranından kendi API anahtarını gir."
        )
    return create_llm_client(credentials.to_config())


def get_embedding_client(
    credentials: ProviderCredentials = Depends(get_credentials),
) -> EmbeddingClient:
    """Build the embedding client from the user's own settings."""

    if not credentials.configured:
        raise LLMConfigurationError(
            "Sağlayıcı anahtarın tanımlı değil. Ayarlar ekranından kendi API anahtarını gir."
        )
    return create_embedding_client(credentials.to_config())


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/auth/register", response_model=SessionToken, status_code=201)
def register(payload: RegisterRequest, users: UserStore = Depends(get_users)) -> SessionToken:
    """Create an account and sign it in straight away."""

    try:
        user = users.register(payload.email, payload.password)
    except AuthError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return SessionToken(token=users.issue_token(user), user=_user_model(user, users))


@router.post("/auth/login", response_model=SessionToken)
def login(payload: LoginRequest, users: UserStore = Depends(get_users)) -> SessionToken:
    """Sign in; a wrong password and an unknown address answer the same way."""

    try:
        user = users.authenticate(payload.email, payload.password)
    except AuthError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    return SessionToken(token=users.issue_token(user), user=_user_model(user, users))


@router.post("/auth/logout", status_code=204)
def logout(
    authorization: str | None = Header(default=None),
    users: UserStore = Depends(get_users),
    user: User = Depends(current_user),
) -> None:
    """Sign out: the token is dropped and the in-memory key with it."""

    if authorization and authorization.lower().startswith("bearer "):
        users.revoke(authorization.split(" ", 1)[1].strip())


@router.get("/auth/me", response_model=UserModel)
def me(user: User = Depends(current_user), users: UserStore = Depends(get_users)) -> UserModel:
    """Who is signed in, and whether their key is currently held."""

    return _user_model(user, users)


@router.get("/provider", response_model=ProviderInfo)
def provider(credentials: ProviderCredentials = Depends(get_credentials)) -> ProviderInfo:
    """Report this user's provider and model -- never the key, not even masked."""

    detail = None if credentials.configured else "API anahtarı girilmedi."
    return ProviderInfo(
        provider=credentials.provider,
        embedding_provider=credentials.provider,
        model=credentials.model or DEFAULT_MODELS.get(credentials.provider, ""),
        embedding_model=credentials.embedding_model
        or DEFAULT_EMBEDDING_MODELS.get(credentials.provider, ""),
        configured=credentials.configured,
        detail=detail,
    )


@router.put("/provider", response_model=ProviderInfo)
def set_provider(
    payload: ProviderUpdate,
    user: User = Depends(current_user),
    users: UserStore = Depends(get_users),
) -> ProviderInfo:
    """Store this user's provider and model, and hold their key in memory.

    The provider and model are persisted (they are not secret).  The key is
    kept in this process only: it is not written to the database, not written
    to a session workspace, and never returned by any endpoint.
    """

    try:
        updated = users.set_provider(
            user,
            provider=payload.provider,
            model=payload.model,
            embedding_model=payload.embedding_model,
            api_key=payload.api_key,
        )
    except AuthError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return provider(users.credentials(updated))


@router.delete("/provider", response_model=ProviderInfo)
def forget_key(
    user: User = Depends(current_user), users: UserStore = Depends(get_users)
) -> ProviderInfo:
    """Forget the key held for this user without touching their model choice."""

    users.clear_key(user)
    return provider(users.credentials(user))


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload(
    files: list[UploadFile] = File(..., description="One or more .csv or .xlsx sources"),
    target_schema: UploadFile = File(..., description="Target schema.yaml"),
    sessions: SessionStore = Depends(get_sessions),
    user: User = Depends(current_user),
) -> UploadResponse:
    """Create a workspace from the uploaded sources and the target schema."""

    session = sessions.create(user)
    try:
        for upload_file in files:
            name = _safe_name(upload_file.filename, "girdi dosyası")
            if Path(name).suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Desteklenmeyen dosya türü: '{name}'. Yalnızca .csv ve .xlsx.",
                )
            await _store(upload_file, session.workspace / name)
            session.inputs.append(name)
        if not session.inputs:
            raise HTTPException(status_code=400, detail="En az bir girdi dosyası gerekli.")

        schema_name = _safe_name(target_schema.filename, "şema dosyası")
        if Path(schema_name).suffix.lower() not in {".yaml", ".yml"}:
            raise HTTPException(status_code=400, detail="Hedef şema .yaml dosyası olmalı.")
        await _store(target_schema, session.schema_path)
        _load_schema(session)
    except HTTPException:
        sessions.discard(session.session_id)
        raise

    return UploadResponse(
        session_id=session.session_id,
        inputs=list(session.inputs),
        target_schema=session.schema_file,
        state=session.state,
    )


@router.post("/analyze/{session_id}", response_model=MappingModel)
def analyze(
    session_id: str,
    payload: AnalyzeRequest = Body(default_factory=AnalyzeRequest),
    sessions: SessionStore = Depends(get_sessions),
    llm: LLMClient = Depends(get_llm_client),
    user: User = Depends(current_user),
) -> MappingModel:
    """Phase 1: profile the sources and propose a plan; merge nothing."""

    session = sessions.get(session_id, user)
    schema = _load_schema(session)
    try:
        profiles = [
            profile_file(path, sheet=_sheet_for(path, payload.sheet)) for path in session.input_paths
        ]
        mapping = match_profiles(profiles, schema, llm)
        dump_mapping(mapping, session.mapping_path)
    except (ProfileError, ContractValidationError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Plan yazılamadı: {error}") from error

    session.state = "analyzed"
    return MappingModel.from_core(mapping)


@router.get("/columns/{session_id}", response_model=ColumnsModel)
def columns(
    session_id: str,
    sheet: str | None = None,
    sessions: SessionStore = Depends(get_sessions),
    user: User = Depends(current_user),
) -> ColumnsModel:
    """The columns a reviewer may pick from, per uploaded file.

    A correction in the UI is a choice among columns that really exist, so the
    dropdown is filled from the profiler -- the same profiles ``analyze`` used.
    No LLM runs here and nothing is written.
    """

    session = sessions.get(session_id, user)
    schema = _load_schema(session)
    try:
        profiles = [
            profile_file(path, sheet=_sheet_for(path, sheet)) for path in session.input_paths
        ]
    except ProfileError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ColumnsModel(
        files=[FileColumnsModel.from_core(profile) for profile in profiles],
        target_columns=[TargetColumnModel.from_core(item) for item in schema.target_columns],
    )


@router.get("/mapping/{session_id}", response_model=MappingModel)
def get_mapping(
    session_id: str,
    sessions: SessionStore = Depends(get_sessions),
    user: User = Depends(current_user),
) -> MappingModel:
    """The current plan, with the counts a review screen shows."""

    return MappingModel.from_core(_load_mapping(sessions.get(session_id, user)))


@router.put("/mapping/{session_id}", response_model=MappingModel)
def put_mapping(
    session_id: str,
    payload: MappingUpdate,
    sessions: SessionStore = Depends(get_sessions),
    user: User = Depends(current_user),
) -> MappingModel:
    """Replace the plan with the user's decisions; the contract validates it."""

    session = sessions.get(session_id, user)
    mapping = payload.to_core()
    try:
        dump_mapping(mapping, session.mapping_path)
    except ContractValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Plan yazılamadı: {error}") from error

    session.state = "analyzed"
    return MappingModel.from_core(mapping)


@router.post("/cluster/{session_id}", response_model=ClustersModel)
def propose_clusters(
    session_id: str,
    payload: ClusterRequest,
    sessions: SessionStore = Depends(get_sessions),
    llm: LLMClient = Depends(get_llm_client),
    embedder: EmbeddingClient = Depends(get_embedding_client),
    user: User = Depends(current_user),
) -> ClustersModel:
    """Phase 1 entity proposal for one approved column; still merges nothing.

    Like ``merger cluster`` this refuses to run while the plan itself is under
    review, and only the distinct values of the chosen column are compared --
    whole rows never reach a provider.
    """

    session = sessions.get(session_id, user)
    schema = _load_schema(session)
    mapping = _load_mapping(session)
    _enforce_review_guard(mapping)

    strategy = payload.strategy or ["prefix"]
    unknown = [item for item in strategy if item not in BLOCKING_STRATEGIES]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz blocking stratejisi: {', '.join(unknown)}. "
            f"Seçenekler: {', '.join(sorted(BLOCKING_STRATEGIES))}.",
        )

    column = next((item for item in schema.target_columns if item.name == payload.column), None)
    if column is None:
        names = ", ".join(item.name for item in schema.target_columns)
        raise HTTPException(
            status_code=400, detail=f"'{payload.column}' hedef şemada yok. Sütunlar: {names}"
        )
    if column.type != "string":
        raise HTTPException(
            status_code=400,
            detail=f"Entity çözümü metin sütunlarında yapılır; '{payload.column}' türü {column.type}.",
        )

    try:
        thresholds = SimilarityThresholds(
            high=DEFAULT_HIGH_THRESHOLD if payload.high is None else payload.high,
            low=DEFAULT_LOW_THRESHOLD if payload.low is None else payload.low,
        )
        result = transform(mapping, session.input_paths, schema, sheet=payload.sheet)
        records = _value_records(result.dataframe[payload.column].to_list())
        blocks = make_blocks(records, strategy=strategy)
        decisions = resolve_pairs(
            blocks,
            embedder=embedder,
            llm=llm if payload.use_llm else None,
            thresholds=thresholds,
        )
        clusters = build_clusters(decisions, target_column=payload.column)
        contract = ClusterContract(clusters=to_cluster_plans(clusters))
        dump_clusters(contract, session.clusters_path)
    except (ContractValidationError, EntityError, TransformError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Küme dosyası yazılamadı: {error}") from error

    return ClustersModel.from_core(contract)


@router.get("/clusters/{session_id}", response_model=ClustersModel)
def get_clusters(
    session_id: str,
    sessions: SessionStore = Depends(get_sessions),
    user: User = Depends(current_user),
) -> ClustersModel:
    """The proposed clusters awaiting approval."""

    return ClustersModel.from_core(_load_clusters(sessions.get(session_id, user)))


@router.put("/clusters/{session_id}", response_model=ClustersModel)
def put_clusters(
    session_id: str,
    payload: ClustersUpdate,
    sessions: SessionStore = Depends(get_sessions),
    user: User = Depends(current_user),
) -> ClustersModel:
    """Store the user's cluster decisions; only ``auto`` ones ever merge."""

    session = sessions.get(session_id, user)
    contract = payload.to_core()
    try:
        dump_clusters(contract.clusters, session.clusters_path)
    except ContractValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Küme dosyası yazılamadı: {error}") from error
    return ClustersModel.from_core(contract)


@router.post("/apply/{session_id}", response_model=ApplyResponse)
def apply(
    session_id: str,
    payload: ApplyRequest = Body(default_factory=ApplyRequest),
    sessions: SessionStore = Depends(get_sessions),
    user: User = Depends(current_user),
) -> ApplyResponse:
    """Phase 2: deterministic merge.

    No LLM client is built here.  Two guards run before anything is written --
    the review guard on the plan and the validator on the transformed data --
    and either one answers ``409`` with nothing written.
    """

    session = sessions.get(session_id, user)
    schema = _load_schema(session)
    mapping = _load_mapping(session)
    _enforce_review_guard(mapping)

    entity: EntitySummary | None = None
    try:
        result = transform(mapping, session.input_paths, schema, sheet=payload.sheet)
        if payload.use_clusters and session.clusters_path.is_file():
            contract = load_clusters(session.clusters_path)
            if contract.clusters:
                dedup = deduplicate(result, contract)
                result = dedup.result
                entity = EntitySummary.from_deduplication(dedup, contract)
            else:
                entity = EntitySummary(target_column="")
        settings = (
            ValidationSettings()
            if payload.null_threshold is None
            else ValidationSettings(null_warning_ratio=payload.null_threshold)
        )
        validation = validate(result, mapping, schema, settings=settings)
        if validation.blocking:
            raise HTTPException(
                status_code=REVIEW_GUARD_STATUS,
                detail=ReviewGuardDetail(
                    error="validation_failed",
                    message=(
                        f"apply durdu: validator {len(validation.errors)} ciddi tutarsızlık buldu. "
                        "Kör birleştirme yapılmaz, hiçbir dosya yazılmadı."
                    ),
                    findings=[FindingModel.from_core(item) for item in validation.errors],
                ).model_dump(),
            )
        fmt = payload.output_format or schema.output.format
        written = write(
            result,
            mapping,
            schema,
            session.workspace / f"merged.{fmt}",
            output_format=fmt,
            report_path=session.workspace / DEFAULT_REPORT_NAME,
            table_name="merged",
            add_provenance=schema.output.add_provenance,
            entity=entity,
            validation=validation,
        )
    except (ContractValidationError, TransformError, ValidationError, WriteError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Çıktı yazılamadı: {error}") from error

    session.merged_name = written.merged_path.name
    session.report_name = written.report_path.name
    session.state = "applied"
    return ApplyResponse.from_core(
        written, validation, skipped_sheets=list(result.skipped_sheets), entity=entity
    )


@router.get("/download/{session_id}/{artifact}")
def download(
    session_id: str,
    artifact: str,
    sessions: SessionStore = Depends(get_sessions),
    user: User = Depends(current_user),
) -> FileResponse:
    """Serve ``merged.<fmt>`` or ``merge_report.xlsx`` of a finished run."""

    if artifact not in {"merged", "report"}:
        raise HTTPException(
            status_code=404, detail=f"Bilinmeyen çıktı: '{artifact}'. 'merged' ya da 'report'."
        )
    session = sessions.get(session_id, user)
    path = session.artifact_path(artifact)
    if path is None:
        raise HTTPException(
            status_code=404, detail="Çıktı henüz üretilmedi; önce /apply çağır."
        )
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.get("/status/{session_id}", response_model=SessionStatus)
def status(
    session_id: str,
    sessions: SessionStore = Depends(get_sessions),
    user: User = Depends(current_user),
) -> SessionStatus:
    """Where this session stands; enough progress for an MVP UI."""

    session = sessions.get(session_id, user)
    counts: StatusCounts | None = None
    if session.mapping_path.is_file():
        try:
            counts = StatusCounts.from_core(load_mapping(session.mapping_path))
        except ContractValidationError:
            counts = None
    artifacts = [name for name in ("merged", "report") if session.artifact_path(name) is not None]
    return SessionStatus(
        session_id=session.session_id,
        state=session.state,
        inputs=list(session.inputs),
        target_schema=session.schema_file,
        counts=counts,
        has_mapping=session.mapping_path.is_file(),
        has_clusters=session.clusters_path.is_file(),
        artifacts=artifacts,
    )


@router.delete("/session/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    sessions: SessionStore = Depends(get_sessions),
    user: User = Depends(current_user),
) -> None:
    """Drop a workspace and its files once the user is done with it."""

    sessions.get(session_id, user)
    sessions.discard(session_id)


def _user_model(user: User, users: UserStore) -> UserModel:
    """The account for a browser: settings yes, key never."""

    credentials = users.credentials(user)
    return UserModel(
        id=user.id,
        email=user.email,
        provider=credentials.provider,
        model=credentials.model or DEFAULT_MODELS.get(credentials.provider, ""),
        embedding_model=credentials.embedding_model
        or DEFAULT_EMBEDDING_MODELS.get(credentials.provider, ""),
        key_configured=credentials.configured,
    )


def _enforce_review_guard(mapping: MappingContract) -> None:
    """Refuse with 409 while any match is still ``review``."""

    pending = pending_reviews(mapping)
    if not pending:
        return
    raise HTTPException(
        status_code=REVIEW_GUARD_STATUS,
        detail=ReviewGuardDetail(
            error="review_pending",
            message=(
                f"{len(pending)} eşleştirme hâlâ onay bekliyor (review). "
                "Kör birleştirme yapılmaz, hiçbir dosya yazılmadı."
            ),
            pending=[
                PendingMatch(
                    target_column=target_column,
                    file=source.file,
                    column=source.column,
                    confidence=source.confidence,
                    reason=source.reason,
                )
                for target_column, source in pending
            ],
        ).model_dump(),
    )


def _load_schema(session: Session) -> SchemaContract:
    try:
        return load_schema(session.schema_path)
    except ContractValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=400, detail=f"Hedef şema okunamadı: {error}") from error


def _load_mapping(session: Session) -> MappingContract:
    if not session.mapping_path.is_file():
        raise HTTPException(status_code=409, detail="Plan yok; önce /analyze çağır.")
    try:
        return load_mapping(session.mapping_path)
    except ContractValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _load_clusters(session: Session):
    if not session.clusters_path.is_file():
        raise HTTPException(status_code=404, detail="Küme dosyası yok; önce /cluster çağır.")
    try:
        return load_clusters(session.clusters_path)
    except ContractValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _value_records(values: list[object]) -> list[dict[str, object]]:
    """Distinct non-empty spellings with how many rows carry each."""

    counts: dict[str, int] = {}
    for value in values:
        if value is None:
            continue
        text = str(value)
        if not text.strip():
            continue
        counts[text] = counts.get(text, 0) + 1
    return [{"name": text, "row_count": count} for text, count in counts.items()]


def _sheet_for(path: Path, sheet: str | None) -> str | None:
    """``sheet`` applies to workbooks only, so a mixed upload still works."""

    return sheet if sheet is not None and path.suffix.lower() == ".xlsx" else None


async def _store(upload_file: UploadFile, destination: Path) -> None:
    """Stream one upload to disk without holding the whole file in memory."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        while chunk := await upload_file.read(1024 * 1024):
            handle.write(chunk)
    await upload_file.close()


def _safe_name(filename: str | None, label: str) -> str:
    """Use the bare file name so an upload can never escape its workspace."""

    name = Path(filename or "").name
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail=f"Geçersiz {label} adı.")
    return name
