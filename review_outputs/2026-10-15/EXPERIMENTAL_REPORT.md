# Experimental report — Smart Parking review

Generated from local executed outputs. All dataset observations are synthetic simulations.

## Dataset

The exported feature timeline contains 4,032 five-minute buckets and 27 model features over 2026-08-01T00:00:00Z to 2026-08-14T23:55:00Z. The raw export contains 6,274 privacy-safe source records. Seed: `20260908`.
Public, version-pinned dataset ZIP: [download from GitHub](https://github.com/dumbly-smart/smart-parking/raw/5b480d1/review_outputs/2026-10-15/dataset/parking_dataset.zip) (publicly accessible). Google Drive mirror: [download](https://drive.google.com/file/d/1-bgCGNuCgbhWTbKyxnMlLpOQH1s3lxSZ/view?usp=drivesdk) (read-only access for `vit.ac.in`).

Training sequences: {'test': 594, 'train': 2810, 'validation': 592}. Continuous variables are standardized using training data only. The unchanged prediction contract uses a 12-bucket lookback and next-bucket target.

The generator is simulated. It does not represent measured weather, site demand, camera accuracy, physical waiting times, or parking throughput.

## Prediction experiments

All models share the same prepared dataset and untouched chronological test split. The persistence baseline predicts that the most recent occupancy ratio continues for one interval. Latency is measured per prediction in this server process.

| Model | MAE | MSE | RMSE | Median latency (ms) | Model size (bytes) |
| --- | ---: | ---: | ---: | ---: | ---: |
| persistence_baseline | 0.120875 | 0.028620 | 0.169173 | 0.000015 | N/A |
| lstm | 0.104062 | 0.016818 | 0.129685 | 0.245910 | 60481 |
| gru | 0.098055 | 0.013891 | 0.117862 | 0.223783 | 52615 |
| transformer | 0.109173 | 0.018098 | 0.134531 | 0.232451 | 110684 |

Lowest measured MAE: **gru** (0.098055). This ranking applies to the generated data and this execution environment only.

Artifacts were reloaded and hash/manifest checked. The configured `/api/prediction` endpoint returned neural predictions without fallback for each family. These are server-side results; no ESP32 or other microcontroller inference was measured.
Model ZIP with weights, manifests, results, and checksums: [download](https://drive.google.com/file/d/1I1ECMeYlJT9-oop4Bh-Qedgti9Kds6lj/view?usp=drivesdk) (read-only access for `vit.ac.in`).

## Allocation optimizer experiments

The benchmark ran 120 distinct scenarios with 3 seeded repetitions. It used the configured weights `{"congestion": 0.3, "distance": 0.35, "fairness": 0.15, "waiting": 0.2}` and 30 iterations per heuristic. 300 full-capacity attempts were recorded separately (60 per policy/reference in this run).

| Algorithm/reference | Successful runs | Success rate | Mean cost | Runtime mean / median / SD (ms) | Mean optimality gap | Invalid assignments |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| first_available | 300 | 0.833 | 0.487125 | 0.000353 / 0.000331 / 0.000218 | 0.108931 | 0 |
| exhaustive_optimum | 300 | 0.833 | 0.378194 | 0.015192 / 0.014984 / 0.006103 | 0.000000 | 0 |
| GA | 300 | 0.833 | 0.378194 | 0.832316 / 0.807225 / 0.075862 | 0.000000 | 0 |
| PSO | 300 | 0.833 | 0.426458 | 1.184595 / 1.157470 / 0.166947 | 0.048264 | 0 |
| ACO | 300 | 0.833 | 0.381779 | 1.182608 / 1.162547 / 0.222801 | 0.003586 | 0 |

Lowest mean objective cost among successful policies: **exhaustive_optimum** (0.378194). Exhaustive enumeration is the exact single-slot optimum for each small scenario; first-available is a simple deterministic selection policy, not FCFS queue scheduling.

These runs measure a simulated one-slot objective and Python software runtime. They do not measure physical parking throughput or real-world waiting time. Heuristic search is not expected to beat exact enumeration for five candidates.

## Reproduction and outputs

Run `make review` to regenerate the dataset, ML artifacts and metrics, verified model ZIP, optimizer tables and figures, and this report. See `REPRODUCE.md` for individual commands.
