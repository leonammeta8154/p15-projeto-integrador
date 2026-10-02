"""Etapa 2 do pipeline: carga dos dados brutos na camada STAGING do PostgreSQL.

Lê os arquivos de data/raw e grava nas tabelas staging.stg_* sem nenhuma
limpeza: os JSONs do IBGE são apenas "achatados" em linhas e colunas, e todos
os valores entram como texto. Cada carga substitui a anterior (TRUNCATE),
então o script pode ser executado quantas vezes for preciso.

Uso (na raiz do projeto, depois de src.extract, src.gerar_vendas e src.setup_db):
    python -m src.load_staging
"""
import logging

import pandas as pd
from sqlalchemy import text

from src import config
from src.db import criar_engine, testar_conexao
from src.utils import ler_municipios, ler_sidra

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("load_staging")

COLUNAS_POPULACAO = ["cod_ibge", "municipio", "cod_variavel", "variavel", "ano", "unidade", "valor"]
COLUNAS_PEVS = [
    "cod_ibge", "municipio", "cod_variavel", "variavel", "ano",
    "cod_produto_ibge", "produto_ibge", "unidade", "valor",
]


def como_texto(df: pd.DataFrame) -> pd.DataFrame:
    """Converte tudo para texto, mantendo ausentes como NULL."""
    return df.astype(object).map(lambda v: None if pd.isna(v) else str(v))


def preparar_municipios() -> pd.DataFrame:
    partes = []
    for uf in config.UFS:
        arquivo = config.DATA_RAW / f"ibge_municipios_{uf}.json"
        df = ler_municipios(arquivo)
        df["arquivo_origem"] = arquivo.name
        partes.append(df)
    return como_texto(pd.concat(partes, ignore_index=True))


def preparar_sidra(padrao: str, colunas: list[str]) -> pd.DataFrame:
    partes = []
    for arquivo in sorted(config.DATA_RAW.glob(padrao)):
        df = ler_sidra(arquivo, converter=False)
        df = df.rename(columns={"cod_categoria": "cod_produto_ibge", "categoria": "produto_ibge"})
        df = df.reindex(columns=colunas)
        df["arquivo_origem"] = arquivo.name
        partes.append(df)
    if not partes:
        raise FileNotFoundError(f"Nenhum arquivo {padrao} em {config.DATA_RAW}. Rode src.extract antes.")
    return como_texto(pd.concat(partes, ignore_index=True))


def preparar_vendas() -> pd.DataFrame:
    arquivo = config.DATA_RAW / "vendas_simuladas.csv"
    df = pd.read_csv(arquivo, dtype=str, encoding="utf-8")
    df["arquivo_origem"] = arquivo.name
    return como_texto(df)


def main() -> None:
    cargas = {
        "stg_municipios": preparar_municipios(),
        "stg_populacao": preparar_sidra("sidra_4709_populacao_*.json", COLUNAS_POPULACAO),
        "stg_pevs": preparar_sidra("sidra_289_pevs_*_*.json", COLUNAS_PEVS),
        "stg_vendas": preparar_vendas(),
    }

    engine = criar_engine()
    testar_conexao(engine)

    # Tudo em uma transação: ou a staging inteira é atualizada, ou nada muda
    with engine.begin() as conn:
        tabelas = ", ".join(f"staging.{t}" for t in cargas)
        conn.execute(text(f"TRUNCATE {tabelas}"))
        for tabela, df in cargas.items():
            df.to_sql(tabela, conn, schema="staging", if_exists="append", index=False, chunksize=5000)

        log.info("%-16s %10s %10s", "tabela", "arquivos", "banco")
        for tabela, df in cargas.items():
            no_banco = conn.execute(text(f"SELECT count(*) FROM staging.{tabela}")).scalar()
            log.info("%-16s %10s %10s", tabela, len(df), no_banco)
            if no_banco != len(df):
                raise RuntimeError(f"Contagem divergente em staging.{tabela}")

    engine.dispose()
    log.info("Carga da staging concluída.")


if __name__ == "__main__":
    main()
