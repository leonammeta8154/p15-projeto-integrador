"""Funções utilitárias compartilhadas pelas etapas do pipeline."""
import json
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

# Símbolos especiais da API SIDRA (https://apisidra.ibge.gov.br/home/ajuda)
#   "-"   zero absoluto
#   "..", "...", "X" e letras  valor não aplicável, não disponível ou inibido
SIMBOLO_ZERO = "-"


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sem acentos e sem espaços nas pontas: 'Açaí ' -> 'acai'."""
    if texto is None or (isinstance(texto, float) and np.isnan(texto)):
        return ""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.strip().lower()


def converter_valor_sidra(valor) -> float:
    """Converte o campo V do SIDRA em número, tratando os símbolos especiais."""
    if valor is None:
        return np.nan
    valor = str(valor).strip()
    if valor == SIMBOLO_ZERO:
        return 0.0
    try:
        return float(valor)
    except ValueError:
        return np.nan


def salvar_json(dados, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)


def ler_json(caminho: Path):
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Leitura dos arquivos brutos do IBGE
# ---------------------------------------------------------------------------
_MAPA_ROTULOS = {
    "Município (Código)": "cod_ibge",
    "Município": "municipio",
    "Variável (Código)": "cod_variavel",
    "Variável": "variavel",
    "Ano (Código)": "cod_ano",
    "Ano": "ano",
    "Unidade de Medida (Código)": "cod_unidade",
    "Unidade de Medida": "unidade",
    "Valor": "valor",
    "Nível Territorial (Código)": "cod_nivel",
    "Nível Territorial": "nivel",
}


def ler_sidra(caminho: Path) -> pd.DataFrame:
    """Lê um JSON bruto da API SIDRA (com cabeçalho) e devolve um DataFrame.

    O primeiro registro do JSON é o cabeçalho, que diz o que é cada campo
    (D1C, D1N...). Usamos esse cabeçalho para nomear as colunas, então o
    código não depende da ordem das dimensões na URL.
    """
    registros = ler_json(caminho)
    if not registros:
        return pd.DataFrame()
    cabecalho, linhas = registros[0], registros[1:]
    df = pd.DataFrame(linhas).rename(columns=cabecalho)

    novos_nomes = {}
    for rotulo in df.columns:
        if rotulo in _MAPA_ROTULOS:
            novos_nomes[rotulo] = _MAPA_ROTULOS[rotulo]
        elif rotulo.endswith("(Código)"):
            novos_nomes[rotulo] = "cod_categoria"  # classificação da tabela
        else:
            novos_nomes[rotulo] = "categoria"
    df = df.rename(columns=novos_nomes)
    df["valor"] = df["valor"].map(converter_valor_sidra)
    return df


def ler_municipios(caminho: Path) -> pd.DataFrame:
    """Lê o JSON da API de Localidades do IBGE (municípios de uma UF)."""
    linhas = []
    for m in ler_json(caminho):
        imediata = m.get("regiao-imediata") or {}
        intermediaria = imediata.get("regiao-intermediaria") or {}
        micro = m.get("microrregiao") or {}
        meso = micro.get("mesorregiao") or {}
        uf = intermediaria.get("UF") or meso.get("UF") or {}
        linhas.append(
            {
                "cod_ibge": int(m["id"]),
                "municipio": m["nome"],
                "uf": uf.get("sigla"),
                "regiao_intermediaria": intermediaria.get("nome"),
                "regiao_imediata": imediata.get("nome"),
            }
        )
    return pd.DataFrame(linhas)


def carregar_municipios(dir_raw: Path, ufs) -> pd.DataFrame:
    partes = [ler_municipios(dir_raw / f"ibge_municipios_{uf}.json") for uf in ufs]
    return pd.concat(partes, ignore_index=True)


def carregar_populacao(dir_raw: Path, ufs) -> pd.DataFrame:
    """População residente (Censo 2022) por município."""
    partes = []
    for uf in ufs:
        df = ler_sidra(dir_raw / f"sidra_4709_populacao_{uf}.json")
        df = df[df["variavel"].map(normalizar_texto).str.startswith("populacao residente")]
        partes.append(df[["cod_ibge", "valor"]])
    pop = pd.concat(partes, ignore_index=True).rename(columns={"valor": "populacao_2022"})
    pop["cod_ibge"] = pop["cod_ibge"].astype(int)
    return pop


def identificar_produto(nome_categoria: str, produtos: dict):
    """Devolve a chave do produto do projeto que corresponde à categoria PEVS."""
    nome = normalizar_texto(nome_categoria)
    for chave, info in produtos.items():
        if info["busca_pevs"] in nome:
            return chave
    return None


def carregar_pevs(dir_raw: Path, ufs, anos, produtos) -> pd.DataFrame:
    """Produção extrativa (PEVS) em formato largo: quantidade e valor por linha."""
    partes = []
    for uf in ufs:
        for ano in anos:
            caminho = dir_raw / f"sidra_289_pevs_{uf}_{ano}.json"
            if caminho.exists():
                partes.append(ler_sidra(caminho))
    df = pd.concat(partes, ignore_index=True)
    df["produto"] = df["categoria"].map(lambda c: identificar_produto(c, produtos))
    df = df[df["produto"].notna()].copy()

    var = df["variavel"].map(normalizar_texto)
    df["medida"] = np.where(var.str.startswith("quantidade"), "quantidade_produzida", "valor_producao_mil_reais")

    # aggfunc="first" preserva NaN (valor não disponível); "sum" viraria zero
    largo = (
        df.pivot_table(
            index=["cod_ibge", "produto", "ano"],
            columns="medida",
            values="valor",
            aggfunc="first",
            dropna=False,
        )
        .reset_index()
    )
    largo.columns.name = None

    unidades = (
        df[df["medida"] == "quantidade_produzida"]
        .groupby("produto")["unidade"]
        .first()
        .rename("unidade_producao")
    )
    largo = largo.merge(unidades, on="produto", how="left")
    largo["cod_ibge"] = largo["cod_ibge"].astype(int)
    largo["ano"] = largo["ano"].astype(int)
    return largo
