"""Etapa 2 do pipeline: criação do banco e da estrutura no PostgreSQL.

1. Cria o banco (padrão: "bioeconomia") em UTF-8, se ainda não existir.
2. Executa sql/01_estrutura.sql (schemas staging e dw, tabelas e índices).

Uso (na raiz do projeto):
    python -m src.setup_db             # cria o que faltar
    python -m src.setup_db --recriar   # apaga e recria os schemas (perde os dados)
"""
import argparse
import logging

from sqlalchemy import text

from src import config
from src.db import criar_engine, nome_banco, testar_conexao

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("setup_db")

ARQUIVO_ESTRUTURA = config.SQL_DIR / "01_estrutura.sql"


def criar_banco(banco: str) -> None:
    # CREATE DATABASE não roda dentro de transação: conecta no banco padrão
    # "postgres" em modo autocommit
    engine = criar_engine("postgres", autocommit=True)
    log.info("Servidor: %s", testar_conexao(engine).split(",")[0])
    with engine.connect() as conn:
        existe = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :nome"), {"nome": banco}
        ).scalar()
        if existe:
            log.info("Banco '%s' já existe.", banco)
        else:
            nome_seguro = banco.replace('"', '""')
            conn.execute(text(f'CREATE DATABASE "{nome_seguro}" ENCODING \'UTF8\' TEMPLATE template0'))
            log.info("Banco '%s' criado (UTF-8).", banco)
    engine.dispose()


def criar_estrutura(recriar: bool) -> None:
    engine = criar_engine()
    sql = ARQUIVO_ESTRUTURA.read_text(encoding="utf-8")
    with engine.begin() as conn:
        if recriar:
            log.warning("Apagando schemas staging e dw (--recriar).")
            conn.execute(text("DROP SCHEMA IF EXISTS dw CASCADE"))
            conn.execute(text("DROP SCHEMA IF EXISTS staging CASCADE"))
        # o driver psycopg2 aceita vários comandos SQL em uma única chamada
        conn.exec_driver_sql(sql)

        tabelas = conn.execute(
            text(
                """
                SELECT table_schema || '.' || table_name
                FROM information_schema.tables
                WHERE table_schema IN ('staging', 'dw')
                ORDER BY table_schema DESC, table_name
                """
            )
        ).scalars().all()
    engine.dispose()
    log.info("Estrutura pronta com %s tabelas:", len(tabelas))
    for nome in tabelas:
        log.info("  %s", nome)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cria o banco e a estrutura do projeto")
    parser.add_argument("--recriar", action="store_true", help="apaga e recria os schemas")
    args = parser.parse_args()

    criar_banco(nome_banco())
    criar_estrutura(args.recriar)


if __name__ == "__main__":
    main()
