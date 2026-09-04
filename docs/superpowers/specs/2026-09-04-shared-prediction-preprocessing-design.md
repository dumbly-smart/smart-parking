# Shared Prediction Preprocessing Design

## Scope

This slice establishes one deterministic, model-neutral preprocessing pipeline
for the prediction comparison milestone. It converts persisted parking context,
session, allocation, and optimizer data into identical chronological
train/validation/test datasets for future LSTM, GRU, and temporal Transformer
trainers.

The forecast target is the total occupied-slot count for the next five-minute
interval. Internally, occupancy is normalized by the configured slot count so
the dataset contract remains valid when deployments use different numbers of
slots. The prepared prediction converts back to a count at the service
boundary in a later slice.

This slice does not implement neural-network architectures, training scripts,
synthetic demo-data commands, prediction persistence, benchmark or runtime API
endpoints, or dashboard behavior.

## Architecture

The implementation has three focused boundaries:

- `prediction/models.py` defines immutable preprocessing configuration, source
  bucket, prepared split, scaler metadata, and dataset contracts, along with
  explicit validation errors.
- `prediction/data.py` reads persisted source records, aggregates them into
  regular five-minute buckets, engineers shared features, constructs
  twelve-step sequences, fits training-only scaling metadata, and creates one
  chronological 70/15/15 split.
- `backend/app/db.py` exposes only the ordered, read-only source records needed
  by preprocessing. SQL and SQLite row details do not leak into the prediction
  package.

Every future predictor will accept the same prepared dataset object. Model
trainers must not perform private resampling, feature engineering, scaling, or
splitting.

## Forecast Contract

Each example uses the previous twelve five-minute buckets, representing one
hour of observed history, to predict occupancy in the immediately following
five-minute bucket. The target is a normalized occupancy ratio in the inclusive
range `[0, 1]`; consumers can multiply it by the configured slot count and
apply their documented rounding policy when they need a count.

The regular bucket timeline is split chronologically before examples are
constructed:

- the earliest 70 percent of buckets are training data;
- the following 15 percent are validation data;
- the final 15 percent are test data.

For `N` resolved buckets, the training boundary is `floor(0.70 * N)` and the
validation boundary adds `floor(0.15 * N)`; the test partition receives the
remainder. Sequences are constructed independently within each partition. No
input window may cross a split boundary, and every partition must contain at
least one complete lookback-and-target example.

Continuous features are standardized with training-only means and population
standard deviations. A zero-variance training feature uses a scale of one.
Validation and test data reuse this metadata unchanged. Boolean, one-hot, and
cyclic features retain their natural bounded values. The occupancy-ratio target
already has a stable `[0, 1]` meaning and is not rescaled.

A stable `split_id` hashes the preprocessing configuration, ordered feature
contract, source time range, and exact chronological split boundaries. Future
persisted predictor runs will use this identifier to demonstrate that LSTM,
GRU, and Transformer results came from the same prepared data.

## Five-Minute Bucket Features

Each regular bucket contains the following model inputs:

- normalized occupancy ratio;
- occupancy change from the preceding resolved bucket;
- trailing 15-minute and 60-minute occupancy averages;
- cyclic hour-of-day sine and cosine values;
- cyclic day-of-week sine and cosine values;
- deterministic weather-category encoding;
- holiday and scheduled-event flags;
- entry count, exit count, and allocation count;
- active-session count and unique-vehicle count;
- returning-vehicle rate;
- mean assigned walking distance;
- mean congestion contribution;
- mean optimizer fairness penalty; and
- an allocation-present flag distinguishing a neutral aggregate from an
  observed zero value.

The existing context samples provide occupancy, weather, holiday, event, and
sample timestamps. Parking sessions provide entry and exit activity, active
session counts, and vehicle recurrence. Allocations and their linked optimizer
runs provide allocation counts and normalized objective values. Objective
components are decoded from the stored optimizer result rather than
recalculated with current configuration.

Weather uses a fixed, documented vocabulary with an `other` category so its
feature shape never depends on validation or test values. Cyclic encodings are
derived from timezone-aware timestamps after normalization to UTC.

## RFID Privacy and Fairness

RFID identity remains available to the parking lifecycle and allocation
optimizer. The optimizer can use vehicle-linked history to enforce its fairness
policy before persisting an allocation.

Prediction preprocessing uses vehicle identity only inside the aggregation
boundary to calculate unique-vehicle counts and a returning-vehicle rate. Raw
RFID values and stable per-vehicle identifiers never appear in the prepared
feature matrix, scaler metadata, split identifier, logs, or validation errors.
Walking-distance, congestion, and fairness signals enter the prediction model
as bucket-level aggregates. Removing raw identity from prediction therefore
does not change allocation fairness behavior.

## Missing Data and Validation

Preprocessing first establishes a regular UTC five-minute grid over the usable
source range.

- Occupancy and weather may carry forward across at most three missing buckets
  by default (15 minutes); the limit is part of preprocessing configuration.
- Entry, exit, and allocation counts are zero when no corresponding event
  occurred in a bucket.
- Buckets without allocations use neutral aggregate values and set
  `allocation_present` to false.
- Candidate sequences crossing an unresolved or over-limit gap are excluded.
- Rolling features use only the current and earlier buckets.

The pipeline raises typed validation errors for malformed or non-timezone-aware
timestamps, occupancy counts outside the configured slot range, invalid flags,
unknown or malformed persisted optimizer metadata, non-finite numeric values,
non-positive slot counts, invalid split or window configuration, insufficient
history, and any split that would be empty.

Records are ordered deterministically. Equal timestamps use stable database
identifiers as tie-breakers, and repeated preprocessing over unchanged data and
configuration produces byte-equivalent arrays and the same `split_id`.

## Dataset Contract

The prepared dataset contains:

- the ordered feature names and target name;
- three immutable splits, each with input sequences, targets, and target
  timestamps;
- the five-minute interval, twelve-step lookback, one-step horizon, slot count,
  and chronological split ratios;
- training-derived scaling metadata;
- the source time range and split boundaries; and
- the stable `split_id`.

Arrays use explicit floating-point dtypes and are read-only after construction.
The dataset validates consistent example counts, sequence shapes, feature
widths, chronological timestamps, and finite values at its boundary.

## Testing

`tests/test_prediction_data.py` will use small deterministic SQLite fixtures to
cover:

- five-minute aggregation and the complete ordered feature contract;
- dynamic slot-count occupancy normalization;
- time, weather, holiday, event, session, walking-distance, congestion, and
  fairness features;
- unique and returning vehicle aggregation without RFID exposure;
- rolling features that never use future buckets;
- short-gap carry-forward and exclusion of windows crossing long gaps;
- chronological 70/15/15 splits with no boundary-crossing sequence;
- scalers fitted only on training data;
- deterministic arrays and `split_id` values;
- stable handling of equal timestamps; and
- every validation failure described above.

Focused prediction tests, the complete test suite, Ruff, and
`git diff --check` must pass before the implementation slice is considered
complete.

## Documentation and Follow-On Work

The README will document the five-minute forecast contract, shared feature
set, privacy boundary, and why runtime prediction can respond immediately while
training remains offline. `progress.md` will record the verified preprocessing
slice without marking the full prediction-comparison milestone complete.

The next slices will add a deterministic demo-data generator, model builders
and training entry points, shared metric and latency evaluation, atomic
`prediction_runs` persistence, comparison and runtime APIs, and deterministic
fallback prediction. Each will consume this preprocessing contract rather than
reimplementing it.
