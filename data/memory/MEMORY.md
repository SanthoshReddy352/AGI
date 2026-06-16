# FRIDAY Memory

_Long-term working notes the agent keeps for itself._

- (2026-06-07) Created skill "create-production-dataset" — a DataDoom spec authoring skill for generating production-grade synthetic datasets. Reads user's sector/problem statement, designs features/causal DAG/difficulty/failures, writes a spec, runs datadoom validate + run, and exports a full bundle (clean, injected, metadata, splits in CSV/JSON/Parquet).