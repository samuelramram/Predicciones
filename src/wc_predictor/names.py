"""Team-name mapping between the data layer (English, martj42/openfootball) and
the presentation / webapp layer (Spanish, Lovable app exports).

The model, Elo, CSV and JSON artifacts keep the English source-of-truth names;
Spanish is used for the .md report and for parsing the pool app's CSV exports
(`ingest.pool_picks`).
"""
from __future__ import annotations

# English (source of truth) → Spanish (app / report)
TEAM_ES = {
    "Mexico": "México", "South Africa": "Sudáfrica", "Czech Republic": "República Checa",
    "South Korea": "Corea del Sur", "Canada": "Canadá", "Switzerland": "Suiza",
    "Bosnia and Herzegovina": "Bosnia y Herzegovina", "Bosnia & Herzegovina": "Bosnia y Herzegovina",
    "Qatar": "Catar", "Brazil": "Brasil", "Scotland": "Escocia", "Morocco": "Marruecos",
    "Haiti": "Haití", "United States": "Estados Unidos", "Australia": "Australia",
    "Paraguay": "Paraguay", "Turkey": "Turquía", "Germany": "Alemania", "Ecuador": "Ecuador",
    "Ivory Coast": "Costa de Marfil", "Curaçao": "Curazao", "Netherlands": "Países Bajos",
    "Sweden": "Suecia", "Japan": "Japón", "Tunisia": "Túnez", "Belgium": "Bélgica",
    "Egypt": "Egipto", "Iran": "Irán", "New Zealand": "Nueva Zelanda", "Spain": "España",
    "Uruguay": "Uruguay", "Saudi Arabia": "Arabia Saudita", "Cape Verde": "Cabo Verde",
    "France": "Francia", "Senegal": "Senegal", "Norway": "Noruega", "Iraq": "Irak",
    "Argentina": "Argentina", "Austria": "Austria", "Algeria": "Argelia", "Jordan": "Jordania",
    "Portugal": "Portugal", "Colombia": "Colombia", "DR Congo": "RD Congo",
    "Uzbekistan": "Uzbekistán", "England": "Inglaterra", "Croatia": "Croacia",
    "Ghana": "Ghana", "Panama": "Panamá",
}

# Spanish → English. "Bosnia y Herzegovina" maps back to the openfootball
# spelling used in fixtures.json ("Bosnia and Herzegovina").
TEAM_EN = {es: en for en, es in TEAM_ES.items() if en != "Bosnia & Herzegovina"}


def team_es(name: str) -> str:
    """English → Spanish display name; identity when unmapped."""
    return TEAM_ES.get(name, name)


def team_en(name: str) -> str:
    """Spanish (app export) → English source-of-truth name; identity when unmapped."""
    return TEAM_EN.get(name.strip(), name.strip())
