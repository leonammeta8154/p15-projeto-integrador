-- =============================================================================
-- P15: verificação do modelo dimensional após o ETL (evidências da Etapa 3)
-- Executar no SQL Shell (psql):  \i sql/03_verificacao_dw.sql
-- =============================================================================
\c bioeconomia
\encoding UTF8
\pset pager off

\echo '1. Registros por tabela do dw'
SELECT 'dim_municipio' AS tabela, count(*) AS registros FROM dw.dim_municipio
UNION ALL SELECT 'dim_produto',             count(*) FROM dw.dim_produto
UNION ALL SELECT 'dim_tempo',               count(*) FROM dw.dim_tempo
UNION ALL SELECT 'fato_producao_extrativa', count(*) FROM dw.fato_producao_extrativa
UNION ALL SELECT 'fato_vendas',             count(*) FROM dw.fato_vendas;

\echo '2. Relatório de qualidade da última execução do ETL'
SELECT tabela, registros, regra
FROM dw.log_qualidade_etl
WHERE executado_em = (SELECT max(executado_em) FROM dw.log_qualidade_etl)
ORDER BY id_log;

\echo '3. Vendas por ano e produto (consulta no modelo estrela)'
SELECT t.ano,
       p.nome                                  AS produto,
       round(sum(v.quantidade))                AS quantidade,
       p.unidade_venda                         AS unidade,
       round(sum(v.receita) / 1000000, 2)      AS receita_milhoes_reais
FROM dw.fato_vendas v
JOIN dw.dim_tempo   t USING (id_tempo)
JOIN dw.dim_produto p USING (id_produto)
GROUP BY t.ano, p.nome, p.unidade_venda
ORDER BY t.ano, p.nome;

\echo '4. Sazonalidade: quantidade média vendida por mês e produto'
SELECT t.mes,
       t.nome_mes,
       round(avg(v.quantidade) FILTER (WHERE p.chave = 'acai'))             AS acai_kg,
       round(avg(v.quantidade) FILTER (WHERE p.chave = 'castanha_do_para')) AS castanha_kg,
       round(avg(v.quantidade) FILTER (WHERE p.chave = 'copaiba'), 1)       AS copaiba_l
FROM dw.fato_vendas v
JOIN dw.dim_tempo   t USING (id_tempo)
JOIN dw.dim_produto p USING (id_produto)
GROUP BY t.mes, t.nome_mes
ORDER BY t.mes;

\echo '5. Maiores produtores de açaí (PEVS 2023) e suas vendas em 2024'
SELECT m.municipio,
       m.uf,
       f.quantidade_produzida   AS producao_2023_t,
       round(sum(v.quantidade)) AS vendas_2024_kg
FROM dw.fato_producao_extrativa f
JOIN dw.dim_municipio m USING (cod_ibge)
JOIN dw.dim_produto   p USING (id_produto)
LEFT JOIN dw.fato_vendas v
       ON v.cod_ibge = f.cod_ibge
      AND v.id_produto = f.id_produto
      AND v.id_tempo BETWEEN 202401 AND 202412
WHERE p.chave = 'acai'
  AND f.ano = 2023
  AND f.quantidade_produzida IS NOT NULL
GROUP BY m.municipio, m.uf, f.quantidade_produzida
ORDER BY f.quantidade_produzida DESC
LIMIT 10;
