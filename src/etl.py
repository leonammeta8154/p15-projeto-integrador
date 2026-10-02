"""Etapa 3 do pipeline: ETL da camada STAGING para o modelo dimensional (dw).

  Extract   : lê as tabelas staging.stg_* do PostgreSQL
  Transform : aplica as regras de src/transform.py
  Load      : grava dimensões e fatos no schema dw, em uma única transação

Saídas extras:
  - dw.log_qualidade_etl          histórico do que cada execução corrigiu/descartou
  - reports/qualidade_etl.csv     o mesmo relatório da última execução
  - data/processed/*.csv          cópia das tabelas do dw (consulta sem banco)

Uso (na raiz do projeto, depois de src.load_staging):
    python -m src.etl
"""
import logging
from datetime import datetime

import pandas as pd
from sqlalchemy import text

from src import config
from src.db import criar_engine, testar_conexao
from src.transform import (
    RegistroQualidade,
    montar_dim_produto,
    montar_dim_tempo,
    transformar_municipios,
    transformar_pevs,
    transformar_vendas,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("etl")

TABELAS_STAGING = ["stg_municipios", "stg_populacao", "stg_pevs", "stg_vendas"]

# Ordem de carga: dimensões antes dos fatos, por causa das chaves estrangeiras
ORDEM_CARGA = ["dim_municipio", "dim_produto", "dim_tempo", "fato_producao_extrativa", "fato_vendas"]


def extrair(engine) -> dict[str, pd.DataFrame]:
    with engine.connect() as conn:
        return {t: pd.read_sql(text(f"SELECT * FROM staging.{t}"), conn) for t in TABELAS_STAGING}


def transformar(stg: dict[str, pd.DataFrame], q: RegistroQualidade) -> dict[str, pd.DataFrame]:
    dim_municipio = transformar_municipios(stg["stg_municipios"], stg["stg_populacao"], q)
    dim_produto = montar_dim_produto()
    dim_tempo = montar_dim_tempo()
    return {
        "dim_municipio": dim_municipio,
        "dim_produto": dim_produto,
        "dim_tempo": dim_tempo,
        "fato_producao_extrativa": transformar_pevs(stg["stg_pevs"], dim_municipio, dim_produto, q),
        "fato_vendas": transformar_vendas(stg["stg_vendas"], dim_municipio, dim_produto, dim_tempo, q),
    }


def carregar(engine, tabelas: dict[str, pd.DataFrame], relatorio: pd.DataFrame) -> None:
    executado_em = datetime.now().astimezone()
    with engine.begin() as conn:
        # Recarga completa: o dw é sempre reconstruído a partir da staging
        conn.execute(text("TRUNCATE " + ", ".join(f"dw.{t}" for t in reversed(ORDEM_CARGA))))
        for nome in ORDEM_CARGA:
            tabelas[nome].to_sql(nome, conn, schema="dw", if_exists="append", index=False, chunksize=5000)

        relatorio.assign(executado_em=executado_em).to_sql(
            "log_qualidade_etl", conn, schema="dw", if_exists="append", index=False
        )

        for nome in ORDEM_CARGA:
            no_banco = conn.execute(text(f"SELECT count(*) FROM dw.{nome}")).scalar()
            if no_banco != len(tabelas[nome]):
                raise RuntimeError(f"Contagem divergente em dw.{nome}")


def salvar_arquivos(tabelas: dict[str, pd.DataFrame], relatorio: pd.DataFrame) -> None:
    config.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for nome, df in tabelas.items():
        df.to_csv(config.DATA_PROCESSED / f"{nome}.csv", index=False, encoding="utf-8")
    relatorio.to_csv(config.REPORTS_DIR / "qualidade_etl.csv", index=False, encoding="utf-8")


def main() -> None:
    engine = criar_engine()
    testar_conexao(engine)

    log.info("Extract: lendo a staging")
    stg = extrair(engine)

    log.info("Transform: aplicando as regras de qualidade")
    q = RegistroQualidade()
    tabelas = transformar(stg, q)
    relatorio = q.como_dataframe()

    log.info("Load: gravando o modelo dimensional")
    carregar(engine, tabelas, relatorio)
    salvar_arquivos(tabelas, relatorio)
    engine.dispose()

    log.info("Relatório de qualidade:")
    for linha in relatorio.itertuples():
        log.info("  %-24s %8s  %s", linha.tabela, linha.registros, linha.regra)
    log.info("Tabelas do dw:")
    for nome in ORDEM_CARGA:
        log.info("  dw.%-24s %8s registros", nome, len(tabelas[nome]))
    log.info("ETL concluído.")


if __name__ == "__main__":
    main()
