CREATE TABLE IF NOT EXISTS importacoes (
  id BIGSERIAL PRIMARY KEY,
  contabilidade_id INT REFERENCES contabilidades(id) ON DELETE CASCADE,
  usuario_id INT REFERENCES usuarios(id),
  arquivo_nome TEXT,
  arquivo_tamanho BIGINT,
  total INT DEFAULT 0,
  gravados INT DEFAULT 0,
  duplicados INT DEFAULT 0,
  ignorados INT DEFAULT 0,
  erros INT DEFAULT 0,
  anexos INT DEFAULT 0,
  detalhe JSONB,
  duracao_ms INT,
  criado_em TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_imp ON importacoes(contabilidade_id, criado_em DESC);

ALTER TABLE documentos ADD COLUMN IF NOT EXISTS importacao_id BIGINT
  REFERENCES importacoes(id) ON DELETE SET NULL;
ALTER TABLE documentos ADD COLUMN IF NOT EXISTS pdf_path TEXT;
ALTER TABLE documentos ADD COLUMN IF NOT EXISTS papel TEXT;
CREATE INDEX IF NOT EXISTS idx_doc_papel ON documentos(empresa_id, papel);
