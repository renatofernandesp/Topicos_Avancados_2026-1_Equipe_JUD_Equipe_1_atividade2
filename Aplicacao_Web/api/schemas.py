"""Schemas Pydantic para a API HTTP do juiz Gemini."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class HealthOut(BaseModel):
    ok: bool
    has_gemini_key: bool


class ModeloJuizOut(BaseModel):
    id_modelo_juiz: int
    nome_exibicao: str
    id_api: str
    provedor: str
    ativo: bool


class ContagensOut(BaseModel):
    perguntas: int
    respostas: int
    avaliacoes: int
    tarefas_juiz_pendentes: int
    respostas_gemini_pendentes: int


class TarefaPendenteOut(BaseModel):
    id_resposta: int
    id_modelo_juiz: int
    id_api_juiz: str
    nome_modelo: str
    versao: str | None = None
    parametro_precisao: str | None = None
    enunciado_preview: str = Field(description="Primeiros caracteres do enunciado.")
    resposta_preview: str = Field(
        default="",
        description="Primeiros caracteres de texto_resposta (respostas_atividade_1).",
    )
    enunciado_completo: str = Field(
        default="",
        description="Texto integral do enunciado (para leitura em modal no frontend).",
    )
    texto_resposta_completo: str = Field(
        default="",
        description="Texto integral de texto_resposta (para leitura em modal no frontend).",
    )


class TarefasPaginaOut(BaseModel):
    total: int
    items: list[TarefaPendenteOut]


class OpcoesFiltroJuizOut(BaseModel):
    modelos_candidatos: list[str]


class ParRespostaJuiz(BaseModel):
    id_resposta: int
    id_modelo_juiz: int


class ExecutarJuizIn(BaseModel):
    ids_resposta: list[int] | None = None
    ids_modelo_juiz: list[int] | None = None
    limite: int | None = Field(default=None, ge=1)
    substituir: bool = False
    pares: list[ParRespostaJuiz] | None = None

    @model_validator(mode="after")
    def substituir_exige_pares(self) -> ExecutarJuizIn:
        if self.substituir and not self.pares:
            raise ValueError("substituir=true exige lista 'pares' não vazia.")
        return self


class ExecutarJuizOut(BaseModel):
    run_id: str
    total_estimado: int


class AvaliacaoHistoricoOut(BaseModel):
    id_avaliacao: int
    modelo_candidato: str | None = None
    modelo_juiz: str | None = None
    enunciado_preview: str
    enunciado_completo: str = ""
    nota_atribuida: float | None = None
    nota_humana: int | None = None
    chain_of_thought_preview: str | None = None
    chain_of_thought_completo: str = ""


class AvaliacoesHistoricoPaginaOut(BaseModel):
    total: int
    items: list[AvaliacaoHistoricoOut]


class PontoCorrelacaoScatter(BaseModel):
    nota_humana: int
    nota_juiz: int


class CorrelacaoJuizHumanoOut(BaseModel):
    """Correlação entre nota do juiz (arredondada) e nota humana; ver analytics.correlacao_juiz_humano."""

    erro: str | None = None
    n_amostras: int | None = None
    spearman_rho: float | None = None
    spearman_p: float | None = None
    kendall_tau: float | None = None
    kendall_p: float | None = None
    cohen_kappa_quadratico: float | None = None
    interpretacao: str | None = None
    eixos_notas: list[int] | None = None
    matriz_confusao: list[list[int]] | None = Field(
        default=None,
        description="Contagens: linha = nota humana, coluna = nota juiz (eixos_notas).",
    )
    scatter_pontos: list[PontoCorrelacaoScatter] | None = None
    scatter_n_total: int | None = None
    scatter_n_plot: int | None = None
    scatter_amostrado: bool | None = None


class JuizEvento(BaseModel):
    """Evento yieldado por executar_juiz_gemini_stream, mais o id da execução."""

    run_id: str
    total: int
    atual: int
    id_resposta: int | None = Field(default=None, alias="id")
    juiz: str | None = None
    nota: float | None = None
    erro: str | None = None
    erro_tipo: str | None = None
    erro_detalhe: str | None = Field(
        default=None,
        description="Traceback truncado se JUDGE_SSE_TRACEBACK=1 no backend.",
    )
    subcrit: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}
