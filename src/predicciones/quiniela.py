from math import exp, factorial


def poisson_prob(lambda_val, k):
    return (lambda_val**k * exp(-lambda_val)) / factorial(k)


def dc_correction(h, a, lh, la, rho):
    """
    Corrección Dixon-Coles para marcadores bajos.
    Con rho < 0 (valor típico -0.10):
      - Aumenta P(0-0) y P(1-1)  → más empates
      - Reduce  P(1-0) y P(0-1)  → menos victorias por gol mínimo
    Solo se aplica a marcadores con h+a <= 2 (1-1 inclusive).
    Ref: Dixon & Coles (1997), Modelling Association Football Scores.
    """
    if h == 0 and a == 0:
        return 1.0 - lh * la * rho
    elif h == 1 and a == 0:
        return 1.0 + la * rho
    elif h == 0 and a == 1:
        return 1.0 + lh * rho
    elif h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def _captured_mass(lambda_home, lambda_away, max_goals):
    """Masa capturada por la grilla 0..max_goals para ambos equipos."""
    mass_home = sum(poisson_prob(lambda_home, k) for k in range(max_goals + 1))
    mass_away = sum(poisson_prob(lambda_away, k) for k in range(max_goals + 1))
    return mass_home * mass_away


def choose_grid_limit(lambda_home, lambda_away, target_mass=0.995, min_goals=5, max_cap=12):
    """
    Selecciona tamaño de grilla adaptativo para minimizar truncamiento.
    """
    for g in range(min_goals, max_cap + 1):
        if _captured_mass(lambda_home, lambda_away, g) >= target_mass:
            return g
    return max_cap


def optimize_pick_for_quiniela(lambda_home, lambda_away, dc_rho=-0.10):
    """
    Optimiza pick para scoring de quiniela (2 pts exacto, 1 pt resultado).

    Implementación Rigurosa Anti-Sesgo con corrección Dixon-Coles:
    1. Calcula P(1), P(X), P(2) totales (normalizados por grilla) con corrección DC.
    2. Encuentra el mejor marcador exacto para cada escenario (1, X, 2).
    3. Calcula el EV de cada escenario: EV = P(Exacto) + P(Resultado).
    4. Elige el escenario con mayor EV.

    dc_rho: parámetro Dixon-Coles (negativo = mayor probabilidad de empates).
    """
    max_goals = choose_grid_limit(lambda_home, lambda_away)

    # 1. Calcular Probabilidades Raw (con corrección Dixon-Coles)
    probs_all = []
    sum_raw = 0.0

    raw_p1, raw_px, raw_p2 = 0.0, 0.0, 0.0

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson_prob(lambda_home, h) * poisson_prob(lambda_away, a)
            p *= dc_correction(h, a, lambda_home, lambda_away, dc_rho)
            
            outcome = 'X'
            if h > a: outcome = '1'
            elif a > h: outcome = '2'
            
            probs_all.append({
                'h': h, 'a': a, 
                'score': f"{h}-{a}", 
                'prob_raw': p,
                'outcome': outcome
            })
            sum_raw += p
            
            if outcome == '1': raw_p1 += p
            elif outcome == 'X': raw_px += p
            elif outcome == '2': raw_p2 += p

    # 2. Normalizar
    captured_mass = sum_raw
    if captured_mass <= 0: return {} # Error case
    
    prob_1 = raw_p1 / captured_mass
    prob_x = raw_px / captured_mass
    prob_2 = raw_p2 / captured_mass
    
    # Normalizar scores individualmente
    for item in probs_all:
        item['prob'] = item['prob_raw'] / captured_mass
    
    # 3. Encontrar el mejor exacto por grupo
    # Filtrar y ordenar
    scores_1 = sorted([x for x in probs_all if x['outcome'] == '1'], key=lambda x: x['prob'], reverse=True)
    scores_x = sorted([x for x in probs_all if x['outcome'] == 'X'], key=lambda x: x['prob'], reverse=True)
    scores_2 = sorted([x for x in probs_all if x['outcome'] == '2'], key=lambda x: x['prob'], reverse=True)
    
    best_1 = scores_1[0] if scores_1 else None
    best_x = scores_x[0] if scores_x else None
    best_2 = scores_2[0] if scores_2 else None
    
    # 4. Calcular EV por Candidato
    candidates = []
    
    if best_1:
        ev_1 = best_1['prob'] + prob_1
        candidates.append({'pick_1x2': '1', 'pick_exact': best_1['score'], 'ev': ev_1})
        
    if best_x:
        ev_x = best_x['prob'] + prob_x
        candidates.append({'pick_1x2': 'X', 'pick_exact': best_x['score'], 'ev': ev_x})
        
    if best_2:
        ev_2 = best_2['prob'] + prob_2
        candidates.append({'pick_1x2': '2', 'pick_exact': best_2['score'], 'ev': ev_2})
        
    # Ordenar candidatos por EV
    candidates = sorted(candidates, key=lambda x: x['ev'], reverse=True)
    winner = candidates[0]
    
    # Calcular gap con el segundo mejor (de distinta outcome si es posible, o raw)
    # Gap confidence usuallly vs 2nd absolute best option in the global table
    # But here we want gap between the chosen strategy and the next best strategy
    ev_confidence_gap = 0.0
    if len(candidates) > 1:
        ev_confidence_gap = winner['ev'] - candidates[1]['ev']
        
    # Recalcular lista global para Top 5 Display
    # Calculamos EV "naive" para todos para mostrar en tabla
    for item in probs_all:
        if item['outcome'] == '1': p_res = prob_1
        elif item['outcome'] == 'X': p_res = prob_x
        else: p_res = prob_2
        item['ev'] = item['prob'] + p_res
        
    top_5_prob = sorted(probs_all, key=lambda x: x['prob'], reverse=True)[:5]
    top_5_ev_naive = sorted(probs_all, key=lambda x: x['ev'], reverse=True)[:5]

    return {
        'pick_exact': winner['pick_exact'],
        'pick_1x2': winner['pick_1x2'],
        'ev': winner['ev'],
        'ev_confidence_gap': ev_confidence_gap,
        'prob_home_win': prob_1,
        'prob_draw': prob_x,
        'prob_away_win': prob_2,
        'top_5_by_prob': top_5_prob,
        'top_5_by_ev': top_5_ev_naive,
        'grid_max_goals': max_goals,
        'captured_mass': captured_mass,
    }
