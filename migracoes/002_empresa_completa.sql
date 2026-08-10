ALTER TABLE empresas ADD COLUMN IF NOT EXISTS matriz_filial TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS situacao_cadastral TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS situacao_data DATE;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS situacao_motivo TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS situacao_especial TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS abertura DATE;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS natureza_juridica TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS natureza_juridica_cod TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS porte TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS capital_social NUMERIC(18,2);
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS cnae_principal TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS cnae_principal_desc TEXT;

ALTER TABLE empresas ADD COLUMN IF NOT EXISTS logradouro TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS numero TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS complemento TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS bairro TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS cep VARCHAR(8);

ALTER TABLE empresas ADD COLUMN IF NOT EXISTS telefone1 TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS telefone2 TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS email TEXT;

ALTER TABLE empresas ADD COLUMN IF NOT EXISTS simples_optante BOOLEAN;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS simples_desde DATE;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS simples_ate DATE;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS mei_optante BOOLEAN;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS mei_desde DATE;

ALTER TABLE empresas ADD COLUMN IF NOT EXISTS receita_bruto JSONB;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS receita_fonte TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS receita_consultado_em TIMESTAMPTZ;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS observacoes TEXT;
ALTER TABLE empresas ADD COLUMN IF NOT EXISTS atualizado_em TIMESTAMPTZ DEFAULT NOW();

CREATE TABLE IF NOT EXISTS empresa_cnaes (
  id SERIAL PRIMARY KEY,
  empresa_id INT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  codigo TEXT NOT NULL,
  descricao TEXT,
  principal BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_cnae_emp ON empresa_cnaes(empresa_id);

CREATE TABLE IF NOT EXISTS empresa_socios (
  id SERIAL PRIMARY KEY,
  empresa_id INT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  nome TEXT NOT NULL,
  documento TEXT,
  qualificacao TEXT,
  faixa_etaria TEXT,
  entrada DATE,
  pais TEXT,
  representante_nome TEXT,
  representante_doc TEXT,
  representante_qualif TEXT
);
CREATE INDEX IF NOT EXISTS idx_socio_emp ON empresa_socios(empresa_id);

CREATE TABLE IF NOT EXISTS empresa_inscricoes (
  id SERIAL PRIMARY KEY,
  empresa_id INT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL,
  numero TEXT NOT NULL,
  uf VARCHAR(2),
  municipio_ibge VARCHAR(7),
  ativa BOOLEAN DEFAULT TRUE,
  CONSTRAINT chk_tipo_insc CHECK (tipo IN ('ie','im','iest','suframa'))
);
CREATE INDEX IF NOT EXISTS idx_insc_emp ON empresa_inscricoes(empresa_id);
