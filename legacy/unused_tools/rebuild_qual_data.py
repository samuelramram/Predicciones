import json

# Reconstruir investigación cualitativa con el campo "role" correcto para todas las ausencias
data = {
    "jornada": 6,
    "tournament": "Liga MX Clausura 2026",
    "note": "Investigación cualitativa completa - 9 partidos de Jornada 6",
    "extracted_date": "2026-02-09",
    "matches": [
        {
            "match_id": 1,
            "home": "Puebla",
            "away": "Pumas",
            "absences": {
                "home": [
                    {
                        "name": "Lucas Cavallini",
                        "role": "atacante",
                        "importance": "media",
                        "note": "Lesión de ligamento cruzado anterior, regresa finales de marzo 2026"
                    }
                ],
                "away": [
                    {
                        "name": "José Juan Macías",
                        "role": "atacante",
                        "importance": "alta",
                        "note": "Lesión de rodilla desde pausa invernal, sin fecha de regreso"
                    },
                    {
                        "name": "Pablo Bennevendo",
                        "role": "defensor",
                        "importance": "alta",
                        "note": "Lesión no especificada, lateral derecho fuera"
                    },
                    {
                        "name": "Santiago Trigos",
                        "role": "mediocampista",
                        "importance": "media",
                        "note": "Lesión no especificada"
                    }
                ]
            },
            "roster_changes": {
                "home": [
                    {
                        "type": "transfer_in",
                        "name": "Alonso Ramírez",
                        "role": "defensor",
                        "weeks_since": 5,
                        "note": "Llegó en enero 2026"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Emilio Orrantia",
                        "role": "mediocampista",
                        "weeks_since": 5,
                        "note": "Llegó en enero 2026"
                    }
                ],
                "away": [
                    {
                        "type": "transfer_in",
                        "name": "Uriel Antuna",
                        "role": "mediocampista",
                        "weeks_since": 2,
                        "note": "Llegó desde Tigres el 29 ene, extremo de Selección Mexicana"
                    },
                    {
                        "type": "transfer_out",
                        "name": "Jorge Ruvalcaba",
                        "role": "mediocampista",
                        "weeks_since": 1,
                        "note": "Vendido a New York Red Bulls (MLS)"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Tony Leone",
                        "role": "defensor",
                        "weeks_since": 5,
                        "note": "Llegó en enero 2026"
                    }
                ]
            },
            "competitive_context": [
                {
                    "side": "away",
                    "factor": "defensive_crisis",
                    "note": "Pumas con 3 bajas en defensa/medio (2 laterales), usa jugadores de emergencia. JJ Macías fuera, Antuna debe compensar salida de Ruvalcaba"
                }
            ]
        },
        {
            "match_id": 2,
            "home": "Toluca",
            "away": "Tijuana",
            "absences": {
                "home": [
                    {
                        "name": "Alexis Vega",
                        "role": "atacante",
                        "importance": "alta",
                        "status": "duda",
                        "note": "Desgarro muscular y molestias en rodilla, se ausentará primeras jornadas para rehabilitarse"
                    },
                    {
                        "name": "Helinho",
                        "role": "atacante",
                        "importance": "media",
                        "status": "duda",
                        "note": "Lesión por distensión"
                    }
                ],
                "away": [
                    {
                        "name": "Gilberto Mora",
                        "role": "mediocampista",
                        "importance": "media",
                        "status": "duda",
                        "note": "Lesión en la ingle"
                    }
                ]
            },
            "roster_changes": {
                "home": [
                    {
                        "type": "transfer_in",
                        "name": "Sebastián Córdova",
                        "role": "mediocampista",
                        "weeks_since": 6,
                        "note": "Llegó 2 ene como agente libre desde Tigres, refuerzo de jerarquía para compensar ausencia de Vega"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Pavel Pérez",
                        "role": "mediocampista",
                        "weeks_since": 5,
                        "note": "Llegó en enero 2026"
                    }
                ],
                "away": [
                    {
                        "type": "transfer_in",
                        "name": "Josef Martínez",
                        "role": "atacante",
                        "weeks_since": 5,
                        "note": "Llegó 6 ene desde San José Earthquakes (MLS), experimentado goleador venezolano"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Ignacio Rivero",
                        "role": "mediocampista",
                        "weeks_since": 1,
                        "note": "Llegó en febrero 2026"
                    }
                ]
            },
            "competitive_context": [
                {
                    "side": "away",
                    "factor": "momentum",
                    "note": "Tijuana invicto con 1V-3E en 5 jornadas (7 pts), uno de los mejores arranques en años. Josef Martínez ya adaptado"
                }
            ]
        },
        {
            "match_id": 3,
            "home": "Atletico de San Luis",
            "away": "Queretaro FC",
            "absences": {
                "home": [],
                "away": []
            },
            "roster_changes": {
                "home": [
                    {
                        "type": "transfer_in",
                        "name": "Santiago Muñoz",
                        "role": "atacante",
                        "weeks_since": 5,
                        "note": "Llegó en enero 2026, joven promesa mexicana"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Fidel Barajas",
                        "role": "atacante",
                        "weeks_since": 5,
                        "note": "Llegó en enero 2026"
                    }
                ],
                "away": []
            },
            "competitive_context": [
                {
                    "side": "away",
                    "factor": "momentum",
                    "note": "Querétaro consiguió su 1ra victoria del torneo en J5 (2-0 vs León), rompiendo racha negativa de 5 meses sin ganar"
                }
            ]
        },
        {
            "match_id": 4,
            "home": "Pachuca",
            "away": "Atlas",
            "absences": {
                "home": [
                    {
                        "name": "Alan Mozo",
                        "role": "defensor",
                        "importance": "alta",
                        "note": "Fractura helicoidal de peroné + esguince grado 2, FUERA RESTO DEL TORNEO (5 meses)"
                    },
                    {
                        "name": "Enner Valencia",
                        "role": "atacante",
                        "importance": "alta",
                        "status": "duda",
                        "note": "Recaída isquiotibiales, +2 meses sin jugar, fuera al menos 2+ semanas adicionales"
                    },
                    {
                        "name": "Elías Montiel",
                        "role": "mediocampista",
                        "importance": "media",
                        "status": "duda",
                        "note": "Desgarro femoral, estimado 3 semanas de baja"
                    }
                ],
                "away": []
            },
            "roster_changes": {
                "home": [
                    {
                        "type": "transfer_in",
                        "name": "René López",
                        "role": "defensor",
                        "weeks_since": 0.7,
                        "note": "FICHAJE DE EMERGENCIA 4 feb - Regresa desde Expansión para cubrir baja de Mozo"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Salomón Rondón",
                        "role": "atacante",
                        "weeks_since": 5,
                        "note": "Regreso desde Real Oviedo"
                    }
                ],
                "away": [
                    {
                        "type": "transfer_in",
                        "name": "Agustín Rodríguez",
                        "role": "atacante",
                        "weeks_since": 0.14,
                        "note": "Fichado 8 feb desde Uruguay, 18 goles en 2025, reemplaza a Djuka - PUEDE DEBUTAR"
                    },
                    {
                        "type": "transfer_out",
                        "name": "Uroš Djuka",
                        "role": "atacante",
                        "weeks_since": 0.57,
                        "note": "Vendido a Monterrey, campeón de goleo Clausura 2025"
                    }
                ]
            },
            "competitive_context": [
                {
                    "side": "home",
                    "factor": "crisis_squad",
                    "note": "Pachuca severamente golpeado: Mozo fuera resto torneo, Valencia y Montiel dudas. René López fichado de emergencia"
                },
                {
                    "side": "away",
                    "factor": "momentum",
                    "note": "Atlas 4to lugar con 9 pts (3V-0E-1D), viene de empatar 2-2 vs Pumas"
                }
            ]
        },
        {
            "match_id": 5,
            "home": "Monterrey",
            "away": "Leon",
            "absences": {
                "home": [],
                "away": [
                    {
                        "name": "Sebastián Vegas",
                        "role": "defensor",
                        "importance": "alta",
                        "note": "Expulsado J5 vs Querétaro (doble amarilla min 62), cumple suspensión automática 1 partido"
                    }
                ]
            },
            "roster_changes": {
                "home": [
                    {
                        "type": "transfer_in",
                        "name": "Uroš Djuka",
                        "role": "atacante",
                        "weeks_since": 0.57,
                        "note": "Fichaje bomba 5 feb desde Atlas, campeón de goleo Clausura 2025 (22 goles en 4 torneos), disponible de inmediato"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Luca Orellano",
                        "role": "mediocampista",
                        "weeks_since": 5,
                        "note": "Llegó desde FC Cincinnati (MLS) en enero"
                    },
                    {
                        "type": "transfer_out",
                        "name": "Germán Berterame",
                        "role": "atacante",
                        "weeks_since": 2,
                        "note": "Vendido a Inter Miami (MLS)"
                    }
                ],
                "away": [
                    {
                        "type": "transfer_in",
                        "name": "Díber Cambindo",
                        "role": "atacante",
                        "weeks_since": 7,
                        "note": "Llegó desde Necaxa en diciembre 2025"
                    }
                ]
            },
            "competitive_context": [
                {
                    "side": "home",
                    "factor": "momentum",
                    "note": "Monterrey incorporó a Djuka (campeón goleo, 22 goles). Dupla letal con Orellano"
                },
                {
                    "side": "away",
                    "factor": "pressure",
                    "note": "León lugar 16 con 4 pts (1V-1E-3D), PEOR INICIO DESDE 2012. Perdió 2-0 vs Querétaro en J5"
                }
            ]
        },
        {
            "match_id": 6,
            "home": "FC Juarez",
            "away": "Necaxa",
            "absences": {
                "home": [
                    {
                        "name": "Jonathan González",
                        "role": "mediocampista",
                        "importance": "media",
                        "note": "Lesión"
                    }
                ],
                "away": []
            },
            "roster_changes": {
                "home": [
                    {
                        "type": "transfer_in",
                        "name": "Ramón Rodríguez",
                        "role": "mediocampista",
                        "weeks_since": 0.43,
                        "note": "Confirmado 6 feb, español cedido desde Aris (Grecia), formado en La Masía"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Javier Aquino",
                        "role": "mediocampista",
                        "weeks_since": 5,
                        "note": "Llegó desde Tigres en enero"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Luca Martínez Dupuy",
                        "role": "atacante",
                        "weeks_since": 5,
                        "note": "Llegó en enero 2026"
                    }
                ],
                "away": [
                    {
                        "type": "transfer_in",
                        "name": "Javier Ruiz",
                        "role": "mediocampista",
                        "weeks_since": 0.57,
                        "note": "Confirmado 5 feb desde Independiente (Argentina)"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Julián Carranza",
                        "role": "atacante",
                        "weeks_since": 5,
                        "note": "Llegó desde Feyenoord en enero"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Lorenzo Faravelli",
                        "role": "mediocampista",
                        "weeks_since": 5,
                        "note": "Llegó desde Cruz Azul"
                    }
                ]
            },
            "competitive_context": [
                {
                    "side": "away",
                    "factor": "momentum",
                    "note": "Necaxa goleó 4-1 a San Luis en J5, llega con impulso ofensivo renovado"
                }
            ]
        },
        {
            "match_id": 7,
            "home": "CD Guadalajara",
            "away": "CF America",
            "absences": {
                "home": [
                    {
                        "name": "Luis Romo",
                        "role": "mediocampista",
                        "importance": "alta",
                        "note": "Lesión muscular muslo derecho vs Mazatlán J5, CONFIRMADO FUERA. Capitán y cerebro del mediocampo"
                    },
                    {
                        "name": "Armando González",
                        "role": "atacante",
                        "importance": "alta",
                        "status": "duda",
                        "note": "Salió tocado vs Mazatlán"
                    },
                    {
                        "name": "José Castillo",
                        "role": "defensor",
                        "importance": "media",
                        "status": "duda",
                        "note": "Salió tocado vs Mazatlán"
                    },
                    {
                        "name": "Gilberto Sepúlveda",
                        "role": "defensor",
                        "importance": "media",
                        "status": "duda",
                        "note": "Fase final de recuperación de lesión previa"
                    },
                    {
                        "name": "Érick Gutiérrez",
                        "role": "mediocampista",
                        "importance": "media",
                        "note": "Descartado por cuestiones de disciplina"
                    },
                    {
                        "name": "Alan Pulido",
                        "role": "atacante",
                        "importance": "media",
                        "note": "Descartado por cuestiones de disciplina"
                    }
                ],
                "away": []
            },
            "roster_changes": {
                "home": [
                    {
                        "type": "transfer_in",
                        "name": "Jonathan Pérez",
                        "role": "mediocampista",
                        "weeks_since": 0.29,
                        "note": "Confirmado 7 feb desde Nashville SC (MLS)"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Ángel Sepúlveda",
                        "role": "atacante",
                        "weeks_since": 5,
                        "note": "Llegó cedido desde Cruz Azul"
                    }
                ],
                "away": [
                    {
                        "type": "transfer_in",
                        "name": "Raphael Veiga",
                        "role": "mediocampista",
                        "weeks_since": 0.86,
                        "note": "Confirmado 3 feb desde Palmeiras (Brasil), disponible de inmediato"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Rodrigo Dourado",
                        "role": "mediocampista",
                        "weeks_since": 5,
                        "note": "Llegó en enero 2026"
                    },
                    {
                        "type": "transfer_out",
                        "name": "Rodrigo Aguirre",
                        "role": "atacante",
                        "weeks_since": 0.57,
                        "note": "Transferido a Tigres"
                    }
                ]
            },
            "competitive_context": [
                {
                    "side": "home",
                    "factor": "momentum",
                    "note": "Chivas LÍDER INVICTO 15 pts (5V-0E-0D), presión enorme por mantener invicto ante América"
                },
                {
                    "side": "away",
                    "factor": "pressure",
                    "note": "Jardine bajo ultimátum de directiva por mal inicio (5 pts en 5 jornadas)"
                }
            ]
        },
        {
            "match_id": 8,
            "home": "Santos Laguna",
            "away": "Mazatlan FC",
            "absences": {
                "home": [],
                "away": []
            },
            "roster_changes": {
                "home": [
                    {
                        "type": "transfer_in",
                        "name": "Lucas Di Yorio",
                        "role": "atacante",
                        "weeks_since": 5,
                        "note": "Llegó en enero 2026"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Ezequiel Bullaude",
                        "role": "mediocampista",
                        "weeks_since": 5,
                        "note": "Llegó en enero 2026"
                    }
                ],
                "away": [
                    {
                        "type": "transfer_in",
                        "name": "Leo Suárez",
                        "role": "mediocampista",
                        "weeks_since": 1,
                        "note": "Llegó en febrero 2026"
                    }
                ]
            },
            "competitive_context": [
                {
                    "side": "home",
                    "factor": "crisis_squad",
                    "note": "Santos ÚLTIMO LUGAR con 1 pt en 5 J (0V-1E-4D), dif goles -12"
                },
                {
                    "side": "away",
                    "factor": "crisis_squad",
                    "note": "Mazatlán lugar 18 con 0 pts en 5 J (0V-0E-5D), ÚNICO EQUIPO SIN SUMAR"
                }
            ]
        },
        {
            "match_id": 9,
            "home": "Cruz Azul",
            "away": "Tigres",
            "absences": {
                "home": [
                    {
                        "name": "Jesús Orozco Chiquete",
                        "role": "defensor",
                        "importance": "alta",
                        "note": "Baja definitiva, no registrado para Concachampions"
                    },
                    {
                        "name": "Kevin Mier",
                        "role": "portero",
                        "importance": "alta",
                        "note": "Fractura de tibia, baja definitiva, no registrado Concachampions"
                    }
                ],
                "away": [
                    {
                        "name": "Marco Farfán",
                        "role": "defensor",
                        "importance": "media",
                        "note": "Lesión"
                    }
                ]
            },
            "roster_changes": {
                "home": [
                    {
                        "type": "transfer_in",
                        "name": "Nicolás Ibáñez",
                        "role": "atacante",
                        "weeks_since": 0,
                        "note": "CONFIRMADO HOY 9 feb - PROBABLEMENTE NO DISPONIBLE J6"
                    },
                    {
                        "type": "transfer_in",
                        "name": "Christian Ebere",
                        "role": "atacante",
                        "weeks_since": 0.43,
                        "note": "Confirmado 6 feb desde Nacional (Uruguay)"
                    }
                ],
                "away": [
                    {
                        "type": "transfer_in",
                        "name": "Rodrigo Aguirre",
                        "role": "atacante",
                        "weeks_since": 0.43,
                        "note": "Confirmado 6 feb desde América, DISPONIBLE DE INMEDIATO"
                    },
                    {
                        "type": "transfer_out",
                        "name": "Nicolás Ibáñez",
                        "role": "atacante",
                        "weeks_since": 0,
                        "note": "Sale a Cruz Azul en préstamo"
                    }
                ]
            },
            "competitive_context": [
                {
                    "side": "home",
                    "factor": "concacaf_load",
                    "note": "Cruz Azul jugó Concachampions el 12 feb, partido Liga MX el 15 feb, SOLO 3 DÍAS DESCANSO"
                },
                {
                    "side": "away",
                    "factor": "concacaf_load",
                    "note": "Tigres jugó Concachampions el 10 feb, 7 partidos en 29 días"
                }
            ]
        }
    ]
}

# Guardar con el formato correcto
with open('Investigacion_cualitativa_jornada6.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("✓ Investigación cualitativa reconstruida con campo 'role' para todas las ausencias")
