import os, re
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from cryptography.hazmat.primitives.serialization import pkcs12
from db import q, FERNET, DIR_CERTS
import auth

router = APIRouter(prefix="/api/certificados", tags=["certificados"])
TAM_MAX = 512 * 1024


def _cnpj_do_cert(cert):
    """CN vem como 'RAZAO SOCIAL:00000000000000'."""
    cn = ""
    for a in cert.subject:
        if a.oid.dotted_string == "2.5.4.3":
            cn = a.value
            break
    m = re.search(r"(\d{14})", cn or "")
    return (cn, m.group(1) if m else None)


def _le_pfx(conteudo, senha):
    try:
        chave, cert, _ = pkcs12.load_key_and_certificates(conteudo, senha.encode())
    except Exception:
        raise HTTPException(400, "Nao foi possivel abrir o certificado. Verifique a senha.")
    if cert is None:
        raise HTTPException(400, "Arquivo sem certificado valido.")
    cn, cnpj = _cnpj_do_cert(cert)
    return {
        "titular_cn": cn,
        "cnpj_titular": cnpj,
        "valido_de": cert.not_valid_before_utc,
        "valido_ate": cert.not_valid_after_utc,
    }


def _confere_cnpj(cnpj_cert, cnpj_empresa):
    """Bloqueia raiz diferente; avisa quando e filial do mesmo grupo."""
    if not cnpj_cert:
        return "O certificado nao informa CNPJ no titular. Confira antes de usar."
    if cnpj_cert == cnpj_empresa:
        return None
    if cnpj_cert[:8] == cnpj_empresa[:8]:
        return (f"O certificado e do CNPJ {cnpj_cert}, da mesma raiz da empresa. "
                "A consulta por CNPJ raiz permite isso, mas confirme que e o desejado.")
    raise HTTPException(
        400,
        f"O certificado pertence ao CNPJ {cnpj_cert}, de outro grupo economico. "
        f"A empresa selecionada e {cnpj_empresa}.")


@router.post("/analisar")
async def analisar(empresa_id: int = Form(...), senha: str = Form(...),
                   arquivo: UploadFile = File(...),
                   u=Depends(auth.exige("cert_escrever"))):
    """Le o .pfx e devolve os dados sem gravar nada."""
    auth.exige_empresa(u, empresa_id)
    conteudo = await arquivo.read()
    if len(conteudo) > TAM_MAX:
        raise HTTPException(400, "Arquivo muito grande para um certificado A1.")
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")

    d = _le_pfx(conteudo, senha)
    emp = q("SELECT cnpj, razao_social FROM empresas WHERE id=%s", (empresa_id,), one=True)
    aviso = _confere_cnpj(d["cnpj_titular"], emp["cnpj"])

    agora = datetime.now(timezone.utc)
    d["vencido"] = d["valido_ate"] < agora
    d["dias_restantes"] = (d["valido_ate"] - agora).days
    d["aviso"] = aviso
    d["empresa"] = emp["razao_social"]
    d["valido_de"] = d["valido_de"].isoformat()
    d["valido_ate"] = d["valido_ate"].isoformat()
    return d


@router.post("")
async def enviar(request: Request, empresa_id: int = Form(...), senha: str = Form(...),
                 arquivo: UploadFile = File(...),
                 u=Depends(auth.exige("cert_escrever"))):
    auth.exige_empresa(u, empresa_id)
    conteudo = await arquivo.read()
    if len(conteudo) > TAM_MAX or not conteudo:
        raise HTTPException(400, "Arquivo invalido.")

    d = _le_pfx(conteudo, senha)
    emp = q("SELECT cnpj FROM empresas WHERE id=%s", (empresa_id,), one=True)
    _confere_cnpj(d["cnpj_titular"], emp["cnpj"])

    if d["valido_ate"] < datetime.now(timezone.utc):
        raise HTTPException(400, "Este certificado ja esta vencido.")

    pasta = Path(DIR_CERTS) / str(empresa_id)
    pasta.mkdir(parents=True, exist_ok=True)
    os.chmod(pasta, 0o700)
    nome = f"cert_{datetime.now():%Y%m%d_%H%M%S}.pfx"
    destino = pasta / nome
    destino.write_bytes(conteudo)
    os.chmod(destino, 0o600)

    q("UPDATE certificados SET ativo=FALSE WHERE empresa_id=%s AND ativo", (empresa_id,))
    novo = q("""INSERT INTO certificados
        (empresa_id,arquivo_path,senha_enc,titular_cn,cnpj_titular,
         valido_de,valido_ate,ativo,enviado_por)
        VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE,%s)
        RETURNING id,titular_cn,valido_ate""",
      (empresa_id, str(destino), FERNET.encrypt(senha.encode()).decode(),
       d["titular_cn"], d["cnpj_titular"], d["valido_de"], d["valido_ate"], u["id"]), one=True)

    import json
    q("""INSERT INTO auditoria (usuario_id,contabilidade_id,empresa_id,acao,detalhe,ip)
         VALUES (%s,%s,%s,'certificado_enviado',%s,%s)""",
      (u["id"], u["contabilidade_id"], empresa_id,
       json.dumps({"cnpj_titular": d["cnpj_titular"],
                   "valido_ate": d["valido_ate"].isoformat()}),
       request.client.host if request.client else None))
    return novo


@router.get("/empresa/{empresa_id}")
def historico(empresa_id: int, u=Depends(auth.usuario_atual)):
    auth.exige_empresa(u, empresa_id)
    return q("""SELECT c.id,c.titular_cn,c.cnpj_titular,c.valido_de,c.valido_ate,
                       c.ativo,c.enviado_em,us.nome AS enviado_por
                FROM certificados c LEFT JOIN usuarios us ON us.id=c.enviado_por
                WHERE c.empresa_id=%s ORDER BY c.enviado_em DESC""", (empresa_id,))


def carrega(empresa_id):
    """Uso interno: devolve (bytes_pfx, senha) do certificado ativo."""
    c = q("""SELECT arquivo_path,senha_enc FROM certificados
             WHERE empresa_id=%s AND ativo""", (empresa_id,), one=True)
    if not c:
        raise HTTPException(400, "Empresa sem certificado ativo.")
    return Path(c["arquivo_path"]).read_bytes(), FERNET.decrypt(c["senha_enc"].encode()).decode()
