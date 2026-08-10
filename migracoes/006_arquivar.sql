ALTER TABLE empresas ADD COLUMN IF NOT EXISTS arquivada_em TIMESTAMPTZ;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS arquivada_por INT REFERENCES usuarios(id);
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS arquivada_motivo TEXT;
CREATE INDEX IF NOT EXISTS idx_emp_ativa ON empresas(contabilidade_id)
  WHERE arquivada_em IS NULL;
