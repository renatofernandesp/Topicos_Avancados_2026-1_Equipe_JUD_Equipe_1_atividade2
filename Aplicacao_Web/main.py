"""
Orquestrador do pipeline LLM-as-a-Juiz.

Uso:
  python main.py <caminho_planilha.xlsx>   # importa + avalia + analisa
  python main.py --only-judge              # só avalia pendentes (Gemini)
  python main.py --only-analytics          # só exibe relatório
"""

import sys
from schema    import create_schema
from importer  import importar_excel
from judge     import executar_juiz
from analytics import exibir_relatorio


def main():
    args = sys.argv[1:]

    if "--only-judge" in args:
        executar_juiz()
        exibir_relatorio()
        return

    if "--only-analytics" in args:
        exibir_relatorio()
        return

    if not args:
        print(__doc__)
        sys.exit(1)

    caminho_excel = args[0]

    print("1. Criando/verificando schema...")
    create_schema()

    print(f"\n2. Importando planilha: {caminho_excel}")
    importar_excel(caminho_excel)

    print("\n3. Executando Juiz-IA (Gemini, 3 modelos)...")
    executar_juiz()

    print("\n4. Gerando relatório de análise...")
    exibir_relatorio()


if __name__ == "__main__":
    main()
