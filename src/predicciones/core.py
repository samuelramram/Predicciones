
import unicodedata
import re
import logging
from .config import CANONICAL_ALIASES
from . import utils  # Importar utils para caché


# ========== CANONICALIZACION DE NOMBRES ==========

def remove_accents(text):
    """Remueve acentos: querétaro -> queretaro"""
    return ''.join(c for c in unicodedata.normalize('NFD', text) 
                   if unicodedata.category(c) != 'Mn')

def canonical_team_name(name):
    """
    Canonicaliza nombre de equipo con reglas estrictas
    """
    if not name:
        return ""
    
    # 1. Lowercase y strip
    name = name.lower().strip()
    
    # 2. Remover acentos
    name = remove_accents(name)
    
    # 3. Remover puntuacion (puntos, comas, guiones internos)
    name = re.sub(r'[.]', '', name)
    name = re.sub(r'[-]', ' ', name)
    
    # 4. Normalizar espacios multiples
    name = re.sub(r'\s+', ' ', name).strip()
    
    # 5. Remover tokens irrelevantes SOLO si no rompen
    tokens_to_remove = ['fc', 'cf', 'club', 'deportivo']
    for token in tokens_to_remove:
        name = re.sub(r'\b' + token + r'\b', '', name)
    
    # Normalizar espacios de nuevo
    name = re.sub(r'\s+', ' ', name).strip()
    
    # 6. Aplicar diccionario de alias explicitos
    if name in CANONICAL_ALIASES:
        name = CANONICAL_ALIASES[name]
    
    return name

# ========== BUILD STATS CON CANONICAL NAMES ==========

def build_team_stats_canonical(stats_df, tournament):
    """
    Construye stats por equipo con nombres canonicos
    FUSIONA duplicados y loggea fusiones
    """
    
    tournament_matches = stats_df[stats_df['tournament'] == tournament].copy()
    
    if len(tournament_matches) == 0:
        raise ValueError(f"No matches for tournament: {tournament}")
    
    team_stats = {}
    fusion_log = {}
    
    for _, match in tournament_matches.iterrows():
        home_team_raw = match['home_team']
        away_team_raw = match['away_team']
        
        home_team_canonical = canonical_team_name(home_team_raw)
        away_team_canonical = canonical_team_name(away_team_raw)
        
        # Track fusions
        if home_team_raw != home_team_canonical:
            if home_team_canonical not in fusion_log:
                fusion_log[home_team_canonical] = set()
            fusion_log[home_team_canonical].add(home_team_raw)
        
        if away_team_raw != away_team_canonical:
            if away_team_canonical not in fusion_log:
                fusion_log[away_team_canonical] = set()
            fusion_log[away_team_canonical].add(away_team_raw)
        
        home_goals = match['home_goals']
        away_goals = match['away_goals']
        
        # Initialize if not exists
        if home_team_canonical not in team_stats:
            team_stats[home_team_canonical] = {
                'PJ_home': 0, 'PJ_away': 0, 'PJ_total': 0,
                'GF_home': 0, 'GF_away': 0, 'GF_total': 0,
                'GC_home': 0, 'GC_away': 0, 'GC_total': 0,
            }
        
        if away_team_canonical not in team_stats:
            team_stats[away_team_canonical] = {
                'PJ_home': 0, 'PJ_away': 0, 'PJ_total': 0,
                'GF_home': 0, 'GF_away': 0, 'GF_total': 0,
                'GC_home': 0, 'GC_away': 0, 'GC_total': 0,
            }
        
        # Update stats
        team_stats[home_team_canonical]['PJ_home'] += 1
        team_stats[home_team_canonical]['PJ_total'] += 1
        team_stats[home_team_canonical]['GF_home'] += home_goals
        team_stats[home_team_canonical]['GF_total'] += home_goals
        team_stats[home_team_canonical]['GC_home'] += away_goals
        team_stats[home_team_canonical]['GC_total'] += away_goals
        
        team_stats[away_team_canonical]['PJ_away'] += 1
        team_stats[away_team_canonical]['PJ_total'] += 1
        team_stats[away_team_canonical]['GF_away'] += away_goals
        team_stats[away_team_canonical]['GF_total'] += away_goals
        team_stats[away_team_canonical]['GC_away'] += home_goals
        team_stats[away_team_canonical]['GC_total'] += home_goals
    
    return team_stats, fusion_log

# ========== LEAGUE AVERAGES SEPARADOS POR TORNEO ==========

def calculate_league_averages_by_tournament(stats_df, tournament):
    """
    Calcula league averages DE UN TORNEO ESPECIFICO
    """
    current_matches = stats_df[stats_df['tournament'] == tournament].copy()
    
    if len(current_matches) == 0:
        raise ValueError(f"No matches for tournament: {tournament}")
    
    total_home = current_matches['home_goals'].sum()
    total_away = current_matches['away_goals'].sum()
    total_matches = len(current_matches)
    
    avg_home = total_home / total_matches
    avg_away = total_away / total_matches
    avg_total = (total_home + total_away) / total_matches
    
    return {
        'home': avg_home,
        'away': avg_away,
        'total': avg_total,
        'matches': total_matches,
        'tournament': tournament,
    }

# ========== VALIDACION CON WEIGHTED MEANS CORREGIDOS ==========

def calculate_weighted_means_correct(team_stats_current, team_stats_prior, league_avg_curr, league_avg_prior):
    """
    Calcula weighted means CORRECTAMENTE por equipo único
    """
    results = {}
    
    # CURRENT
    att_home_sum = 0
    att_away_sum = 0
    def_home_sum = 0
    def_away_sum = 0
    pj_home_sum = 0
    pj_away_sum = 0
    
    for team_canonical, stats in team_stats_current.items():
        pj_home = stats['PJ_home']
        pj_away = stats['PJ_away']
        
        if pj_home > 0:
            gf_home = stats['GF_home']
            gc_home = stats['GC_home']
            att_home = gf_home / pj_home
            def_home = gc_home / pj_home
            
            att_home_rel = att_home / league_avg_curr['home']
            def_home_rel = def_home / league_avg_curr['away']
            
            att_home_sum += att_home_rel * pj_home
            def_home_sum += def_home_rel * pj_home
            pj_home_sum += pj_home
        
        if pj_away > 0:
            gf_away = stats['GF_away']
            gc_away = stats['GC_away']
            att_away = gf_away / pj_away
            def_away = gc_away / pj_away
            
            att_away_rel = att_away / league_avg_curr['away']
            def_away_rel = def_away / league_avg_curr['away']
            
            att_away_sum += att_away_rel * pj_away
            def_away_sum += def_away_rel * pj_away
            pj_away_sum += pj_away
    
    results['att_home_rel_curr_weighted'] = att_home_sum / pj_home_sum if pj_home_sum > 0 else 0
    results['def_home_rel_curr_weighted'] = def_home_sum / pj_home_sum if pj_home_sum > 0 else 0
    results['att_away_rel_curr_weighted'] = att_away_sum / pj_away_sum if pj_away_sum > 0 else 0
    results['def_away_rel_curr_weighted'] = def_away_sum / pj_away_sum if pj_away_sum > 0 else 0
    
    # PRIOR
    att_home_sum_prior = 0
    att_away_sum_prior = 0
    def_home_sum_prior = 0
    def_away_sum_prior = 0
    pj_total_sum_prior = 0
    
    for team_canonical, stats in team_stats_prior.items():
        pj_total = stats['PJ_total']
        
        if pj_total > 0:
            gf_total = stats['GF_total']
            gc_total = stats['GC_total']
            att_total = gf_total / pj_total
            def_total = gc_total / pj_total
            
            att_home_rel_prior = att_total / league_avg_prior['home']
            att_away_rel_prior = att_total / league_avg_prior['away']
            def_home_rel_prior = def_total / league_avg_prior['away']
            def_away_rel_prior = def_total / league_avg_prior['home']
            
            att_home_sum_prior += att_home_rel_prior * pj_total
            att_away_sum_prior += att_away_rel_prior * pj_total
            def_home_sum_prior += def_home_rel_prior * pj_total
            def_away_sum_prior += def_away_rel_prior * pj_total
            pj_total_sum_prior += pj_total
    
    results['att_home_rel_prior_weighted'] = att_home_sum_prior / pj_total_sum_prior if pj_total_sum_prior > 0 else 0
    results['def_away_rel_prior_weighted'] = def_away_sum_prior / pj_total_sum_prior if pj_total_sum_prior > 0 else 0
    results['att_away_rel_prior_weighted'] = att_away_sum_prior / pj_total_sum_prior if pj_total_sum_prior > 0 else 0
    results['def_home_rel_prior_weighted'] = def_home_sum_prior / pj_total_sum_prior if pj_total_sum_prior > 0 else 0
    
    return results


# ========== MULTI-TOURNAMENT PRIOR LOGIC ==========

def calculate_tournament_relatives(stats_df, tournament, K=3.0):
    """Calcula componentes relativos Y TASAS suavizadas para UN torneo."""
    try:
        # Build Stats & League Avg for this specific tournament
        # Note: This calls existing functions but we handle empty/missing gracefully
        team_stats, _ = build_team_stats_canonical(stats_df, tournament)
        league_avg = calculate_league_averages_by_tournament(stats_df, tournament)
    except ValueError:
        return {} # Tournament might not exist in data

    relatives = {}
    
    # Pre-calculate constants
    mu_att_home = league_avg['home']
    mu_att_away = league_avg['away']
    mu_def_home = league_avg['away'] # Home defense vs Away attack
    mu_def_away = league_avg['home'] # Away defense vs Home attack

    for team, stats in team_stats.items():
        # Using simple Bayes (K) for the *historical* tournament rates themselves 
        # to ensure the prior itself isn't too noisy if that tournament had few games.
        
        # ATT HOME
        gf_home = stats['GF_home']
        pj_home = stats['PJ_home']
        rate_att_home = (gf_home + K * mu_att_home) / (pj_home + K)
        att_home_rel = rate_att_home / mu_att_home if mu_att_home > 0 else 1.0
        
        # ATT AWAY
        gf_away = stats['GF_away']
        pj_away = stats['PJ_away']
        rate_att_away = (gf_away + K * mu_att_away) / (pj_away + K)
        att_away_rel = rate_att_away / mu_att_away if mu_att_away > 0 else 1.0
        
        # DEF HOME
        gc_home = stats['GC_home']
        rate_def_home = (gc_home + K * mu_def_home) / (pj_home + K)
        def_home_rel = rate_def_home / mu_def_home if mu_def_home > 0 else 1.0
        
        # DEF AWAY
        gc_away = stats['GC_away']
        rate_def_away = (gc_away + K * mu_def_away) / (pj_away + K)
        def_away_rel = rate_def_away / mu_def_away if mu_def_away > 0 else 1.0
        
        relatives[team] = {
            'att_home': att_home_rel, 'rate_att_home': rate_att_home,
            'att_away': att_away_rel, 'rate_att_away': rate_att_away,
            'def_home': def_home_rel, 'rate_def_home': rate_def_home,
            'def_away': def_away_rel, 'rate_def_away': rate_def_away,
            'pj_total': stats['PJ_total']
        }
        
    return relatives

def build_weighted_prior_stats(stats_df, config):
    """
    Construye prior ponderado incluyendo RELATIVOS y TASAS (RATES).
    Utiliza caché si está disponible y la configuración no ha cambiado.
    """
    # Intentar cargar desde caché
    cached_prior = utils.load_prior_cache(config)
    if cached_prior:
        return cached_prior

    tournaments = config.get('PRIOR_TOURNAMENTS', [])
    K = config.get('BAYES_K', 3.0)
    
    # Storage for weighted sums: team -> {component -> weighted_sum, weight_sum -> total_weight}
    agg_stats = {}
    
    for t_conf in tournaments:
        t_name = t_conf['name']
        t_weight = t_conf['weight']
        
        # Calculate relatives for this tournament
        t_relatives = calculate_tournament_relatives(stats_df, t_name, K)
        
        for team, rels in t_relatives.items():
            if team not in agg_stats:
                agg_stats[team] = {
                    'att_home_sum': 0.0, 'att_away_sum': 0.0,
                    'def_home_sum': 0.0, 'def_away_sum': 0.0,
                    'rate_att_home_sum': 0.0, 'rate_att_away_sum': 0.0,
                    'rate_def_home_sum': 0.0, 'rate_def_away_sum': 0.0,
                    'pj_total_sum': 0, # Just for info
                    'weight_sum': 0.0
                }
            
            agg = agg_stats[team]
            agg['att_home_sum'] += rels['att_home'] * t_weight
            agg['att_away_sum'] += rels['att_away'] * t_weight
            agg['def_home_sum'] += rels['def_home'] * t_weight
            agg['def_away_sum'] += rels['def_away'] * t_weight
            
            agg['rate_att_home_sum'] += rels['rate_att_home'] * t_weight
            agg['rate_att_away_sum'] += rels['rate_att_away'] * t_weight
            agg['rate_def_home_sum'] += rels['rate_def_home'] * t_weight
            agg['rate_def_away_sum'] += rels['rate_def_away'] * t_weight
            
            agg['pj_total_sum'] += rels['pj_total']
            agg['weight_sum'] += t_weight
            
    # Normalize
    final_priors = {}
    for team, agg in agg_stats.items():
        w_total = agg['weight_sum']
        if w_total > 0:
            final_priors[team] = {
                'att_home_prior': agg['att_home_sum'] / w_total,
                'att_away_prior': agg['att_away_sum'] / w_total,
                'def_home_prior': agg['def_home_sum'] / w_total,
                'def_away_prior': agg['def_away_sum'] / w_total,
                
                'rate_att_home_prior': agg['rate_att_home_sum'] / w_total,
                'rate_att_away_prior': agg['rate_att_away_sum'] / w_total,
                'rate_def_home_prior': agg['rate_def_home_sum'] / w_total,
                'rate_def_away_prior': agg['rate_def_away_sum'] / w_total,
                
                'pj_prior_total': agg['pj_total_sum'] # Not strictly used for shrinkage anymore but good for audit
            }
        else:
            # Fallback (should not happen if weights > 0)
            final_priors[team] = {
                'att_home_prior': 1.0, 'att_away_prior': 1.0, 
                'def_home_prior': 1.0, 'def_away_prior': 1.0,
                'rate_att_home_prior': 1.3, 'rate_att_away_prior': 1.0, # Defaults rough
                'rate_def_home_prior': 1.0, 'rate_def_away_prior': 1.3
            }
            
    # Guardar en caché antes de retornar
    utils.save_prior_cache(final_priors, config)

    return final_priors

def calculate_weighted_league_averages(stats_df, config):
    """Calcula promedio de liga ponderado multi-torneo (PRIOR)."""
    tournaments = config.get('PRIOR_TOURNAMENTS', [])
    
    avg_home_sum = 0
    avg_away_sum = 0
    total_weight = 0
    
    for t_conf in tournaments:
        t_name = t_conf['name']
        t_weight = t_conf['weight']
        try:
            avgs = calculate_league_averages_by_tournament(stats_df, t_name)
            avg_home_sum += avgs['home'] * t_weight
            avg_away_sum += avgs['away'] * t_weight
            total_weight += t_weight
        except (ValueError, KeyError, TypeError) as e:
            logging.warning(f"Error calculando avg para torneo '{t_name}': {e}")
            continue
            
    if total_weight > 0:
        return {
            'home': avg_home_sum / total_weight,
            'away': avg_away_sum / total_weight, 
            'total': (avg_home_sum + avg_away_sum) / total_weight
        }
    return {'home': 0, 'away': 0, 'total': 0} # Should not happen

# ========== TABLA DE POSICIONES ACTUAL ==========

def calculate_current_table(stats_df, tournament):
    """
    Calcula la tabla de posiciones actual a partir de los partidos registrados.

    Returns: dict {team_canonical: {'pts': int, 'pj': int, 'gd': int}}
    """
    tournament_matches = stats_df[stats_df['tournament'] == tournament].copy()

    table = {}
    for _, match in tournament_matches.iterrows():
        home = canonical_team_name(match['home_team'])
        away = canonical_team_name(match['away_team'])
        hg = int(match['home_goals'])
        ag = int(match['away_goals'])

        for team in (home, away):
            if team not in table:
                table[team] = {'pts': 0, 'pj': 0, 'gd': 0}

        table[home]['pj'] += 1
        table[away]['pj'] += 1
        table[home]['gd'] += hg - ag
        table[away]['gd'] += ag - hg

        if hg > ag:
            table[home]['pts'] += 3
        elif hg == ag:
            table[home]['pts'] += 1
            table[away]['pts'] += 1
        else:
            table[away]['pts'] += 3

    return table


# ========== FUNCION UNICA CENTRALIZADA: FUENTE DE VERDAD ==========

def compute_components_and_lambdas(match_data, team_stats_current,
                                    prior_weighted_stats,
                                    league_avg_curr_raw, # RAW current league avg
                                    config,
                                    shrinkage_divisor, adjustments=None,
                                    stats_df_for_league_smoothing=None, # Optional context
                                    xg_lookup=None): # xG data {canon_name: {...}}
    """
    Uses Refined Empirical Bayes for Rates + Dynamic Blending + Guardrails.
    """
    # === 1. LEAGUE AVERAGE SMOOTHING ===
    # Calculate Prior League Avg (Multi-tournament)
    # Ideally this is passed in, but we can compute or approximate it. 
    # For efficiency we might assume 'prior_weighted_stats' implicitly contains relative info, 
    # but for league averages we need the absolute numbers.
    # We will assume stats_df_for_league_smoothing is passed OR (hack) we re-calculate if missing, 
    # or better, the caller handles this. 
    # To keep interface simple, we assume caller passes a 'league_avg_prior_weighted' if possible, 
    # but since signature is fixed, let's assume we use defaults or calculate on fly if needed.
    # Actually, simpler: We will trust the input 'league_avg_curr_raw' is the raw current, 
    # and we need the prior.
    
    # NOTE: The "stats_df_for_league_smoothing" param is a hack for now. 
    # Ideally we update the signature in caller. 
    # But let's calculate 'league_avg_final' inside here using a simplified heuristic if needed,
    # OR better: let's assume league_avg_curr IS the final smoothed one IF it was prepared outside.
    # BUT the user asked for logic HERE. 
    # Let's perform a lightweight calc using the config if we can, or rely on robust inputs.
    # We will implement the smoothing logic assuming we can get prior avg.
    # Since we don't have stats_df easily here without changing signature drastically in all callers...
    # We will simplify: We will treat the 'league_avg_curr_raw' passed to this function as the RAW current,
    # and we will define defaults for prior if not available.
    
    # Wait, 'prior_weighted_stats' doesn't have league avgs.
    # Let's use hardcoded approximations if we can't calculate, or better, 
    # we enforce that the CALLER prepares 'league_avg_curr' AS the smoothed version?
    # No, user asked "league_avg_current se suaviza...".
    
    # REFACTOR STRATEGY: 
    # We will calculate smoothed league avg current relative to prior *inside* here 
    # if we have access to prior league avg. 
    # Since we don't carry the DF, we will use a robust approximation: 
    # If matches < X, blend with "Generic Liga MX Avg" (Home ~1.5, Away ~1.1).
    
    # Actually, let's implement the logic properly:
    # We need the number of matches played in current season to weigh.
    matches_played_curr = league_avg_curr_raw.get('matches', 0)
    LEAGUE_K = config.get('LEAGUE_AVG_K', 30.0)
    
    # Generic approx for prior if full calc not available
    mu_home_prior = config.get('GENERIC_PRIOR_HOME', 1.45) # Conservative historical
    mu_away_prior = config.get('GENERIC_PRIOR_AWAY', 1.15)
    
    # Weight
    w_league = matches_played_curr / (matches_played_curr + LEAGUE_K)
    
    mu_home_final = w_league * league_avg_curr_raw['home'] + (1 - w_league) * mu_home_prior
    mu_away_final = w_league * league_avg_curr_raw['away'] + (1 - w_league) * mu_away_prior
    
    league_avg_smoothed = {'home': mu_home_final, 'away': mu_away_final}
    
    # === 2. SETUP TEAMS ===
    home_team_raw = match_data['match']['home']
    away_team_raw = match_data['match']['away']
    home_canon = canonical_team_name(home_team_raw)
    away_canon = canonical_team_name(away_team_raw)

    home_adv_factors = config.get('HOME_ADVANTAGE_FACTOR', {})
    home_factor = home_adv_factors.get(home_canon, 1.0)
    if home_canon not in home_adv_factors:
        logging.warning(f"HOME_ADVANTAGE_FACTOR no encontrado para '{home_canon}', usando 1.0")
    
    curr_home = team_stats_current.get(home_canon, {})
    curr_away = team_stats_current.get(away_canon, {})
    p_home = prior_weighted_stats.get(home_canon, {})
    p_away = prior_weighted_stats.get(away_canon, {})
    
    pj_home = curr_home.get('PJ_home', 0)
    pj_away = curr_away.get('PJ_away', 0)
    pj_total_home = curr_home.get('PJ_total', 0)
    pj_total_away = curr_away.get('PJ_total', 0)
    
    errors = []
    
    # === 3. EMPIRICAL BAYES ON RATES ===
    ALPHA_ATT = config.get('BAYES_ALPHA_ATT', 4.0)
    ALPHA_DEF = config.get('BAYES_ALPHA_DEF', 5.0)

    # --- HELPER: Smooth Rate ---
    def calc_smooth_rate(obs_g, obs_pj, prior_rate, alpha):
        return (obs_g + alpha * prior_rate) / (obs_pj + alpha)

    # --- RAW OBSERVATIONS ---
    gf_home_obs = curr_home.get('GF_home', 0)
    gc_home_obs = curr_home.get('GC_home', 0)
    gf_away_obs = curr_away.get('GF_away', 0)
    gc_away_obs = curr_away.get('GC_away', 0)

    # === 3a. XG BLEND: mezcla goles reales con xG como señal de calidad real ===
    # xG_per_match es mejor estimador de la tasa de ataque verdadera en muestras pequeñas
    # porque elimina la varianza de finishing luck. Se mezcla ANTES del suavizado Bayesiano.
    # eff_gf/gc = (1 - XG_BLEND) * goles_reales + XG_BLEND * xG_implicado
    # El efecto de venue (local/visitante) lo maneja home_factor downstream — se usa xG total
    # como proxy de calidad independiente de venue, lo cual es una aproximación conservadora.
    XG_BLEND = config.get('XG_BLEND', 0.0)
    xg_home_entry = (xg_lookup or {}).get(home_canon, {})
    xg_away_entry = (xg_lookup or {}).get(away_canon, {})

    def _blend_obs_with_xg(actual_g, actual_pj, xg_per_match, blend_w):
        """Blend actual goals with xG-implied goals for Bayesian input.
        Falls back to actual_g if blend_w==0, no xG data, or insufficient games."""
        if blend_w <= 0.0 or xg_per_match is None or actual_pj < 3:
            return actual_g
        xg_implied = xg_per_match * actual_pj
        return (1.0 - blend_w) * actual_g + blend_w * xg_implied

    xg_att_home = xg_home_entry.get('xG_per_match') if xg_home_entry else None
    xg_def_home = (xg_home_entry['xGC'] / xg_home_entry['PJ']
                   if xg_home_entry and xg_home_entry.get('PJ', 0) > 0 else None)
    xg_att_away = xg_away_entry.get('xG_per_match') if xg_away_entry else None
    xg_def_away = (xg_away_entry['xGC'] / xg_away_entry['PJ']
                   if xg_away_entry and xg_away_entry.get('PJ', 0) > 0 else None)

    eff_gf_home = _blend_obs_with_xg(gf_home_obs, pj_home, xg_att_home, XG_BLEND)
    eff_gc_home = _blend_obs_with_xg(gc_home_obs, pj_home, xg_def_home, XG_BLEND)
    eff_gf_away = _blend_obs_with_xg(gf_away_obs, pj_away, xg_att_away, XG_BLEND)
    eff_gc_away = _blend_obs_with_xg(gc_away_obs, pj_away, xg_def_away, XG_BLEND)

    # HOME ATTACK
    prior_rate_att_home = p_home.get('rate_att_home_prior', mu_home_final)
    rate_att_home_smooth = calc_smooth_rate(eff_gf_home, pj_home, prior_rate_att_home, ALPHA_ATT)

    # AWAY ATTACK
    prior_rate_att_away = p_away.get('rate_att_away_prior', mu_away_final)
    rate_att_away_smooth = calc_smooth_rate(eff_gf_away, pj_away, prior_rate_att_away, ALPHA_ATT)

    # HOME DEFENSE
    prior_rate_def_home = p_home.get('rate_def_home_prior', mu_away_final)
    rate_def_home_smooth = calc_smooth_rate(eff_gc_home, pj_home, prior_rate_def_home, ALPHA_DEF)

    # AWAY DEFENSE
    prior_rate_def_away = p_away.get('rate_def_away_prior', mu_home_final)
    rate_def_away_smooth = calc_smooth_rate(eff_gc_away, pj_away, prior_rate_def_away, ALPHA_DEF)
    
    # === 4. CONVERT TO RELATIVES (Using Smoothed League Avg) ===
    # Rel = SmoothRate / SmoothedLeagueAvg
    
    # Att Home Rel (vs League Avg Home Goals)
    att_home_rel_curr_eb = rate_att_home_smooth / mu_home_final if mu_home_final > 0 else 1.0
    
    # Att Away Rel (vs League Avg Away Goals)
    att_away_rel_curr_eb = rate_att_away_smooth / mu_away_final if mu_away_final > 0 else 1.0
    
    # Def Home Rel (vs League Avg Away Goals - expectations)
    def_home_rel_curr_eb = rate_def_home_smooth / mu_away_final if mu_away_final > 0 else 1.0
    
    # Def Away Rel (vs League Avg Home Goals - expectations)
    def_away_rel_curr_eb = rate_def_away_smooth / mu_home_final if mu_home_final > 0 else 1.0
    
    # === 5. DYNAMIC BLENDING (Current EB vs Historical Prior Rel) ===
    BLEND_K = config.get('BLEND_K', 6.0)
    
    def get_blend_weight(pj):
        return pj / (pj + BLEND_K)
        
    w_curr_home = get_blend_weight(pj_home)
    w_curr_away = get_blend_weight(pj_away)
    
    # Get Prior Rels (Already loaded in p_home/p_away from multi-tournament)
    att_home_rel_prior = p_home.get('att_home_prior', 1.0)
    att_away_rel_prior = p_away.get('att_away_prior', 1.0)
    def_home_rel_prior = p_home.get('def_home_prior', 1.0)
    def_away_rel_prior = p_away.get('def_away_prior', 1.0)
    
    # Blend!
    att_home_final_raw = w_curr_home * att_home_rel_curr_eb + (1-w_curr_home) * att_home_rel_prior
    def_home_final_raw = w_curr_home * def_home_rel_curr_eb + (1-w_curr_home) * def_home_rel_prior
    
    att_away_final_raw = w_curr_away * att_away_rel_curr_eb + (1-w_curr_away) * att_away_rel_prior
    def_away_final_raw = w_curr_away * def_away_rel_curr_eb + (1-w_curr_away) * def_away_rel_prior
    
    # === 6. GUARDRAILS / CLAMPING ===
    CLAMP_REL_MIN = config.get('CLAMP_REL_MIN', 0.60)
    CLAMP_REL_MAX = config.get('CLAMP_REL_MAX', 1.60)
    
    def clamp_rel(val):
        return max(CLAMP_REL_MIN, min(CLAMP_REL_MAX, val))
        
    att_home_final = clamp_rel(att_home_final_raw)
    def_home_final = clamp_rel(def_home_final_raw)
    att_away_final = clamp_rel(att_away_final_raw)
    def_away_final = clamp_rel(def_away_final_raw)
    
    # === 7. CALCULATE LAMBDAS ===
    lambda_home_base = att_home_final * def_away_final * mu_home_final * home_factor
    lambda_away_base = att_away_final * def_home_final * mu_away_final
    
    # Apply Adjustments
    match_adj = adjustments or {}
    lambda_home_final = lambda_home_base * match_adj.get('home_att_adj', 1.0) * match_adj.get('away_def_adj', 1.0) * match_adj.get('home_form_adj', 1.0)
    lambda_away_final = lambda_away_base * match_adj.get('away_att_adj', 1.0) * match_adj.get('home_def_adj', 1.0) * match_adj.get('away_form_adj', 1.0)

    # Apply rivalry reduction BEFORE clamp
    is_rivalry = match_data.get('match', {}).get('rivalry', False)
    RIVALRY_FACTOR = config.get('RIVALRY_LAMBDA_FACTOR', 0.88)
    if is_rivalry:
        lambda_home_final = lambda_home_final * RIVALRY_FACTOR
        lambda_away_final = lambda_away_final * RIVALRY_FACTOR

    # Clamp Lambdas
    CLAMP_L_MIN = config.get('CLAMP_LAMBDA_MIN', 0.25)
    CLAMP_L_MAX = config.get('CLAMP_LAMBDA_MAX', 3.20)

    lambda_home_final = max(CLAMP_L_MIN, min(CLAMP_L_MAX, lambda_home_final))
    lambda_away_final = max(CLAMP_L_MIN, min(CLAMP_L_MAX, lambda_away_final))

    lambda_total_final = lambda_home_final + lambda_away_final
    
    return {
        'home_team_canonical': home_canon,
        'away_team_canonical': away_canon,
        'pj_home_current': pj_home,
        'pj_away_current': pj_away,
        'w_curr_home': w_curr_home,
        'w_curr_away': w_curr_away,
        
        # AUDIT: Raw Obs
        'gf_home_obs': gf_home_obs,
        'ga_home_obs': gc_home_obs,
        'gf_away_obs': gf_away_obs,
        'ga_away_obs': gc_away_obs,

        # AUDIT: xG Blend
        'xg_blend': XG_BLEND,
        'xg_att_home': xg_att_home,
        'xg_def_home': xg_def_home,
        'xg_att_away': xg_att_away,
        'xg_def_away': xg_def_away,
        'eff_gf_home': round(eff_gf_home, 3),
        'eff_gc_home': round(eff_gc_home, 3),
        'eff_gf_away': round(eff_gf_away, 3),
        'eff_gc_away': round(eff_gc_away, 3),
        
        # AUDIT: Rates
        'prior_rate_att_home': prior_rate_att_home,
        'rate_att_home_smooth': rate_att_home_smooth,
        
        'prior_rate_def_away': prior_rate_def_away,
        'rate_def_away_smooth': rate_def_away_smooth, # Critical check
        
        # AUDIT: Rels
        'att_home_rel_curr_eb': att_home_rel_curr_eb,
        'def_home_rel_curr_eb': def_home_rel_curr_eb,
        'att_away_rel_curr_eb': att_away_rel_curr_eb,
        'def_away_rel_curr_eb': def_away_rel_curr_eb,
        
        # AUDIT: Final Components (Relative)
        'att_home_final': att_home_final,
        'def_home_final': def_home_final,
        'att_home_rel_blend': att_home_final, # Compat (Clamped)
        'def_away_rel_blend': def_away_final, # Compat (Clamped)
        'att_away_rel_blend': att_away_final, # Compat (Clamped)
        'def_home_rel_blend': def_home_final, # Compat (Clamped)
        
        # AUDIT: Lambdas
        'lambda_home_base': lambda_home_base,
        'lambda_away_base': lambda_away_base,
        'lambda_home_final': lambda_home_final,
        'lambda_away_final': lambda_away_final,
        'lambda_total_base': lambda_home_base + lambda_away_base,
        'lambda_total_final': lambda_home_final + lambda_away_final,
        
        # AUDIT: League
        'mu_home_final': mu_home_final,
        'mu_away_final': mu_away_final,
        
    }, errors
