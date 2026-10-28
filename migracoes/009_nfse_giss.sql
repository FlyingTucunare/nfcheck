-- Roteamento de provedor de NFS-e por município
ALTER TABLE municipios ADD COLUMN IF NOT EXISTS provedor_nfse text;
ALTER TABLE municipios ADD COLUMN IF NOT EXISTS giss_slug text;
ALTER TABLE municipios ADD COLUMN IF NOT EXISTS schema_versao_giss text;

DO $$ BEGIN
    ALTER TABLE municipios ADD CONSTRAINT chk_provedor_nfse
        CHECK (provedor_nfse IS NULL OR provedor_nfse IN ('emissor_nacional','giss_abrasf'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Classificação nacional do serviço (LC116/NBS) + campos novos de Reforma Tributária
ALTER TABLE servicos ADD COLUMN IF NOT EXISTS item_lista_servico text;
ALTER TABLE servicos ADD COLUMN IF NOT EXISTS codigo_nbs text;
ALTER TABLE servicos ADD COLUMN IF NOT EXISTS cind_op text;
ALTER TABLE servicos ADD COLUMN IF NOT EXISTS cclass_trib text;

-- Suporte a emissão via GISS/ABRASF (RPS+lote) na mesma tabela do Emissor Nacional
ALTER TABLE nfse_emitidas ADD COLUMN IF NOT EXISTS provedor text NOT NULL DEFAULT 'emissor_nacional';
ALTER TABLE nfse_emitidas ADD COLUMN IF NOT EXISTS numero_rps bigint;
ALTER TABLE nfse_emitidas ADD COLUMN IF NOT EXISTS serie_rps character varying(5);
ALTER TABLE nfse_emitidas ADD COLUMN IF NOT EXISTS protocolo_lote text;

DO $$ BEGIN
    ALTER TABLE nfse_emitidas ADD CONSTRAINT chk_provedor_emitida
        CHECK (provedor IN ('emissor_nacional','giss_abrasf'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Correlação Item LC116 -> NBS -> cIndOp -> cClassTrib (Reforma Tributária IBS/CBS)
CREATE TABLE IF NOT EXISTS correlacao_nbs_ibscbs (
    id bigserial PRIMARY KEY,
    item_lista_servico text NOT NULL,
    descricao_item text,
    codigo_nbs text,
    descricao_nbs text,
    ps_onerosa text,
    adq_exterior text,
    cind_op text,
    local_incidencia text,
    cclass_trib text,
    nome_cclass_trib text
);
CREATE INDEX IF NOT EXISTS idx_correlacao_item ON correlacao_nbs_ibscbs(item_lista_servico);

-- Códigos de erro/alerta do provedor GISS (padrão ABRASF)
CREATE TABLE IF NOT EXISTS giss_erros_alertas (
    codigo text PRIMARY KEY,
    mensagem text NOT NULL,
    solucao text
);

-- Guarulhos pré-configurado: Emissor Nacional bloqueado (E0039), usa GISS/ABRASF
UPDATE municipios SET provedor_nfse = 'giss_abrasf', giss_slug = 'guarulhos', schema_versao_giss = 'ibscbs_v1'
WHERE codigo_ibge = '3518800';
