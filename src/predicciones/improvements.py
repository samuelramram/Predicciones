import pandas as pd
import numpy as np
import src.predicciones.config as config
import src.predicciones.core as dl


def _get_team_matches(stats_df, team_name, match_date, n):
    """Helper: returns last N matches for a team before match_date, sorted recent-first."""
    df = stats_df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df['date']):
        df['date'] = pd.to_datetime(df['date'], dayfirst=True)
    if 'home_canon' not in df.columns:
        df['home_canon'] = df['home_team'].apply(dl.canonical_team_name)
    if 'away_canon' not in df.columns:
        df['away_canon'] = df['away_team'].apply(dl.canonical_team_name)
    match_date = pd.to_datetime(match_date)
    return df[
        ((df['home_canon'] == team_name) | (df['away_canon'] == team_name)) &
        (df['date'] < match_date)
    ].sort_values('date', ascending=False).head(n)


def _match_points(row, team_name):
    """Returns 3/1/0 points for a team in a given match row."""
    is_home = (row['home_canon'] == team_name)
    gf = row['home_goals'] if is_home else row['away_goals']
    ga = row['away_goals'] if is_home else row['home_goals']
    return 3 if gf > ga else (1 if gf == ga else 0)

def calculate_momentum_direction(stats_df, team_name, match_date, n=5,
                                 threshold=0.20, bonus_max=0.02):
    """
    Detecta si el equipo está acelerando o desacelerando comparando
    el ritmo de puntos de los últimos 2 partidos vs los 3 anteriores (de los últimos 5).

    Returns: (direction_multiplier, info_dict)
      direction_multiplier ≈ 1.0 ± bonus_max
    """
    team_matches = _get_team_matches(stats_df, team_name, match_date, n)

    if len(team_matches) < n:
        return 1.0, {"status": "insufficient_data", "games": len(team_matches)}

    rows = list(team_matches.iterrows())
    recent_pts = sum(_match_points(row, team_name) for _, row in rows[:2])
    prior_pts  = sum(_match_points(row, team_name) for _, row in rows[2:5])

    recent_pct = recent_pts / 6.0   # max 6 pts en 2 partidos
    prior_pct  = prior_pts  / 9.0   # max 9 pts en 3 partidos
    direction  = recent_pct - prior_pct

    multiplier = 1.0
    if direction > threshold:
        multiplier = 1.0 + bonus_max * min(direction / 0.40, 1.0)
    elif direction < -threshold:
        multiplier = 1.0 - bonus_max * min(-direction / 0.40, 1.0)

    return multiplier, {
        "status": "calculated",
        "recent_2_pts": recent_pts,
        "prior_3_pts": prior_pts,
        "recent_pct": recent_pct,
        "prior_pct": prior_pct,
        "direction": direction,
        "multiplier": multiplier,
    }


def calculate_home_crisis_factor(stats_df, team_name, match_date, n_home=4,
                                  crisis_threshold=1, crisis_penalty=0.92,
                                  stronghold_bonus=1.04):
    """
    Detecta si el equipo LOCAL está en crisis o en racha como local.
    Revisa los últimos n_home partidos jugados DE LOCAL antes de match_date.

    Crisis     : ≤ crisis_threshold victorias locales → multiplier = crisis_penalty  (default -8%)
    Stronghold : ≥ (n_home - 1) victorias locales     → multiplier = stronghold_bonus (default +4%)
    Normal     : multiplier = 1.0

    Returns: (multiplier, info_dict)
    """
    df = stats_df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df['date']):
        df['date'] = pd.to_datetime(df['date'], dayfirst=True)
    if 'home_canon' not in df.columns:
        df['home_canon'] = df['home_team'].apply(dl.canonical_team_name)

    match_date = pd.to_datetime(match_date)
    home_matches = df[
        (df['home_canon'] == team_name) &
        (df['date'] < match_date)
    ].sort_values('date', ascending=False).head(n_home)

    if len(home_matches) < 3:
        return 1.0, {"status": "insufficient_data", "home_games": len(home_matches)}

    home_wins = int((home_matches['home_goals'] > home_matches['away_goals']).sum())
    total = len(home_matches)
    win_rate = home_wins / total

    if home_wins <= crisis_threshold:
        multiplier = crisis_penalty
        label = "crisis"
    elif home_wins >= (total - 1):
        multiplier = stronghold_bonus
        label = "stronghold"
    else:
        multiplier = 1.0
        label = "normal"

    return multiplier, {
        "status": "calculated",
        "home_games": total,
        "home_wins": home_wins,
        "win_rate": win_rate,
        "multiplier": multiplier,
        "label": label,
    }


def calculate_recent_form(stats_df, team_name, match_date, n=5):
    """
    Calculates a form multiplier based on the last N games.
    """
    # Ensure date column is datetime
    if not pd.api.types.is_datetime64_any_dtype(stats_df['date']):
        stats_df['date'] = pd.to_datetime(stats_df['date'], dayfirst=True)
        
    match_date = pd.to_datetime(match_date)
    
    # Filter for team matches before the specific date
    # We need to check both home_team and away_team columns
    # And we need to use canonical names for comparison if possible, 
    # but stats_df might have raw names. 
    # Ideally stats_df should have been pre-processed, but we can do a quick apply here 
    # or just assume the caller handles it. 
    # Given the pipeline structure, stats_df is raw from CSV.
    
    # Efficiency: create a mask. 
    # We will normalize the team name we are looking for.
    # And we will normalize the dataframe columns on the fly or assuming they are somewhat cleaner.
    # 'Stats_liga_mx.json' usually has specific names.
    
    # Let's try to filter using the string containment or exact match if we know the mapping.
    # better to use dl.canonical_team_name on the df if it's small enough, or just iterate.
    # Stats file is small (~600 rows).
    
    # Create a copy to avoid SettingWithCopy warning on the main df if we modify it
    df = stats_df.copy()
    
    # Normalize team names in df for accurate matching
    # unique_teams = pd.concat([df['home_team'], df['away_team']]).unique()
    # mapping = {t: dl.canonical_team_name(t) for t in unique_teams}
    # df['home_canon'] = df['home_team'].map(mapping)
    # df['away_canon'] = df['away_team'].map(mapping)
    
    # Fast filtering
    # We assume 'team_name' passed in is already canonical.
    
    # To avoid mapping everything, apply canonicalization in lambda (slower but safe)
    # or just rely on the fact that we can search for the name.
    
    # Let's do it robustly.
    # df['home_canon'] = df['home_team'].apply(dl.canonical_team_name) # OPTIMIZACION: Ya viene de afuera
    # df['away_canon'] = df['away_team'].apply(dl.canonical_team_name) # OPTIMIZACION: Ya viene de afuera
    
    if 'home_canon' not in df.columns:
         df['home_canon'] = df['home_team'].apply(dl.canonical_team_name)
    if 'away_canon' not in df.columns:
         df['away_canon'] = df['away_team'].apply(dl.canonical_team_name)
    
    team_matches = df[
        ((df['home_canon'] == team_name) | (df['away_canon'] == team_name)) & 
        (df['date'] < match_date)
    ].sort_values('date', ascending=False).head(n)
    
    if len(team_matches) < 3:
        return 1.0, {"status": "insufficient_data", "games": len(team_matches), "pct": 0.5} # Neutral 0.5 pct
        
    points = 0
    max_points = len(team_matches) * 3
    
    for _, row in team_matches.iterrows():
        is_home = (row['home_canon'] == team_name)
        gf = row['home_goals'] if is_home else row['away_goals']
        ga = row['away_goals'] if is_home else row['home_goals']
        
        if gf > ga:
            points += 3
        elif gf == ga:
            points += 1
            
    pct_points = points / max_points if max_points > 0 else 0
    
    # Config values
    # RECENT_FORM_MAX_WEIGHT defaults to 0.05
    boost_max = 0.05
    penalty_max = 0.05
    
    multiplier = 1.0
    
    if pct_points >= 0.60:
        # Scale from 0.60 (1.0) to 1.00 (1.05)
        factor = (pct_points - 0.60) / 0.40
        multiplier = 1.0 + (factor * boost_max)
        
    elif pct_points <= 0.30:
        # Scale from 0.0 (0.95) to 0.30 (1.0)
        factor = (0.30 - pct_points) / 0.30
        multiplier = 1.0 - (factor * penalty_max)
        
    return multiplier, {
        "status": "calculated",
        "games": len(team_matches),
        "points": points,
        "max_points": max_points,
        "pct": pct_points,
        "multiplier": multiplier
    }
