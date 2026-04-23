
# src/predicciones/config.py

import os

def get_config(jornada):
    """
    Genera configuración dinámica por jornada.
    
    Args:
        jornada (int): Número de jornada (1-17)
    
    Returns:
        dict: Configuración completa del modelo
    """
    return {
        'JORNADA': jornada,
        'CURRENT_TOURNAMENT': 'Clausura 2026',
        'PRIOR_TOURNAMENTS': [
            {'name': 'Clausura 2024', 'weight': 0.10},
            {'name': 'Apertura 2024', 'weight': 0.15},
            {'name': 'Clausura 2025', 'weight': 0.25},
            {'name': 'Apertura 2025', 'weight': 0.50},
        ],
        'GENERIC_PRIOR_HOME': 1.38,   # μ_home real Clausura 2026 (J1-J8): 98 goles / 71 partidos
        'GENERIC_PRIOR_AWAY': 1.20,   # μ_away real Clausura 2026 (J1-J8): 85 goles / 71 partidos (era 1.09 con J1-J6; J7-J8 visitante anotó 1.53/partido)

        # Dixon-Coles draw correction (ρ negativo = aumenta P(0-0) y P(1-1), reduce P(1-0) y P(0-1))
        'DC_RHO': -0.10,

        # Crisis / Momentum
        'HOME_CRISIS_WINS_THRESHOLD': 1,   # ≤ 1 victoria local en últimos N_HOME_FORM partidos → crisis
        'N_HOME_FORM': 4,                   # Partidos de local a revisar para crisis
        'MOMENTUM_THRESHOLD': 0.20,         # Diferencia de ritmo (últimas 2 vs previas 3) para activar bonus
        'MOMENTUM_BONUS_MAX': 0.02,         # ±2% máximo por aceleración/desaceleración

        # Baja uncertainty capping
        'BAJA_UNCERTAINTY_THRESHOLD': 0.25, # Si penalización combinada > umbral → bajar confianza a MEDIO

        # Strategic Improvements
        'RIVALRY_LAMBDA_FACTOR': 0.88,  # -12% goals in classics
        'ABSTAIN_GAP_THRESHOLD': 0.03,
        'ABSTAIN_SPREAD_THRESHOLD': 0.10,
        'ABSTAIN_MIN_PROB': 0.40,
        
        'HOME_ADVANTAGE_FACTOR': {
            # Factor = GF_local/PJ / μ_global (Apertura 2025 + Clausura 2026)
            'toluca':              1.586,
            'tigres':              1.338,
            'cruz azul':           1.190,
            'guadalajara':         1.190,
            'america':             1.136,
            'monterrey':           1.136,
            'atlas':               1.027,
            'juarez':              0.991,
            'tijuana':             0.991,
            'santos laguna':       0.892,
            'mazatlan':            0.892,
            'pumas':               0.865,
            'puebla':              0.811,
            'leon':                0.811,
            'necaxa':              0.811,
            'atletico de san luis':0.811,
            'queretaro':           0.757,
            'pachuca':             0.694,
        },

        'MAX_JORNADAS_CURRENT': 17,
        'EXPECTED_MATCHES_CURRENT': 153,  # 18 equipos, 17 jornadas, 9 partidos/jornada
        'EXPECTED_TEAMS': 18,
        'SHRINKAGE_DIVISOR_ACTUAL': 18.0,
        'SHRINKAGE_DIVISOR_PROPUESTO': 18.0,
        'W_CURR_MAX': 0.85,
        'BAYES_K': 3.0,
        'BAYES_ALPHA_ATT': 4.0,
        'BAYES_ALPHA_DEF': 5.0,
        'BLEND_K': 6.0,
        'LEAGUE_AVG_K': 30.0,
        'CLAMP_REL_MIN': 0.60,
        'CLAMP_REL_MAX': 1.60,
        'CLAMP_LAMBDA_MIN': 0.25,
        'CLAMP_LAMBDA_MAX': 4.00,

        # xG Integration (xgscore.io data)
        # XG_BLEND: peso del xG_per_match vs goles reales en el suavizado Bayesiano.
        #   0.0 = solo goles reales (comportamiento anterior)
        #   0.40 = 40% xG + 60% goles reales (recomendado para muestras < 10 partidos)
        'XG_BLEND': 0.40,
        # XG_PTS_REGRESSION_FACTOR: sensibilidad de la regresión xPTS.
        #   Si actual_pts >> xPTS → el equipo sobreperformó resultados → reducción leve de lambda.
        #   Factor 0.15 → máx ±3% (capeado). Ejemplo: Cruz Azul +5.6pts sobre xPTS → -3% lambda.
        'XG_PTS_REGRESSION_FACTOR': 0.15,
        'XG_STATS_PATH': 'data/xg_stats.json',

        # Dynamic paths based on jornada
        'INPUT_MATCHES': f'data/inputs/jornada_{jornada}_final.json',
        'INPUT_QUALITATIVE': f'data/inputs/Investigacion_cualitativa_jornada{jornada}.json',
        'INPUT_CONTEXT': f'data/inputs/context_adjustments_jornada{jornada}.json',
        'INPUT_EVALUATION': 'data/inputs/evaluacion_bajas.json',  # Común a todas
        'INPUT_PERPLEXITY_BAJAS': 'data/inputs/perplexity_bajas_semana.json',
        'INPUT_STATS': 'data/inputs/Stats_liga_mx.json',  # Común a todas
        'OUTPUT_CSV': 'outputs/diagnostico_lambda_components.csv',
        'OUTPUT_TXT': 'outputs/diagnostico_report.txt',
    }


def resolve_config(jornada=None):
    """
    Resuelve la configuración activa.

    Precedencia:
    1) Argumento explícito `jornada`
    2) Variable de entorno `PRED_JORNADA`
    3) Fallback a jornada 10 (jornada activa)
    """
    if jornada is None:
        env_jornada = os.getenv('PRED_JORNADA')
        jornada = int(env_jornada) if env_jornada else 10
    return get_config(int(jornada))

# Backwards compatibility: CONFIG default para J6 (o env si existe)
CONFIG = resolve_config()

# Diccionario de alias EXPLICITOS (mundo real es feo)
CANONICAL_ALIASES = {
    'cf america': 'america',
    'club america': 'america',
    'américa': 'america',
    'pumas': 'pumas',
    'pumas unam': 'pumas',
    'pumas de la unam': 'pumas',
    'unam': 'pumas',
    'queretaro fc': 'queretaro',
    'club queretaro': 'queretaro',
    'querétaro': 'queretaro',
    'tigres uanl': 'tigres',
    'tigres de la uanl': 'tigres',
    'uanl': 'tigres',
    'cd guadalajara': 'guadalajara',
    'club guadalajara': 'guadalajara',
    'fc juarez': 'juarez',
    'atletico san luis': 'atletico de san luis',
    'san luis': 'atletico de san luis',
    'chivas': 'guadalajara',
    'santos': 'santos laguna',
    'leon': 'leon',
}
