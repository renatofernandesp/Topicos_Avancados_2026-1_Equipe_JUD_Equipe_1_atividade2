"""
Pipeline LLM-as-a-Juiz — delegação para o serviço Gemini (3 juízes + rubrica + BERTScore).

Constantes de rubrica em rubrica.py. Execução em judge_gemini_service.
"""

from rubrica import CRITERIOS, PESOS, calcular_nota_final
from judge_gemini_service import (
    contar_respostas_incompletas,
    contar_tarefas_pendentes,
    executar_juiz_gemini,
    executar_juiz_gemini_stream,
)


def executar_juiz():
    executar_juiz_gemini()


def executar_juiz_stream():
    return executar_juiz_gemini_stream()


__all__ = [
    "CRITERIOS",
    "PESOS",
    "calcular_nota_final",
    "contar_respostas_incompletas",
    "contar_tarefas_pendentes",
    "executar_juiz",
    "executar_juiz_stream",
]
