"""Conexão com o PostgreSQL.

As credenciais ficam no arquivo .env (fora do Git). Veja .env.example.
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine

from src import config

load_dotenv(config.ROOT / ".env", override=True)  # o .env prevalece sobre variáveis antigas


def nome_banco() -> str:
    return os.getenv("PGDATABASE", "bioeconomia")


def montar_url(banco: str | None = None) -> URL:
    senha = os.getenv("PGPASSWORD")
    if not senha:
        raise RuntimeError(
            "Senha do PostgreSQL não encontrada. Crie o arquivo .env a partir do "
            ".env.example e preencha PGPASSWORD."
        )
    # URL.create trata caracteres especiais da senha (@, #, %...) com segurança
    return URL.create(
        "postgresql+psycopg2",
        username=os.getenv("PGUSER", "postgres"),
        password=senha,
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        database=banco or nome_banco(),
    )


def criar_engine(banco: str | None = None, autocommit: bool = False) -> Engine:
    """Cria a conexão. client_encoding=utf8 evita o problema de acentos do
    Windows (página de código 1252)."""
    opcoes = {"isolation_level": "AUTOCOMMIT"} if autocommit else {}
    return create_engine(
        montar_url(banco),
        connect_args={"client_encoding": "utf8"},
        **opcoes,
    )


def testar_conexao(engine: Engine) -> str:
    """Retorna a versão do servidor. Traduz o erro mais comum no Windows:
    com o PostgreSQL em português, a mensagem de senha incorreta chega com
    acentos em outra codificação e vira UnicodeDecodeError."""
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT version()")).scalar()
    except UnicodeDecodeError as erro:
        raise RuntimeError(
            "Falha ao conectar no PostgreSQL. Causa mais provável: senha incorreta "
            "no arquivo .env (PGPASSWORD)."
        ) from erro
