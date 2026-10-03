"""Variável alvo e engenharia de features.

ALVO (alta_demanda): 1 quando a quantidade vendida no mês supera a média dos
12 meses ANTERIORES do mesmo município e produto; 0 caso contrário.

  - Compara cada município com o seu próprio histórico, então um município
    pequeno pode ter "alta demanda" tanto quanto uma capital.
  - Usa só meses passados na média, sem olhar o próprio mês nem o futuro.
  - Exige os 12 meses anteriores completos: os meses de 2022 servem apenas de
    histórico.

FEATURES: todas calculadas com informação disponível ATÉ o mês anterior ao
previsto (t-1), para que o modelo possa ser usado de verdade no início de cada
mês. As decisões vêm da análise exploratória (notebooks/01_eda.ipynb).
"""
import numpy as np
import pandas as pd

JANELA_HISTORICO = 12
CHAVE_SERIE = ["cod_ibge", "id_produto"]
ANO_TESTE = 2024  # validação temporal: treino em 2023, teste em 2024

COLUNAS_ID = ["cod_ibge", "municipio", "uf", "id_produto", "chave", "nome", "id_tempo", "ano", "mes"]

# nome: (grupo, descrição, informação usada)
DICIONARIO_FEATURES = {
    "log_razao_lag1": ("Memória recente", "Log da razão entre a quantidade do mês anterior e a média dos 12 meses anteriores", "t-1"),
    "log_razao_lag2": ("Memória recente", "Log da razão entre a quantidade de dois meses antes e a média dos 12 meses anteriores", "t-2"),
    "log_razao_media3": ("Memória recente", "Log da razão entre a média dos últimos 3 meses e a média dos 12 meses anteriores", "t-3 a t-1"),
    "log_variacao_lag1": ("Memória recente", "Log da variação da quantidade entre os dois últimos meses", "t-2 e t-1"),
    "alta_mes_anterior": ("Memória recente", "Alvo do mês anterior (1 = alta demanda); vazio em jan/2023, pois 2022 não tem alvo", "t-1"),
    "log_razao_lag12": ("Sazonalidade", "Log da razão entre a quantidade do mesmo mês do ano anterior e a média dos 12 meses anteriores", "t-12"),
    "indice_sazonal_hist": ("Sazonalidade", "Índice sazonal do produto no mês do ano, calculado só com os anos anteriores", "anos anteriores"),
    "mes_seno": ("Sazonalidade", "Seno do mês do ano (codificação cíclica)", "calendário"),
    "mes_cosseno": ("Sazonalidade", "Cosseno do mês do ano (codificação cíclica)", "calendário"),
    "log_preco_rel_lag1": ("Preço", "Log da razão entre o preço do mês anterior e a média de preço dos 12 meses anteriores", "t-1"),
    "log_populacao": ("Contexto", "Log da população residente (Censo 2022)", "estático"),
    "log_producao_ano_anterior": ("Contexto", "Log da produção extrativa do produto no município no ano anterior (PEVS)", "ano anterior"),
    "produz_no_municipio": ("Contexto", "1 se houve produção extrativa do produto no município no ano anterior", "ano anterior"),
    "producao_indisponivel": ("Contexto", "1 se o IBGE não divulgou a produção do ano anterior (símbolo ...)", "ano anterior"),
    "chave": ("Contexto", "Produto (categórica: açaí, castanha-do-pará, copaíba)", "estático"),
    "uf": ("Contexto", "Unidade da federação (categórica: AP, PA, AM)", "estático"),
}
FEATURES_CATEGORICAS = ["chave", "uf"]
FEATURES_NUMERICAS = [f for f in DICIONARIO_FEATURES if f not in FEATURES_CATEGORICAS]
FEATURES = FEATURES_NUMERICAS + FEATURES_CATEGORICAS
ALVO = "alta_demanda"


def dicionario_features() -> pd.DataFrame:
    return pd.DataFrame(
        [(nome, *info) for nome, info in DICIONARIO_FEATURES.items()],
        columns=["feature", "grupo", "descricao", "informacao_usada"],
    )


def adicionar_alvo(base: pd.DataFrame, janela: int = JANELA_HISTORICO) -> pd.DataFrame:
    df = base.sort_values(CHAVE_SERIE + ["id_tempo"]).copy()
    df["media_12m_anteriores"] = df.groupby(CHAVE_SERIE)["quantidade"].transform(
        lambda s: s.shift(1).rolling(janela, min_periods=janela).mean()
    )
    tem_alvo = df["media_12m_anteriores"].notna() & df["quantidade"].notna()
    df["alta_demanda"] = pd.Series(pd.NA, index=df.index, dtype="Int64")
    df.loc[tem_alvo, "alta_demanda"] = (
        df.loc[tem_alvo, "quantidade"] > df.loc[tem_alvo, "media_12m_anteriores"]
    ).astype(int)
    return df


def completar_calendario(base: pd.DataFrame) -> pd.DataFrame:
    """Garante uma linha por série e mês, mesmo quando o mês não tem venda
    registrada. Assim, "mês anterior" é sempre o mês anterior no calendário, e
    não a linha anterior da tabela."""
    estaticas = ["cod_ibge", "id_produto", "municipio", "uf", "chave", "nome", "populacao_2022"]
    series = base[estaticas].drop_duplicates(CHAVE_SERIE)
    meses = base[["id_tempo", "ano", "mes"]].drop_duplicates()
    grade = series.merge(meses, how="cross")
    grade = grade.merge(
        base[CHAVE_SERIE + ["id_tempo", "quantidade", "preco_unitario"]],
        on=CHAVE_SERIE + ["id_tempo"],
        how="left",
    )
    producao = base[CHAVE_SERIE + ["ano", "producao_ano_anterior_t"]].drop_duplicates(CHAVE_SERIE + ["ano"])
    grade = grade.merge(producao, on=CHAVE_SERIE + ["ano"], how="left")
    return grade.sort_values(CHAVE_SERIE + ["id_tempo"]).reset_index(drop=True)


def indice_sazonal_historico(df: pd.DataFrame) -> np.ndarray:
    """Índice sazonal do produto em cada mês do ano, usando só anos anteriores.

    Para cada série e ano, divide a quantidade do mês pela média do ano; depois
    tira a média por produto e mês. A linha de 2024 recebe a média de 2022 e
    2023; a de 2023, apenas a de 2022.
    """
    media_ano = df.groupby(CHAVE_SERIE + ["ano"])["quantidade"].transform("mean")
    razao = (df["quantidade"] / media_ano).rename("indice")
    por_ano = razao.groupby([df["id_produto"], df["ano"], df["mes"]]).mean().reset_index()

    partes = []
    for ano in sorted(df["ano"].unique()):
        anteriores = por_ano[por_ano["ano"] < ano]
        if not anteriores.empty:
            partes.append(anteriores.groupby(["id_produto", "mes"], as_index=False)["indice"].mean().assign(ano=ano))
    historico = pd.concat(partes, ignore_index=True)
    return df[["id_produto", "ano", "mes"]].merge(historico, on=["id_produto", "ano", "mes"], how="left")["indice"].to_numpy()


def construir_features(base: pd.DataFrame) -> pd.DataFrame:
    """Recebe a base de vendas (src.leitura.montar_base_vendas) e devolve a
    base de modelagem: identificação, features, alvo e conjunto (treino/teste)."""
    df = adicionar_alvo(completar_calendario(base))
    serie = df.groupby(CHAVE_SERIE)
    media = df["media_12m_anteriores"]

    def defasar(coluna, meses):
        return serie[coluna].shift(meses)

    def media_movel(coluna, janela):
        return serie[coluna].transform(lambda s: s.shift(1).rolling(janela, min_periods=janela).mean())

    with np.errstate(divide="ignore", invalid="ignore"):
        df["log_razao_lag1"] = np.log(defasar("quantidade", 1) / media)
        df["log_razao_lag2"] = np.log(defasar("quantidade", 2) / media)
        df["log_razao_media3"] = np.log(media_movel("quantidade", 3) / media)
        df["log_variacao_lag1"] = np.log(defasar("quantidade", 1) / defasar("quantidade", 2))
        df["log_razao_lag12"] = np.log(defasar("quantidade", 12) / media)
        df["log_preco_rel_lag1"] = np.log(defasar("preco_unitario", 1) / media_movel("preco_unitario", 12))

    df["alta_mes_anterior"] = defasar("alta_demanda", 1).astype("Float64").astype(float)
    df["indice_sazonal_hist"] = indice_sazonal_historico(df)
    df["mes_seno"] = np.sin(2 * np.pi * df["mes"] / 12)
    df["mes_cosseno"] = np.cos(2 * np.pi * df["mes"] / 12)
    df["log_populacao"] = np.log(df["populacao_2022"])
    df["log_producao_ano_anterior"] = np.log1p(df["producao_ano_anterior_t"])
    df["produz_no_municipio"] = (df["producao_ano_anterior_t"].fillna(0) > 0).astype(int)
    df["producao_indisponivel"] = df["producao_ano_anterior_t"].isna().astype(int)

    df[FEATURES_NUMERICAS] = df[FEATURES_NUMERICAS].replace([np.inf, -np.inf], np.nan)

    modelo = df[df[ALVO].notna()].copy()
    modelo[ALVO] = modelo[ALVO].astype(int)
    modelo["conjunto"] = np.where(modelo["ano"] >= ANO_TESTE, "teste", "treino")
    colunas = list(dict.fromkeys(COLUNAS_ID + FEATURES + [ALVO, "conjunto"]))  # sem repetir chave e uf
    return modelo[colunas].reset_index(drop=True)
