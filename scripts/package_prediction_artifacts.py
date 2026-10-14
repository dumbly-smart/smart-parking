"""Package the verified trained prediction models and manifests for delivery."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

DEFAULT_ARTIFACT_DIRECTORY = Path("artifacts/prediction")
DEFAULT_OUTPUT = Path(
    "review_outputs/2026-10-15/ml_results/prediction_model_artifacts.zip"
)
MODEL_TYPES = ("lstm", "gru", "transformer")


def package(artifact_directory: Path, output: Path, results_csv: Path | None = None) -> Path:
    manifests: list[tuple[Path, dict[str, object], Path]] = []
    for model_type in MODEL_TYPES:
        candidates = sorted(
            artifact_directory.glob(f"{model_type}-*.json"),
            key=lambda path: path.stat().st_mtime_ns,
        )
        if not candidates:
            raise FileNotFoundError(f"No {model_type} artifact manifest in {artifact_directory}")
        manifest_path = candidates[-1]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        model_path = artifact_directory / str(manifest["artifact_filename"])
        if not model_path.is_file():
            raise FileNotFoundError(model_path)
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if digest != manifest["artifact_sha256"]:
            raise ValueError(f"SHA-256 mismatch for {model_path}")
        if manifest.get("model") != model_type:
            raise ValueError(f"Expected {model_type} manifest, found {manifest.get('model')}")
        manifests.append((manifest_path, manifest, model_path))

    split_ids = {str(manifest["split_id"]) for _, manifest, _ in manifests}
    if len(split_ids) != 1:
        raise ValueError("Model manifests do not share the same prepared dataset split")

    output.parent.mkdir(parents=True, exist_ok=True)
    checksums = [
        f"{hashlib.sha256(model.read_bytes()).hexdigest()}  models/{model.name}"
        for _, _, model in manifests
    ]
    index = [
        {
            "model": manifest["model"],
            "file": model.name,
            "sha256": manifest["artifact_sha256"],
            "size_bytes": model.stat().st_size,
            "mae": manifest.get("mae"),
            "rmse": manifest.get("rmse"),
            "seed": manifest.get("seed"),
            "split_id": manifest["split_id"],
        }
        for _, manifest, model in manifests
    ]
    readme = (
        "# Smart parking prediction model artifacts\n\n"
        "Genuine TensorFlow/Keras models trained on the documented simulated dataset. "
        "These artifacts are for reproducibility and local inference, not validated "
        "real-world forecasts.\n\n"
        "Each model has a compatible JSON manifest containing preprocessing parameters, "
        "feature schema, configuration, test metrics, versions, and SHA-256. All model "
        "inputs exclude RFID identifiers. Samples are synthetic. Latency is measured "
        "on the training server; no microcontroller inference or power measurement "
        "is included.\n"
    )

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("README.md", readme)
        archive.writestr("SHA256SUMS", "\n".join(checksums) + "\n")
        archive.writestr("artifact_index.json", json.dumps(index, indent=2) + "\n")
        if results_csv is not None and results_csv.is_file():
            archive.write(results_csv, "model_comparison.csv")
        for manifest_path, _, model_path in manifests:
            archive.write(model_path, f"models/{model_path.name}")
            archive.write(manifest_path, f"manifests/{manifest_path.name}")

    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"Invalid ZIP archive: {output}")
        for _, _, model_path in manifests:
            archived = archive.read(f"models/{model_path.name}")
            if hashlib.sha256(archived).hexdigest() != hashlib.sha256(
                model_path.read_bytes()
            ).hexdigest():
                raise ValueError(f"Archived model verification failed: {model_path.name}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-directory", type=Path, default=DEFAULT_ARTIFACT_DIRECTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--results-csv",
        type=Path,
        default=Path("review_outputs/2026-10-15/ml_results/model_comparison.csv"),
    )
    args = parser.parse_args()
    print(package(args.artifact_directory, args.output, args.results_csv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
