"""Leitura do modelo dimensional (schema dw) para análise e modelagem.

Os notebooks leem os dados direto do PostgreSQL. Se o banco não estiver
disponível (por exemplo, para quem só clonou o repositório), a leitura usa a
cópia em CSV que o ETL grava em data/processed, com o mesmo conteúdo.
"""
import logging

import pandas as pd
from sqlalchemy import text

from src import config

TABELAS_DW = ["dim_municipio", "dim_produto", "dim_tempo", "fato_producao_extrativa", "fato_vendas"]


def carregar_dw(fonte: str = "auto") -> tuple[dict[str, pd.DataFrame], str]:
    """Carrega as tabelas do dw.

    fonte: "postgres", "csv" ou "auto" (tenta o banco e usa os CSVs se falhar).
    Retorna (tabelas, descrição da origem).
    """
    if fonte in ("auto", "postgres"):
        try:
            from src.db import criar_engine

            engine = criar_engine()
            with engine.connect() as conn:
                # coerce_float (padrão) converte NUMERIC do PostgreSQL em float
                tabelas = {t: pd.read_sql(text(f"SELECT * FROM dw.{t}"), conn) for t in TABELAS_DW}
            engine.dispose()
            return tabelas, "PostgreSQL (schema dw)"
        except Exception as erro:  # banco fora do ar, .env ausente etc.
            if fonte == "postgres":
                raise
            logging.warning("Banco indisponível (%s). Usando data/processed.", erro)

    tabelas = {t: pd.read_csv(config.DATA_PROCESSED / f"{t}.csv") for t in TABELAS_DW}
    return tabelas, "CSV (data/processed)"


def montar_base_vendas(dw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Une o fato de vendas às dimensões e à produção extrativa do ano anterior.

    A produção usada é a do ano anterior ao da venda, porque a PEVS de um ano
    só é publicada no ano seguinte: é a informação que estaria disponível na
    hora de prever.
    """
    producao = dw["fato_producao_extrativa"][["cod_ibge", "id_produto", "ano", "quantidade_produzida"]]
    base = (
        dw["fato_vendas"]
        .merge(dw["dim_municipio"], on="cod_ibge")
        .merge(dw["dim_produto"], on="id_produto")
        .merge(dw["dim_tempo"], on="id_tempo")
    )
    # Produção do ano anterior e de dois anos antes (para medir a variação da oferta)
    for defasagem, coluna in [(1, "producao_ano_anterior_t"), (2, "producao_dois_anos_antes_t")]:
        base = base.merge(
            producao.assign(ano=producao["ano"] + defasagem).rename(columns={"quantidade_produzida": coluna}),
            on=["cod_ibge", "id_produto", "ano"],
            how="left",
        )
    base["ano_producao"] = base["ano"] - 1
    base["data_referencia"] = pd.to_datetime(base["data_referencia"])
    numericas = ["quantidade", "preco_unitario", "receita", "populacao_2022",
                 "producao_ano_anterior_t", "producao_dois_anos_antes_t"]
    for coluna in numericas:
        base[coluna] = base[coluna].astype(float)
    return base.sort_values(["cod_ibge", "id_produto", "id_tempo"]).reset_index(drop=True)
