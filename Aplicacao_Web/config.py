"""
Módulo de configuração centralizado.

Gerencia a conexão com o banco de dados via túnel SSH usando paramiko diretamente,
sem depender do sshtunnel (incompatível com paramiko >= 3.0).
"""

import atexit
import os
import select
import socket
import threading

import paramiko
import psycopg2
from dotenv import load_dotenv

load_dotenv()

_tunnel_lock = threading.Lock()


def _tunnel_params():
    return {
        "ssh_host": os.getenv("SSH_HOST", "177.10.120.254"),
        "ssh_port": int(os.getenv("SSH_PORT", "1989")),
        "ssh_user": os.getenv("SSH_USER", "ufsprocc"),
        "ssh_password": os.getenv("SSH_PASSWORD", "Procc@ufs@!$"),
        "remote_db_host": os.getenv("REMOTE_DB_HOST", "127.0.0.1"),
        "remote_db_port": int(os.getenv("REMOTE_DB_PORT", "5432")),
        "local_bind_host": os.getenv("DB_HOST", "127.0.0.1"),
        "local_bind_port": int(os.getenv("DB_PORT", "5433")),
    }


def _pg_params():
    return {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", "5433")),
        "dbname": os.getenv("DB_NAME", "judge_db"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", "Procc2026ufs-_"),
    }


def get_db_cli_params():
    """Host/port do túnel local e credenciais PostgreSQL (psql, pg_dump)."""
    t = _tunnel_params()
    p = _pg_params()
    return {
        "db_host": t["local_bind_host"],
        "db_port": t["local_bind_port"],
        "dbname": p["dbname"],
        "user": p["user"],
        "password": p["password"],
    }


def _forward(sock: socket.socket, chan: paramiko.Channel):
    """Encaminha bytes bidirecionalmente entre socket local e canal SSH."""
    try:
        while True:
            r, _, _ = select.select([sock, chan], [], [], 5.0)
            if sock in r:
                data = sock.recv(4096)
                if not data:
                    break
                chan.sendall(data)
            if chan in r:
                data = chan.recv(4096)
                if not data:
                    break
                sock.sendall(data)
    finally:
        try:
            sock.close()
        except OSError:
            pass
        try:
            chan.close()
        except Exception:
            pass


class _SSHTunnel:
    """Túnel SSH com port-forward local, usando paramiko sem sshtunnel."""

    def __init__(self, ssh_host, ssh_port, ssh_user, ssh_password,
                 remote_host, remote_port, local_host, local_port):
        self._ssh_host = ssh_host
        self._ssh_port = ssh_port
        self._ssh_user = ssh_user
        self._ssh_password = ssh_password
        self._remote_host = remote_host
        self._remote_port = remote_port
        self._local_host = local_host
        self._local_port = local_port
        self._client: paramiko.SSHClient | None = None
        self._server_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.is_active = False

    def start(self):
        timeout = float(os.getenv("SSH_SOCKET_TIMEOUT", "20"))
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(
            self._ssh_host,
            port=self._ssh_port,
            username=self._ssh_user,
            password=self._ssh_password,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
        )
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        self._server_sock.bind((self._local_host, self._local_port))
        self._server_sock.listen(5)
        self.is_active = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        print(f"✓ Túnel SSH ativo em {self._local_host}:{self._local_port}")

    def _serve(self):
        transport = self._client.get_transport()
        while self.is_active:
            self._server_sock.settimeout(1.0)
            try:
                client_sock, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                chan = transport.open_channel(
                    "direct-tcpip",
                    (self._remote_host, self._remote_port),
                    addr,
                )
            except Exception as e:
                print(f"[!] Canal SSH falhou: {e}")
                client_sock.close()
                continue
            t = threading.Thread(target=_forward, args=(client_sock, chan), daemon=True)
            t.start()

    def stop(self):
        self.is_active = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass


_server: _SSHTunnel | None = None


def start_tunnel():
    """Inicia o túnel SSH se ainda não estiver ativo."""
    global _server
    p = _tunnel_params()
    with _tunnel_lock:
        if _server and _server.is_active:
            return
        try:
            _server = _SSHTunnel(
                ssh_host=p["ssh_host"],
                ssh_port=p["ssh_port"],
                ssh_user=p["ssh_user"],
                ssh_password=p["ssh_password"],
                remote_host=p["remote_db_host"],
                remote_port=p["remote_db_port"],
                local_host=p["local_bind_host"],
                local_port=p["local_bind_port"],
            )
            _server.start()
        except Exception as e:
            print(f"[!] Falha ao iniciar o túnel SSH: {e}")
            _server = None
            raise


def get_connection():
    """Garante que o túnel esteja ativo e retorna uma conexão psycopg2."""
    start_tunnel()
    pg = _pg_params()
    return psycopg2.connect(
        host=pg["host"],
        port=pg["port"],
        dbname=pg["dbname"],
        user=pg["user"],
        password=pg["password"],
        connect_timeout=int(os.getenv("PG_CONNECT_TIMEOUT", "10")),
    )


@atexit.register
def stop_tunnel():
    global _server
    if _server and _server.is_active:
        _server.stop()
        print("✓ Túnel SSH encerrado.")
