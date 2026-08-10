ALTER TABLE cursores_dfe DROP CONSTRAINT IF EXISTS chk_origem;
ALTER TABLE cursores_dfe ADD CONSTRAINT chk_origem
  CHECK (origem IN ('sefaz_nfe','sefaz_cte','adn'));

UPDATE cursores_dfe SET origem='sefaz_nfe' WHERE origem='sefaz';

INSERT INTO cursores_dfe (empresa_id, origem)
SELECT e.id, o.origem FROM empresas e
CROSS JOIN (VALUES ('sefaz_nfe'),('sefaz_cte'),('adn')) AS o(origem)
ON CONFLICT (empresa_id, origem) DO NOTHING;

ALTER TABLE cursores_dfe ADD COLUMN IF NOT EXISTS caught_up BOOLEAN DEFAULT FALSE;
ALTER TABLE cursores_dfe ADD COLUMN IF NOT EXISTS ultimo_cstat TEXT;
ALTER TABLE cursores_dfe ADD COLUMN IF NOT EXISTS ultima_vazia TIMESTAMPTZ;
ALTER TABLE cursores_dfe ADD COLUMN IF NOT EXISTS ultima_com_resultado TIMESTAMPTZ;
ALTER TABLE cursores_dfe ADD COLUMN IF NOT EXISTS janela_ativa BOOLEAN DEFAULT FALSE;
ALTER TABLE cursores_dfe ADD COLUMN IF NOT EXISTS janela_inicio TIME;
ALTER TABLE cursores_dfe ADD COLUMN IF NOT EXISTS janela_fim TIME;
ALTER TABLE cursores_dfe ADD COLUMN IF NOT EXISTS pausado BOOLEAN DEFAULT FALSE;
ALTER TABLE cursores_dfe ADD COLUMN IF NOT EXISTS pausado_motivo TEXT;

CREATE TABLE IF NOT EXISTS documentos (
  id BIGSERIAL PRIMARY KEY,
  empresa_id INT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  chave VARCHAR(44),
  nsu BIGINT,
  origem TEXT NOT NULL,
  tipo TEXT NOT NULL,
  schema_xml TEXT,
  emitente_cnpj VARCHAR(14),
  emitente_nome TEXT,
  destinatario_cnpj VARCHAR(14),
  numero TEXT,
  serie TEXT,
  emissao TIMESTAMPTZ,
  valor NUMERIC(18,2),
  situacao TEXT,
  manifestacao TEXT,
  manifestacao_em TIMESTAMPTZ,
  resumo BOOLEAN DEFAULT FALSE,
  xml_path TEXT,
  recebido_em TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT uq_doc UNIQUE (empresa_id, chave, tipo)
);
CREATE INDEX IF NOT EXISTS idx_doc_emp ON documentos(empresa_id, emissao DESC);
CREATE INDEX IF NOT EXISTS idx_doc_nsu ON documentos(empresa_id, origem, nsu);
CREATE INDEX IF NOT EXISTS idx_doc_chave ON documentos(chave);
CREATE INDEX IF NOT EXISTS idx_doc_manif ON documentos(empresa_id, manifestacao)
  WHERE manifestacao IS NULL;

CREATE TABLE IF NOT EXISTS sync_log (
  id BIGSERIAL PRIMARY KEY,
  empresa_id INT REFERENCES empresas(id) ON DELETE CASCADE,
  origem TEXT,
  cstat TEXT,
  motivo TEXT,
  nsu_inicial BIGINT,
  nsu_final BIGINT,
  novos INT DEFAULT 0,
  duracao_ms INT,
  criado_em TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_synclog ON sync_log(empresa_id, criado_em DESC);
