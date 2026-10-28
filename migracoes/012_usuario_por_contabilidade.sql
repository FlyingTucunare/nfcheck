-- O mesmo e-mail pode existir em contabilidades diferentes: um contador
-- pode ser cliente de duas contabilidades distintas. Cada uma mantem o
-- proprio cadastro, com senha propria - o isolamento entre contabilidades
-- e o principio que rege este sistema (elas guardam certificados digitais
-- de terceiros e nao podem enxergar acessos umas das outras).
ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS usuarios_email_key;

-- superadmin nao tem contabilidade: COALESCE(0) garante unicidade entre eles
CREATE UNIQUE INDEX IF NOT EXISTS uq_usuario_email_cont
  ON usuarios (COALESCE(contabilidade_id, 0), lower(email));

CREATE INDEX IF NOT EXISTS idx_usuario_email ON usuarios (lower(email));
