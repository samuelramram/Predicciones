# Implementation Plan - Recent Form Adjustment

We will add a "Recent Form" factor to the prediction model to weight teams that are on a winning/losing streak.

## User Review Required
>
> [!IMPORTANT]
> This change introduces a new dynamic variable: **Recent Form**.
> It will adjust the team's attack/defense power by up to +/- 5% based on their last 5 games.
>
> **Logic:**
>
> * Get last 5 games (regardless of tournament) before the match date.
> * Calculate Points Percentage (Pts / 15).
> * If > 60% (9+ points): Boost.
> * If < 30% (4- points): Penalty.

## Proposed Changes

### [New Module] `src/predicciones/improvements.py`

* `calculate_recent_form(stats_df, team_name, match_date, n=5)`:
  * Filters `stats_df` for matches involving `team_name` where `date < match_date`.
  * Sorts by date descending.
  * Takes top N.
  * Calculates points (3 for win, 1 for draw).
  * Returns a multiplier (e.g., 1.03 for good form, 0.97 for bad).

### [Modify] `src/predicciones/config.py`

* Add constants:
  * `FORM_WEIGHT_MAX`: 0.05 (5% max adjustment)
  * `FORM_GAMES_N`: 5

### [Modify] `app/steps/gen_predicciones.py`

* Import `improvements`.
* Inside the match loop:
  * Calculate form factor for Home and Away.
  * Add to `match_adjustments` dictionary (e.g., `home_form_adj`).
  * Log the calculated form factor for transparency.

### [Modify] `src/predicciones/core.py`

* Update `compute_components_and_lambdas` to apply `home_form_adj` and `away_form_adj` to the lambdas.
  * `lambda_home *= adjustments.get('home_form_adj', 1.0)`
  * `lambda_away *= adjustments.get('away_form_adj', 1.0)`

## Verification Plan

### Automated Tests

* Create `tests/test_improvements.py` to test the logic with a small dummy dataframe.
* Run the pipeline `python app/steps/gen_predicciones.py` and check the console output to see "Form Adjustments" being applied (we will add print statements).
