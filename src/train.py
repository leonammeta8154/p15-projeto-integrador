"""Etapa 6 do pipeline: treinamento, seleção e avaliação do modelo.

Lê a base de modelagem (ml.features_demanda), compara as regras de referência
e três modelos, escolhe o melhor pela validação temporal em 2023 e o avalia
uma única vez no teste de 2024.

Saídas:
  - models/modelo_alta_demanda.pkl        modelo final + metadados
  - reports/metricas_modelos.csv          comparação de todos os modelos
  - reports/metricas_por_produto.csv      desempenho do modelo final por produto
  - reports/importancia_features.csv      importância por permutação
  - data/processed/previsoes_teste.csv    previsões de 2024
  - ml.metricas_modelos e ml.previsoes_teste no PostgreSQL

Uso (na raiz do projeto, depois de src.build_features):
    python -m src.train
"""
import logging

from src import config
from src.modelagem import (
    carregar_base_modelagem,
    importancia_permutacao,
    metricas_por_grupo,
    salvar_modelo,
    tabela_previsoes,
    treinar_e_avaliar,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("train")


def gravar_no_banco(metricas, previsoes) -> None:
    from sqlalchemy import text

    from src.db import criar_engine

    engine = criar_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS ml"))
        metricas.reset_index().to_sql("metricas_modelos", conn, schema="ml", if_exists="replace", index=False)
        previsoes.to_sql("previsoes_teste", conn, schema="ml", if_exists="replace", index=False, chunksize=5000)
        conn.execute(text("ALTER TABLE ml.previsoes_teste ADD PRIMARY KEY (cod_ibge, id_produto, id_tempo)"))
    engine.dispose()
    log.info("Gravado em ml.metricas_modelos e ml.previsoes_teste.")


def main() -> None:
    df, origem = carregar_base_modelagem()
    log.info("Base de modelagem: %s (%s linhas)", origem, len(df))

    log.info("Treinando: validação temporal em 2023 e teste em 2024 (pode levar alguns minutos)")
    saida = treinar_e_avaliar(df)
    resultados = saida["resultados"]

    pacote = salvar_modelo(saida)
    previsoes = tabela_previsoes(saida)
    por_produto = metricas_por_grupo(previsoes, "nome")
    importancia = importancia_permutacao(saida["modelos"][saida["melhor"]], saida["teste"])

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    resultados.round(4).to_csv(config.REPORTS_DIR / "metricas_modelos.csv", encoding="utf-8")
    por_produto.round(4).to_csv(config.REPORTS_DIR / "metricas_por_produto.csv", index=False, encoding="utf-8")
    importancia.round(4).to_csv(config.REPORTS_DIR / "importancia_features.csv", index=False, encoding="utf-8")
    previsoes.to_csv(config.DATA_PROCESSED / "previsoes_teste.csv", index=False, encoding="utf-8")

    if origem.startswith("PostgreSQL"):
        gravar_no_banco(resultados.round(4), previsoes)

    log.info("%-46s %8s %8s %8s %8s", "modelo", "F1 valid", "Accuracy", "F1", "AUC")
    for nome, linha in resultados.iterrows():
        log.info("%-46s %8.3f %8.3f %8.3f %8.3f", nome, linha["f1_validacao"], linha["accuracy"], linha["f1"], linha["auc"])
    log.info("Modelo final (melhor F1 na validação temporal): %s [%s]", pacote["nome"], pacote["parametros"])
    log.info("Teste 2024: Accuracy %.3f | F1 %.3f", pacote["metricas_teste_2024"]["accuracy"], pacote["metricas_teste_2024"]["f1"])
    log.info("Modelo salvo em %s", config.MODELS_DIR / "modelo_alta_demanda.pkl")


if __name__ == "__main__":
    main()
