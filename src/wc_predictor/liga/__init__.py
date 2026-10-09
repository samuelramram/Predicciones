"""Liga de bots: varios pronosticadores (y Samuel) compiten en la misma quiniela.

Cada bot emite, por partido, una distribución 1X2 y un boleto (1X2 + marcador).
Se califican con las reglas reales del pool (2 exacto / 1 resultado), con Brier y
log-loss sobre sus probabilidades, y con un bankroll FICTICIO apostado contra la
línea de cierre. Los picks de cada jornada se sellan (SHA-256 + timestamp) antes
del primer partido para que nadie — ni un bot — pueda cambiarlos después.

Módulos:
    bots     — quiénes compiten y cómo pican
    scoring  — puntos de quiniela, Brier, log-loss, bankroll ficticio
    seal     — sellado y verificación de boletos
"""
