-- =============================================================================
-- P15: verificação da camada staging (evidências da Etapa 2)
-- Executar no SQL Shell (psql):  \i sql/02_verificacao_staging.sql
-- =============================================================================
\c bioeconomia
\encoding UTF8
\pset pager off

\echo '1. Registros carregados por tabela'
SELECT 'stg_municipios' AS tabela, count(*) AS registros FROM staging.stg_municipios
UNION ALL SELECT 'stg_populacao', count(*) FROM staging.stg_populacao
UNION ALL SELECT 'stg_pevs',      count(*) FROM staging.stg_pevs
UNION ALL SELECT 'stg_vendas',    count(*) FROM staging.stg_vendas;

\echo '2. Municípios por UF'
SELECT uf, count(*) AS municipios
FROM staging.stg_municipios
GROUP BY uf ORDER BY uf;

\echo '3. Problema: grafias diferentes do mesmo produto nas vendas'
SELECT produto, count(*) AS registros
FROM staging.stg_vendas
GROUP BY produto ORDER BY registros DESC;

\echo '4. Problema: dois formatos de mês de referência'
SELECT CASE WHEN mes_referencia LIKE '__/____' THEN 'MM/AAAA' ELSE 'AAAA-MM' END AS formato,
       count(*) AS registros
FROM staging.stg_vendas
GROUP BY 1;

\echo '5. Problemas: código IBGE ausente, preço ausente e quantidade negativa'
SELECT count(*) FILTER (WHERE cod_ibge IS NULL)              AS sem_cod_ibge,
       count(*) FILTER (WHERE preco_unitario IS NULL)        AS sem_preco,
       count(*) FILTER (WHERE quantidade::numeric < 0)       AS quantidade_negativa
FROM staging.stg_vendas;

\echo '6. Problema: linhas duplicadas'
SELECT count(*) - count(DISTINCT (id_venda, mes_referencia, cod_ibge, municipio, uf, produto,
                                  quantidade, unidade, preco_unitario, receita)) AS duplicadas
FROM staging.stg_vendas;

\echo '7. PEVS: valores especiais do IBGE ainda em texto (- zero, ... e X indisponível)'
SELECT CASE WHEN valor ~ '^[0-9]+(\.[0-9]+)?$' THEN 'numérico' ELSE valor END AS valor_bruto,
       count(*) AS registros
FROM staging.stg_pevs
GROUP BY 1 ORDER BY registros DESC;

\echo '8. PEVS: produtos de interesse do projeto encontrados na tabela 289'
SELECT DISTINCT produto_ibge
FROM staging.stg_pevs
WHERE produto_ibge ILIKE '%açaí%' OR produto_ibge ILIKE '%castanha-do-pará%' OR produto_ibge ILIKE '%copaíba%'
ORDER BY 1;
