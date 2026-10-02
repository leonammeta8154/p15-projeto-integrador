"""Variável alvo e engenharia de features.

ALVO (alta_demanda): 1 quando a quantidade vendida no mês supera a média dos
12 meses ANTERIORES do mesmo município e produto; 0 caso contrário.

  - Compara cada município com o seu próprio histórico, então um município
    pequeno pode ter "alta demanda" tanto quanto uma capital.
  - Usa só meses passados na média, sem olhar o próprio mês nem o futuro.
  - Os 12 primeiros meses de cada série (2022) ficam sem alvo: servem apenas
    de histórico.
"""
import pandas as pd

JANELA_HISTORICO = 12
CHAVE_SERIE = ["cod_ibge", "id_produto"]


def adicionar_alvo(base: pd.DataFrame, janela: int = JANELA_HISTORICO) -> pd.DataFrame:
    df = base.sort_values(CHAVE_SERIE + ["id_tempo"]).copy()
    df["media_12m_anteriores"] = df.groupby(CHAVE_SERIE)["quantidade"].transform(
        lambda s: s.shift(1).rolling(janela, min_periods=janela).mean()
    )
    tem_historico = df["media_12m_anteriores"].notna()
    df["alta_demanda"] = pd.Series(pd.NA, index=df.index, dtype="Int64")
    df.loc[tem_historico, "alta_demanda"] = (
        df.loc[tem_historico, "quantidade"] > df.loc[tem_historico, "media_12m_anteriores"]
    ).astype(int)
    return df
