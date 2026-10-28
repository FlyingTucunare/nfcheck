import os
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from db import q
import auth
import empresas
import certificados
import importacao
import documentos
import nfse_api
import seguranca
import usuarios
import worker

app = FastAPI(title="NFCheck", docs_url=None, redoc_url=None)
BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.include_router(empresas.router)
app.include_router(certificados.router)
app.include_router(importacao.router)
app.include_router(documentos.router)
app.include_router(nfse_api.router)
app.include_router(usuarios.router)


@app.on_event("startup")
def _sobe_worker():
    """Worker de DFe em thread de fundo. Desligavel por WORKER_DFE=0 no .env."""
    worker.iniciar()


@app.on_event("shutdown")
def _para_worker():
    worker.parar()

class Login(BaseModel):
    email: str
    senha: str
    codigo: str | None = None       # TOTP, quando o front ja manda junto
    contabilidade_id: int | None = None   # quando o e-mail existe em mais de uma


class Login2FA(BaseModel):
    token_parcial: str
    codigo: str


class TrocaSenha(BaseModel):
    senha_atual: str
    senha_nova: str


class Ativa2FA(BaseModel):
    segredo: str
    codigo: str


class Senha(BaseModel):
    senha: str

def _ip(request: Request):
    """Atras do nginx/cloudflared o IP real vem no X-Forwarded-For."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def _sessao(u):
    return {"token": auth.cria_token(u),
            "usuario": {"id": u["id"], "nome": u["nome"], "email": u["email"],
                        "perfil": u["perfil"], "contabilidade_id": u["contabilidade_id"]},
            "trocar_senha": bool(u.get("senha_provisoria"))}


@app.post("/api/login")
def login(dados: Login, request: Request):
    ip = _ip(request)
    email = (dados.email or "").strip()

    restam = seguranca.bloqueio_ativo(email, ip)
    if restam:
        seguranca.registra_tentativa(email, ip, False, "bloqueado")
        raise HTTPException(429,
            f"Muitas tentativas. Tente de novo em {restam} minuto(s).")

    candidatos = q("""SELECT us.*, c.razao_social AS nome_contabilidade
                      FROM usuarios us
                      LEFT JOIN contabilidades c ON c.id = us.contabilidade_id
                      WHERE lower(us.email)=lower(%s) AND us.ativo""", (email,))
    casaram = [x for x in candidatos if auth.confere(dados.senha, x["senha_hash"])]

    if dados.contabilidade_id:
        casaram = [x for x in casaram
                   if x["contabilidade_id"] == dados.contabilidade_id]

    if len(casaram) > 1:
        # mesmo e-mail e mesma senha em contabilidades diferentes
        return {"escolher_contabilidade": [
            {"id": x["contabilidade_id"], "nome": x["nome_contabilidade"] or "Sistema"}
            for x in casaram]}

    u = casaram[0] if casaram else None
    if not u:
        seguranca.registra_tentativa(email, ip, False, "credencial invalida")
        sobram = seguranca.tentativas_restantes(email)
        # nao revela se o e-mail existe: a mensagem e a mesma nos dois casos
        extra = f" Restam {sobram} tentativa(s)." if 0 < sobram <= 3 else ""
        raise HTTPException(401, "E-mail ou senha invalidos." + extra)

    # senha correta: se o 2FA estiver ativo, ainda falta o codigo
    if u["totp_ativo"] and u["totp_secret"]:
        if not dados.codigo:
            return {"precisa_totp": True,
                    "token_parcial": auth.cria_token_parcial(u["id"])}
        if not (seguranca.confere_totp(u["totp_secret"], dados.codigo)
                or seguranca.usa_codigo_recuperacao(u["id"], dados.codigo)):
            seguranca.registra_tentativa(email, ip, False, "codigo 2FA invalido")
            raise HTTPException(401, "Codigo de verificacao invalido.")

    seguranca.registra_tentativa(email, ip, True)
    q("UPDATE usuarios SET ultimo_login=NOW() WHERE id=%s", (u["id"],))
    seguranca.registra(u["id"], "login", {"2fa": bool(u["totp_ativo"])}, ip,
                       u["contabilidade_id"])
    return _sessao(u)


@app.post("/api/login/2fa")
def login_2fa(dados: Login2FA, request: Request):
    """Segunda etapa: o token parcial prova que a senha ja foi validada,
    entao a senha nao precisa trafegar de novo."""
    ip = _ip(request)
    uid = auth.le_token_parcial(dados.token_parcial)
    if not uid:
        raise HTTPException(401, "Sessao expirada. Faca o login de novo.")

    u = q("SELECT * FROM usuarios WHERE id=%s", (uid,), one=True)
    if not u or not u["ativo"]:
        raise HTTPException(401, "Usuario inativo")

    restam = seguranca.bloqueio_ativo(u["email"], ip)
    if restam:
        raise HTTPException(429,
            f"Muitas tentativas. Tente de novo em {restam} minuto(s).")

    if not (seguranca.confere_totp(u["totp_secret"], dados.codigo)
            or seguranca.usa_codigo_recuperacao(u["id"], dados.codigo)):
        seguranca.registra_tentativa(u["email"], ip, False, "codigo 2FA invalido")
        raise HTTPException(401, "Codigo de verificacao invalido.")

    seguranca.registra_tentativa(u["email"], ip, True)
    q("UPDATE usuarios SET ultimo_login=NOW() WHERE id=%s", (u["id"],))
    seguranca.registra(u["id"], "login", {"2fa": True}, ip, u["contabilidade_id"])
    return _sessao(u)


@app.post("/api/senha/trocar")
def trocar_senha(dados: TrocaSenha, request: Request,
                 u=Depends(auth.usuario_atual)):
    atual = q("SELECT * FROM usuarios WHERE id=%s", (u["id"],), one=True)
    if not auth.confere(dados.senha_atual, atual["senha_hash"]):
        raise HTTPException(401, "Senha atual incorreta.")
    problema = seguranca.valida_forca(dados.senha_nova)
    if problema:
        raise HTTPException(400, problema)
    if auth.confere(dados.senha_nova, atual["senha_hash"]):
        raise HTTPException(400, "A nova senha precisa ser diferente da atual.")
    q("""UPDATE usuarios SET senha_hash=%s, senha_provisoria=false,
           senha_alterada_em=now() WHERE id=%s""",
      (auth.hash_senha(dados.senha_nova), u["id"]))
    seguranca.registra(u["id"], "senha_alterada", None, _ip(request),
                       u["contabilidade_id"])
    return {"ok": True}


@app.post("/api/2fa/preparar")
def preparar_2fa(u=Depends(auth.usuario_atual)):
    """Gera o segredo e o QR Code. So passa a valer depois do /ativar."""
    segredo = seguranca.gera_segredo()
    uri = seguranca.uri_qrcode(u["email"], segredo)
    return {"segredo": segredo, "uri": uri, "qrcode": seguranca.qrcode_svg(uri)}


@app.post("/api/2fa/ativar")
def ativar_2fa(dados: Ativa2FA, request: Request, u=Depends(auth.usuario_atual)):
    if not seguranca.confere_totp(dados.segredo, dados.codigo):
        raise HTTPException(400,
            "Codigo invalido. Confira o horario do celular e tente de novo.")
    codigos = seguranca.ativa_totp(u["id"], dados.segredo)
    seguranca.registra(u["id"], "2fa_ativado", None, _ip(request),
                       u["contabilidade_id"])
    return {"ok": True, "codigos_recuperacao": codigos}


@app.post("/api/2fa/desativar")
def desativar_2fa(dados: Senha, request: Request, u=Depends(auth.usuario_atual)):
    atual = q("SELECT senha_hash FROM usuarios WHERE id=%s", (u["id"],), one=True)
    if not auth.confere(dados.senha, atual["senha_hash"]):
        raise HTTPException(401, "Senha incorreta.")
    seguranca.desativa_totp(u["id"])
    seguranca.registra(u["id"], "2fa_desativado", None, _ip(request),
                       u["contabilidade_id"])
    return {"ok": True}


@app.get("/api/2fa/situacao")
def situacao_2fa(u=Depends(auth.usuario_atual)):
    d = q("SELECT totp_ativo, senha_provisoria FROM usuarios WHERE id=%s",
          (u["id"],), one=True)
    return {"ativo": bool(d["totp_ativo"]),
            "codigos_restantes": seguranca.codigos_restantes(u["id"]),
            "senha_provisoria": bool(d["senha_provisoria"])}

@app.get("/api/auditoria")
def auditoria(inicio: str = "", fim: str = "", acao: str = "",
              usuario_id: int | None = None, limite: int = 300,
              u=Depends(auth.exige("ver"))):
    """Trilha de acoes sensiveis. Cada perfil so enxerga o proprio escopo -
    um admin de contabilidade nao ve o que outra contabilidade fez."""
    sql = ["""SELECT a.id, a.criado_em, a.acao, a.detalhe, a.ip,
                a.usuario_id, a.empresa_id,
                us.nome AS usuario, us.email AS usuario_email,
                e.razao_social AS empresa
              FROM auditoria a
              LEFT JOIN usuarios us ON us.id = a.usuario_id
              LEFT JOIN empresas e  ON e.id = a.empresa_id
              WHERE 1=1"""]
    p = []
    if u["perfil"] != "superadmin":
        sql.append("AND a.contabilidade_id = %s")
        p.append(u["contabilidade_id"])
    if inicio:
        sql.append("AND a.criado_em >= %s"); p.append(inicio)
    if fim:
        sql.append("AND a.criado_em < (%s::date + 1)"); p.append(fim)
    if acao:
        sql.append("AND a.acao = %s"); p.append(acao)
    if usuario_id:
        sql.append("AND a.usuario_id = %s"); p.append(usuario_id)
    sql.append("ORDER BY a.id DESC LIMIT %s")
    p.append(min(limite, 1000))

    linhas = q(" ".join(sql), tuple(p))
    acoes = q("""SELECT acao, count(*) AS n FROM auditoria
                 WHERE (%s::int IS NULL OR contabilidade_id = %s)
                 GROUP BY acao ORDER BY acao""",
              (None if u["perfil"] == "superadmin" else u["contabilidade_id"],
               None if u["perfil"] == "superadmin" else u["contabilidade_id"]))
    return {"registros": linhas, "acoes": acoes}


@app.get("/api/alertas")
def listar_alertas(situacao: str = "abertos", u=Depends(auth.exige("ver"))):
    import alertas as al
    cont = None if u["perfil"] == "superadmin" else u["contabilidade_id"]
    sql = ["""SELECT a.*, e.razao_social AS empresa, c.razao_social AS contabilidade,
                us.nome AS lido_por_nome
              FROM alertas a
              LEFT JOIN empresas e ON e.id = a.empresa_id
              LEFT JOIN contabilidades c ON c.id = a.contabilidade_id
              LEFT JOIN usuarios us ON us.id = a.lido_por
              WHERE 1=1"""]
    p = []
    if cont:
        sql.append("AND a.contabilidade_id = %s"); p.append(cont)
    if situacao == "abertos":
        sql.append("AND a.resolvido_em IS NULL")
    elif situacao == "resolvidos":
        sql.append("AND a.resolvido_em IS NOT NULL")
    sql.append("""ORDER BY a.resolvido_em NULLS FIRST,
                    CASE a.nivel WHEN 'erro' THEN 0 WHEN 'aviso' THEN 1 ELSE 2 END,
                    a.criado_em DESC LIMIT 300""")
    return {"alertas": q(" ".join(sql), tuple(p)), "resumo": al.resumo(cont)}


@app.post("/api/alertas/{aid}/lido")
def marcar_lido(aid: int, u=Depends(auth.exige("ver"))):
    a = q("SELECT contabilidade_id FROM alertas WHERE id=%s", (aid,), one=True)
    if not a:
        raise HTTPException(404, "Alerta nao encontrado")
    if u["perfil"] != "superadmin" and a["contabilidade_id"] != u["contabilidade_id"]:
        raise HTTPException(403, "Alerta fora do seu escopo")
    q("""UPDATE alertas SET lido_em=now(), lido_por=%s
         WHERE id=%s AND lido_em IS NULL""", (u["id"], aid))
    return {"ok": True}


@app.post("/api/alertas/verificar")
def verificar_agora(u=Depends(auth.exige("ver"))):
    """Roda a varredura sob demanda, sem esperar o ciclo do worker."""
    import alertas as al
    novos, resolvidos = al.varre()
    return {"ok": True, "novos": novos, "resolvidos": resolvidos}


@app.get("/api/eu")
def eu(u=Depends(auth.usuario_atual)):
    return {"usuario": u, "permissoes": sorted(auth.PERM.get(u["perfil"], set()))}

@app.get("/api/saude")
def saude():
    q("SELECT 1")
    return {"status": "ok"}

@app.get("/painel")
def painel():
    return FileResponse(BASE / "static" / "painel.html")

def _pagina(nome: str, escopo: str):
    """Serve static/paginas/<escopo>/<nome>.html, com fallback para a casca generica."""
    alvo = BASE / "static" / "paginas" / escopo / f"{nome}.html"
    if alvo.exists():
        return FileResponse(alvo)
    return FileResponse(BASE / "static" / "paginas" / "emconstrucao.html")

@app.get("/escritorio/{modulo}")
def pagina_escritorio(modulo: str):
    return _pagina(modulo, "escritorio")

@app.get("/e/{modulo}")
def pagina_empresa(modulo: str):
    return _pagina(modulo, "empresa")

@app.get("/conta/seguranca")
def conta_seguranca():
    return FileResponse(BASE / "static" / "paginas" / "conta" / "seguranca.html")

@app.get("/empresa")
def empresa_home():
    return FileResponse(BASE / "static" / "paginas" / "empresa" / "home.html")

@app.get("/")
def raiz():
    idx = BASE / "static" / "login.html"
    return FileResponse(idx) if idx.exists() else JSONResponse({"nfcheck": "no ar"})
