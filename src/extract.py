"""Etapa 1 do pipeline: EXTRAÇÃO das fontes públicas do IBGE.

Fontes coletadas (salvas sem alteração em data/raw/):
  1. API de Localidades do IBGE  -> municípios de AP, PA e AM
  2. SIDRA tabela 4709           -> população residente (Censo 2022)
  3. SIDRA tabela 289 (PEVS)     -> produção extrativa por município e ano

Os arquivos já baixados são reaproveitados (cache). Use --force para baixar
tudo de novo.

Uso (na raiz do projeto):
    python -m src.extract
    python -m src.extract --force
"""
import argparse
import logging
import time
from urllib.parse import quote

import requests

from src import config
from src.utils import ler_json, normalizar_texto, salvar_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("extract")


def baixar_json(url: str):
    """GET com novas tentativas, pois as APIs do IBGE oscilam com frequência."""
    for tentativa in range(1, config.TENTATIVAS + 1):
        try:
            resposta = requests.get(url, timeout=config.TIMEOUT_SEGUNDOS)
            resposta.raise_for_status()
            return resposta.json()
        except (requests.RequestException, ValueError) as erro:
            log.warning("Falha (tentativa %s/%s) em %s: %s", tentativa, config.TENTATIVAS, url, erro)
            if tentativa == config.TENTATIVAS:
                raise
            time.sleep(5 * tentativa)


def obter(url: str, nome_arquivo: str, force: bool):
    """Baixa e salva em data/raw, ou reaproveita o arquivo se já existir."""
    destino = config.DATA_RAW / nome_arquivo
    if destino.exists() and not force:
        log.info("Cache: %s", nome_arquivo)
        return ler_json(destino)
    log.info("Baixando: %s", nome_arquivo)
    dados = baixar_json(url)
    salvar_json(dados, destino)
    return dados


def url_sidra(caminho: str) -> str:
    # Os parâmetros do SIDRA têm espaços (ex.: "in n3 16"), que precisam de encoding
    return f"{config.URL_SIDRA}/{quote(caminho)}"


# ---------------------------------------------------------------------------
# Fonte 1: municípios
# ---------------------------------------------------------------------------
def extrair_municipios(force: bool) -> None:
    for uf, codigo in config.UFS.items():
        obter(config.URL_LOCALIDADES.format(uf=codigo), f"ibge_municipios_{uf}.json", force)


# ---------------------------------------------------------------------------
# Fonte 2: população (Censo 2022)
# ---------------------------------------------------------------------------
def extrair_populacao(force: bool) -> None:
    for uf, codigo in config.UFS.items():
        caminho = f"t/{config.TABELA_POPULACAO}/n6/in n3 {codigo}/v/allxp/p/last"
        obter(url_sidra(caminho), f"sidra_4709_populacao_{uf}.json", force)


# ---------------------------------------------------------------------------
# Fonte 3: PEVS (produção extrativa)
# ---------------------------------------------------------------------------
def descobrir_classificacao_pevs(force: bool) -> int:
    """Lê os metadados da tabela 289 para descobrir o código da classificação
    'Tipo de produto extrativo', em vez de deixá-lo fixo no código."""
    metadados = obter(
        config.URL_METADADOS.format(tabela=config.TABELA_PEVS),
        f"sidra_{config.TABELA_PEVS}_metadados.json",
        force,
    )
    classificacoes = metadados.get("classificacoes", [])
    for c in classificacoes:
        if "produto" in normalizar_texto(c.get("nome")):
            return int(c["id"])
    if classificacoes:
        return int(classificacoes[0]["id"])
    raise RuntimeError("Classificação de produto não encontrada nos metadados da tabela 289.")


def extrair_pevs(force: bool) -> None:
    id_classificacao = descobrir_classificacao_pevs(force)
    log.info("Classificação de produto da PEVS: c%s", id_classificacao)
    # Uma consulta por UF e por ano mantém cada requisição bem abaixo do
    # limite de 100.000 valores da API SIDRA.
    for uf, codigo in config.UFS.items():
        for ano in config.ANOS_PEVS:
            caminho = (
                f"t/{config.TABELA_PEVS}/n6/in n3 {codigo}/v/allxp/p/{ano}"
                f"/c{id_classificacao}/allxt"
            )
            obter(url_sidra(caminho), f"sidra_289_pevs_{uf}_{ano}.json", force)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extração das fontes públicas do IBGE")
    parser.add_argument("--force", action="store_true", help="baixa novamente mesmo com cache")
    args = parser.parse_args()

    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    extrair_municipios(args.force)
    extrair_populacao(args.force)
    extrair_pevs(args.force)
    log.info("Extração concluída. Arquivos em %s", config.DATA_RAW)


if __name__ == "__main__":
    main()
