import os
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request
from jose import jwt, JWTError
import bcrypt
from db import q, JWT_SECRET

ALGO = "HS256"
HORAS_TOKEN = 8

PERFIS = ("superadmin", "contabilidade_admin", "contabilidade_operador", "cliente_final")

PERM = {
    "superadmin":             {"admin","empresa_escrever","cert_escrever","usuario_escrever",
                               "ver","baixar","relatorio","manifestar","emitir","importar"},
    "contabilidade_admin":    {"empresa_escrever","cert_escrever","usuario_escrever",
                               "ver","baixar","relatorio","manifestar","emitir","importar"},
    "contabilidade_operador": {"ver","baixar","relatorio","manifestar","emitir","importar"},
    "cliente_final":          {"ver","baixar","relatorio"},
}

def _b(s):
    """bcrypt trunca em 72 bytes; corta explicitamente para nao estourar."""
    return s.encode("utf-8")[:72]

def hash_senha(s):
    return bcrypt.hashpw(_b(s), bcrypt.gensalt()).decode()

def confere(s, h):
    try:
        return bcrypt.checkpw(_b(s), h.encode())
    except (ValueError, TypeError):
        return False

def cria_token(u):
    exp = datetime.now(timezone.utc) + timedelta(hours=HORAS_TOKEN)
    return jwt.encode({"sub": str(u["id"]), "perfil": u["perfil"],
                       "cont": u["contabilidade_id"], "exp": exp}, JWT_SECRET, algorithm=ALGO)

def cria_token_parcial(usuario_id, minutos=5):
    """Token curto que prova apenas que a SENHA foi validada, enquanto o
    usuario digita o codigo do 2FA. Nao serve para acessar nada: o
    usuario_atual() recusa tokens com escopo '2fa'."""
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutos)
    return jwt.encode({"sub": str(usuario_id), "escopo": "2fa", "exp": exp},
                      JWT_SECRET, algorithm=ALGO)


def le_token_parcial(token):
    """Devolve o id do usuario, ou None se o token for invalido/expirado."""
    try:
        p = jwt.decode(token, JWT_SECRET, algorithms=[ALGO])
    except JWTError:
        return None
    if p.get("escopo") != "2fa":
        return None
    return int(p["sub"])


def usuario_atual(request: Request):
    h = request.headers.get("Authorization", "")
    if not h.startswith("Bearer "):
        raise HTTPException(401, "Nao autenticado")
    try:
        p = jwt.decode(h[7:], JWT_SECRET, algorithms=[ALGO])
    except JWTError:
        raise HTTPException(401, "Token invalido ou expirado")
    if p.get("escopo") == "2fa":
        raise HTTPException(401, "Verificacao em duas etapas pendente")
    u = q("""SELECT id,nome,email,perfil,contabilidade_id,ativo,senha_provisoria
             FROM usuarios WHERE id=%s""", (int(p["sub"]),), one=True)
    if not u or not u["ativo"]:
        raise HTTPException(401, "Usuario inativo")
    return u

def exige(permissao):
    def dep(u=Depends(usuario_atual)):
        if permissao not in PERM.get(u["perfil"], set()):
            raise HTTPException(403, "Sem permissao para esta acao")
        return u
    return dep

def empresas_visiveis(u):
    if u["perfil"] == "superadmin":
        return q("SELECT id FROM empresas")
    if u["perfil"] == "cliente_final":
        return q("""SELECT e.id FROM empresas e
                    JOIN usuario_empresas ue ON ue.empresa_id=e.id
                    WHERE ue.usuario_id=%s""", (u["id"],))
    return q("SELECT id FROM empresas WHERE contabilidade_id=%s", (u["contabilidade_id"],))

def exige_empresa(u, empresa_id):
    ids = {e["id"] for e in empresas_visiveis(u)}
    if int(empresa_id) not in ids:
        raise HTTPException(403, "Empresa fora do seu escopo")
    return int(empresa_id)
