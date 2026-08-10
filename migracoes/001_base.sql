CREATE TABLE IF NOT EXISTS contabilidades (
  id SERIAL PRIMARY KEY,
  razao_social TEXT NOT NULL,
  nome_fantasia TEXT,
  cnpj VARCHAR(14) UNIQUE NOT NULL,
  email TEXT NOT NULL,
  telefone TEXT,
  plano TEXT DEFAULT 'basico',
  status TEXT NOT NULL DEFAULT 'pendente',
  limite_empresas INT DEFAULT 10,
  criado_em TIMESTAMPTZ DEFAULT NOW(),
  aprovado_em TIMESTAMPTZ,
  aprovado_por INT
);

CREATE TABLE IF NOT EXISTS usuarios (
  id SERIAL PRIMARY KEY,
  contabilidade_id INT REFERENCES contabilidades(id) ON DELETE CASCADE,
  nome TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  senha_hash TEXT NOT NULL,
  perfil TEXT NOT NULL,
  ativo BOOLEAN DEFAULT TRUE,
  totp_secret TEXT,
  totp_ativo BOOLEAN DEFAULT FALSE,
  ultimo_login TIMESTAMPTZ,
  criado_em TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT chk_perfil CHECK (perfil IN
    ('superadmin','contabilidade_admin','contabilidade_operador','cliente_final'))
);

CREATE TABLE IF NOT EXISTS empresas (
  id SERIAL PRIMARY KEY,
  contabilidade_id INT NOT NULL REFERENCES contabilidades(id),
  razao_social TEXT NOT NULL,
  nome_fantasia TEXT,
  cnpj VARCHAR(14) UNIQUE NOT NULL,
  cnpj_raiz VARCHAR(8) NOT NULL,
  ie TEXT, im TEXT,
  municipio_ibge VARCHAR(7),
  municipio_nome TEXT,
  uf VARCHAR(2),
  regime_tributario TEXT,
  status TEXT DEFAULT 'ativa',
  criado_em TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_emp_cont ON empresas(contabilidade_id);
CREATE INDEX IF NOT EXISTS idx_emp_raiz ON empresas(cnpj_raiz);

CREATE TABLE IF NOT EXISTS empresa_transferencias (
  id SERIAL PRIMARY KEY,
  empresa_id INT NOT NULL REFERENCES empresas(id),
  contabilidade_origem_id INT REFERENCES contabilidades(id),
  contabilidade_destino_id INT REFERENCES contabilidades(id),
  motivo TEXT,
  aprovado_por INT REFERENCES usuarios(id),
  criado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS certificados (
  id SERIAL PRIMARY KEY,
  empresa_id INT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  arquivo_path TEXT NOT NULL,
  senha_enc TEXT NOT NULL,
  titular_cn TEXT,
  cnpj_titular VARCHAR(14),
  valido_de TIMESTAMPTZ,
  valido_ate TIMESTAMPTZ,
  ativo BOOLEAN DEFAULT TRUE,
  enviado_por INT REFERENCES usuarios(id),
  enviado_em TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cert_um_ativo
  ON certificados(empresa_id) WHERE ativo;
CREATE INDEX IF NOT EXISTS idx_cert_venc ON certificados(valido_ate) WHERE ativo;

CREATE TABLE IF NOT EXISTS usuario_empresas (
  usuario_id INT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  empresa_id INT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  PRIMARY KEY (usuario_id, empresa_id)
);

CREATE TABLE IF NOT EXISTS cursores_dfe (
  id SERIAL PRIMARY KEY,
  empresa_id INT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  origem TEXT NOT NULL,
  ultimo_nsu BIGINT DEFAULT 0,
  max_nsu BIGINT,
  ultima_sync TIMESTAMPTZ,
  proxima_sync TIMESTAMPTZ DEFAULT NOW(),
  status TEXT DEFAULT 'ok',
  erro_msg TEXT,
  CONSTRAINT chk_origem CHECK (origem IN ('sefaz','adn')),
  CONSTRAINT uq_cursor UNIQUE (empresa_id, origem)
);

CREATE TABLE IF NOT EXISTS fila_sincronizacao (
  id SERIAL PRIMARY KEY,
  empresa_id INT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  origem TEXT NOT NULL,
  prioridade INT DEFAULT 5,
  tentativas INT DEFAULT 0,
  agendado_para TIMESTAMPTZ DEFAULT NOW(),
  iniciado_em TIMESTAMPTZ,
  status TEXT DEFAULT 'pendente',
  erro_msg TEXT
);
CREATE INDEX IF NOT EXISTS idx_fila_prox
  ON fila_sincronizacao(status, agendado_para, prioridade);

CREATE TABLE IF NOT EXISTS auditoria (
  id BIGSERIAL PRIMARY KEY,
  usuario_id INT REFERENCES usuarios(id),
  contabilidade_id INT,
  empresa_id INT,
  acao TEXT NOT NULL,
  detalhe JSONB,
  ip TEXT,
  criado_em TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_aud_data ON auditoria(criado_em DESC);
