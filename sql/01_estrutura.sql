-- =============================================================================
-- P15 Projeto Integrador: estrutura do banco "bioeconomia"
--
-- Duas camadas:
--   staging : dados brutos, exatamente como chegaram das fontes (tudo texto)
--   dw      : modelo dimensional (estrela), com tipos, chaves e restrições,
--             preenchido pelo ETL em Python a partir da staging
--
-- Pode ser executado mais de uma vez (IF NOT EXISTS).
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS dw;

COMMENT ON SCHEMA staging IS 'Dados brutos das fontes, sem tratamento (tudo em texto).';
COMMENT ON SCHEMA dw IS 'Modelo dimensional tratado pelo ETL, base para features e modelo.';

-- -----------------------------------------------------------------------------
-- CAMADA STAGING
-- Tudo em TEXT de propósito: a staging não rejeita nada, guarda o dado como
-- veio (inclusive "-", "..." e "X" do IBGE e as grafias erradas das vendas).
-- Tipagem, validação e limpeza acontecem no ETL.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging.stg_municipios (
    cod_ibge              TEXT,
    municipio             TEXT,
    uf                    TEXT,
    regiao_intermediaria  TEXT,
    regiao_imediata       TEXT,
    arquivo_origem        TEXT        NOT NULL,
    carregado_em          TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE staging.stg_municipios IS 'Fonte 1: API de Localidades do IBGE.';

CREATE TABLE IF NOT EXISTS staging.stg_populacao (
    cod_ibge        TEXT,
    municipio       TEXT,
    cod_variavel    TEXT,
    variavel        TEXT,
    ano             TEXT,
    unidade         TEXT,
    valor           TEXT,
    arquivo_origem  TEXT        NOT NULL,
    carregado_em    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE staging.stg_populacao IS 'Fonte 2: SIDRA tabela 4709 (Censo 2022).';

CREATE TABLE IF NOT EXISTS staging.stg_pevs (
    cod_ibge         TEXT,
    municipio        TEXT,
    cod_variavel     TEXT,
    variavel         TEXT,
    ano              TEXT,
    cod_produto_ibge TEXT,
    produto_ibge     TEXT,
    unidade          TEXT,
    valor            TEXT,
    arquivo_origem   TEXT        NOT NULL,
    carregado_em     TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE staging.stg_pevs IS 'Fonte 3: SIDRA tabela 289 (PEVS), todos os produtos extrativos.';

CREATE TABLE IF NOT EXISTS staging.stg_vendas (
    id_venda        TEXT,
    mes_referencia  TEXT,
    cod_ibge        TEXT,
    municipio       TEXT,
    uf              TEXT,
    produto         TEXT,
    quantidade      TEXT,
    unidade         TEXT,
    preco_unitario  TEXT,
    receita         TEXT,
    arquivo_origem  TEXT        NOT NULL,
    carregado_em    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE staging.stg_vendas IS 'Fonte 4: relatório de vendas simulado, com problemas de qualidade.';

-- -----------------------------------------------------------------------------
-- CAMADA DW: modelo estrela
-- Duas tabelas fato compartilham as dimensões de município e produto.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_municipio (
    cod_ibge              INTEGER      PRIMARY KEY,
    municipio             VARCHAR(100) NOT NULL,
    uf                    CHAR(2)      NOT NULL,
    regiao_intermediaria  VARCHAR(100),
    regiao_imediata       VARCHAR(100),
    populacao_2022        INTEGER      CHECK (populacao_2022 >= 0)
);
COMMENT ON TABLE dw.dim_municipio IS 'Municípios de AP, PA e AM com população do Censo 2022.';

CREATE TABLE IF NOT EXISTS dw.dim_produto (
    id_produto     SMALLINT     PRIMARY KEY,
    chave          VARCHAR(30)  NOT NULL UNIQUE,
    nome           VARCHAR(60)  NOT NULL,
    unidade_venda  VARCHAR(5)   NOT NULL
);
COMMENT ON TABLE dw.dim_produto IS 'Produtos da bioeconomia analisados (açaí, castanha-do-pará, óleo de copaíba).';

CREATE TABLE IF NOT EXISTS dw.dim_tempo (
    id_tempo         INTEGER      PRIMARY KEY,   -- formato AAAAMM
    data_referencia  DATE         NOT NULL UNIQUE,
    ano              SMALLINT     NOT NULL,
    mes              SMALLINT     NOT NULL CHECK (mes BETWEEN 1 AND 12),
    trimestre        SMALLINT     NOT NULL CHECK (trimestre BETWEEN 1 AND 4),
    nome_mes         VARCHAR(10)  NOT NULL
);
COMMENT ON TABLE dw.dim_tempo IS 'Calendário mensal das vendas.';

CREATE TABLE IF NOT EXISTS dw.fato_producao_extrativa (
    cod_ibge                  INTEGER   NOT NULL REFERENCES dw.dim_municipio (cod_ibge),
    id_produto                SMALLINT  NOT NULL REFERENCES dw.dim_produto (id_produto),
    ano                       SMALLINT  NOT NULL,
    quantidade_produzida      NUMERIC(14, 3),   -- NULL = dado não disponível no IBGE
    unidade_producao          VARCHAR(20),
    valor_producao_mil_reais  NUMERIC(14, 3),
    PRIMARY KEY (cod_ibge, id_produto, ano)
);
COMMENT ON TABLE dw.fato_producao_extrativa IS 'Produção extrativa anual por município e produto (PEVS/IBGE).';

CREATE TABLE IF NOT EXISTS dw.fato_vendas (
    cod_ibge        INTEGER        NOT NULL REFERENCES dw.dim_municipio (cod_ibge),
    id_produto      SMALLINT       NOT NULL REFERENCES dw.dim_produto (id_produto),
    id_tempo        INTEGER        NOT NULL REFERENCES dw.dim_tempo (id_tempo),
    quantidade      NUMERIC(14, 1) NOT NULL CHECK (quantidade >= 0),
    preco_unitario  NUMERIC(10, 2) NOT NULL CHECK (preco_unitario > 0),
    receita         NUMERIC(16, 2) NOT NULL CHECK (receita >= 0),
    PRIMARY KEY (cod_ibge, id_produto, id_tempo)
);
COMMENT ON TABLE dw.fato_vendas IS 'Vendas mensais tratadas: uma linha por município, produto e mês.';

-- -----------------------------------------------------------------------------
-- Auditoria do ETL: o que cada execução corrigiu ou descartou (não é apagada
-- entre execuções, formando um histórico)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.log_qualidade_etl (
    id_log        SERIAL       PRIMARY KEY,
    executado_em  TIMESTAMPTZ  NOT NULL,
    tabela        VARCHAR(40)  NOT NULL,
    regra         VARCHAR(200) NOT NULL,
    registros     INTEGER      NOT NULL
);
COMMENT ON TABLE dw.log_qualidade_etl IS 'Relatório de qualidade de cada execução do ETL.';

CREATE INDEX IF NOT EXISTS ix_fato_vendas_tempo   ON dw.fato_vendas (id_tempo);
CREATE INDEX IF NOT EXISTS ix_fato_vendas_produto ON dw.fato_vendas (id_produto);
CREATE INDEX IF NOT EXISTS ix_fato_producao_ano   ON dw.fato_producao_extrativa (ano);
