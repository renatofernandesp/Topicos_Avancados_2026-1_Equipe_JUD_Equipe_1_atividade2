from sshtunnel import SSHTunnelForwarder
import psycopg2
import time

# --- DADOS DO SERVIDOR SSH ---
SSH_IP = '177.10.120.254'
SSH_PORTA = 1989
SSH_USER = 'ufsprocc'
SSH_SENHA = 'Procc@ufs@!$'

# --- DADOS DO BANCO DE DADOS ---
DB_USER = 'postgres'
DB_SENHA = 'Procc2026ufs-_'
DB_NOME = 'judge_db'
DB_PORTA = 5432

try:
    print(f"Status: Abrindo túnel SSH via porta {SSH_PORTA}...")
    
    server = SSHTunnelForwarder(
        (SSH_IP, SSH_PORTA),
        ssh_username=SSH_USER,
        ssh_password=SSH_SENHA,
        remote_bind_address=('127.0.0.1', DB_PORTA),
        set_keepalive=60.0
    )
    server.start()
    print(f"✓ Túnel estabelecido! Porta local temporária: {server.local_bind_port}")
    time.sleep(1)

    try:
        print(f"Status: Conectando ao banco '{DB_NOME}'...")
        conn = psycopg2.connect(
            host='127.0.0.1',
            port=server.local_bind_port,
            user=DB_USER,
            password=DB_SENHA,
            dbname=DB_NOME,
            connect_timeout=10
        )
        cur = conn.cursor()
        print("✓ Sucesso! Você está conectado no banco de dados.\n")

        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;")
        tabelas = cur.fetchall()
        
        print(f"--- Tabelas no Banco {DB_NOME} ---")
        if not tabelas:
            print("Nenhuma tabela encontrada no schema 'public'.")
        else:
            for i, (nome,) in enumerate(tabelas, 1):
                print(f"{i:02d}. {nome}")
        cur.close()
        conn.close()
    except Exception as e_db:
        print(f"\n[!] Erro ao conectar no BANCO: {e_db}")
    finally:
        server.stop()
        print("\nStatus: Túnel SSH encerrado com segurança.")
except Exception as e_ssh:
    print(f"\n[!] Erro no SSH: {e_ssh}")