"""
Utilitários de backup e restore do banco PostgreSQL.

Uso:
  python db_utils.py dump    [arquivo.sql]   — gera dump completo
  python db_utils.py restore  arquivo.sql    — restaura a partir do dump
  python db_utils.py reset                   — dropa e recria o schema
"""

import os
import sys
import subprocess
from schema import create_schema
from config import get_connection, get_db_cli_params

DEFAULT_DUMP = "backup_atv2.sql"


def _env() -> dict:
    get_connection().close()
    s = get_db_cli_params()
    return {**os.environ, "PGPASSWORD": s["password"]}


def dump(arquivo: str = DEFAULT_DUMP):
    s = get_db_cli_params()
    cmd = [
        "pg_dump",
        "-h", s["db_host"], "-p", str(s["db_port"]),
        "-U", s["user"],
        "--no-password",
        "--clean", "--if-exists",
        "--format=plain",
        "-f", arquivo,
        s["dbname"],
    ]
    subprocess.run(cmd, env=_env(), check=True)
    print(f"Dump salvo em: {arquivo}")


def restore(arquivo: str):
    if not os.path.exists(arquivo):
        print(f"Arquivo não encontrado: {arquivo}")
        sys.exit(1)
    s = get_db_cli_params()
    cmd = [
        "psql",
        "-h", s["db_host"], "-p", str(s["db_port"]),
        "-U", s["user"],
        "--no-password",
        "-d", s["dbname"],
        "-f", arquivo,
    ]
    subprocess.run(cmd, env=_env(), check=True)
    print(f"Restore concluído a partir de: {arquivo}")


def reset():
    drop = """
        DROP VIEW IF EXISTS vw_avaliacoes_completas;
        DROP TABLE IF EXISTS rubrica_subcriterios CASCADE;
        DROP TABLE IF EXISTS avaliacoes_juiz CASCADE;
        DROP TABLE IF EXISTS respostas_atividade_1 CASCADE;
        DROP TABLE IF EXISTS perguntas CASCADE;
        DROP TABLE IF EXISTS datasets CASCADE;
        DROP TABLE IF EXISTS modelos CASCADE;
        DROP TABLE IF EXISTS modelos_juiz CASCADE;
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(drop)
        conn.commit()
    print("Tabelas removidas.")
    create_schema()
    print("Schema recriado.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    cmd = args[0]
    if cmd == "dump":
        dump(args[1] if len(args) > 1 else DEFAULT_DUMP)
    elif cmd == "restore":
        if len(args) < 2:
            print("Informe o arquivo SQL: python db_utils.py restore arquivo.sql")
            sys.exit(1)
        restore(args[1])
    elif cmd == "reset":
        reset()
    else:
        print(f"Comando desconhecido: {cmd}")
        sys.exit(1)
