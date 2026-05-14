"""
Inicia túnel SSH via sshtunnel com auto-logon e mantém a aplicação conectada.
"""
import time
import sys
from sshtunnel import SSHTunnelForwarder

SSH_USER = "ufsprocc"
SSH_HOST = "177.10.120.254"
SSH_PORT = 1989
SSH_PASSWORD = "Procc@ufs@!$"

LOCAL_PORT = 5433
REMOTE_PORT = 5432  # porta do PostgreSQL no servidor

if __name__ == "__main__":
    try:
        print(f"Iniciando túnel SSH: localhost:{LOCAL_PORT} -> {SSH_HOST}:{REMOTE_PORT} via porta {SSH_PORT}...")
        server = SSHTunnelForwarder(
            (SSH_HOST, SSH_PORT),
            ssh_username=SSH_USER,
            ssh_password=SSH_PASSWORD,
            remote_bind_address=('127.0.0.1', REMOTE_PORT),
            local_bind_address=('127.0.0.1', LOCAL_PORT),
            set_keepalive=60.0
        )
        server.start()
        print("✓ Túnel ativo com auto-logon! Pressione Ctrl+C para encerrar.")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
            print("Túnel encerrado.")
    except Exception as e:
        print(f"Erro ao iniciar o túnel SSH: {e}")
        sys.exit(1)
