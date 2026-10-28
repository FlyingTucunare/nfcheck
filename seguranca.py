"""Camada de segurança do login: controle de tentativas, 2FA (TOTP) e
troca obrigatória de senha.

Escrito para o NFCheck sair de trás do Cloudflare Access. O vetor mais
provável assim que o endereço fica público é força bruta no /api/login -
por isso o bloqueio por tentativas é o item central.

O sistema guarda certificados digitais A1 de terceiros: um acesso indevido
permite emitir documento fiscal em nome das empresas do cliente. Toda
decisão aqui pende para o lado conservador.
"""
import base64
import io
import os
import secrets
from datetime import datetime, timedelta, timezone

import pyotp

from db import q

# --- política de tentativas ---
MAX_TENTATIVAS = 5          # erros consecutivos antes de bloquear
JANELA_MIN = 15             # minutos considerados para contar as tentativas
BLOQUEIO_MIN = 15           # minutos de bloqueio depois de estourar
MAX_POR_IP = 20             # teto por IP na janela (varredura de e-mails)

APP_NOME = "NFCheck"


def _agora():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------- tentativas
def registra_tentativa(email, ip, sucesso, motivo=None):
    q("""INSERT INTO login_tentativas (email, ip, sucesso, motivo)
         VALUES (%s,%s,%s,%s)""",
      ((email or "").lower().strip(), ip, sucesso, motivo))


def _conta(campo, valor, minutos):
    r = q(f"""SELECT count(*) AS n FROM login_tentativas
              WHERE {campo} = %s AND NOT sucesso
                AND quando > now() - interval '{int(minutos)} minutes'""",
          (valor,), one=True)
    return (r or {}).get("n", 0)


def bloqueio_ativo(email, ip):
    """Devolve os minutos restantes de bloqueio, ou 0 se estiver liberado.

    Conta apenas falhas posteriores ao último login bem-sucedido: quem
    acerta a senha zera o contador e não fica preso por erros antigos.
    """
    email = (email or "").lower().strip()

    ultimo_ok = q("""SELECT max(quando) AS q FROM login_tentativas
                     WHERE email = %s AND sucesso""", (email,), one=True)
    corte = (ultimo_ok or {}).get("q")

    falhas = q("""SELECT count(*) AS n, max(quando) AS ultima
                  FROM login_tentativas
                  WHERE email = %s AND NOT sucesso
                    AND quando > now() - interval '%s minutes'
                    AND (%s::timestamptz IS NULL OR quando > %s::timestamptz)""",
               (email, JANELA_MIN, corte, corte), one=True)

    n = (falhas or {}).get("n", 0)
    if n >= MAX_TENTATIVAS:
        ultima = falhas["ultima"]
        fim = ultima + timedelta(minutes=BLOQUEIO_MIN)
        restam = (fim - _agora()).total_seconds() / 60
        if restam > 0:
            return max(1, int(restam) + 1)

    # teto por IP: pega varredura de varios e-mails a partir do mesmo lugar
    if ip and _conta("ip", ip, JANELA_MIN) >= MAX_POR_IP:
        return BLOQUEIO_MIN

    return 0


def tentativas_restantes(email):
    email = (email or "").lower().strip()
    ultimo_ok = q("""SELECT max(quando) AS q FROM login_tentativas
                     WHERE email = %s AND sucesso""", (email,), one=True)
    corte = (ultimo_ok or {}).get("q")
    r = q("""SELECT count(*) AS n FROM login_tentativas
             WHERE email = %s AND NOT sucesso
               AND quando > now() - interval '%s minutes'
               AND (%s::timestamptz IS NULL OR quando > %s::timestamptz)""",
          (email, JANELA_MIN, corte, corte), one=True)
    return max(0, MAX_TENTATIVAS - (r or {}).get("n", 0))


def limpa_antigas(dias=30):
    q("DELETE FROM login_tentativas WHERE quando < now() - interval '%s days'", (dias,))


# ------------------------------------------------------------- senha
def precisa_trocar_senha(usuario):
    """Senha inicial definida pelo administrador precisa ser trocada no
    primeiro acesso - ela costuma ser combinada por telefone ou mensagem."""
    return bool(usuario.get("senha_provisoria"))


def marca_senha_definitiva(usuario_id):
    q("""UPDATE usuarios SET senha_provisoria = false,
           senha_alterada_em = now() WHERE id = %s""", (usuario_id,))


def valida_forca(senha):
    """Regras mínimas. Devolve None se estiver boa, ou a mensagem do problema."""
    if len(senha or "") < 10:
        return "A senha precisa ter pelo menos 10 caracteres."
    if senha.isdigit() or senha.isalpha():
        return "Misture letras, números e ao menos um símbolo."
    if not any(c.isdigit() for c in senha):
        return "Inclua ao menos um número."
    if not any(c.isalpha() for c in senha):
        return "Inclua ao menos uma letra."
    comuns = {"12345678910", "senha123456", "nfcheck2026", "administrador"}
    if senha.lower() in comuns:
        return "Essa senha é fácil de adivinhar. Escolha outra."
    return None


# ------------------------------------------------------------- TOTP (2FA)
def gera_segredo():
    return pyotp.random_base32()


def uri_qrcode(email, segredo):
    """URI otpauth:// que o app autenticador lê."""
    return pyotp.totp.TOTP(segredo).provisioning_uri(name=email, issuer_name=APP_NOME)


def qrcode_svg(uri):
    """QR Code em SVG - evita depender de biblioteca de imagem."""
    try:
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode("utf-8")
    except Exception:
        return None


def confere_totp(segredo, codigo):
    """valid_window=1 tolera relógio dessincronizado em ate 30s para cada lado."""
    if not segredo or not codigo:
        return False
    return pyotp.TOTP(segredo).verify(str(codigo).strip().replace(" ", ""),
                                      valid_window=1)


def ativa_totp(usuario_id, segredo):
    q("UPDATE usuarios SET totp_secret=%s, totp_ativo=true WHERE id=%s",
      (segredo, usuario_id))
    return gera_codigos_recuperacao(usuario_id)


def desativa_totp(usuario_id):
    q("""UPDATE usuarios SET totp_secret=NULL, totp_ativo=false WHERE id=%s""",
      (usuario_id,))
    q("DELETE FROM totp_recuperacao WHERE usuario_id=%s", (usuario_id,))


def gera_codigos_recuperacao(usuario_id, quantos=8):
    """Códigos de uso único, para quando o usuário perde o celular.
    Guardados com hash - o texto puro só aparece uma vez, na geração."""
    import auth
    q("DELETE FROM totp_recuperacao WHERE usuario_id=%s", (usuario_id,))
    codigos = []
    for _ in range(quantos):
        c = f"{secrets.randbelow(10**5):05d}-{secrets.randbelow(10**5):05d}"
        codigos.append(c)
        q("""INSERT INTO totp_recuperacao (usuario_id, codigo_hash)
             VALUES (%s,%s)""", (usuario_id, auth.hash_senha(c)))
    return codigos


def usa_codigo_recuperacao(usuario_id, codigo):
    import auth
    for r in q("""SELECT id, codigo_hash FROM totp_recuperacao
                  WHERE usuario_id=%s AND usado_em IS NULL""", (usuario_id,)):
        if auth.confere(str(codigo).strip(), r["codigo_hash"]):
            q("UPDATE totp_recuperacao SET usado_em=now() WHERE id=%s", (r["id"],))
            return True
    return False


def codigos_restantes(usuario_id):
    r = q("""SELECT count(*) AS n FROM totp_recuperacao
             WHERE usuario_id=%s AND usado_em IS NULL""", (usuario_id,), one=True)
    return (r or {}).get("n", 0)


# ------------------------------------------------------------- auditoria
def registra(usuario_id, acao, detalhe=None, ip=None,
             contabilidade_id=None, empresa_id=None):
    """Trilha de auditoria das ações sensíveis. 'detalhe' é jsonb."""
    import json
    try:
        q("""INSERT INTO auditoria (usuario_id, contabilidade_id, empresa_id,
               acao, detalhe, ip)
             VALUES (%s,%s,%s,%s,%s,%s)""",
          (usuario_id, contabilidade_id, empresa_id, acao,
           json.dumps(detalhe, ensure_ascii=False) if detalhe is not None else None,
           ip))
    except Exception:
        pass    # auditoria nunca pode derrubar a operação principal
