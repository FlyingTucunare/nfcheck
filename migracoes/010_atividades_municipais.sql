CREATE TABLE IF NOT EXISTS atividades_municipais (
    id                 bigserial PRIMARY KEY,
    municipio_ibge     text NOT NULL,
    codigo             text NOT NULL,
    codigo_servico     text,
    item_lista_servico text,
    descricao          text,
    aliquota           numeric(6,3),
    vigencia_inicio    date,
    vigencia_fim       date,
    tipo_codigo        text,
    atualizado_em      timestamptz DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_atividade_mun
  ON atividades_municipais (municipio_ibge, codigo, COALESCE(vigencia_inicio,'1900-01-01'));
CREATE INDEX IF NOT EXISTS idx_ativ_mun      ON atividades_municipais(municipio_ibge);
CREATE INDEX IF NOT EXISTS idx_ativ_item     ON atividades_municipais(municipio_ibge, item_lista_servico);
CREATE INDEX IF NOT EXISTS idx_ativ_cnae     ON atividades_municipais(municipio_ibge, left(codigo,7));

ALTER TABLE municipios ADD COLUMN IF NOT EXISTS atividades_atualizado_em timestamptz;
