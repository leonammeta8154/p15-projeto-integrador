"""Etapa 1 do pipeline: geração da FONTE DE VENDAS (dados simulados).

Simula o relatório mensal de vendas de uma rede de comercialização de
produtos da bioeconomia em AP, PA e AM (jan/2022 a dez/2024).

A simulação é ancorada nos dados REAIS do IBGE já extraídos:
  - população do município (Censo 2022)      -> tamanho do mercado
  - produção extrativa do ano anterior (PEVS) -> oferta local do produto

Regras da simulação (todas documentadas no README):
  - demanda cresce com a população e com a produção local do ano anterior;
  - sazonalidade simplificada por produto (safra);
  - tendência leve de crescimento (5% ao ano);
  - ruído com memória (AR(1)): um mês bom tende a ser seguido de outro bom;
  - preço cai na safra e onde há mais produção local.

Depois, problemas de qualidade são inseridos de propósito, para que a etapa
de transformação (ETL) tenha o que tratar, como numa base real.

Uso (na raiz do projeto, depois de rodar src.extract):
    python -m src.gerar_vendas
"""
import logging

import numpy as np
import pandas as pd

from src import config
from src.utils import carregar_municipios, carregar_pevs, carregar_populacao

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("gerar_vendas")

ARQUIVO_SAIDA = config.DATA_RAW / "vendas_simuladas.csv"

# Grafias alternativas usadas para "sujar" a coluna de produto
VARIANTES_PRODUTO = {
    "acai": ["acai", "AÇAÍ", " Açaí ", "Acai"],
    "castanha_do_para": ["castanha do para", "CASTANHA-DO-PARÁ", "Castanha do Pará"],
    "copaiba": ["oleo de copaiba", "Copaíba", "ÓLEO DE COPAÍBA"],
}


def montar_base() -> tuple[pd.DataFrame, pd.DataFrame]:
    municipios = carregar_municipios(config.DATA_RAW, config.UFS)
    populacao = carregar_populacao(config.DATA_RAW, config.UFS)
    base = municipios.merge(populacao, on="cod_ibge", how="inner")
    base = base[base["populacao_2022"] > 0].reset_index(drop=True)

    pevs = carregar_pevs(config.DATA_RAW, config.UFS, config.ANOS_PEVS, config.PRODUTOS)
    pevs["quantidade_produzida"] = pevs["quantidade_produzida"].fillna(0)
    return base, pevs


def simular_vendas(base: pd.DataFrame, pevs: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    meses = pd.period_range(config.INICIO_VENDAS, config.FIM_VENDAS, freq="M")
    n_meses = len(meses)
    mes_do_ano = np.array([m.month for m in meses])
    ano = np.array([m.year for m in meses])
    t = np.arange(n_meses)

    blocos = []
    for chave, info in config.PRODUTOS.items():
        # Produção relativa (0 a 1) do município no ano anterior, em escala log
        prod = pevs[pevs["produto"] == chave][["cod_ibge", "ano", "quantidade_produzida"]]
        maximo = np.log1p(prod["quantidade_produzida"]).max()
        if not np.isfinite(maximo) or maximo <= 0:
            maximo = 1.0
        prod_rel = {
            (r.cod_ibge, r.ano): np.log1p(r.quantidade_produzida) / maximo
            for r in prod.itertuples()
        }

        sazonal = info["amplitude"] * np.cos(2 * np.pi * (mes_do_ano - info["pico_safra"]) / 12)

        for m in base.itertuples():
            rel = np.array([prod_rel.get((m.cod_ibge, a - 1), 0.0) for a in ano])
            efeito_local = rng.normal(0, 0.2)  # preferência local fixa

            ruido = np.zeros(n_meses)
            for i in range(n_meses):
                anterior = ruido[i - 1] if i > 0 else 0.0
                ruido[i] = 0.6 * anterior + rng.normal(0, 0.18)

            log_qtd = (
                np.log(info["k_demanda"] * (m.populacao_2022 / 1000) ** 0.85)
                + np.log1p(0.6 * rel)
                + sazonal
                + 0.05 * (t / 12)
                + efeito_local
                + ruido
            )
            quantidade = np.round(np.exp(log_qtd), 1)

            preco = (
                info["preco_base"]
                * (1 - 0.6 * sazonal)
                * (1 + 0.04 * (ano - ano[0]))
                * (1 - 0.15 * rel)
                * rng.lognormal(0, 0.05, n_meses)
            )
            preco = np.round(preco, 2)

            blocos.append(
                pd.DataFrame(
                    {
                        "mes_referencia": [str(p) for p in meses],
                        "cod_ibge": m.cod_ibge,
                        "municipio": m.municipio,
                        "uf": m.uf,
                        "produto_chave": chave,
                        "produto": info["nome"],
                        "quantidade": quantidade,
                        "unidade": info["unidade"],
                        "preco_unitario": preco,
                        "receita": np.round(quantidade * preco, 2),
                    }
                )
            )

    vendas = pd.concat(blocos, ignore_index=True)
    vendas.insert(0, "id_venda", np.arange(1, len(vendas) + 1))
    return vendas


def inserir_problemas(vendas: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Insere problemas típicos de bases reais. Retorna a base 'suja'."""
    df = vendas.copy()
    n = len(df)
    df["cod_ibge"] = df["cod_ibge"].astype("Int64")

    def sortear(fracao):
        return rng.choice(n, size=int(n * fracao), replace=False)

    # 1. Nome do produto com grafias diferentes (15%)
    idx = sortear(0.15)
    df.loc[idx, "produto"] = [
        rng.choice(VARIANTES_PRODUTO[c]) for c in df.loc[idx, "produto_chave"]
    ]
    # 2. Data em outro formato: "MM/AAAA" em vez de "AAAA-MM" (10%)
    idx = sortear(0.10)
    df.loc[idx, "mes_referencia"] = [f"{s[5:7]}/{s[:4]}" for s in df.loc[idx, "mes_referencia"]]
    # 3. Nome do município em caixa alta (5%)
    idx = sortear(0.05)
    df.loc[idx, "municipio"] = df.loc[idx, "municipio"].str.upper()
    # 4. Código IBGE ausente (0,5%): recuperável pelo nome + UF
    idx = sortear(0.005)
    df.loc[idx, "cod_ibge"] = pd.NA
    # 5. Preço unitário ausente (1,5%): recuperável por receita / quantidade
    idx = sortear(0.015)
    df.loc[idx, "preco_unitario"] = np.nan
    # 6. Erro de digitação na quantidade: valor 100x maior (0,3%)
    idx = sortear(0.003)
    df.loc[idx, "quantidade"] = df.loc[idx, "quantidade"] * 100
    # 7. Quantidade com sinal trocado (0,2%)
    idx = sortear(0.002)
    df.loc[idx, "quantidade"] = -df.loc[idx, "quantidade"]
    # 8. Linhas duplicadas na exportação (0,8%)
    duplicadas = df.iloc[sortear(0.008)]
    df = pd.concat([df, duplicadas], ignore_index=True)

    # Embaralha, como numa exportação sem ordenação
    df = df.sample(frac=1, random_state=config.SEED).reset_index(drop=True)
    return df.drop(columns=["produto_chave"])


def main() -> None:
    rng = np.random.default_rng(config.SEED)
    base, pevs = montar_base()
    log.info("Municípios com população: %s | registros PEVS: %s", len(base), len(pevs))

    vendas = simular_vendas(base, pevs, rng)
    vendas_sujas = inserir_problemas(vendas, rng)

    ARQUIVO_SAIDA.parent.mkdir(parents=True, exist_ok=True)
    vendas_sujas.to_csv(ARQUIVO_SAIDA, index=False, encoding="utf-8")
    log.info(
        "Vendas simuladas: %s linhas (%s registros + duplicatas) -> %s",
        len(vendas_sujas),
        len(vendas),
        ARQUIVO_SAIDA,
    )


if __name__ == "__main__":
    main()
