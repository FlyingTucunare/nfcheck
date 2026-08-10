-- padrao do escritorio
ALTER TABLE contabilidades ADD COLUMN IF NOT EXISTS janela_ativa BOOLEAN DEFAULT FALSE;
ALTER TABLE contabilidades ADD COLUMN IF NOT EXISTS janela_inicio TIME;
ALTER TABLE contabilidades ADD COLUMN IF NOT EXISTS janela_fim TIME;
ALTER TABLE contabilidades ADD COLUMN IF NOT EXISTS ciencia_auto BOOLEAN DEFAULT FALSE;

-- sobreposicao por empresa: NULL = herda do escritorio
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS janela_ativa BOOLEAN;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS janela_inicio TIME;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS janela_fim TIME;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS ciencia_auto BOOLEAN;

-- a janela sai do cursor: agora e por empresa
ALTER TABLE cursores_dfe DROP COLUMN IF EXISTS janela_ativa;
ALTER TABLE cursores_dfe DROP COLUMN IF EXISTS janela_inicio;
ALTER TABLE cursores_dfe DROP COLUMN IF EXISTS janela_fim;

-- resolve a configuracao efetiva (empresa sobrepoe escritorio)
CREATE OR REPLACE VIEW config_efetiva AS
SELECT e.id AS empresa_id, e.contabilidade_id,
       COALESCE(e.janela_ativa,  c.janela_ativa,  FALSE) AS janela_ativa,
       COALESCE(e.janela_inicio, c.janela_inicio)        AS janela_inicio,
       COALESCE(e.janela_fim,    c.janela_fim)           AS janela_fim,
       COALESCE(e.ciencia_auto,  c.ciencia_auto,  FALSE) AS ciencia_auto,
       (e.janela_ativa IS NULL AND e.janela_inicio IS NULL
        AND e.janela_fim IS NULL) AS janela_herdada,
       (e.ciencia_auto IS NULL)                          AS ciencia_herdada
  FROM empresas e
  JOIN contabilidades c ON c.id = e.contabilidade_id;

-- registro de cada ciencia dada
CREATE TABLE IF NOT EXISTS manifestacoes (
  id BIGSERIAL PRIMARY KEY,
  empresa_id INT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  documento_id BIGINT REFERENCES documentos(id) ON DELETE SET NULL,
  chave VARCHAR(44) NOT NULL,
  evento TEXT NOT NULL,
  automatica BOOLEAN DEFAULT FALSE,
  usuario_id INT REFERENCES usuarios(id),
  cstat TEXT,
  motivo TEXT,
  protocolo TEXT,
  criado_em TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_manif_emp ON manifestacoes(empresa_id, criado_em DESC);
CREATE INDEX IF NOT EXISTS idx_manif_chave ON manifestacoes(chave);
