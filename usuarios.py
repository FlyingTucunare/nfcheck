"""Gestão de usuários e acessos.

Regras de quem cria quem:
  superadmin           -> qualquer perfil, em qualquer contabilidade
  contabilidade_admin  -> operador e cliente_final, so na propria contabilidade

Um admin de contabilidade NAO cria outro admin: admin gerencia certificados
digitais de terceiros, entao a promocao passa pelo superadmin.
"""
import random
import re
import unicodedata
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from db import q
import auth
import emails
import seguranca

router = APIRouter(prefix="/api/usuarios", tags=["usuarios"])

ROTULO = {
    "superadmin": "Administrador do sistema",
    "contabilidade_admin": "Administrador da contabilidade",
    "contabilidade_operador": "Operador",
    "cliente_final": "Cliente (acesso às próprias empresas)",
}
CRIAVEIS = {
    "superadmin": ["superadmin", "contabilidade_admin", "contabilidade_operador",
                   "cliente_final"],
    "contabilidade_admin": ["contabilidade_operador", "cliente_final"],
}


class UsuarioEntrada(BaseModel):
    nome: str
    sobrenome: str
    email: str
    telefone: str
    cpf: str | None = None
    perfil: str
    contabilidade_id: int | None = None
    empresas: list[int] = []          # so para cliente_final


class UsuarioEdicao(BaseModel):
    nome: str
    sobrenome: str
    telefone: str
    cpf: str | None = None
    perfil: str | None = None
    empresas: list[int] | None = None


def _limpa(v):
    return re.sub(r"\D", "", v or "")


def _sem_acento(txt):
    return "".join(c for c in unicodedata.normalize("NFKD", txt or "")
                   if not unicodedata.combining(c))


def gera_senha(nome, sobrenome):
    """Nome.Sobrenome#HHMM + um digito aleatorio.

    Ditavel por telefone e passa nas regras de forca. Como e provisoria e
    morre no primeiro acesso, o objetivo e ser transmissivel, nao eterna.
    """
    def parte(t):
        t = _sem_acento(t or "").strip()
        t = re.sub(r"[^A-Za-z]", "", t)[:12]
        return (t[:1].upper() + t[1:].lower()) or "Usuario"
    agora = datetime.now(timezone.utc).astimezone()
    return (f"{parte(nome)}.{parte(sobrenome)}#"
            f"{agora.strftime('%H%M')}{random.randint(0, 9)}")


def _valida_email(e):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$", (e or "").strip()))


def _valida_cpf(cpf):
    """Digitos verificadores. CPF e opcional, mas se vier tem que ser real."""
    c = _limpa(cpf)
    if len(c) != 11 or c == c[0] * 11:
        return False
    for i in (9, 10):
        s = sum(int(c[j]) * ((i + 1) - j) for j in range(i))
        d = (s * 10) % 11
        if d == 10:
            d = 0
        if d != int(c[i]):
            return False
    return True


def _pode_criar(u, perfil):
    return perfil in CRIAVEIS.get(u["perfil"], [])


def _escopo(u, alvo):
    """Um admin de contabilidade so enxerga a propria equipe."""
    if u["perfil"] == "superadmin":
        return True
    return alvo["contabilidade_id"] == u["contabilidade_id"]


def _nome_completo(nome, sobrenome):
    return f"{(nome or '').strip()} {(sobrenome or '').strip()}".strip()


# ------------------------------------------------------------------ listar
@router.get("")
def listar(u=Depends(auth.exige("usuario_escrever"))):
    if u["perfil"] == "superadmin":
        linhas = q("""SELECT us.id, us.nome, us.email, us.telefone, us.perfil,
                        us.ativo, us.totp_ativo, us.senha_provisoria,
                        us.ultimo_login, us.criado_em, us.contabilidade_id,
                        c.razao_social AS contabilidade,
                        (SELECT count(*) FROM usuario_empresas ue
                          WHERE ue.usuario_id = us.id) AS empresas_vinculadas
                      FROM usuarios us
                      LEFT JOIN contabilidades c ON c.id = us.contabilidade_id
                      ORDER BY us.ativo DESC, us.nome""")
    else:
        linhas = q("""SELECT us.id, us.nome, us.email, us.telefone, us.perfil,
                        us.ativo, us.totp_ativo, us.senha_provisoria,
                        us.ultimo_login, us.criado_em, us.contabilidade_id,
                        NULL AS contabilidade,
                        (SELECT count(*) FROM usuario_empresas ue
                          WHERE ue.usuario_id = us.id) AS empresas_vinculadas
                      FROM usuarios us
                      WHERE us.contabilidade_id = %s
                      ORDER BY us.ativo DESC, us.nome""",
                   (u["contabilidade_id"],))
    return {"usuarios": linhas,
            "perfis_criaveis": [{"id": p, "rotulo": ROTULO[p]}
                                for p in CRIAVEIS.get(u["perfil"], [])],
            "eu": u["id"]}


@router.get("/empresas-disponiveis")
def empresas_disponiveis(u=Depends(auth.exige("usuario_escrever"))):
    """Empresas que podem ser vinculadas a um cliente_final."""
    ids = [e["id"] for e in auth.empresas_visiveis(u)]
    if not ids:
        return []
    return q("""SELECT id, razao_social, cnpj FROM empresas
                WHERE id = ANY(%s) AND arquivada_em IS NULL
                ORDER BY razao_social""", (ids,))


# ------------------------------------------------------------------ criar
@router.post("")
def criar(d: UsuarioEntrada, request: Request,
          u=Depends(auth.exige("usuario_escrever"))):
    if not _pode_criar(u, d.perfil):
        raise HTTPException(403,
            "Seu perfil não pode criar usuários com esse nível de acesso.")
    if not d.nome.strip() or not d.sobrenome.strip():
        raise HTTPException(400, "Informe nome e sobrenome.")
    if not _valida_email(d.email):
        raise HTTPException(400, "E-mail inválido.")
    if len(_limpa(d.telefone)) < 10:
        raise HTTPException(400, "Telefone inválido. Informe com DDD.")
    if d.cpf and not _valida_cpf(d.cpf):
        raise HTTPException(400, "CPF inválido.")

    email = d.email.strip().lower()
    if q("SELECT id FROM usuarios WHERE lower(email)=%s", (email,), one=True):
        raise HTTPException(400, "Já existe um usuário com esse e-mail.")

    cont = d.contabilidade_id if u["perfil"] == "superadmin" else u["contabilidade_id"]
    if d.perfil != "superadmin" and not cont:
        raise HTTPException(400, "Informe a contabilidade.")

    senha = gera_senha(d.nome, d.sobrenome)
    novo = q("""INSERT INTO usuarios (contabilidade_id, nome, email, telefone,
                  cpf, senha_hash, perfil, ativo, senha_provisoria)
                VALUES (%s,%s,%s,%s,%s,%s,%s,true,true)
                RETURNING id, nome, email, perfil""",
             (cont, _nome_completo(d.nome, d.sobrenome), email,
              _limpa(d.telefone), _limpa(d.cpf) or None,
              auth.hash_senha(senha), d.perfil), one=True)

    if d.perfil == "cliente_final" and d.empresas:
        permitidas = {e["id"] for e in auth.empresas_visiveis(u)}
        for eid in d.empresas:
            if eid in permitidas:
                q("""INSERT INTO usuario_empresas (usuario_id, empresa_id)
                     VALUES (%s,%s) ON CONFLICT DO NOTHING""", (novo["id"], eid))

    nome_cont = None
    if cont:
        c = q("SELECT razao_social FROM contabilidades WHERE id=%s", (cont,), one=True)
        nome_cont = (c or {}).get("razao_social")

    ok, detalhe = emails.boas_vindas(novo["nome"], email, senha,
                                     ROTULO[d.perfil], nome_cont)
    seguranca.registra(u["id"], "usuario_criado",
                       {"usuario": email, "perfil": d.perfil, "email_enviado": ok},
                       request.headers.get("x-forwarded-for"), cont)
    return {"usuario": novo, "senha": senha, "email_enviado": ok,
            "email_detalhe": None if ok else str(detalhe)[:200]}


# ------------------------------------------------------------------ editar
@router.put("/{uid}")
def editar(uid: int, d: UsuarioEdicao, request: Request,
           u=Depends(auth.exige("usuario_escrever"))):
    alvo = q("SELECT * FROM usuarios WHERE id=%s", (uid,), one=True)
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado")
    if not _escopo(u, alvo):
        raise HTTPException(403, "Usuário fora do seu escopo")
    if d.cpf and not _valida_cpf(d.cpf):
        raise HTTPException(400, "CPF inválido.")

    perfil = alvo["perfil"]
    if d.perfil and d.perfil != alvo["perfil"]:
        if uid == u["id"]:
            raise HTTPException(400, "Você não pode alterar o próprio perfil.")
        if not _pode_criar(u, d.perfil):
            raise HTTPException(403, "Seu perfil não pode conceder esse nível de acesso.")
        perfil = d.perfil

    q("""UPDATE usuarios SET nome=%s, telefone=%s, cpf=%s, perfil=%s WHERE id=%s""",
      (_nome_completo(d.nome, d.sobrenome), _limpa(d.telefone),
       _limpa(d.cpf) or None, perfil, uid))

    if d.empresas is not None and perfil == "cliente_final":
        permitidas = {e["id"] for e in auth.empresas_visiveis(u)}
        q("DELETE FROM usuario_empresas WHERE usuario_id=%s", (uid,))
        for eid in d.empresas:
            if eid in permitidas:
                q("""INSERT INTO usuario_empresas (usuario_id, empresa_id)
                     VALUES (%s,%s) ON CONFLICT DO NOTHING""", (uid, eid))

    seguranca.registra(u["id"], "usuario_editado", {"usuario_id": uid},
                       request.headers.get("x-forwarded-for"),
                       alvo["contabilidade_id"])
    return q("""SELECT id, nome, email, telefone, cpf, perfil, ativo
                FROM usuarios WHERE id=%s""", (uid,), one=True)


@router.post("/{uid}/situacao")
def situacao(uid: int, request: Request, u=Depends(auth.exige("usuario_escrever"))):
    """Ativa ou desativa. Nao ha exclusao: a auditoria referencia o usuario."""
    alvo = q("SELECT * FROM usuarios WHERE id=%s", (uid,), one=True)
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado")
    if not _escopo(u, alvo):
        raise HTTPException(403, "Usuário fora do seu escopo")
    if uid == u["id"]:
        raise HTTPException(400, "Você não pode desativar a própria conta.")

    novo = not alvo["ativo"]
    q("UPDATE usuarios SET ativo=%s WHERE id=%s", (novo, uid))
    seguranca.registra(u["id"], "usuario_ativado" if novo else "usuario_desativado",
                       {"usuario": alvo["email"]},
                       request.headers.get("x-forwarded-for"),
                       alvo["contabilidade_id"])
    return {"ok": True, "ativo": novo}


@router.post("/{uid}/resetar-senha")
def resetar_senha(uid: int, request: Request,
                  u=Depends(auth.exige("usuario_escrever"))):
    alvo = q("SELECT * FROM usuarios WHERE id=%s", (uid,), one=True)
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado")
    if not _escopo(u, alvo):
        raise HTTPException(403, "Usuário fora do seu escopo")

    partes = (alvo["nome"] or "Usuario").split()
    senha = gera_senha(partes[0], partes[-1] if len(partes) > 1 else "Acesso")
    q("""UPDATE usuarios SET senha_hash=%s, senha_provisoria=true WHERE id=%s""",
      (auth.hash_senha(senha), uid))
    q("DELETE FROM login_tentativas WHERE email=%s", (alvo["email"],))

    ok, detalhe = emails.senha_redefinida(alvo["nome"], alvo["email"], senha)
    seguranca.registra(u["id"], "senha_resetada",
                       {"usuario": alvo["email"], "email_enviado": ok},
                       request.headers.get("x-forwarded-for"),
                       alvo["contabilidade_id"])
    return {"ok": True, "senha": senha, "email_enviado": ok,
            "email_detalhe": None if ok else str(detalhe)[:200]}


@router.post("/{uid}/desativar-2fa")
def desativar_2fa(uid: int, request: Request,
                  u=Depends(auth.exige("usuario_escrever"))):
    """Socorro para quem perdeu o celular e esgotou os codigos de recuperacao."""
    alvo = q("SELECT * FROM usuarios WHERE id=%s", (uid,), one=True)
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado")
    if not _escopo(u, alvo):
        raise HTTPException(403, "Usuário fora do seu escopo")
    if not alvo["totp_ativo"]:
        raise HTTPException(400, "Este usuário não usa verificação em duas etapas.")

    seguranca.desativa_totp(uid)
    seguranca.registra(u["id"], "2fa_desativado_por_admin",
                       {"usuario": alvo["email"]},
                       request.headers.get("x-forwarded-for"),
                       alvo["contabilidade_id"])
    return {"ok": True}


class AcessoCliente(BaseModel):
    """Atalho do card da empresa: cria (ou amplia) o acesso do dono dela."""
    empresa_id: int
    nome: str
    sobrenome: str
    email: str
    telefone: str
    cpf: str | None = None


@router.post("/acesso-cliente")
def acesso_cliente(d: AcessoCliente, request: Request,
                   u=Depends(auth.exige("usuario_escrever"))):
    """Da acesso ao dono de uma empresa.

    Se a pessoa ja tem acesso nesta contabilidade, a empresa e ADICIONADA ao
    login existente em vez de gerar erro de duplicidade - o mesmo dono pode
    ter varias empresas e usa um login so.
    """
    auth.exige_empresa(u, d.empresa_id)
    if not _pode_criar(u, "cliente_final"):
        raise HTTPException(403, "Seu perfil não pode conceder acesso de cliente.")
    if not _valida_email(d.email):
        raise HTTPException(400, "E-mail inválido.")
    if not d.nome.strip() or not d.sobrenome.strip():
        raise HTTPException(400, "Informe nome e sobrenome.")
    if len(_limpa(d.telefone)) < 10:
        raise HTTPException(400, "Telefone inválido. Informe com DDD.")
    if d.cpf and not _valida_cpf(d.cpf):
        raise HTTPException(400, "CPF inválido.")

    email = d.email.strip().lower()
    emp = q("SELECT id, razao_social, contabilidade_id FROM empresas WHERE id=%s",
            (d.empresa_id,), one=True)
    cont = emp["contabilidade_id"]
    c = q("SELECT razao_social FROM contabilidades WHERE id=%s", (cont,), one=True)
    nome_cont = (c or {}).get("razao_social")

    existente = q("""SELECT * FROM usuarios
                     WHERE lower(email)=%s AND COALESCE(contabilidade_id,0)=%s""",
                  (email, cont or 0), one=True)

    if existente:
        if existente["perfil"] != "cliente_final":
            raise HTTPException(400,
                "Este e-mail já pertence a um usuário da equipe, não a um cliente.")
        if not existente["ativo"]:
            raise HTTPException(400,
                "Este e-mail pertence a um acesso desativado. Reative-o em "
                "Usuários e acessos.")

        ja = q("""SELECT 1 FROM usuario_empresas
                  WHERE usuario_id=%s AND empresa_id=%s""",
               (existente["id"], d.empresa_id), one=True)
        if ja:
            return {"situacao": "ja_tinha", "usuario_id": existente["id"],
                    "nome": existente["nome"], "empresa": emp["razao_social"]}

        q("""INSERT INTO usuario_empresas (usuario_id, empresa_id)
             VALUES (%s,%s) ON CONFLICT DO NOTHING""",
          (existente["id"], d.empresa_id))
        total = q("""SELECT count(*) AS n FROM usuario_empresas
                     WHERE usuario_id=%s""", (existente["id"],), one=True)["n"]

        ok, detalhe = emails.empresa_adicionada(
            existente["nome"], email, emp["razao_social"], nome_cont, total)
        seguranca.registra(u["id"], "empresa_vinculada_a_cliente",
                           {"usuario": email, "empresa_id": d.empresa_id,
                            "email_enviado": ok},
                           request.headers.get("x-forwarded-for"), cont, d.empresa_id)
        return {"situacao": "empresa_adicionada", "usuario_id": existente["id"],
                "nome": existente["nome"], "empresa": emp["razao_social"],
                "total_empresas": total, "email_enviado": ok,
                "email_detalhe": None if ok else str(detalhe)[:200]}

    senha = gera_senha(d.nome, d.sobrenome)
    novo = q("""INSERT INTO usuarios (contabilidade_id, nome, email, telefone,
                  cpf, senha_hash, perfil, ativo, senha_provisoria)
                VALUES (%s,%s,%s,%s,%s,%s,'cliente_final',true,true)
                RETURNING id, nome, email""",
             (cont, _nome_completo(d.nome, d.sobrenome), email,
              _limpa(d.telefone), _limpa(d.cpf) or None,
              auth.hash_senha(senha)), one=True)
    q("""INSERT INTO usuario_empresas (usuario_id, empresa_id)
         VALUES (%s,%s) ON CONFLICT DO NOTHING""", (novo["id"], d.empresa_id))

    ok, detalhe = emails.boas_vindas(novo["nome"], email, senha,
                                     ROTULO["cliente_final"], nome_cont)
    seguranca.registra(u["id"], "acesso_cliente_criado",
                       {"usuario": email, "empresa_id": d.empresa_id,
                        "email_enviado": ok},
                       request.headers.get("x-forwarded-for"), cont, d.empresa_id)
    return {"situacao": "criado", "usuario_id": novo["id"], "nome": novo["nome"],
            "empresa": emp["razao_social"], "senha": senha, "email_enviado": ok,
            "email_detalhe": None if ok else str(detalhe)[:200]}


@router.get("/empresa/{empresa_id}/clientes")
def clientes_da_empresa(empresa_id: int, u=Depends(auth.exige("usuario_escrever"))):
    """Quem ja tem acesso de cliente a esta empresa."""
    auth.exige_empresa(u, empresa_id)
    return q("""SELECT us.id, us.nome, us.email, us.ativo, us.senha_provisoria,
                  us.ultimo_login,
                  (SELECT count(*) FROM usuario_empresas x
                    WHERE x.usuario_id = us.id) AS empresas_vinculadas
                FROM usuarios us
                JOIN usuario_empresas ue ON ue.usuario_id = us.id
                WHERE ue.empresa_id = %s AND us.perfil = 'cliente_final'
                ORDER BY us.nome""", (empresa_id,))


@router.get("/{uid}/empresas")
def empresas_do_usuario(uid: int, u=Depends(auth.exige("usuario_escrever"))):
    alvo = q("SELECT * FROM usuarios WHERE id=%s", (uid,), one=True)
    if not alvo or not _escopo(u, alvo):
        raise HTTPException(404, "Usuário não encontrado")
    return [r["empresa_id"] for r in
            q("SELECT empresa_id FROM usuario_empresas WHERE usuario_id=%s", (uid,))]
