
import json
import os
import re
import src.predicciones.core as dl

# === CONFIGURACION DE PENALIZACIONES (Shared) ===
PENALTIES = {
    'GK_KEY': 1.15,      # Aumento en goles concedidos (Defensa debil)
    'DF_KEY': 1.10,      # Aumento en goles concedidos
    'DF_REG': 1.05,
    'MF_KEY': 0.90,      # Reduccion en ataque (Ataque debil)
    'MF_REG': 0.97,      # Ajustado de 0.95 a 0.97 segun calibracion
    'FW_KEY': 0.85,      # Reduccion en ataque
    'FW_REG': 0.93,      # Ajustado de 0.91 a 0.93 segun calibracion
    'STATUS_DUDA_FACTOR': 0.35, # Factor para reducir impacto si es Duda (0.35 = 35% del impacto aplicado)
}

KEY_PLAYERS_CACHE = {}

def load_key_players(file_path="data/key_players.json"):
    """
    Loads key players and elite traits into a cache for quick lookup.
    Returns a dict: {(team_canonical, player_name_lower): {'rank': int, 'elite': bool}}
    """
    global KEY_PLAYERS_CACHE
    if KEY_PLAYERS_CACHE:
        return KEY_PLAYERS_CACHE
        
    if not os.path.exists(file_path):
        print(f"WARNING: {file_path} not found. Key player logic disabled.")
        return {}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        cache = {}
        # 1. Process Ranked Players
        for p in data.get('players', []):
            tm = dl.canonical_team_name(p.get('team', ''))
            nm = dl.remove_accents(p.get('name', '').lower().strip())
            rank = p.get('rank', 999)
            if tm and nm:
                cache[(tm, nm)] = {'rank': rank, 'elite': False}
                
        # 2. Process Elite Traits (Force Elite)
        elite_sections = data.get('elite_traits_players', {})
        for trait, players in elite_sections.items():
            for p in players:
                tm = dl.canonical_team_name(p.get('team', ''))
                nm = dl.remove_accents(p.get('name', '').lower().strip())
                if tm and nm:
                    if (tm, nm) not in cache:
                        cache[(tm, nm)] = {'rank': 999, 'elite': True}
                    else:
                        cache[(tm, nm)]['elite'] = True
                        
        KEY_PLAYERS_CACHE = cache
        return cache
    except Exception as e:
        print(f"ERROR loading key players: {e}")
        return {}

def get_player_importance_level(team, player_name):
    """
    Determines if a player is 'High', 'Mid', or 'Low' importance based on key_players.json
    """
    cache = load_key_players()
    # Normalize player name too (remove accents) to ensure match
    player_norm = dl.remove_accents(player_name.lower().strip())
    key = (dl.canonical_team_name(team), player_norm)
    
    if key in cache:
        info = cache[key]
        if info['elite'] or info['rank'] <= 40:
            return 'High'
        elif info['rank'] <= 80:
            return 'Mid'
            
    return None # No override



def normalize_role(role):
    r = (role or "").lower().strip()
    if r in ["gk", "goalkeeper"]: return "portero"
    if "portero" in r: return "portero"
    if any(x in r for x in ["defensa", "defensor", "lateral", "central", "cb", "lb", "rb", "df"]): return "defensa"
    if any(x in r for x in ["mediocampista", "volante", "medio", "mediocentro", "cm", "dm", "am", "mf"]): return "medio"
    if any(x in r for x in ["delantero", "atacante", "extremo", "fw", "st", "cf", "wing"]): return "ataque"
    return "unknown"


def apply_minutes_gate(baja):
    """
    Gate: reduce impact si jugador sin minutos confirmados.
    Evita penalizaciones excesivas por jugadores suplentes sin minutos.
    
    Args:
        baja (dict): Diccionario de baja con campos: player, manual_impact_level, minutes_played
    
    Returns:
        str: Impact level ajustado ('High', 'Mid', 'Low')
    """
    minutes = baja.get('minutes_played', None)
    impact_orig = baja.get('manual_impact_level', 'Low')
    player = baja.get('player', 'Unknown')
    
    # Si no hay info de minutos, forzar max=Mid
    if minutes is None and impact_orig == 'High':
        print(f"⚠️ WARNING: {player} tiene impact='High' sin minutes_played. Downgrade a 'Mid'")
        return 'Mid'
    
    # Si tiene pocos minutos, no puede ser High
    if minutes is not None and minutes < 90 and impact_orig == 'High':
        print(f"⚠️ WARNING: {player} tiene {minutes} minutos < 90 con impact='High'. Downgrade a 'Mid'")
        return 'Mid'
    
    return impact_orig

def _ensure_team_adjustment(team_adjustments, team):
    if team not in team_adjustments:
        team_adjustments[team] = {
            'att_adj': 1.0,
            'def_adj': 1.0,
            'notes': [],
            'report_log': [],
            'context_txt': [],
            'ausencias_txt': [],
            'ausencias_items': [],
            'movimientos_txt': []
        }


# === DATA COLLECTION & DEDUPLICATION ===

def collect_manual_bajas(file_path="data/inputs/evaluacion_bajas.json"):
    """
    Collects raw bajas from manual evaluation file.
    Returns list of dicts.
    """
    if not os.path.exists(file_path):
        return []
        
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    bajas_list = []
    for item in data.get('bajas_identificadas', []):
        team = dl.canonical_team_name(item['team'])
        if not team: continue
        
        # Key Player Override (Early Check)
        player = item.get('player', 'Unknown')
        impact = item.get('manual_impact_level', 'Low')
        auto_imp = get_player_importance_level(team, player)
        
        if auto_imp == 'High' and impact != 'High':
             impact = 'High'
        elif auto_imp == 'Mid' and impact == 'Low':
             impact = 'Mid'
             
        # Minute Gate: skipped for manual entries (user has explicitly validated these)

        bajas_list.append({
            'team': team,
            'player': player,
            'role': item.get('role', ''),
            'status': item.get('status', '').title(),
            'impact_level': impact,
            'reason': item.get('reason', ''),
            'confidence': 1.0, # Manual is absolute truth usually
            'recency_days': 0,
            'source': 'manual',
            'raw_data': item
        })
    return bajas_list

def collect_perplexity_bajas(file_path="data/inputs/perplexity_bajas_semana.json"):
    """
    Collects raw bajas from Perplexity file.
    Returns list of dicts.
    """
    if not os.path.exists(file_path):
        return []

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    bajas = data.get('bajas', [])
    if not isinstance(bajas, list): return []
    
    bajas_list = []
    for item in bajas:
        team = dl.canonical_team_name(item.get('team', ''))
        if not team: continue
        
        # Filtering Logic
        is_active = item.get('is_active_for_next_match', None)
        recency = int(item.get('recency_days', 0))
        
        if is_active is False: continue
        if bool(item.get('is_retired', False)): continue
        if bool(item.get('is_transferred_out', False)): continue
        
        curr_team = dl.canonical_team_name(item.get('current_team', ''))
        if curr_team and curr_team != team: continue
        
        if str(item.get('verification_status', '')).lower() != 'confirmed': continue
        if recency > 21 and is_active is not True: continue
        
        conf = float(item.get('confidence', 0.75))
        if recency > 14 and is_active is not True: conf = min(conf, 0.55)
        
        # Key Player Check
        player = item.get('player', 'Unknown')
        impact = item.get('impact_level', 'Low')
        auto_imp = get_player_importance_level(team, player)
        if auto_imp == 'High': impact = 'High'
        elif auto_imp == 'Mid' and impact == 'Low': impact = 'Mid'
        
        if impact.lower() in ['low', 'none', 'unknown']:
             continue

        bajas_list.append({
            'team': team,
            'player': player,
            'role': item.get('role', ''),
            'status': item.get('status', 'Duda'),
            'impact_level': impact,
            'reason': item.get('reason', ''),
            'confidence': conf,
            'recency_days': recency,
            'source': 'perplexity',
            'raw_data': item
        })
    return bajas_list

def deduplicate_bajas(bajas_list):
    """
    Deduplicates bajas list based on (team, normalized_player).
    Priority: Impact Level > Confidence > Source(Manual>Perplexity)
    """
    unique_map = {}
    
    impact_score = {'High': 3, 'Mid': 2, 'Low': 1, 'None': 0}
    
    for item in bajas_list:
        p_norm = dl.remove_accents(item['player'].lower().strip())
        team = item['team']
        key = (team, p_norm)
        
        if key not in unique_map:
            unique_map[key] = item
        else:
            existing = unique_map[key]
            
            # Compare Scores
            score_new = impact_score.get(item['impact_level'], 0)
            score_old = impact_score.get(existing['impact_level'], 0)
            
            if score_new > score_old:
                unique_map[key] = item
                # print(f"  > Dedup: Replaced {existing['player']} ({existing['impact_level']}) with {item['impact_level']} from {item['source']}")
            elif score_new == score_old:
                # Tie-break: Confidence
                if item['confidence'] > existing['confidence']:
                    unique_map[key] = item
                elif item['confidence'] == existing['confidence']:
                     # Tie-break: Manual wins
                     if item['source'] == 'manual' and existing['source'] != 'manual':
                         unique_map[key] = item
    
    return list(unique_map.values())

def apply_bajas_list(team_adjustments, bajas_list):
    """
    Applies the final deduplicated list of bajas to team_adjustments.
    """
    for item in bajas_list:
        _apply_scaled_adjustment(
            team_adjustments=team_adjustments,
            team_name=item['team'],
            player=item['player'],
            role=item['role'],
            impact_level=item['impact_level'],
            status=item['status'],
            reason=item['reason'],
            source=item['source'],
            confidence=item['confidence'],
            recency_days=item['recency_days']
        )
    return team_adjustments

# === LEGACY ADAPTERS (For backward compatibility if needed, though we will update gen_predicciones) ===

def load_bajas_penalties(file_path="data/inputs/evaluacion_bajas.json"):
    # Now just a wrapper for the new flow if called in isolation (not recommended)
    raw = collect_manual_bajas(file_path)
    adj = {}
    apply_bajas_list(adj, raw)
    return adj

def load_qualitative_adjustments(team_adjustments, qualitative_path="data/inputs/Investigacion_cualitativa_jornada6.json"):
    """
    Loads qualitative context and transfers.
    Updates the team_adjustments dictionary in place.
    """
    if not os.path.exists(qualitative_path):
        print(f"WARNING: {qualitative_path} not found. Skipping qualitative adjustments.")
        return team_adjustments
        
    with open(qualitative_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    lines = content.splitlines()
    current_section = None
    current_team = None
    current_context_type = None
    
    # Initialize keys if missing
    for team in team_adjustments:
        if 'movimientos_txt' not in team_adjustments[team]: team_adjustments[team]['movimientos_txt'] = []
        if 'context_txt' not in team_adjustments[team]: team_adjustments[team]['context_txt'] = []
        if 'report_log' not in team_adjustments[team]: team_adjustments[team]['report_log'] = []
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if "TRANSFERENCIAS" in line: current_section = 'transfers'; continue
        if "CONTEXTO" in line: current_section = 'context'; continue
        if "AUSENCIAS" in line: current_section = 'skip'; continue
        if "NOTAS" in line: current_section = 'skip'; continue
        
        if current_section == 'transfers':
            if "Equipo:" in line:
                tm_match = re.search(r"Equipo:\s*(.*?)\s*\|", line)
                ply_match = re.search(r"Jugador:\s*(.*?)\s*\|", line)
                if tm_match:
                    tm_name = dl.canonical_team_name(tm_match.group(1))
                    ply_name = ply_match.group(1) if ply_match else "Player"
                    
                    if tm_name not in team_adjustments:
                        team_adjustments[tm_name] = {
                            'att_adj': 1.0, 
                            'def_adj': 1.0, 
                            'notes': [], 
                            'report_log': [],
                            'ausencias_txt': [], 
                            'movimientos_txt': [], 
                            'context_txt': []
                        }
                    
                    # Ensure keys exist (if created above they do, if existed from bajas they might not have these specific lists)
                    if 'movimientos_txt' not in team_adjustments[tm_name]: team_adjustments[tm_name]['movimientos_txt'] = []
                    
                    # Apply Transfer Boost
                    team_adjustments[tm_name]['att_adj'] *= 1.02
                    team_adjustments[tm_name]['notes'].append(f"TRANSFER BOOST (+2%): {ply_name}")
                    team_adjustments[tm_name]['movimientos_txt'].append(f"- 🟢 **ALTA ({tm_name.title()}):** {ply_name}")
                    team_adjustments[tm_name]['report_log'].append({
                        'desc': f"BOOST Lambda Propio (Fichaje): {ply_name}", 
                        'pct': 2.0, 
                        'type': 'HOME'
                    })

        elif current_section == 'context':
            if line.startswith("Tipo:"):
                current_context_type = line.replace("Tipo:", "").strip()
            elif line.startswith("Afecta a:"):
                affects_line = line.replace("Afecta a:", "").strip()
                segments = [s.strip() for s in affects_line.split('/')]
                
                for segment in segments:
                    # Strict Regex for Team Matching
                    # We iterate over known aliases to find EXACT word matches
                    # e.g. "San Luis" should not match "Luis" if "Luis" was an alias (it's not but illustrative)
                    # We use word boundaries \b
                    
                    found_team = None
                    # Sort candidates by length desc to match "Atletico San Luis" before "San Luis"
                    candidates = sorted(['pumas', 'america', 'chivas', 'guadalajara', 'cruz azul', 'toluca', 'tigres', 'monterrey', 'pachuca', 'leon', 'santos', 'mazatlan', 'puebla', 'juarez', 'tijuana', 'necaxa', 'san luis', 'queretaro', 'atlas'], key=len, reverse=True)
                    
                    for t_code in candidates:
                         # Regex: \b(pumas)\b case insensitive
                         pattern = r'\b' + re.escape(t_code) + r'\b'
                         if re.search(pattern, segment, re.IGNORECASE):
                             found_team = dl.canonical_team_name(t_code)
                             break # Stop at first longest match
                    
                    if found_team:
                         tm_name = found_team
                         if tm_name not in team_adjustments:
                             # Ensure structure exists
                             _ensure_team_adjustment(team_adjustments, tm_name)

                         if 'context_txt' not in team_adjustments[tm_name]: team_adjustments[tm_name]['context_txt'] = []
                         if 'report_log' not in team_adjustments[tm_name]: team_adjustments[tm_name]['report_log'] = []

                         current_team = tm_name 

                         subtype_match = re.search(r"\(([^)]+)\)", segment)
                         team_subtype = subtype_match.group(1) if subtype_match else (current_context_type or "")
                             
                         if "momentum" in team_subtype.lower() and "crisis" not in team_subtype.lower():
                             team_adjustments[tm_name]['att_adj'] *= 1.05
                             team_adjustments[tm_name]['notes'].append(f"CONTEXT MOMENTUM (+5%): {team_subtype}")
                             team_adjustments[tm_name]['report_log'].append({'desc': f"Contexto: {team_subtype}", 'pct': 5.0, 'type': 'HOME'})
                         elif "crisis" in team_subtype.lower() or ("extrema" in team_subtype.lower() and "crisis" in current_context_type.lower()):
                             team_adjustments[tm_name]['att_adj'] *= 0.95
                             team_adjustments[tm_name]['def_adj'] *= 1.05
                             team_adjustments[tm_name]['notes'].append(f"CONTEXT CRISIS (-5% Att, -5% Def): {team_subtype}")
                             team_adjustments[tm_name]['report_log'].append({'desc': f"Contexto: {team_subtype}", 'pct': -5.0, 'type': 'HOME'})
                             # elif "winning_streak" in team_subtype.lower():
                             #     team_adjustments[tm_name]['att_adj'] *= 1.03
                             #     team_adjustments[tm_name]['notes'].append(f"CONTEXT WINNING STREAK (+3%): {team_subtype}")
                             #     team_adjustments[tm_name]['report_log'].append({'desc': f"Contexto: Buena Forma (5 ganados)", 'pct': 3.0, 'type': 'HOME'})
                             
                             current_team = tm_name

            elif line.startswith("Evidencia:") and current_team:
                evidence = line.replace("Evidencia:", "").strip()
                if 'context_txt' not in team_adjustments[current_team]: team_adjustments[current_team]['context_txt'] = []
                team_adjustments[current_team]['context_txt'].append(f"- ℹ️ **CONTEXTO:** {evidence}")

    return team_adjustments



def _apply_scaled_adjustment(team_adjustments, team_name, player, role, impact_level, status, reason,
                             source='perplexity', confidence=0.75, recency_days=0):
    """
    Aplica ajuste de bajas con factor de confianza y recencia.

    Escala final = confidence * recency_factor
    recency_factor decae linealmente hasta 0.55 en 14 días.
    """
    _ensure_team_adjustment(team_adjustments, team_name)

    role_raw = (role or '')
    role_norm = normalize_role(role_raw)
    status_l = (status or '').lower()

    if (impact_level or '').lower() in ['low', 'none', 'unknown', 'desconocido']:
        # Check for Key Player Override even if source says Low/Unknown
        auto_imp = get_player_importance_level(team_name, player)
        if auto_imp == 'High':
             print(f"⚡ UPGRADE (Perplexity): {player} is ELITE. Force High Impact.")
             impact_level = 'High'
             is_key = True
        elif auto_imp == 'Mid':
             impact_level = 'Mid'
        else:
             return

    is_key = (impact_level or '').lower() == 'high'

    # Jugadores en duda: ignorar completamente — el ruido supera al beneficio
    if 'duda' in status_l:
        return

    impact_factor = 1.0

    recency_days = max(0, min(30, int(recency_days or 0)))
    recency_factor = max(0.55, 1.0 - (recency_days / 31.0) * 0.45)
    scale = max(0.30, min(1.0, float(confidence or 0.75))) * recency_factor

    penalty_att = 1.0
    penalty_def = 1.0
    desc_log = ""
    pct_log = 0.0

    if role_norm == "portero":
        base = PENALTIES['GK_KEY'] if is_key else 1.05
        effect = (base - 1.0) * impact_factor * scale
        penalty_def = 1.0 + effect
        desc_log = f"Lambda Rival (Portero) [{source}]"
        pct_log = effect * 100
        affects = 'AWAY'
    elif role_norm == "defensa":
        base = PENALTIES['DF_KEY'] if is_key else PENALTIES['DF_REG']
        effect = (base - 1.0) * impact_factor * scale
        penalty_def = 1.0 + effect
        desc_log = f"Lambda Rival (Defensa) [{source}]"
        pct_log = effect * 100
        affects = 'AWAY'
    elif role_norm == "medio":
        base = PENALTIES['MF_KEY'] if is_key else PENALTIES['MF_REG']
        effect = (1.0 - base) * impact_factor * scale
        penalty_att = 1.0 - effect
        desc_log = f"Lambda Propio (Medio) [{source}]"
        pct_log = (penalty_att - 1.0) * 100
        affects = 'HOME'
    elif role_norm == "ataque":
        base = PENALTIES['FW_KEY'] if is_key else PENALTIES['FW_REG']
        effect = (1.0 - base) * impact_factor * scale
        penalty_att = 1.0 - effect
        desc_log = f"Lambda Propio (Ataque) [{source}]"
        pct_log = (penalty_att - 1.0) * 100
        affects = 'HOME'
    else:
        # Rol desconocido: ajuste mínimo conservador
        effect = 0.02 * scale * impact_factor
        penalty_att = 1.0 - effect
        desc_log = f"Lambda Propio (Rol no clasificado) [{source}]"
        pct_log = (penalty_att - 1.0) * 100
        affects = 'HOME'

    curr = team_adjustments[team_name]
    curr['att_adj'] *= penalty_att
    curr['def_adj'] *= penalty_def

    icon = "🚑" if "fuera" in status_l or "out" in status_l else "⚠️"
    curr['ausencias_txt'].append(
        f"{icon} **{player}** ({role or 'N/A'}): {status or 'N/A'} - *{reason or 'Sin detalle'}* "
        f"[Impacto: {impact_level}, Confianza:{confidence:.2f}, Recencia:{recency_days}d]"
    )
    
    # Add Structured Item
    curr['ausencias_items'].append({
        'player': player,
        'role': role_norm,
        'status': status,
        'reason': reason,
        'impact_level': impact_level,
        'confidence': confidence,
        'recency_days': recency_days,
        'source': source
    })

    curr['notes'].append(
        f"{source.upper()} | {player} ({role}) impact={impact_level} conf={confidence:.2f} recency={recency_days}d"
    )

    curr['report_log'].append({
        'desc': f"{desc_log}: {player} ({status})",
        'pct': pct_log,
        'type': affects
    })




# === CONTEXT ADJUSTMENTS (Structured Qualitative) ===

VALID_CONTEXT_TYPES = {
    'squad_fatigue',       # Multiple games in short window (Concachampions, Copa, etc.)
    'rotation_expected',   # Coach announced rotation / rest of starters
    'tactical_change',     # New formation, new coach, significant system change
    'suspension',          # Disciplinary (yellow accumulation, red card — NOT injury)
    'motivation_crisis',   # Bad run + management conflict + relegation pressure
    'motivation_boost',    # Must-win derby, historic milestone, home debut of key player
}

def collect_context_adjustments(file_path):
    """
    Loads structured context adjustments from JSON.
    Each entry has team, type, att_adj, def_adj, confidence, evidence.
    Effect is scaled: final_adj = 1.0 + (base_adj - 1.0) * confidence
    Returns list of processed dicts ready to apply.
    """
    if not file_path or not os.path.exists(file_path):
        return []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"WARNING: Could not load context adjustments from {file_path}: {e}")
        return []

    raw_items = data.get('context_adjustments', [])
    if not isinstance(raw_items, list):
        return []

    result = []
    for item in raw_items:
        team = dl.canonical_team_name(item.get('team', ''))
        if not team:
            continue

        ctx_type = item.get('type', 'unknown')
        att_adj_base = float(item.get('att_adj', 1.0))
        def_adj_base = float(item.get('def_adj', 1.0))
        confidence = max(0.30, min(1.0, float(item.get('confidence', 0.75))))

        # Scale effect magnitude by confidence:
        # If att_adj=0.95 and confidence=0.5 → actual effect = 0.975 (half the suppression)
        att_adj_scaled = 1.0 + (att_adj_base - 1.0) * confidence
        def_adj_scaled = 1.0 + (def_adj_base - 1.0) * confidence

        note_text = item.get('notes', item.get('evidence', ''))

        result.append({
            'team': team,
            'match': item.get('match', ''),
            'type': ctx_type,
            'att_adj': att_adj_scaled,
            'def_adj': def_adj_scaled,
            'confidence': confidence,
            'note': note_text,
        })

    return result


def apply_context_adjustments(team_adjustments, context_list):
    """
    Applies structured context adjustments to team_adjustments dict.
    Works on top of existing bajas adjustments — multiplicative.
    """
    for item in context_list:
        team = item['team']
        _ensure_team_adjustment(team_adjustments, team)

        team_adjustments[team]['att_adj'] *= item['att_adj']
        team_adjustments[team]['def_adj'] *= item['def_adj']

        pct_att = (item['att_adj'] - 1.0) * 100
        pct_def = (item['def_adj'] - 1.0) * 100
        note = (
            f"CONTEXT | {item['type']} conf={item['confidence']:.2f}"
            + (f" Att{pct_att:+.1f}%" if abs(pct_att) > 0.1 else "")
            + (f" Def{pct_def:+.1f}%" if abs(pct_def) > 0.1 else "")
            + f": {item['note'][:80]}"
        )
        team_adjustments[team]['notes'].append(note)
        team_adjustments[team]['report_log'].append({
            'desc': f"Contexto ({item['type']}): {item['note'][:60]}",
            'pct': pct_att,
            'type': 'HOME'
        })

    return team_adjustments


def load_perplexity_weekly_bajas(team_adjustments, file_path="data/inputs/perplexity_bajas_semana.json"):
    # This acts as an "Add to existing" in legacy mode, 
    # BUT it won't deduplicate against what's already inside team_adjustments 
    # because team_adjustments is already processed.
    # We strongly recommend using the new flow in gen_predicciones.
    raw = collect_perplexity_bajas(file_path)
    # We can't easily dedup against already applied adjustments without parsing them back.
    # So we simply apply.
    apply_bajas_list(team_adjustments, raw)
    return team_adjustments
