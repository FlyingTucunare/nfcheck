-- configuracao de emissao por empresa
CREATE TABLE IF NOT EXISTS nfse_config (
  empresa_id INT PRIMARY KEY REFERENCES empresas(id) ON DELETE CASCADE,
  ambiente TEXT NOT NULL DEFAULT '2',
  serie_dps VARCHAR(5) NOT NULL DEFAULT '00001',
  proximo_numero BIGINT NOT NULL DEFAULT 1,
  regime_especial TEXT,
  optante_simples BOOLEAN DEFAULT FALSE,
  incentivo_fiscal BOOLEAN DEFAULT FALSE,
  aliquota_iss NUMERIC(6,4),
  iss_retido_padrao BOOLEAN DEFAULT FALSE,
  email_remetente TEXT,
  enviar_email_auto BOOLEAN DEFAULT FALSE,
  copia_email TEXT,
  observacao_padrao TEXT,
  ativo BOOLEAN DEFAULT FALSE,
  atualizado_em TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT chk_amb_nfse CHECK (ambiente IN ('1','2'))
);

-- tomadores
CREATE TABLE IF NOT EXISTS tomadores (
  id SERIAL PRIMARY KEY,
  empresa_id INT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  tipo_doc TEXT NOT NULL DEFAULT 'cnpj',
  documento VARCHAR(14) NOT NULL,
  razao_social TEXT NOT NULL,
  nome_fantasia TEXT,
  ie TEXT, im TEXT,
  email TEXT, telefone TEXT,
  logradouro TEXT, numero TEXT, complemento TEXT, bairro TEXT,
  municipio_ibge VARCHAR(7), municipio_nome TEXT, uf VARCHAR(2), cep VARCHAR(8),
  pais VARCHAR(4) DEFAULT '1058',
  situacao_cadastral TEXT,
  receita_consultado_em TIMESTAMPTZ,
  observacoes TEXT,
  ativo BOOLEAN DEFAULT TRUE,
  criado_em TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT uq_tomador UNIQUE (empresa_id, documento),
  CONSTRAINT chk_tipo_doc CHECK (tipo_doc IN ('cnpj','cpf','nif'))
);
CREATE INDEX IF NOT EXISTS idx_tom_emp ON tomadores(empresa_id) WHERE ativo;

-- servicos cadastrados
CREATE TABLE IF NOT EXISTS servicos (
  id SERIAL PRIMARY KEY,
  empresa_id INT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  apelido TEXT NOT NULL,
  codigo_tributacao TEXT NOT NULL,
  cnae TEXT,
  descricao TEXT NOT NULL,
  valor_padrao NUMERIC(15,2),
  aliquota_iss NUMERIC(6,4),
  iss_retido BOOLEAN DEFAULT FALSE,
  municipio_incidencia VARCHAR(7),
  tributacao_municipio TEXT DEFAULT '1',
  favorito BOOLEAN DEFAULT FALSE,
  pis NUMERIC(6,4), cofins NUMERIC(6,4), inss NUMERIC(6,4),
  ir NUMERIC(6,4), csll NUMERIC(6,4),
  ativo BOOLEAN DEFAULT TRUE,
  criado_em TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_srv_emp ON servicos(empresa_id) WHERE ativo;

-- notas emitidas e rascunhos
CREATE TABLE IF NOT EXISTS nfse_emitidas (
  id BIGSERIAL PRIMARY KEY,
  empresa_id INT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  tomador_id INT REFERENCES tomadores(id),
  servico_id INT REFERENCES servicos(id),
  situacao TEXT NOT NULL DEFAULT 'rascunho',
  serie_dps VARCHAR(5),
  numero_dps BIGINT,
  id_dps VARCHAR(45),
  chave_acesso VARCHAR(50),
  numero_nfse TEXT,
  competencia DATE,
  emissao TIMESTAMPTZ,
  descricao TEXT,
  codigo_tributacao TEXT,
  valor_servico NUMERIC(15,2),
  valor_deducoes NUMERIC(15,2) DEFAULT 0,
  valor_desconto NUMERIC(15,2) DEFAULT 0,
  base_calculo NUMERIC(15,2),
  aliquota_iss NUMERIC(6,4),
  valor_iss NUMERIC(15,2),
  iss_retido BOOLEAN DEFAULT FALSE,
  valor_pis NUMERIC(15,2), valor_cofins NUMERIC(15,2),
  valor_inss NUMERIC(15,2), valor_ir NUMERIC(15,2), valor_csll NUMERIC(15,2),
  valor_liquido NUMERIC(15,2),
  xml_dps TEXT,
  xml_nfse TEXT,
  cstat TEXT, motivo TEXT,
  substituida_por BIGINT REFERENCES nfse_emitidas(id),
  substitui BIGINT REFERENCES nfse_emitidas(id),
  cancelada_em TIMESTAMPTZ,
  cancelamento_motivo TEXT,
  recorrencia_id INT,
  email_enviado_em TIMESTAMPTZ,
  criado_por INT REFERENCES usuarios(id),
  criado_em TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT chk_sit_nfse CHECK (situacao IN
    ('rascunho','processando','autorizada','rejeitada','cancelada','substituida'))
);
CREATE INDEX IF NOT EXISTS idx_nfse_emp ON nfse_emitidas(empresa_id, emissao DESC);
CREATE INDEX IF NOT EXISTS idx_nfse_chave ON nfse_emitidas(chave_acesso);
CREATE UNIQUE INDEX IF NOT EXISTS idx_nfse_dps
  ON nfse_emitidas(empresa_id, serie_dps, numero_dps)
  WHERE numero_dps IS NOT NULL;

-- eventos da NFS-e (cancelamento, carta de correcao, substituicao)
CREATE TABLE IF NOT EXISTS nfse_eventos (
  id BIGSERIAL PRIMARY KEY,
  nfse_id BIGINT NOT NULL REFERENCES nfse_emitidas(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL,
  motivo TEXT,
  texto TEXT,
  xml TEXT,
  cstat TEXT,
  retorno TEXT,
  usuario_id INT REFERENCES usuarios(id),
  criado_em TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_nfsev ON nfse_eventos(nfse_id, criado_em DESC);

-- emissao recorrente
CREATE TABLE IF NOT EXISTS nfse_recorrencias (
  id SERIAL PRIMARY KEY,
  empresa_id INT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  tomador_id INT NOT NULL REFERENCES tomadores(id),
  servico_id INT NOT NULL REFERENCES servicos(id),
  apelido TEXT,
  valor NUMERIC(15,2) NOT NULL,
  descricao TEXT,
  dia_emissao INT NOT NULL DEFAULT 1,
  automatica BOOLEAN DEFAULT FALSE,
  inicio DATE NOT NULL,
  fim DATE,
  ultima_emissao DATE,
  proxima_emissao DATE,
  ativo BOOLEAN DEFAULT TRUE,
  criado_em TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT chk_dia CHECK (dia_emissao BETWEEN 1 AND 28)
);
CREATE INDEX IF NOT EXISTS idx_recor ON nfse_recorrencias(proxima_emissao)
  WHERE ativo;

-- alertas do sistema
CREATE TABLE IF NOT EXISTS alertas (
  id BIGSERIAL PRIMARY KEY,
  contabilidade_id INT REFERENCES contabilidades(id) ON DELETE CASCADE,
  empresa_id INT REFERENCES empresas(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL,
  nivel TEXT NOT NULL DEFAULT 'aviso',
  titulo TEXT NOT NULL,
  detalhe TEXT,
  referencia TEXT,
  lido_em TIMESTAMPTZ,
  lido_por INT REFERENCES usuarios(id),
  resolvido_em TIMESTAMPTZ,
  criado_em TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT chk_nivel CHECK (nivel IN ('info','aviso','erro'))
);
CREATE INDEX IF NOT EXISTS idx_alerta ON alertas(contabilidade_id, criado_em DESC)
  WHERE lido_em IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_alerta_unico
  ON alertas(COALESCE(empresa_id,0), tipo, COALESCE(referencia,''))
  WHERE resolvido_em IS NULL;
