
import hashlib
import json
import os
import subprocess

def calculate_file_hash(filepath):
    """Calcula SHA256 de un archivo."""
    if not os.path.exists(filepath):
        return "FILE_NOT_FOUND"
    
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def calculate_config_hash(config):
    """
    Hash de parámetros críticos del modelo que afectan prior.
    Usado para cache invalidation.
    """
    critical_params = {
        'BAYES_ALPHA_ATT': config['BAYES_ALPHA_ATT'],
        'BAYES_ALPHA_DEF': config['BAYES_ALPHA_DEF'],
        'BLEND_K': config['BLEND_K'],
        'LEAGUE_AVG_K': config['LEAGUE_AVG_K'],
        'BAYES_K': config['BAYES_K'],
        'CLAMP_REL_MIN': config['CLAMP_REL_MIN'],
        'CLAMP_REL_MAX': config['CLAMP_REL_MAX'],
        'PRIOR_TOURNAMENTS': config['PRIOR_TOURNAMENTS'],
    }
    hash_str = json.dumps(critical_params, sort_keys=True).encode()
    return hashlib.sha256(hash_str).hexdigest()[:8]  # 8 chars suficientes

def save_prior_cache(prior_stats, config, cache_dir='data/processed'):
    """
    Guarda prior multi-torneo con hash de config.
    
    Args:
        prior_stats (dict): Resultado de build_weighted_prior_stats()
        config (dict): Configuración del modelo
        cache_dir (str): Directorio de caché
    
    Returns:
        str: Path del archivo de caché guardado
    """
    os.makedirs(cache_dir, exist_ok=True)
    config_hash = calculate_config_hash(config)
    cache_path = os.path.join(cache_dir, f'prior_cache_{config_hash}.json')
    
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(prior_stats, f, indent=2)
    
    print(f"✅ Prior cache guardado: {cache_path}")
    return cache_path

def load_prior_cache(config, cache_dir='data/processed'):
    """
    Carga prior multi-torneo si hash de config coincide.
    
    Args:
        config (dict): Configuración del modelo
        cache_dir (str): Directorio de caché
    
    Returns:
        dict | None: Prior stats si existe y hash coincide, None otherwise
    """
    config_hash = calculate_config_hash(config)
    cache_path = os.path.join(cache_dir, f'prior_cache_{config_hash}.json')
    
    if os.path.exists(cache_path):
        with open(cache_path, 'r', encoding='utf-8') as f:
            prior_stats = json.load(f)
        print(f"✅ Prior cache cargado: {cache_path}")
        return prior_stats
    
    print(f"⚠️ Prior cache no encontrado, se calculará: {cache_path}")
    return None

def get_git_commit():
    """Obtiene commit hash actual de git."""
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], 
                                       stderr=subprocess.DEVNULL).decode().strip()
    except:
        return None

def is_git_dirty():
    """Verifica si hay cambios no commiteados."""
    try:
        result = subprocess.check_output(['git', 'status', '--porcelain'], 
                                         stderr=subprocess.DEVNULL).decode()
        return len(result.strip()) > 0
    except:
        return None
