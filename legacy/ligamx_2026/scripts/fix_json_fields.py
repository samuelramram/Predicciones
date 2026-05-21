#!/usr/bin/env python3
"""
Script para agregar campos faltantes a jornada JSON
Agrega:
- evidence_level a absences
- evidence_level a roster_changes  
- team a competitive_context (requiere análisis manual del claim)
"""
import json
import sys
from pathlib import Path

def add_evidence_level(items, default="medio_top"):
    """Add evidence_level to items if missing"""
    for item in items:
        if "evidence_level" not in item:
            item["evidence_level"] = default
    return items

def analyze_context_team(claim_text, home_team, away_team):
    """
    Intenta determinar qué equipo es afectado por el contexto
    basado en el texto del claim.
    """
    claim_lower = claim_text.lower()
    home_lower = home_team.lower()
    away_lower = away_team.lower()
    
    # Si menciona explícitamente al equipo
    if home_lower in claim_lower and away_lower not in claim_lower:
        return "home"
    elif away_lower in claim_lower and home_lower not in claim_lower:
        return "away"
    
    # Heurísticas comunes
    # Contextos negativos (fatigue, crisis, pressure) típicamente afectan al equipo mencionado
    # Momentum positivo también
    
    # Si no podemos determinar, devolvemos None para manual review
    return None

def fix_json_fields(input_file, output_file=None):
    """Add missing fields to JSON"""
    
    if output_file is None:
        output_file = input_file.replace(".json", "_fixed.json")
    
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    needs_manual_review = []
    
    for i, match in enumerate(data.get("matches", [])):
        match_info = match.get("match", {})
        home_team = match_info.get("home", "")
        away_team = match_info.get("away", "")
        match_id = f"{home_team} vs {away_team}"
        
        print(f"\n[*] Processing: {match_id}")
        
        # Fix absences
        absences = match.get("absences", {})
        for side in ["home", "away"]:
            if side in absences:
                before_count = len([a for a in absences[side] if "evidence_level" in a])
                absences[side] = add_evidence_level(absences[side], "medio_top")
                after_count = len([a for a in absences[side] if "evidence_level" in a])
                if after_count > before_count:
                    print(f"  [+] Added evidence_level to {after_count - before_count} {side} absences")
        
        # Fix roster_changes
        roster_changes = match.get("roster_changes", {})
        for side in ["home", "away"]:
            if side in roster_changes:
                before_count = len([r for r in roster_changes[side] if "evidence_level" in r])
                roster_changes[side] = add_evidence_level(roster_changes[side], "medio_top")
                after_count = len([r for r in roster_changes[side] if "evidence_level" in r])
                if after_count > before_count:
                    print(f"  [+] Added evidence_level to {after_count - before_count} {side} roster_changes")
        
        # Fix competitive_context (más complejo - requiere análisis)
        context_items = match.get("competitive_context", [])
        for ctx in context_items:
            if "team" not in ctx or ctx.get("team") is None:
                claim = ctx.get("claim", "")
                detected_team = analyze_context_team(claim, home_team, away_team)
                
                if detected_team:
                    ctx["team"] = detected_team
                    print(f"  [+] Auto-detected team '{detected_team}' for context: {ctx.get('type')}")
                else:
                    # Marcar para revisión manual
                    needs_manual_review.append({
                        "match_id": match_id,
                        "context_type": ctx.get("type"),
                        "claim": claim
                    })
                    # Por ahora, usar heurística conservadora
                    # Presión/crisis típicamente afecta al equipo que juega mal
                    # Si no sabemos, dejamos None para que genere warning
                    print(f"  [!] NEEDS MANUAL REVIEW: {ctx.get('type')} - '{claim[:60]}...'")
    
    # Save fixed JSON
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    
    print(f"\n[+] Fixed JSON saved to: {output_file}")
    
    if needs_manual_review:
        print(f"\n[!] {len(needs_manual_review)} context items need manual team assignment:")
        for item in needs_manual_review:
            print(f"  - {item['match_id']}: {item['context_type']}")
            print(f"    Claim: {item['claim'][:80]}...")
    
    return output_file

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fix_json_fields.py <input_json>")
        print("Example: python fix_json_fields.py data/processed/jornada_5_final.json")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    fix_json_fields(input_file, output_file)
