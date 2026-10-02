"""Configurações centrais do projeto P15.

Tudo o que define o escopo do pipeline fica aqui, para que os demais
scripts não tenham valores "escondidos" no meio do código.
"""
from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
MODELS_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
SQL_DIR = ROOT / "sql"

# ---------------------------------------------------------------------------
# Escopo territorial: UFs da Amazônia trabalhadas na disciplina (código IBGE)
# ---------------------------------------------------------------------------
UFS = {"AP": 16, "PA": 15, "AM": 13}

# ---------------------------------------------------------------------------
# Produtos da bioeconomia
# - "busca_pevs": trecho usado para localizar a categoria na tabela 289 do
#   SIDRA pelo NOME (assim não dependemos de códigos fixos de categoria).
# - "preco_base": preço médio de referência usado SOMENTE na simulação de
#   vendas (valor ilustrativo, não é dado oficial).
# - "k_demanda": consumo base por mil habitantes/mês usado na simulação.
# - "pico_safra" / "amplitude": sazonalidade simplificada (mês de pico e
#   intensidade da variação ao longo do ano).
# ---------------------------------------------------------------------------
PRODUTOS = {
    "acai": {
        "nome": "Açaí",
        "busca_pevs": "acai",
        "unidade": "kg",
        "preco_base": 12.0,
        "k_demanda": 35.0,
        "pico_safra": 10,
        "amplitude": 0.35,
    },
    "castanha_do_para": {
        "nome": "Castanha-do-pará",
        "busca_pevs": "castanha-do-para",
        "unidade": "kg",
        "preco_base": 45.0,
        "k_demanda": 4.0,
        "pico_safra": 2,
        "amplitude": 0.25,
    },
    "copaiba": {
        "nome": "Óleo de copaíba",
        "busca_pevs": "copaiba",
        "unidade": "L",
        "preco_base": 90.0,
        "k_demanda": 0.6,
        "pico_safra": 8,
        "amplitude": 0.10,
    },
}

# ---------------------------------------------------------------------------
# Fontes públicas (IBGE)
# ---------------------------------------------------------------------------
URL_LOCALIDADES = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"
URL_SIDRA = "https://apisidra.ibge.gov.br/values"
URL_METADADOS = "https://servicodados.ibge.gov.br/api/v3/agregados/{tabela}/metadados"

TABELA_PEVS = 289        # Produção da Extração Vegetal e da Silvicultura (PEVS)
TABELA_POPULACAO = 4709  # Censo 2022: população residente por município

# Anos da PEVS baixados. As vendas de um ano usam a produção do ano ANTERIOR,
# porque a PEVS de um ano só é publicada no ano seguinte.
ANOS_PEVS = [2021, 2022, 2023, 2024]

# ---------------------------------------------------------------------------
# Simulação de vendas
# ---------------------------------------------------------------------------
INICIO_VENDAS = "2022-01"
FIM_VENDAS = "2024-12"
SEED = 42

# ---------------------------------------------------------------------------
# Requisições HTTP
# ---------------------------------------------------------------------------
TIMEOUT_SEGUNDOS = 90
TENTATIVAS = 3
