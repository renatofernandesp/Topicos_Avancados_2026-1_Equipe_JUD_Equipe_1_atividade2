import pandas as pd

# Dados de teste
dados = [
    {
        "dataset": "OAB_Exame",
        "dominio": "Jurídico",
        "enunciado": "Qual é o prazo prescricional para ação de cobrança de dívida ativa tributária?",
        "resposta_ouro": "O prazo prescricional para cobrança de dívida ativa tributária é de 5 anos, conforme art. 174 do CTN.",
        "modelo": "GPT-4",
        "versao": "turbo",
        "precisao": "FP16",
        "texto_resposta": "O prazo é de 5 anos contados da constituição definitiva do crédito tributário, conforme previsto no Código Tributário Nacional.",
        "tempo_inferencia_ms": 1200,
        "nota_humana": 5
    },
    {
        "dataset": "OAB_Exame",
        "dominio": "Jurídico",
        "enunciado": "O que caracteriza o crime de estelionato?",
        "resposta_ouro": "Estelionato é obter vantagem ilícita mediante fraude, induzindo ou mantendo alguém em erro (art. 171 CP).",
        "modelo": "GPT-4",
        "versao": "turbo",
        "precisao": "FP16",
        "texto_resposta": "É quando alguém engana outra pessoa para conseguir dinheiro ou bens.",
        "tempo_inferencia_ms": 800,
        "nota_humana": 3
    },
    {
        "dataset": "ENEM",
        "dominio": "Biologia",
        "enunciado": "Explique o processo de fotossíntese.",
        "resposta_ouro": "Fotossíntese é o processo pelo qual plantas convertem luz solar, água e CO2 em glicose e oxigênio, ocorrendo nos cloroplastos.",
        "modelo": "Claude",
        "versao": "3.5",
        "precisao": "FP32",
        "texto_resposta": "As plantas usam luz solar para produzir açúcar e liberar oxigênio através dos cloroplastos nas folhas.",
        "tempo_inferencia_ms": 950,
        "nota_humana": 4
    }
]

# Criar DataFrame e salvar
df = pd.DataFrame(dados)
df.to_excel("teste_dados.xlsx", index=False)
print("✅ Arquivo 'teste_dados.xlsx' criado com sucesso!")
print(f"📊 {len(dados)} linhas de teste")
