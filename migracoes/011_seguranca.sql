-- tentativas de login: base do bloqueio por forca bruta
CREATE TABLE IF NOT EXISTS login_tentativas (
    id       bigserial PRIMARY KEY,
    email    text,
    ip       text,
    sucesso  boolean NOT NULL DEFAULT false,
    motivo   text,
    quando   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tent_email ON login_tentativas(email, quando DESC);
CREATE INDEX IF NOT EXISTS idx_tent_ip    ON login_tentativas(ip, quando DESC);

-- senha inicial definida pelo admin precisa ser trocada no primeiro acesso
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS senha_provisoria boolean DEFAULT false;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS senha_alterada_em timestamptz;

-- codigos de uso unico para quando o usuario perde o celular do 2FA
CREATE TABLE IF NOT EXISTS totp_recuperacao (
    id          bigserial PRIMARY KEY,
    usuario_id  integer NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    codigo_hash text NOT NULL,
    usado_em    timestamptz,
    criado_em   timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_totp_rec ON totp_recuperacao(usuario_id)
  WHERE usado_em IS NULL;
