# Projection File Schema — v1

**Status:** Draft (Phase 0)
**Contract:** Python writes this file; C# reads it. Neither side needs to know the other's internals.

---

## File

`projections_<year>_v<N>.parquet` (+ `.csv` mirror for inspection)

Example: `projections_2026_v1.parquet`

Saved to `data/processed/` locally; published as a GitHub Release asset for distribution.

---

## Columns

| Column | Type | Notes |
|--------|------|-------|
| `player_id` | string | GSIS ID (nflverse). Primary key for matching across seasons. |
| `player_name` | string | Display name (e.g. "CeeDee Lamb"). |
| `position` | string | One of: `QB`, `RB`, `WR`, `TE`. |
| `team` | string | Most recent team abbreviation (nflverse format). |
| `projected_ppr` | float | Projected full-season PPR fantasy points. |
| `projected_half` | float | Projected half-PPR points. *(v1: derived as `projected_ppr - 0.5 * receptions_proj`; deferred until component-stat model exists)* |
| `projected_standard` | float | Projected standard-scoring points. *(same caveat as half)* |
| `games` | int | Games played in most recent season (from training data). |
| `games_delta` | int | Year-over-year change in games played. |
| `position_rmse` | float | Walk-forward RMSE for this position's model (QB 78.68, RB 62.10, WR 54.87, TE 39.25 as of v1). Used for ceiling/floor in C#. |
| `underdog_adp` | float | Underdog ADP (source: 4for4 CSV). `NaN` if player not listed. |
| `injury_flag` | bool | True if `games < 13` AND `games_delta < -5`. Signals a player returning from significant missed time. |
| `market_estimate` | bool | True if projection is ADP-derived fallback (no NFL history — rookies, etc.). *(set by `src/draft/market_fallback.py` in the advisor table: ADP-derived projection for players the model cannot score; synthetic `market:<name>` IDs when no GSIS ID exists)* |
| `schema_version` | string | Literal `"v1"`. Allows C# to validate compatibility on load. |

---

## Constraints

- One row per player. No duplicates on `player_id`.
- Positions limited to QB / RB / WR / TE. K and DST excluded.
- Players with fewer than 4 games in their most recent season are excluded (same threshold as training data filter).
- `projected_ppr` is always present and non-null. Other projected formats may be NaN in v1 if the component model is not yet built.
- `underdog_adp` is NaN for players not in the ADP source; C# treats NaN as unranked (place at the end of the pool).

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v1 | 2026-10 | Initial schema. PPR projections only; half/standard as derived fields pending component model. |

---

## Future Fields (deferred)

- `adp_source` — which ADP source(s) contributed (for v2 consensus ADP)
- `projected_receptions` — needed for accurate half/standard derivation
- `team_context_tier` — depth-chart rank within team (Phase 3 feature work)
