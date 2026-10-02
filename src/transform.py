"""Etapa 3 do pipeline: regras de TRANSFORMAÇÃO do ETL.

Funções puras (recebem e devolvem DataFrames, sem acessar o banco), para que
cada regra possa ser lida, testada e explicada isoladamente. Toda correção ou
descarte é contabilizado no RegistroQualidade, que vira o relatório de
qualidade do ETL.
"""
import re

import numpy as np
import pandas as pd

from src import config
from src.utils import converter_valor_sidra, identificar_produto, normalizar_texto, pevs_largo

NOMES_MES = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

# Palavra-chave (já normalizada) que identifica cada produto nas vendas
REGRAS_PRODUTO = {"acai": "acai", "castanha": "castanha_do_para", "copaiba": "copaiba"}

# Tolerâncias das regras de validação das vendas
TOLERANCIA_RECEITA = 0.05            # quantidade × preço pode diferir da receita em até 5%
FAIXA_PRECO = (0.2, 5.0)             # preço aceito entre 0,2x e 5x a mediana do produto


class RegistroQualidade:
    """Acumula o que cada regra do ETL corrigiu ou descartou."""

    def __init__(self):
        self.itens = []

    def registrar(self, tabela: str, regra: str, registros) -> None:
        self.itens.append({"tabela": tabela, "regra": regra, "registros": int(registros)})

    def como_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self.itens, columns=["tabela", "regra", "registros"])


# ---------------------------------------------------------------------------
# Dimensões
# ---------------------------------------------------------------------------
def transformar_municipios(stg_mun: pd.DataFrame, stg_pop: pd.DataFrame, q: RegistroQualidade) -> pd.DataFrame:
    mun = stg_mun[["cod_ibge", "municipio", "uf", "regiao_intermediaria", "regiao_imediata"]].copy()
    mun["cod_ibge"] = pd.to_numeric(mun["cod_ibge"], errors="coerce")
    mun["uf"] = mun["uf"].str.strip().str.upper()
    q.registrar("dim_municipio", "registros lidos da staging", len(mun))

    antes = len(mun)
    mun = mun.dropna(subset=["cod_ibge"]).drop_duplicates(subset=["cod_ibge"])
    q.registrar("dim_municipio", "descartados: código ausente ou repetido", antes - len(mun))
    mun["cod_ibge"] = mun["cod_ibge"].astype(int)

    pop = stg_pop[stg_pop["variavel"].map(normalizar_texto).str.startswith("populacao residente")].copy()
    pop["cod_ibge"] = pd.to_numeric(pop["cod_ibge"], errors="coerce")
    pop["populacao_2022"] = pop["valor"].map(converter_valor_sidra)
    pop = pop.dropna(subset=["cod_ibge"]).drop_duplicates(subset=["cod_ibge"])
    pop["cod_ibge"] = pop["cod_ibge"].astype(int)

    mun = mun.merge(pop[["cod_ibge", "populacao_2022"]], on="cod_ibge", how="left")
    q.registrar("dim_municipio", "municípios sem população no Censo 2022", mun["populacao_2022"].isna().sum())
    mun["populacao_2022"] = mun["populacao_2022"].astype("Int64")
    return mun.sort_values("cod_ibge").reset_index(drop=True)


def montar_dim_produto() -> pd.DataFrame:
    linhas = [
        {"id_produto": i, "chave": chave, "nome": info["nome"], "unidade_venda": info["unidade"]}
        for i, (chave, info) in enumerate(config.PRODUTOS.items(), start=1)
    ]
    return pd.DataFrame(linhas)


def montar_dim_tempo() -> pd.DataFrame:
    meses = pd.period_range(config.INICIO_VENDAS, config.FIM_VENDAS, freq="M")
    return pd.DataFrame(
        {
            "id_tempo": [m.year * 100 + m.month for m in meses],
            "data_referencia": [m.start_time.date() for m in meses],
            "ano": [m.year for m in meses],
            "mes": [m.month for m in meses],
            "trimestre": [m.quarter for m in meses],
            "nome_mes": [NOMES_MES[m.month - 1] for m in meses],
        }
    )


# ---------------------------------------------------------------------------
# Fato: produção extrativa (PEVS)
# ---------------------------------------------------------------------------
def transformar_pevs(
    stg_pevs: pd.DataFrame, dim_mun: pd.DataFrame, dim_prod: pd.DataFrame, q: RegistroQualidade
) -> pd.DataFrame:
    df = stg_pevs.copy()
    q.registrar("fato_producao_extrativa", "registros lidos da staging (todos os produtos)", len(df))

    df["produto"] = df["produto_ibge"].map(lambda c: identificar_produto(c, config.PRODUTOS))
    df = df[df["produto"].notna()].copy()
    q.registrar("fato_producao_extrativa", "registros dos 3 produtos do projeto (demais ignorados)", len(df))

    bruto = df["valor"].astype(str).str.strip()
    numerico = bruto.str.fullmatch(r"-?\d+(\.\d+)?")
    q.registrar("fato_producao_extrativa", "símbolo '-' do IBGE convertido em zero", (bruto == "-").sum())
    q.registrar(
        "fato_producao_extrativa",
        "símbolos '...', '..' ou 'X' do IBGE convertidos em NULL (não disponível)",
        (~numerico & (bruto != "-")).sum(),
    )
    df["valor"] = df["valor"].map(converter_valor_sidra)

    largo = pevs_largo(df)
    antes = len(largo)
    largo = largo[largo["cod_ibge"].isin(dim_mun["cod_ibge"])]
    q.registrar("fato_producao_extrativa", "descartados: município fora do cadastro", antes - len(largo))

    largo = largo.merge(dim_prod[["id_produto", "chave"]], left_on="produto", right_on="chave")
    fato = largo[
        ["cod_ibge", "id_produto", "ano", "quantidade_produzida", "unidade_producao", "valor_producao_mil_reais"]
    ]
    q.registrar("fato_producao_extrativa", "registros gravados", len(fato))
    return fato.sort_values(["cod_ibge", "id_produto", "ano"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Fato: vendas
# ---------------------------------------------------------------------------
def padronizar_produto(texto) -> str | None:
    """'AÇAÍ', ' Açaí ', 'acai' -> 'acai'; 'castanha do para' -> 'castanha_do_para'."""
    t = normalizar_texto(texto).replace("-", " ")
    for termo, chave in REGRAS_PRODUTO.items():
        if termo in t:
            return chave
    return None


def converter_mes(texto) -> int | None:
    """'2024-03' ou '03/2024' -> 202403. Formato inválido -> None."""
    t = str(texto).strip()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", t):
        ano, mes = int(m[1]), int(m[2])
    elif m := re.fullmatch(r"(\d{1,2})/(\d{4})", t):
        mes, ano = int(m[1]), int(m[2])
    else:
        return None
    return ano * 100 + mes if 1 <= mes <= 12 else None


def _descartar(df: pd.DataFrame, mascara: pd.Series, q: RegistroQualidade, motivo: str) -> pd.DataFrame:
    q.registrar("fato_vendas", f"descartados: {motivo}", mascara.sum())
    return df[~mascara].copy()


def transformar_vendas(
    stg_vendas: pd.DataFrame,
    dim_mun: pd.DataFrame,
    dim_prod: pd.DataFrame,
    dim_tempo: pd.DataFrame,
    q: RegistroQualidade,
) -> pd.DataFrame:
    colunas = [
        "id_venda", "mes_referencia", "cod_ibge", "municipio", "uf",
        "produto", "quantidade", "unidade", "preco_unitario", "receita",
    ]
    df = stg_vendas[colunas].copy()
    q.registrar("fato_vendas", "registros lidos da staging", len(df))

    # 1. Linhas duplicadas
    antes = len(df)
    df = df.drop_duplicates()
    q.registrar("fato_vendas", "linhas duplicadas removidas", antes - len(df))

    # 2. Nome do produto com grafias diferentes
    df["chave"] = df["produto"].map(padronizar_produto)
    nome_oficial = df["chave"].map({c: i["nome"] for c, i in config.PRODUTOS.items()})
    q.registrar("fato_vendas", "nome do produto padronizado", (df["chave"].notna() & (df["produto"] != nome_oficial)).sum())
    df = _descartar(df, df["chave"].isna(), q, "produto não reconhecido")

    # 3. Mês em dois formatos
    q.registrar("fato_vendas", "mês convertido de MM/AAAA", df["mes_referencia"].str.contains("/", na=False).sum())
    df["id_tempo"] = df["mes_referencia"].map(converter_mes)
    df = _descartar(df, ~df["id_tempo"].isin(dim_tempo["id_tempo"]), q, "mês inválido ou fora do período")
    df["id_tempo"] = df["id_tempo"].astype(int)

    # 4. Código IBGE ausente: recuperado por nome do município + UF
    df["cod_ibge"] = pd.to_numeric(df["cod_ibge"], errors="coerce")
    ausente = df["cod_ibge"].isna()
    cadastro = dim_mun.assign(
        chave_nome=dim_mun["municipio"].map(normalizar_texto) + "|" + dim_mun["uf"]
    ).set_index("chave_nome")["cod_ibge"]
    chave_nome = df.loc[ausente, "municipio"].map(normalizar_texto) + "|" + df.loc[ausente, "uf"].str.strip().str.upper()
    recuperado = chave_nome.map(cadastro)
    df.loc[ausente, "cod_ibge"] = recuperado
    q.registrar("fato_vendas", "código IBGE recuperado por nome do município + UF", recuperado.notna().sum())
    df = _descartar(df, ~df["cod_ibge"].isin(dim_mun["cod_ibge"]), q, "município não identificado")
    df["cod_ibge"] = df["cod_ibge"].astype(int)

    # 5. Nome do município fora do padrão (ex.: caixa alta): informativo,
    #    pois o nome oficial vem da dimensão e a chave é o código IBGE
    nome_cadastro = df["cod_ibge"].map(dim_mun.set_index("cod_ibge")["municipio"])
    q.registrar("fato_vendas", "nome do município fora do padrão (substituído pelo cadastro)", (df["municipio"] != nome_cadastro).sum())

    # 6. Conversão numérica
    for coluna in ["quantidade", "preco_unitario", "receita"]:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")
    df = _descartar(df, df["quantidade"].isna() | df["receita"].isna(), q, "quantidade ou receita não numérica")

    # 7. Quantidade com sinal trocado
    negativa = df["quantidade"] < 0
    df.loc[negativa, "quantidade"] = -df.loc[negativa, "quantidade"]
    q.registrar("fato_vendas", "quantidade negativa corrigida (sinal)", negativa.sum())

    # 8. Erro de digitação na quantidade: quantidade × preço não bate com a
    #    receita; a receita é o campo confiável, então a quantidade é recalculada
    tem_preco = df["preco_unitario"].notna() & (df["preco_unitario"] > 0)
    calculada = df["quantidade"] * df["preco_unitario"]
    divergente = tem_preco & ((calculada - df["receita"]).abs() > TOLERANCIA_RECEITA * df["receita"].abs() + 0.01)
    df.loc[divergente, "quantidade"] = (df.loc[divergente, "receita"] / df.loc[divergente, "preco_unitario"]).round(1)
    q.registrar("fato_vendas", "quantidade recalculada por receita / preço (erro de digitação)", divergente.sum())

    # 9. Preço ausente: recalculado por receita / quantidade
    sem_preco = ~tem_preco & (df["quantidade"] > 0)
    df.loc[sem_preco, "preco_unitario"] = (df.loc[sem_preco, "receita"] / df.loc[sem_preco, "quantidade"]).round(2)
    q.registrar("fato_vendas", "preço unitário recalculado por receita / quantidade", sem_preco.sum())

    # 10. Validação final do preço: fora da faixa plausível do produto
    mediana = df.groupby("chave")["preco_unitario"].transform("median")
    fora = (
        df["preco_unitario"].isna()
        | (df["preco_unitario"] < FAIXA_PRECO[0] * mediana)
        | (df["preco_unitario"] > FAIXA_PRECO[1] * mediana)
    )
    df = _descartar(df, fora, q, "preço fora da faixa plausível do produto")

    # 11. Unicidade da chave do fato (município, produto, mês)
    df["id_venda_num"] = pd.to_numeric(df["id_venda"], errors="coerce")
    df = df.sort_values("id_venda_num")
    df = _descartar(df, df.duplicated(["cod_ibge", "chave", "id_tempo"], keep="first"), q, "chave município + produto + mês repetida")

    df = df.merge(dim_prod[["id_produto", "chave"]], on="chave")
    fato = df[["cod_ibge", "id_produto", "id_tempo", "quantidade", "preco_unitario", "receita"]].copy()
    fato["quantidade"] = fato["quantidade"].round(1)
    fato["preco_unitario"] = fato["preco_unitario"].round(2)
    fato["receita"] = fato["receita"].round(2)
    q.registrar("fato_vendas", "registros gravados", len(fato))
    return fato.sort_values(["cod_ibge", "id_produto", "id_tempo"]).reset_index(drop=True)
