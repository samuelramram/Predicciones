# ===========================================================================
# setup_repo.ps1 — Reset completo + re-init Git + commit inicial + remote
# Uso:
#   cd "C:\Users\Samuel Ramirez\.gemini\antigravity\scratch\Predicciones"
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
#   .\setup_repo.ps1
#
# Notas:
#   - Usa single-quotes en todos los strings para evitar que PowerShell
#     interprete +, (, ), *, $ dentro del mensaje de commit.
#   - Idempotente: puedes correrlo varias veces sin miedo.
#   - NO hace push. El push lo corres tú a mano al final (para que veas
#     el prompt de autenticacion y uses tu PAT).
# ===========================================================================

$ErrorActionPreference = 'Stop'

# ----- Configuracion -----
$RepoUrl       = 'https://github.com/samuelramram/Predicciones.git'
$GitUserName   = 'Samuel Ramirez'
$GitUserEmail  = 'samuelram93@gmail.com'
$CommitTitle   = 'init: Predicciones Liga MX - modelo quiniela Clausura 2026 hasta J10'
$CommitBody    = 'Restauracion del repo tras bloqueo de cuenta anterior. Core del modelo: Poisson con Dixon-Coles, shrinkage bayesiano multi-torneo, integracion xG y xPTS regression, optimizador de EV de quiniela, pipeline de 3 pasos, evaluador e inputs manuales hasta Jornada 10 Clausura 2026.'

# ===========================================================================
# Paso 1: Limpieza de archivos temporales
# ===========================================================================
Write-Host ''
Write-Host '===> Paso 1: Limpieza de temporales' -ForegroundColor Cyan

$dirsToRemove = @(
    '.venv',
    '.pytest_cache',
    '__pycache__',
    'app\steps\__pycache__',
    'scripts\__pycache__',
    'src\__pycache__',
    'src\predicciones\__pycache__',
    'tests\__pycache__'
)
foreach ($d in $dirsToRemove) {
    if (Test-Path $d) {
        Remove-Item -Recurse -Force $d
        Write-Host "  removed dir : $d"
    }
}

$filesToRemove = @(
    'debug_investigation.txt',
    'debug_output.txt',
    'gen_predicciones_log.txt',
    'pipeline_log.txt',
    'pipeline_run_output.txt',
    'test_output.txt'
)
foreach ($f in $filesToRemove) {
    if (Test-Path $f) {
        Remove-Item -Force $f
        Write-Host "  removed file: $f"
    }
}

# Reportes sueltos en raiz (los buenos estan en outputs/)
$rootReports = Get-ChildItem -Path '.' -Filter 'reporte_tecnico_jornada_*.md' -File -ErrorAction SilentlyContinue
foreach ($r in $rootReports) {
    Remove-Item -Force $r.FullName
    Write-Host "  removed file: $($r.Name)"
}

# ===========================================================================
# Paso 2: Re-init de Git
# ===========================================================================
Write-Host ''
Write-Host '===> Paso 2: Re-inicializando Git' -ForegroundColor Cyan

if (Test-Path '.git') {
    Remove-Item -Recurse -Force '.git'
    Write-Host '  .git viejo eliminado'
}

git init -b main | Out-Null
git config user.name  $GitUserName
git config user.email $GitUserEmail
Write-Host "  user.name  = $GitUserName"
Write-Host "  user.email = $GitUserEmail"

# Desactivar pager de less para que no te atrape la terminal
git config --global pager.log    false
git config --global pager.diff   false
git config --global pager.branch false

# ===========================================================================
# Paso 3: Stage + Commit inicial
# ===========================================================================
Write-Host ''
Write-Host '===> Paso 3: Stage + commit inicial' -ForegroundColor Cyan

git add .

# Nota: pasamos los mensajes por variable ya en single-quote para evitar
# interpretacion de PowerShell.
git commit -m $CommitTitle -m $CommitBody | Out-Host

Write-Host ''
Write-Host '===> Log local:' -ForegroundColor Cyan
git log --oneline

# ===========================================================================
# Paso 4: Configurar remote
# ===========================================================================
Write-Host ''
Write-Host '===> Paso 4: Remote' -ForegroundColor Cyan

# Si ya existia un remote origin, lo quitamos y re-creamos
$existingRemote = git remote 2>$null
if ($existingRemote -contains 'origin') {
    git remote remove origin
    Write-Host '  remote origin previo eliminado'
}
git remote add origin $RepoUrl
git branch -M main
Write-Host "  origin -> $RepoUrl"

# ===========================================================================
# Listo
# ===========================================================================
Write-Host ''
Write-Host '==================================================================' -ForegroundColor Green
Write-Host ' LISTO. Ahora haz el push a mano:' -ForegroundColor Green
Write-Host '==================================================================' -ForegroundColor Green
Write-Host ''
Write-Host '  git push -u origin main' -ForegroundColor Yellow
Write-Host ''
Write-Host ' Si te pide usuario/password:' -ForegroundColor Gray
Write-Host '   Username: samuelramram'
Write-Host '   Password: usa un Personal Access Token (NO tu contrasena real)'
Write-Host '            genera uno en: https://github.com/settings/tokens'
Write-Host '            scope: repo   |   expiration: 90 dias'
Write-Host ''
Write-Host ' Si el repo remoto ya tiene commits:' -ForegroundColor Gray
Write-Host '   git push -u origin main --force'
Write-Host ''
