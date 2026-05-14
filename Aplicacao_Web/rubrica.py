"""Pesos da rubrica multidimensional e cálculo da nota final (1.0–5.0)."""

PESOS = {
    "correcao_factual": 0.30,
    "completude": 0.25,
    "clareza": 0.20,
    "coerencia": 0.15,
    "relevancia": 0.10,
}

CRITERIOS = tuple(PESOS.keys())


def calcular_nota_final(resultado: dict) -> float:
    """Média ponderada das notas inteiras por critério."""
    return round(
        sum(resultado[c]["nota"] * p for c, p in PESOS.items()),
        2,
    )
