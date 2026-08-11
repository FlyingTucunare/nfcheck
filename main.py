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

app = FastAPI(title="NFCheck", docs_url=None, redoc_url=None)
BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.include_router(empresas.router)
app.include_router(certificados.router)
app.include_router(importacao.router)
app.include_router(documentos.router)

class Login(BaseModel):
    email: str
    senha: str

@app.post("/api/login")
def login(dados: Login, request: Request):
    u = q("SELECT * FROM usuarios WHERE lower(email)=lower(%s)", (dados.email,), one=True)
    if not u or not u["ativo"] or not auth.confere(dados.senha, u["senha_hash"]):
        raise HTTPException(401, "E-mail ou senha invalidos")
    q("UPDATE usuarios SET ultimo_login=NOW() WHERE id=%s", (u["id"],))
    q("""INSERT INTO auditoria (usuario_id,contabilidade_id,acao,ip)
         VALUES (%s,%s,'login',%s)""",
      (u["id"], u["contabilidade_id"], request.client.host if request.client else None))
    return {"token": auth.cria_token(u),
            "usuario": {"id": u["id"], "nome": u["nome"], "email": u["email"],
                        "perfil": u["perfil"], "contabilidade_id": u["contabilidade_id"]}}

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

@app.get("/empresa")
def empresa_home():
    return FileResponse(BASE / "static" / "paginas" / "empresa" / "home.html")

@app.get("/")
def raiz():
    idx = BASE / "static" / "login.html"
    return FileResponse(idx) if idx.exists() else JSONResponse({"nfcheck": "no ar"})
