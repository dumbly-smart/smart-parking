"""Lazy TensorFlow builders for comparable occupancy forecasters."""

import random
from typing import Any

import numpy as np

from prediction.training import ModelFamily, PredictionTrainingError, TrainingConfig


def _load_tensorflow() -> Any | None:
    try:
        import tensorflow as tf
    except ImportError:
        return None
    return tf


def _require_tensorflow() -> Any:
    tensorflow = _load_tensorflow()
    if tensorflow is None:
        raise PredictionTrainingError(
            "missing_ml_dependency",
            "TensorFlow is required for training; install it with pip install -e '.[ml]'",
        )
    return tensorflow


def configure_determinism(config: TrainingConfig, tensorflow: Any | None = None) -> Any:
    """Seed every training RNG and request deterministic TensorFlow operations."""
    tf = tensorflow if tensorflow is not None else _require_tensorflow()
    random.seed(config.seed)
    np.random.seed(config.seed)
    tf.keras.utils.set_random_seed(config.seed)
    tf.config.experimental.enable_op_determinism()
    return tf


def _recurrent_model(tf: Any, config: TrainingConfig, input_shape: tuple[int, int]) -> Any:
    inputs = tf.keras.Input(shape=input_shape)
    recurrent = tf.keras.layers.LSTM if config.model is ModelFamily.LSTM else tf.keras.layers.GRU
    encoded = recurrent(config.recurrent_units)(inputs)
    outputs = tf.keras.layers.Dense(1, activation="sigmoid")(encoded)
    return tf.keras.Model(inputs, outputs, name=f"occupancy_{config.model.value}")


def _transformer_model(tf: Any, config: TrainingConfig, input_shape: tuple[int, int]) -> Any:
    lookback_steps, _ = input_shape
    inputs = tf.keras.Input(shape=input_shape)
    projected = tf.keras.layers.Dense(config.transformer_width)(inputs)
    positions = tf.keras.ops.arange(0, lookback_steps, 1)
    position_values = tf.keras.layers.Embedding(
        input_dim=lookback_steps,
        output_dim=config.transformer_width,
        name="position_embedding",
    )(positions)
    encoded = tf.keras.layers.Add()([projected, position_values])
    attended = tf.keras.layers.MultiHeadAttention(
        num_heads=config.transformer_heads,
        key_dim=config.transformer_width // config.transformer_heads,
    )(encoded, encoded)
    encoded = tf.keras.layers.LayerNormalization()(encoded + attended)
    feed_forward = tf.keras.layers.Dense(config.transformer_width * 2, activation="relu")(encoded)
    feed_forward = tf.keras.layers.Dense(config.transformer_width)(feed_forward)
    encoded = tf.keras.layers.LayerNormalization()(encoded + feed_forward)
    pooled = tf.keras.layers.GlobalAveragePooling1D()(encoded)
    outputs = tf.keras.layers.Dense(1, activation="sigmoid")(pooled)
    return tf.keras.Model(inputs, outputs, name="occupancy_transformer")


def build_model(config: TrainingConfig, input_shape: tuple[int, int]) -> Any:
    """Build and compile one model under the shared regression contract."""
    if (
        not isinstance(input_shape, tuple)
        or len(input_shape) != 2
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in input_shape
        )
    ):
        raise PredictionTrainingError(
            "incompatible_dataset",
            "model input shape must contain positive lookback and feature sizes",
        )
    tf = configure_determinism(config)
    if config.model is ModelFamily.TRANSFORMER:
        model = _transformer_model(tf, config, input_shape)
    else:
        model = _recurrent_model(tf, config, input_shape)
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=config.learning_rate),
        loss="mse",
    )
    return model
