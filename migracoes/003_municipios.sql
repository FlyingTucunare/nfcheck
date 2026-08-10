CREATE TABLE IF NOT EXISTS municipios (
  codigo_ibge VARCHAR(7) PRIMARY KEY,
  nome TEXT NOT NULL,
  uf VARCHAR(2) NOT NULL,
  nome_norm TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mun_busca ON municipios(uf, nome_norm);
