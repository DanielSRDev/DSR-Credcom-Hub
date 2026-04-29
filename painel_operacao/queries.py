SQL_PAINEL_OPERACAO = """
;WITH tipo_negociacao_campo AS (
    SELECT cca_id
    FROM dbo.tb_credor_campo
    WHERE cca_nivel = 4
      AND cca_nome = 'Tipo de Negociação'
),
evento_acordo AS (
    SELECT
        ce.evc_id,
        ce.evc_data,
        ce.cli_id,
        ce.ope_id,
        op.ope_login,
        ROW_NUMBER() OVER (
            PARTITION BY ce.evc_id
            ORDER BY ce.evc_data DESC
        ) AS rn
    FROM dbo.tb_cliente_evento ce
    INNER JOIN dbo.tb_evento e
        ON e.eve_id = ce.eve_id
    LEFT JOIN dbo.tb_operador op
        ON op.ope_id = ce.ope_id
    WHERE e.eve_nome = 'Acordo'
      AND ce.evc_data >= %s
      AND ce.evc_data < DATEADD(DAY, 1, %s)
),
base_acordo AS (
    SELECT DISTINCT
        a.aco_id,
        a.aco_numero,
        a.aco_data,
        a.aco_principal,
        a.aco_multa,
        a.aco_juros,
        a.aco_ho,
        a.aco_sub_total,
        a.aco_total,
        a.aco_entrada,
        a.aco_despesas,
        a.aco_desc_princ,
        a.aco_desc_multa,
        a.aco_desc_juros,
        a.aco_desc_ho,
        a.aco_desc_total,
        a.aco_num_parc,
        a.aco_status,
        a.aco_tipo,
        a.aco_etl_alteracao,

        COALESCE(pss.pes_nome, pss_nv.pes_nome) AS pes_nome,
        COALESCE(pss.pes_cpfcnpj, pss_nv.pes_cpfcnpj) AS pes_cpfcnpj,

        COALESCE(c.con_numero, c_nv.con_numero) AS con_numero,
        COALESCE(c.cre_id, c_nv.cre_id) AS cre_id,
        COALESCE(c.fil_id, c_nv.fil_id) AS fil_id,
        COALESCE(c.pro_id, c_nv.pro_id) AS pro_id
    FROM dbo.tb_acordo a

    LEFT JOIN dbo.tb_acordo_parcela ap
        ON ap.aco_id = a.aco_id
    LEFT JOIN dbo.tb_parcela p
        ON p.par_id = ap.par_id
    LEFT JOIN dbo.tb_negociacao n
        ON n.neg_id = p.neg_id
    LEFT JOIN dbo.tb_contrato c
        ON c.con_id = n.con_id
    LEFT JOIN dbo.tb_cliente cl
        ON cl.cli_id = c.cli_id
    LEFT JOIN dbo.tb_pessoa pss
        ON pss.pes_id = cl.cli_id

    LEFT JOIN dbo.tb_negociacao_vinculo nv
        ON nv.aco_id = a.aco_id
    LEFT JOIN dbo.tb_negociacao n_nv
        ON n_nv.neg_id = nv.neg_id
    LEFT JOIN dbo.tb_contrato c_nv
        ON c_nv.con_id = n_nv.con_id
    LEFT JOIN dbo.tb_cliente cl_nv
        ON cl_nv.cli_id = c_nv.cli_id
    LEFT JOIN dbo.tb_pessoa pss_nv
        ON pss_nv.pes_id = cl_nv.cli_id
)
SELECT
    b.aco_numero AS numero_acordo,
    b.aco_id AS aco_id,
    b.aco_data AS data_acordo,
    ev.evc_data AS data_emissao,
    b.aco_etl_alteracao AS data_etl_alteracao,
    b.pes_nome AS cliente,
    b.pes_cpfcnpj AS cpf_cnpj,
    b.con_numero AS contrato,
    cr.cre_id AS cre_id,
    cr.cre_sigla AS credor,
    CONCAT(
        COALESCE(cf.fil_codigo, ''),
        CASE
            WHEN cf.fil_codigo IS NOT NULL AND cf.fil_nome IS NOT NULL THEN ' - '
            ELSE ''
        END,
        COALESCE(cf.fil_nome, '')
    ) AS filial,
    pr.pro_nome AS tipo_contrato,
    STRING_AGG(ac_tipo.cca_valor, ' | ') AS tipo_negociacao,
    b.aco_principal AS principal_bruto,
    ISNULL(b.aco_desc_princ, 0) AS desconto_principal,
    b.aco_principal - ISNULL(b.aco_desc_princ, 0) AS principal_liquido,
    b.aco_multa AS multa_bruta,
    ISNULL(b.aco_desc_multa, 0) AS desconto_multa,
    b.aco_multa - ISNULL(b.aco_desc_multa, 0) AS multa_liquida,
    b.aco_juros AS juros_bruto,
    ISNULL(b.aco_desc_juros, 0) AS desconto_juros,
    b.aco_juros - ISNULL(b.aco_desc_juros, 0) AS juros_liquido,
    b.aco_ho AS honorario_bruto,
    ISNULL(b.aco_desc_ho, 0) AS desconto_honorario,
    b.aco_ho - ISNULL(b.aco_desc_ho, 0) AS honorario_liquido,
    ISNULL(b.aco_despesas, 0) AS despesas,
    b.aco_sub_total AS subtotal_bruto,
    ISNULL(b.aco_desc_total, 0) AS desconto_total,
    b.aco_total AS valor_total_liquido,
    b.aco_entrada AS valor_entrada,
    b.aco_num_parc AS qtd_parcelas_acordo,
    ast.aco_status_descricao AS status_acordo,
    b.aco_tipo AS tipo_acordo,
    ev.ope_login AS emitido_por
FROM evento_acordo ev
INNER JOIN base_acordo b
    ON b.aco_id = ev.evc_id
   AND ev.rn = 1
LEFT JOIN dbo.tb_credor cr
    ON cr.cre_id = b.cre_id
LEFT JOIN dbo.tb_credor_filial cf
    ON cf.fil_id = b.fil_id
LEFT JOIN dbo.tb_produto pr
    ON pr.pro_id = b.pro_id
LEFT JOIN dbo.tb_acordo_status ast
    ON ast.aco_status = b.aco_status
LEFT JOIN tipo_negociacao_campo tnc
    ON 1 = 1
LEFT JOIN dbo.tb_acordo_campo ac_tipo
    ON ac_tipo.aco_id = b.aco_id
   AND ac_tipo.cca_id = tnc.cca_id
   AND ac_tipo.cca_valor IS NOT NULL
WHERE (
    b.aco_data IS NULL
    OR b.aco_data < DATEADD(DAY, 1, %s)
)
GROUP BY
    b.aco_numero,
    b.aco_id,
    b.aco_data,
    ev.evc_data,
    b.aco_etl_alteracao,
    b.pes_nome,
    b.pes_cpfcnpj,
    b.con_numero,
    cr.cre_id,
    cr.cre_sigla,
    cf.fil_codigo,
    cf.fil_nome,
    pr.pro_nome,
    b.aco_principal,
    b.aco_desc_princ,
    b.aco_multa,
    b.aco_desc_multa,
    b.aco_juros,
    b.aco_desc_juros,
    b.aco_ho,
    b.aco_desc_ho,
    b.aco_despesas,
    b.aco_sub_total,
    b.aco_desc_total,
    b.aco_total,
    b.aco_entrada,
    b.aco_num_parc,
    ast.aco_status_descricao,
    b.aco_tipo,
    ev.ope_login
ORDER BY ev.evc_data DESC
"""

SQL_PAGAMENTOS_ACORDO = """
SELECT
    p.pgo_id,
    p.pgo_data,
    p.pgo_valor,
    p.aco_id,
    p.pct_id,
    p.fpg_id,
    p.pgo_parcial,
    p.pgo_etl_alteracao
FROM dbo.tb_pagamento p
WHERE p.pgo_data >= %s
  AND p.pgo_data < DATEADD(DAY, 1, %s)
  AND p.aco_id IS NOT NULL
ORDER BY p.pgo_data DESC, p.pgo_id DESC
"""

SQL_RELATORIO_GERAL_HUB_BASE = """
;WITH tipo_negociacao_campo AS (
    SELECT cca_id
    FROM dbo.tb_credor_campo
    WHERE cca_nivel = 4
      AND cca_nome = 'Tipo de Negociação'
),
evento_acordo AS (
    SELECT
        ce.evc_id,
        ce.evc_data,
        ce.cli_id,
        ce.ope_id,
        op.ope_login,
        ROW_NUMBER() OVER (
            PARTITION BY ce.evc_id
            ORDER BY ce.evc_data DESC
        ) AS rn
    FROM dbo.tb_cliente_evento ce
    INNER JOIN dbo.tb_evento e
        ON e.eve_id = ce.eve_id
    LEFT JOIN dbo.tb_operador op
        ON op.ope_id = ce.ope_id
    WHERE e.eve_nome = 'Acordo'
),
base_acordo AS (
    SELECT DISTINCT
        a.aco_id,
        a.aco_numero,
        a.aco_data,
        a.aco_ho,
        ISNULL(a.aco_desc_ho, 0) AS desconto_honorario,
        a.aco_num_parc,
        a.aco_status,
        a.aco_tipo,
        a.aco_etl_alteracao,

        COALESCE(pss.pes_nome, pss_nv.pes_nome) AS pes_nome,
        COALESCE(pss.pes_cpfcnpj, pss_nv.pes_cpfcnpj) AS pes_cpfcnpj,

        COALESCE(c.con_numero, c_nv.con_numero) AS con_numero,
        COALESCE(c.cre_id, c_nv.cre_id) AS cre_id,
        COALESCE(c.fil_id, c_nv.fil_id) AS fil_id,
        COALESCE(c.pro_id, c_nv.pro_id) AS pro_id
    FROM dbo.tb_acordo a

    LEFT JOIN dbo.tb_acordo_parcela ap
        ON ap.aco_id = a.aco_id
    LEFT JOIN dbo.tb_parcela p
        ON p.par_id = ap.par_id
    LEFT JOIN dbo.tb_negociacao n
        ON n.neg_id = p.neg_id
    LEFT JOIN dbo.tb_contrato c
        ON c.con_id = n.con_id
    LEFT JOIN dbo.tb_cliente cl
        ON cl.cli_id = c.cli_id
    LEFT JOIN dbo.tb_pessoa pss
        ON pss.pes_id = cl.cli_id

    LEFT JOIN dbo.tb_negociacao_vinculo nv
        ON nv.aco_id = a.aco_id
    LEFT JOIN dbo.tb_negociacao n_nv
        ON n_nv.neg_id = nv.neg_id
    LEFT JOIN dbo.tb_contrato c_nv
        ON c_nv.con_id = n_nv.con_id
    LEFT JOIN dbo.tb_cliente cl_nv
        ON cl_nv.cli_id = c_nv.cli_id
    LEFT JOIN dbo.tb_pessoa pss_nv
        ON pss_nv.pes_id = cl_nv.cli_id
)
SELECT
    'HUB' AS origem_registro,
    b.aco_numero AS numero_acordo,
    b.aco_id AS aco_id,
    b.aco_data AS data_acordo,
    ev.evc_data AS data_emissao,
    CAST(NULL AS DATETIME) AS data_pagamento,
    b.aco_etl_alteracao AS data_etl_alteracao,
    b.pes_nome AS cliente,
    b.pes_cpfcnpj AS cpf_cnpj,
    b.con_numero AS contrato,
    cr.cre_id AS cre_id,
    cr.cre_sigla AS credor,
    CONCAT(
        COALESCE(cf.fil_codigo, ''),
        CASE
            WHEN cf.fil_codigo IS NOT NULL AND cf.fil_nome IS NOT NULL THEN ' - '
            ELSE ''
        END,
        COALESCE(cf.fil_nome, '')
    ) AS filial,
    pr.pro_nome AS tipo_contrato,
    STRING_AGG(ac_tipo.cca_valor, ' | ') AS tipo_negociacao,
    b.aco_ho AS honorario_bruto,
    b.desconto_honorario AS desconto_honorario,
    b.aco_ho - b.desconto_honorario AS honorario_liquido,
    b.aco_num_parc AS qtd_parcelas_acordo,
    ast.aco_status_descricao AS status_acordo,
    b.aco_tipo AS tipo_acordo,
    ev.ope_login AS emitido_por_login,
    ev.ope_login AS emitido_por_nome,
    CAST(0 AS DECIMAL(14,2)) AS valor_pago_periodo
FROM evento_acordo ev
INNER JOIN base_acordo b
    ON b.aco_id = ev.evc_id
   AND ev.rn = 1
LEFT JOIN dbo.tb_credor cr
    ON cr.cre_id = b.cre_id
LEFT JOIN dbo.tb_credor_filial cf
    ON cf.fil_id = b.fil_id
LEFT JOIN dbo.tb_produto pr
    ON pr.pro_id = b.pro_id
LEFT JOIN dbo.tb_acordo_status ast
    ON ast.aco_status = b.aco_status
LEFT JOIN tipo_negociacao_campo tnc
    ON 1 = 1
LEFT JOIN dbo.tb_acordo_campo ac_tipo
    ON ac_tipo.aco_id = b.aco_id
   AND ac_tipo.cca_id = tnc.cca_id
   AND ac_tipo.cca_valor IS NOT NULL
WHERE ev.evc_data >= %s
  AND ev.evc_data < DATEADD(DAY, 1, %s)
GROUP BY
    b.aco_numero,
    b.aco_id,
    b.aco_data,
    ev.evc_data,
    b.aco_etl_alteracao,
    b.pes_nome,
    b.pes_cpfcnpj,
    b.con_numero,
    cr.cre_id,
    cr.cre_sigla,
    cf.fil_codigo,
    cf.fil_nome,
    pr.pro_nome,
    b.aco_ho,
    b.desconto_honorario,
    b.aco_num_parc,
    ast.aco_status_descricao,
    b.aco_tipo,
    ev.ope_login
ORDER BY ev.evc_data DESC
"""

SQL_RELATORIO_GERAL_PAGOS_EXTRA = """
;WITH periodo AS (
    SELECT
        CAST(%s AS DATE) AS data_ini,
        CAST(%s AS DATE) AS data_fim
),
pagamentos_periodo AS (
    SELECT
        p.pgo_id,
        p.aco_id,
        p.pgo_data AS data_pagamento,
        ROW_NUMBER() OVER (
            PARTITION BY p.aco_id
            ORDER BY p.pgo_data DESC, p.pgo_id DESC
        ) AS rn
    FROM dbo.tb_pagamento p
    CROSS JOIN periodo per
    WHERE p.pgo_data >= per.data_ini
      AND p.pgo_data < DATEADD(DAY, 1, per.data_fim)
      AND p.aco_id IS NOT NULL
),
evento_acordo AS (
    SELECT
        ce.evc_id,
        ce.evc_data,
        ce.ope_id,
        op.ope_login,
        ROW_NUMBER() OVER (
            PARTITION BY ce.evc_id
            ORDER BY ce.evc_data DESC
        ) AS rn
    FROM dbo.tb_cliente_evento ce
    INNER JOIN dbo.tb_evento e
        ON e.eve_id = ce.eve_id
    LEFT JOIN dbo.tb_operador op
        ON op.ope_id = ce.ope_id
    WHERE e.eve_nome = 'Acordo'
),
base_acordo AS (
    SELECT DISTINCT
        a.aco_id,
        a.aco_numero,
        a.aco_data,
        a.aco_ho,
        ISNULL(a.aco_desc_ho, 0) AS desconto_honorario,
        a.aco_num_parc,
        a.aco_status,
        a.aco_tipo,
        a.aco_etl_alteracao,

        COALESCE(pss.pes_nome, pss_nv.pes_nome) AS pes_nome,
        COALESCE(pss.pes_cpfcnpj, pss_nv.pes_cpfcnpj) AS pes_cpfcnpj,

        COALESCE(c.con_numero, c_nv.con_numero) AS con_numero,
        COALESCE(c.cre_id, c_nv.cre_id) AS cre_id,
        COALESCE(c.fil_id, c_nv.fil_id) AS fil_id,
        COALESCE(c.pro_id, c_nv.pro_id) AS pro_id
    FROM dbo.tb_acordo a

    LEFT JOIN dbo.tb_acordo_parcela ap
        ON ap.aco_id = a.aco_id
    LEFT JOIN dbo.tb_parcela p
        ON p.par_id = ap.par_id
    LEFT JOIN dbo.tb_negociacao n
        ON n.neg_id = p.neg_id
    LEFT JOIN dbo.tb_contrato c
        ON c.con_id = n.con_id
    LEFT JOIN dbo.tb_cliente cl
        ON cl.cli_id = c.cli_id
    LEFT JOIN dbo.tb_pessoa pss
        ON pss.pes_id = cl.cli_id

    LEFT JOIN dbo.tb_negociacao_vinculo nv
        ON nv.aco_id = a.aco_id
    LEFT JOIN dbo.tb_negociacao n_nv
        ON n_nv.neg_id = nv.neg_id
    LEFT JOIN dbo.tb_contrato c_nv
        ON c_nv.con_id = n_nv.con_id
    LEFT JOIN dbo.tb_cliente cl_nv
        ON cl_nv.cli_id = c_nv.cli_id
    LEFT JOIN dbo.tb_pessoa pss_nv
        ON pss_nv.pes_id = cl_nv.cli_id
)
SELECT
    'PAGAMENTO_EXTRA' AS origem_registro,

    b.aco_numero AS numero_acordo,
    b.aco_id AS aco_id,
    b.aco_data AS data_acordo,

    ev.evc_data AS data_emissao,
    pg.data_pagamento AS data_pagamento,

    b.aco_etl_alteracao AS data_etl_alteracao,
    b.pes_nome AS cliente,
    b.pes_cpfcnpj AS cpf_cnpj,
    b.con_numero AS contrato,

    cr.cre_id AS cre_id,
    cr.cre_sigla AS credor,

    CONCAT(
        COALESCE(cf.fil_codigo, ''),
        CASE
            WHEN cf.fil_codigo IS NOT NULL AND cf.fil_nome IS NOT NULL THEN ' - '
            ELSE ''
        END,
        COALESCE(cf.fil_nome, '')
    ) AS filial,

    pr.pro_nome AS tipo_contrato,
    CAST(NULL AS VARCHAR(255)) AS tipo_negociacao,

    b.aco_ho AS honorario_bruto,
    b.desconto_honorario AS desconto_honorario,
    b.aco_ho - b.desconto_honorario AS honorario_liquido,

    b.aco_num_parc AS qtd_parcelas_acordo,
    ast.aco_status_descricao AS status_acordo,
    b.aco_tipo AS tipo_acordo,

    ev.ope_login AS emitido_por_login,
    ev.ope_login AS emitido_por_nome,

    CAST(1 AS DECIMAL(14,2)) AS valor_pago_periodo

FROM pagamentos_periodo pg
INNER JOIN base_acordo b
    ON b.aco_id = pg.aco_id
CROSS JOIN periodo per

LEFT JOIN evento_acordo ev
    ON ev.evc_id = b.aco_id
   AND ev.rn = 1

LEFT JOIN dbo.tb_credor cr
    ON cr.cre_id = b.cre_id
LEFT JOIN dbo.tb_credor_filial cf
    ON cf.fil_id = b.fil_id
LEFT JOIN dbo.tb_produto pr
    ON pr.pro_id = b.pro_id
LEFT JOIN dbo.tb_acordo_status ast
    ON ast.aco_status = b.aco_status

WHERE pg.rn = 1
  AND (
      ev.evc_data IS NULL
      OR NOT (
          ev.evc_data >= per.data_ini
          AND ev.evc_data < DATEADD(DAY, 1, per.data_fim)
      )
  )

ORDER BY
    pg.data_pagamento DESC,
    b.aco_numero DESC
"""
