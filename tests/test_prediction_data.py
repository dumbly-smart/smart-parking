from datetime import UTC, datetime

import numpy as np
import pytest

from prediction.models import (
    CONTINUOUS_FEATURE_NAMES,
    FEATURE_NAMES,
    PredictionDataError,
    PreparedDataset,
    PreparedSplit,
    PreprocessingConfig,
    ScalerMetadata,
)


def test_preprocessing_config_has_approved_defaults() -> None:
    config = PreprocessingConfig()

    assert config.interval_minutes == 5
    assert config.lookback_steps == 12
    assert config.horizon_steps == 1
    assert config.train_fraction == 0.70
    assert config.validation_fraction == 0.15
    assert config.max_carry_intervals == 3


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"interval_minutes": 0}, "invalid_config"),
        ({"lookback_steps": 0}, "invalid_config"),
        ({"horizon_steps": 0}, "invalid_config"),
        ({"train_fraction": 0.9, "validation_fraction": 0.2}, "invalid_config"),
        ({"max_carry_intervals": -1}, "invalid_config"),
    ],
)
def test_preprocessing_config_rejects_invalid_values(
    overrides: dict[str, object], code: str
) -> None:
    with pytest.raises(PredictionDataError) as raised:
        PreprocessingConfig(**overrides)

    assert raised.value.code == code


def test_prepared_split_copies_and_freezes_arrays() -> None:
    source_inputs = np.zeros((2, 12, len(FEATURE_NAMES)), dtype=np.float64)
    source_targets = np.array([0.2, 0.4], dtype=np.float64)
    split = PreparedSplit(
        inputs=source_inputs,
        targets=source_targets,
        target_timestamps=(
            datetime(2026, 9, 4, 10, tzinfo=UTC),
            datetime(2026, 9, 4, 10, 5, tzinfo=UTC),
        ),
    )
    source_inputs[0, 0, 0] = 99

    assert split.inputs[0, 0, 0] == 0
    assert not split.inputs.flags.writeable
    assert not split.targets.flags.writeable
    with pytest.raises(ValueError):
        split.inputs[0, 0, 0] = 1


def _prepared_dataset(
    *,
    train_timestamps: tuple[datetime, ...] = (datetime(2026, 9, 4, 10, tzinfo=UTC),),
    validation_timestamps: tuple[datetime, ...] = (datetime(2026, 9, 4, 11, tzinfo=UTC),),
    test_timestamps: tuple[datetime, ...] = (datetime(2026, 9, 4, 12, tzinfo=UTC),),
    scaler_indices: tuple[int, ...] | None = None,
) -> PreparedDataset:
    values = np.zeros((1, 12, len(FEATURE_NAMES)), dtype=np.float64)

    def split(timestamps: tuple[datetime, ...]) -> PreparedSplit:
        return PreparedSplit(values, np.zeros(1), timestamps)

    indices = (
        tuple(FEATURE_NAMES.index(name) for name in CONTINUOUS_FEATURE_NAMES)
        if scaler_indices is None
        else scaler_indices
    )
    return PreparedDataset(
        feature_names=FEATURE_NAMES,
        target_name="occupancy_ratio",
        train=split(train_timestamps),
        validation=split(validation_timestamps),
        test=split(test_timestamps),
        scaler=ScalerMetadata(indices, tuple(0.0 for _ in indices), tuple(1.0 for _ in indices)),
        split_id="split",
        source_started_at=datetime(2026, 9, 4, 9, tzinfo=UTC),
        source_ended_at=datetime(2026, 9, 4, 13, tzinfo=UTC),
        train_ended_at=datetime(2026, 9, 4, 10, 30, tzinfo=UTC),
        validation_ended_at=datetime(2026, 9, 4, 11, 30, tzinfo=UTC),
        config=PreprocessingConfig(),
        slot_count=10,
    )


@pytest.mark.parametrize(
    ("train_timestamps", "validation_timestamps", "test_timestamps"),
    [
        (
            (datetime(2026, 9, 4, 11, tzinfo=UTC),),
            (datetime(2026, 9, 4, 10, tzinfo=UTC),),
            (datetime(2026, 9, 4, 12, tzinfo=UTC),),
        ),
        (
            (datetime(2026, 9, 4, 10, 45, tzinfo=UTC),),
            (datetime(2026, 9, 4, 11, tzinfo=UTC),),
            (datetime(2026, 9, 4, 12, tzinfo=UTC),),
        ),
        (
            (datetime(2026, 9, 4, 10, tzinfo=UTC),),
            (datetime(2026, 9, 4, 11, tzinfo=UTC),),
            (datetime(2026, 9, 4, 14, tzinfo=UTC),),
        ),
    ],
)
def test_prepared_dataset_rejects_overlapping_or_out_of_bound_timestamps(
    train_timestamps: tuple[datetime, ...],
    validation_timestamps: tuple[datetime, ...],
    test_timestamps: tuple[datetime, ...],
) -> None:
    with pytest.raises(PredictionDataError) as raised:
        _prepared_dataset(
            train_timestamps=train_timestamps,
            validation_timestamps=validation_timestamps,
            test_timestamps=test_timestamps,
        )

    assert raised.value.code == "invalid_dataset"


@pytest.mark.parametrize(
    "scaler_indices",
    [
        (0,),
        tuple(FEATURE_NAMES.index(name) for name in CONTINUOUS_FEATURE_NAMES[:-1]),
        (
            *tuple(FEATURE_NAMES.index(name) for name in CONTINUOUS_FEATURE_NAMES),
            FEATURE_NAMES.index("holiday"),
        ),
    ],
)
def test_prepared_dataset_requires_exact_continuous_scaler_features(
    scaler_indices: tuple[int, ...],
) -> None:
    with pytest.raises(PredictionDataError) as raised:
        _prepared_dataset(scaler_indices=scaler_indices)

    assert raised.value.code == "invalid_dataset"
