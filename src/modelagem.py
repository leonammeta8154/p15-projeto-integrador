"""Etapa 6: treinamento, seleção e avaliação dos modelos de classificação.

Metodologia
  - Treino: 2023. Teste: 2024. O teste é usado UMA vez, só para a avaliação
    final; nenhuma escolha (modelo ou hiperparâmetro) olha para ele.
  - Seleção de hiperparâmetros e do modelo final: validação cruzada temporal
    DENTRO de 2023, com janela crescente (treina até o mês k e valida nos
    dois meses seguintes), pela média do F1.
  - Referências: duas regras ingênuas, sem aprendizado, que o modelo precisa
    superar para justificar a sua existência.
"""
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src import config
from src.features import ALVO, FEATURES, FEATURES_CATEGORICAS, FEATURES_NUMERICAS

SEED = 42
ARQUIVO_MODELO = config.MODELS_DIR / "modelo_alta_demanda.pkl"


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------
def carregar_base_modelagem() -> tuple[pd.DataFrame, str]:
    """Lê ml.features_demanda do PostgreSQL; sem banco, usa o CSV gerado."""
    try:
        from sqlalchemy import text

        from src.db import criar_engine

        engine = criar_engine()
        with engine.connect() as conn:
            df = pd.read_sql(text("SELECT * FROM ml.features_demanda"), conn)
        engine.dispose()
        origem = "PostgreSQL (ml.features_demanda)"
    except Exception:
        df = pd.read_csv(config.DATA_PROCESSED / "features_modelo.csv")
        origem = "CSV (data/processed/features_modelo.csv)"
    df = df.sort_values(["id_tempo", "cod_ibge", "id_produto"]).reset_index(drop=True)
    return df, origem


def separar(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    treino = df[df["conjunto"] == "treino"].reset_index(drop=True)
    teste = df[df["conjunto"] == "teste"].reset_index(drop=True)
    return treino, teste


def folds_temporais(treino: pd.DataFrame, primeiro_corte: int = 6, meses_validacao: int = 2):
    """Janela crescente dentro do treino: (até jun -> jul/ago), (até ago ->
    set/out), (até out -> nov/dez). Nunca valida em mês anterior ao treino."""
    folds = []
    for corte in range(primeiro_corte, 12, meses_validacao):
        idx_treino = np.where(treino["mes"] <= corte)[0]
        idx_valid = np.where((treino["mes"] > corte) & (treino["mes"] <= corte + meses_validacao))[0]
        folds.append((idx_treino, idx_valid))
    return folds


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
def _codificador():
    return OneHotEncoder(handle_unknown="ignore")


def modelos_candidatos() -> dict[str, tuple[Pipeline, dict]]:
    """Pipelines completos (pré-processamento + modelo) e grades de busca.

    O pré-processamento fica dentro do pipeline, então é ajustado só com os
    dados de treino de cada etapa da validação.
    """
    imputar = lambda: SimpleImputer(strategy="median", add_indicator=True)  # noqa: E731

    logistica = Pipeline([
        ("prep", ColumnTransformer([
            ("num", make_pipeline(imputar(), StandardScaler()), FEATURES_NUMERICAS),
            ("cat", _codificador(), FEATURES_CATEGORICAS),
        ])),
        ("modelo", LogisticRegression(max_iter=2000)),
    ])
    floresta = Pipeline([
        ("prep", ColumnTransformer([
            ("num", imputar(), FEATURES_NUMERICAS),
            ("cat", _codificador(), FEATURES_CATEGORICAS),
        ])),
        ("modelo", RandomForestClassifier(n_estimators=300, n_jobs=-1, random_state=SEED)),
    ])
    boosting = Pipeline([
        ("prep", ColumnTransformer([
            ("num", "passthrough", FEATURES_NUMERICAS),  # trata valores ausentes nativamente
            ("cat", _codificador(), FEATURES_CATEGORICAS),
        ])),
        ("modelo", HistGradientBoostingClassifier(max_iter=300, random_state=SEED)),
    ])
    return {
        "Regressão logística": (logistica, {"modelo__C": [0.1, 1.0, 10.0]}),
        "Random Forest": (floresta, {"modelo__max_depth": [8, None], "modelo__min_samples_leaf": [5, 20]}),
        "Gradient Boosting": (boosting, {"modelo__learning_rate": [0.03, 0.1], "modelo__max_leaf_nodes": [15, 31]}),
    }


def regras_ingenuas(df: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Referências sem aprendizado: (previsão, escore para a AUC)."""
    mes_anterior = df["alta_mes_anterior"].fillna(0).to_numpy()
    sazonal = df["indice_sazonal_hist"].to_numpy()
    return {
        "Regra: repetir o mês anterior": (mes_anterior.astype(int), mes_anterior),
        "Regra: época de safra (índice sazonal > 1)": ((sazonal > 1).astype(int), sazonal),
    }


# ---------------------------------------------------------------------------
# Avaliação
# ---------------------------------------------------------------------------
def calcular_metricas(y_real, y_prev, escore=None) -> dict:
    return {
        "accuracy": accuracy_score(y_real, y_prev),
        "f1": f1_score(y_real, y_prev),
        "precisao": precision_score(y_real, y_prev, zero_division=0),
        "recall": recall_score(y_real, y_prev),
        "auc": roc_auc_score(y_real, escore) if escore is not None else np.nan,
    }


def treinar_e_avaliar(df: pd.DataFrame) -> dict:
    """Executa toda a Etapa 6 e devolve resultados, modelos e previsões."""
    treino, teste = separar(df)
    folds = folds_temporais(treino)
    y_treino, y_teste = treino[ALVO], teste[ALVO]

    linhas, previsoes, ajustados, buscas = [], {}, {}, {}

    for nome, (prev_treino, _) in regras_ingenuas(treino).items():
        f1_folds = [f1_score(y_treino.iloc[v], prev_treino[v]) for _, v in folds]
        prev, escore = regras_ingenuas(teste)[nome]
        previsoes[nome] = (prev, escore)
        linhas.append({"modelo": nome, "tipo": "referência", "f1_validacao": np.mean(f1_folds),
                       "melhores_parametros": "-", **calcular_metricas(y_teste, prev, escore)})

    for nome, (pipeline, grade) in modelos_candidatos().items():
        busca = GridSearchCV(pipeline, grade, cv=folds, scoring="f1", refit=True)
        busca.fit(treino[FEATURES], y_treino)  # refit: melhor configuração treinada em todo o 2023
        modelo = busca.best_estimator_
        prob = modelo.predict_proba(teste[FEATURES])[:, 1]
        prev = (prob >= 0.5).astype(int)
        ajustados[nome], buscas[nome], previsoes[nome] = modelo, busca, (prev, prob)
        parametros = ", ".join(f"{k.replace('modelo__', '')}={v}" for k, v in busca.best_params_.items())
        linhas.append({"modelo": nome, "tipo": "aprendizado de máquina", "f1_validacao": busca.best_score_,
                       "melhores_parametros": parametros, **calcular_metricas(y_teste, prev, prob)})

    resultados = pd.DataFrame(linhas).set_index("modelo")
    aprendidos = resultados[resultados["tipo"] == "aprendizado de máquina"]
    melhor = aprendidos["f1_validacao"].idxmax()  # escolha pela validação, não pelo teste
    return {
        "resultados": resultados,
        "melhor": melhor,
        "modelos": ajustados,
        "buscas": buscas,
        "previsoes": previsoes,
        "treino": treino,
        "teste": teste,
        "folds": folds,
    }


def tabela_previsoes(saida: dict) -> pd.DataFrame:
    """Previsões do modelo final no teste, com a regra de referência ao lado."""
    teste = saida["teste"]
    prev, prob = saida["previsoes"][saida["melhor"]]
    ref, _ = saida["previsoes"]["Regra: repetir o mês anterior"]
    return teste[["cod_ibge", "municipio", "uf", "id_produto", "nome", "id_tempo", "mes", ALVO]].assign(
        previsto=prev, probabilidade_alta=np.round(prob, 4), previsto_regra_mes_anterior=ref,
        acertou=lambda d: (d["previsto"] == d[ALVO]).astype(int),
    )


def salvar_modelo(saida: dict) -> dict:
    melhor = saida["melhor"]
    linha = saida["resultados"].loc[melhor]
    pacote = {
        "modelo": saida["modelos"][melhor],
        "nome": melhor,
        "features": FEATURES,
        "alvo": ALVO,
        "parametros": linha["melhores_parametros"],
        "periodo_treino": "jan/2023 a dez/2023",
        "metricas_teste_2024": {m: float(linha[m]) for m in ["accuracy", "f1", "precisao", "recall", "auc"]},
        "treinado_em": datetime.now().isoformat(timespec="seconds"),
        "versao_scikit_learn": sklearn.__version__,
    }
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(pacote, ARQUIVO_MODELO)
    return pacote


def carregar_modelo() -> dict:
    return joblib.load(ARQUIVO_MODELO)


def importancia_permutacao(modelo, dados: pd.DataFrame, repeticoes: int = 10) -> pd.DataFrame:
    """Queda média do F1 quando os valores de uma feature são embaralhados:
    quanto maior a queda, mais o modelo depende daquela feature."""
    from sklearn.inspection import permutation_importance

    resultado = permutation_importance(
        modelo, dados[FEATURES], dados[ALVO], scoring="f1", n_repeats=repeticoes, random_state=SEED, n_jobs=-1
    )
    return (
        pd.DataFrame({"feature": FEATURES, "queda_f1_media": resultado.importances_mean,
                      "queda_f1_desvio": resultado.importances_std})
        .sort_values("queda_f1_media", ascending=False)
        .reset_index(drop=True)
    )


def metricas_por_grupo(previsoes: pd.DataFrame, coluna: str) -> pd.DataFrame:
    linhas = []
    for valor, grupo in previsoes.groupby(coluna):
        linhas.append({coluna: valor, "registros": len(grupo),
                       "f1_modelo": f1_score(grupo[ALVO], grupo["previsto"]),
                       "f1_regra_mes_anterior": f1_score(grupo[ALVO], grupo["previsto_regra_mes_anterior"]),
                       "accuracy_modelo": accuracy_score(grupo[ALVO], grupo["previsto"])})
    return pd.DataFrame(linhas)
