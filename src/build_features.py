"""Etapa 5 do pipeline: geração da base de modelagem (features + alvo).

Lê o modelo dimensional, calcula as features de src/features.py e grava:
  - ml.features_demanda (PostgreSQL), com chave primária município + produto + mês
  - data/processed/features_modelo.csv
  - reports/dicionario_features.csv

Uso (na raiz do projeto, depois de src.etl):
    python -m src.build_features
"""
import logging

from sqlalchemy import text

from src import config
from src.features import ALVO, FEATURES, construir_features, dicionario_features
from src.leitura import carregar_dw, montar_base_vendas

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("build_features")

TABELA_DESTINO = "features_demanda"


def gravar_no_banco(features) -> None:
    from src.db import criar_engine

    engine = criar_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS ml"))
        features.to_sql(TABELA_DESTINO, conn, schema="ml", if_exists="replace", index=False, chunksize=5000)
        conn.execute(text(f"ALTER TABLE ml.{TABELA_DESTINO} ADD PRIMARY KEY (cod_ibge, id_produto, id_tempo)"))
        conn.execute(text(f"COMMENT ON TABLE ml.{TABELA_DESTINO} IS 'Base de modelagem: features (até t-1) e alvo alta_demanda.'"))
        no_banco = conn.execute(text(f"SELECT count(*) FROM ml.{TABELA_DESTINO}")).scalar()
    engine.dispose()
    if no_banco != len(features):
        raise RuntimeError("Contagem divergente em ml.features_demanda")
    log.info("Gravado em ml.%s (%s linhas).", TABELA_DESTINO, no_banco)


def main() -> None:
    dw, origem = carregar_dw()
    log.info("Fonte do modelo dimensional: %s", origem)

    features = construir_features(montar_base_vendas(dw))

    config.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    features.to_csv(config.DATA_PROCESSED / "features_modelo.csv", index=False, encoding="utf-8")
    dicionario_features().to_csv(config.REPORTS_DIR / "dicionario_features.csv", index=False, encoding="utf-8")

    if origem.startswith("PostgreSQL"):
        gravar_no_banco(features)
    else:
        log.warning("Banco indisponível: base gravada só em data/processed.")

    resumo = features.groupby("conjunto")[ALVO].agg(registros="size", taxa_alta_demanda="mean")
    log.info("Base de modelagem: %s linhas, %s features", len(features), len(FEATURES))
    for conjunto, linha in resumo.iterrows():
        log.info("  %-7s %6d registros | alta demanda: %.1f%%", conjunto, int(linha["registros"]), 100 * linha["taxa_alta_demanda"])
    ausentes = features[FEATURES].isna().sum()
    for nome, total in ausentes[ausentes > 0].items():
        log.info("  valores ausentes em %-26s %6s", nome, total)
    log.info("Features concluídas.")


if __name__ == "__main__":
    main()
