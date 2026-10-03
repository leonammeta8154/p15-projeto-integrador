"""Executa o pipeline completo, da coleta ao modelo, em um único comando.

    Fontes de Dados -> PostgreSQL -> ETL Python -> Features -> Machine Learning -> Métricas

Etapas, na ordem:
  1. extract          coleta das fontes do IBGE (usa o cache de data/raw)
  2. gerar_vendas     fonte de vendas simulada (semente fixa: resultado idêntico)
  3. setup_db         cria o banco e a estrutura, se ainda não existirem
  4. load_staging     carga dos dados brutos na staging
  5. etl              staging -> modelo dimensional (dw)
  6. build_features   dw -> base de modelagem (ml.features_demanda)
  7. train            treino, seleção, avaliação e modelo final (.pkl)

Uso (na raiz do projeto, com o .env configurado):
    python -m src.pipeline
"""
import logging
import sys
import time

from src import build_features, etl, extract, gerar_vendas, load_staging, setup_db, train

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("pipeline")

ETAPAS = [
    ("1/7 Coleta das fontes do IBGE", extract.main),
    ("2/7 Fonte de vendas simulada", gerar_vendas.main),
    ("3/7 Banco e estrutura no PostgreSQL", setup_db.main),
    ("4/7 Carga da staging", load_staging.main),
    ("5/7 ETL para o modelo dimensional", etl.main),
    ("6/7 Engenharia de features", build_features.main),
    ("7/7 Treino e avaliação do modelo", train.main),
]


def main() -> None:
    argv_original = sys.argv
    sys.argv = [argv_original[0]]  # as etapas usam argparse; roda cada uma com os padrões
    inicio = time.time()
    try:
        for titulo, executar in ETAPAS:
            log.info("=" * 70)
            log.info(titulo)
            log.info("=" * 70)
            t0 = time.time()
            executar()
            log.info("%s concluída em %.1f s", titulo, time.time() - t0)
    finally:
        sys.argv = argv_original
    log.info("Pipeline completo em %.1f s.", time.time() - inicio)


if __name__ == "__main__":
    main()
