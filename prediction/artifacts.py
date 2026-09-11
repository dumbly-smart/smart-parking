"""Safe publication and validation of trained prediction artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from numbers import Real
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from prediction.models import FEATURE_NAMES, TARGET_NAME, PreparedDataset
from prediction.training import (
    EvaluationMetrics,
    ModelFamily,
    PredictionTrainingError,
    TrainingConfig,
)

MANIFEST_SCHEMA_VERSION = 1


class SavedModel(Protocol):
    def save(self, path: Path) -> None: ...


@dataclass(frozen=True)
class ArtifactManifest:
    schema_version: int
    model: ModelFamily
    artifact_format: str
    artifact_filename: str
    artifact_sha256: str
    split_id: str
    feature_names: tuple[str, ...]
    target_name: str
    slot_count: int
    interval_minutes: int
    lookback_steps: int
    horizon_steps: int
    seed: int
    epochs: int
    batch_size: int
    learning_rate: float
    patience: int
    recurrent_units: int
    transformer_width: int
    transformer_heads: int
    train_examples: int
    validation_examples: int
    test_examples: int
    mae: float
    mse: float
    rmse: float
    inference_latency_ms: float
    latency_repetitions: int
    tensorflow_version: str
    keras_version: str
    completed_at: str

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["model"] = self.model.value
        payload["feature_names"] = list(self.feature_names)
        return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_metrics(metrics: EvaluationMetrics) -> None:
    values = (metrics.mae, metrics.mse, metrics.rmse, metrics.inference_latency_ms)
    if not all(_is_finite_non_negative(value) for value in values):
        raise PredictionTrainingError(
            "invalid_manifest", "artifact metrics must be finite and non-negative"
        )


def _is_finite_non_negative(value: object) -> bool:
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    return math.isfinite(normalized) and normalized >= 0


def _build_manifest(
    artifact_filename: str,
    artifact_sha256: str,
    dataset: PreparedDataset,
    config: TrainingConfig,
    metrics: EvaluationMetrics,
    framework_versions: dict[str, str],
    completed_at: datetime,
) -> ArtifactManifest:
    _validate_metrics(metrics)
    if completed_at.tzinfo is None or completed_at.utcoffset() is None:
        raise PredictionTrainingError("invalid_manifest", "completion time must be timezone-aware")
    return ArtifactManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        model=config.model,
        artifact_format="keras-v3",
        artifact_filename=artifact_filename,
        artifact_sha256=artifact_sha256,
        split_id=dataset.split_id,
        feature_names=dataset.feature_names,
        target_name=dataset.target_name,
        slot_count=dataset.slot_count,
        interval_minutes=dataset.config.interval_minutes,
        lookback_steps=dataset.config.lookback_steps,
        horizon_steps=dataset.config.horizon_steps,
        seed=config.seed,
        epochs=config.epochs,
        batch_size=config.batch_size,
        learning_rate=float(config.learning_rate),
        patience=config.patience,
        recurrent_units=config.recurrent_units,
        transformer_width=config.transformer_width,
        transformer_heads=config.transformer_heads,
        train_examples=dataset.train.inputs.shape[0],
        validation_examples=dataset.validation.inputs.shape[0],
        test_examples=dataset.test.inputs.shape[0],
        mae=metrics.mae,
        mse=metrics.mse,
        rmse=metrics.rmse,
        inference_latency_ms=metrics.inference_latency_ms,
        latency_repetitions=config.latency_repetitions,
        tensorflow_version=framework_versions.get("tensorflow", "unavailable"),
        keras_version=framework_versions.get("keras", "unavailable"),
        completed_at=completed_at.astimezone(UTC).isoformat(),
    )


def publish_artifact(
    model: SavedModel,
    dataset: PreparedDataset,
    config: TrainingConfig,
    metrics: EvaluationMetrics,
    artifact_directory: Path,
    *,
    framework_versions: dict[str, str] | None = None,
    completed_at: datetime | None = None,
) -> Path:
    """Publish model bytes before atomically exposing their manifest."""
    directory = Path(artifact_directory)
    staging: Path | None = None
    manifest_staging: Path | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        staging = directory / f".{uuid4().hex}.staging.keras"
        model.save(staging)
        if not staging.is_file():
            raise OSError("model save did not create a file artifact")
        digest = _sha256_file(staging)
        artifact = directory / f"{digest}.keras"
        if artifact.exists() and _sha256_file(artifact) == digest:
            staging.unlink()
        else:
            os.replace(staging, artifact)
        manifest = _build_manifest(
            artifact.name,
            digest,
            dataset,
            config,
            metrics,
            framework_versions or {},
            completed_at or datetime.now(UTC),
        )
        manifest_name = f"{config.model.value}-{dataset.split_id[:12]}-{config.seed}.json"
        manifest_path = directory / manifest_name
        manifest_staging = directory / f".{manifest_path.name}.{uuid4().hex}.tmp"
        encoded = json.dumps(manifest.as_dict(), sort_keys=True, separators=(",", ":"))
        with manifest_staging.open("x", encoding="utf-8") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(manifest_staging, manifest_path)
        return manifest_path
    except PredictionTrainingError:
        raise
    except Exception as error:
        raise PredictionTrainingError(
            "artifact_write_failed", "failed to publish prediction artifact"
        ) from error
    finally:
        for temporary in (staging, manifest_staging):
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _manifest_from_payload(payload: object) -> ArtifactManifest:
    if not isinstance(payload, dict):
        raise PredictionTrainingError("invalid_manifest", "manifest must be a JSON object")
    try:
        values = dict(payload)
        values["model"] = ModelFamily(values["model"])
        values["feature_names"] = tuple(values["feature_names"])
        manifest = ArtifactManifest(**values)
    except (KeyError, TypeError, ValueError) as error:
        raise PredictionTrainingError("invalid_manifest", "manifest schema is invalid") from error
    if (
        not isinstance(manifest.schema_version, int)
        or isinstance(manifest.schema_version, bool)
        or manifest.schema_version != MANIFEST_SCHEMA_VERSION
    ):
        raise PredictionTrainingError("invalid_manifest", "manifest schema version is unsupported")
    _validate_metrics(
        EvaluationMetrics(
            manifest.mae,
            manifest.mse,
            manifest.rmse,
            manifest.inference_latency_ms,
        )
    )
    try:
        completed = datetime.fromisoformat(manifest.completed_at)
    except (TypeError, ValueError) as error:
        raise PredictionTrainingError("invalid_manifest", "completion time is invalid") from error
    if completed.tzinfo is None or completed.utcoffset() != timedelta(0):
        raise PredictionTrainingError("invalid_manifest", "completion time must be UTC")
    _validate_manifest_contract(manifest)
    return manifest


def _validate_manifest_contract(manifest: ArtifactManifest) -> None:
    hexadecimal = frozenset("0123456789abcdef")
    valid_artifact_hash = (
        isinstance(manifest.artifact_sha256, str)
        and len(manifest.artifact_sha256) == 64
        and set(manifest.artifact_sha256) <= hexadecimal
    )
    valid_split_id = (
        isinstance(manifest.split_id, str)
        and len(manifest.split_id) == 64
        and set(manifest.split_id) <= hexadecimal
    )
    if (
        manifest.artifact_format != "keras-v3"
        or not isinstance(manifest.artifact_filename, str)
        or not manifest.artifact_filename
        or not valid_artifact_hash
        or not valid_split_id
        or manifest.feature_names != FEATURE_NAMES
        or manifest.target_name != TARGET_NAME
        or manifest.interval_minutes != 5
        or manifest.lookback_steps != 12
        or manifest.horizon_steps != 1
    ):
        raise PredictionTrainingError(
            "invalid_manifest", "manifest does not match the prediction contract"
        )
    positive_counts = (
        manifest.slot_count,
        manifest.train_examples,
        manifest.validation_examples,
        manifest.test_examples,
        manifest.latency_repetitions,
    )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in positive_counts
    ):
        raise PredictionTrainingError(
            "invalid_manifest", "manifest counts must be positive integers"
        )
    if not all(
        isinstance(value, str) and value
        for value in (manifest.tensorflow_version, manifest.keras_version)
    ):
        raise PredictionTrainingError(
            "invalid_manifest", "manifest framework versions must be non-empty strings"
        )
    try:
        TrainingConfig(
            model=manifest.model,
            seed=manifest.seed,
            epochs=manifest.epochs,
            batch_size=manifest.batch_size,
            learning_rate=manifest.learning_rate,
            patience=manifest.patience,
            recurrent_units=manifest.recurrent_units,
            transformer_width=manifest.transformer_width,
            transformer_heads=manifest.transformer_heads,
            latency_repetitions=manifest.latency_repetitions,
        )
    except PredictionTrainingError as error:
        raise PredictionTrainingError(
            "invalid_manifest", "manifest training configuration is invalid"
        ) from error


def load_manifest(
    manifest_path: Path, *, expected_dataset: PreparedDataset | None = None
) -> ArtifactManifest:
    """Validate manifest identity and artifact bytes without importing TensorFlow."""
    path = Path(manifest_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PredictionTrainingError("invalid_manifest", "manifest cannot be read") from error
    manifest = _manifest_from_payload(payload)
    filename = Path(manifest.artifact_filename)
    if filename.name != manifest.artifact_filename or filename.suffix != ".keras":
        raise PredictionTrainingError(
            "invalid_manifest", "artifact filename must be a safe basename"
        )
    artifact = path.parent / filename
    try:
        if artifact.resolve().parent != path.parent.resolve():
            raise PredictionTrainingError("invalid_manifest", "artifact path escapes its directory")
        digest = _sha256_file(artifact)
    except PredictionTrainingError:
        raise
    except OSError as error:
        raise PredictionTrainingError("artifact_mismatch", "artifact cannot be read") from error
    if digest != manifest.artifact_sha256 or artifact.name != f"{digest}.keras":
        raise PredictionTrainingError(
            "artifact_mismatch", "artifact digest does not match manifest"
        )
    if expected_dataset is not None and (
        manifest.split_id != expected_dataset.split_id
        or manifest.feature_names != expected_dataset.feature_names
        or manifest.target_name != expected_dataset.target_name
        or manifest.slot_count != expected_dataset.slot_count
        or manifest.interval_minutes != expected_dataset.config.interval_minutes
        or manifest.lookback_steps != expected_dataset.config.lookback_steps
        or manifest.horizon_steps != expected_dataset.config.horizon_steps
        or manifest.train_examples != expected_dataset.train.inputs.shape[0]
        or manifest.validation_examples != expected_dataset.validation.inputs.shape[0]
        or manifest.test_examples != expected_dataset.test.inputs.shape[0]
    ):
        raise PredictionTrainingError(
            "invalid_manifest", "manifest is incompatible with the expected prepared dataset"
        )
    return manifest
