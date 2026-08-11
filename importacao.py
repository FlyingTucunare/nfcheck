"""Importacao em lote de XML e PDF.
A empresa e detectada pelo proprio XML (emitente ou destinatario) e conferida
contra o escopo do usuario. PDF entra apenas como anexo de um XML existente."""
import io, os, re, time, zipfile, json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from lxml import etree
from db import q, DIR_XML
import auth
import sefaz

router = APIRouter(prefix="/api/importacao", tags=["importacao"])

TAM_MAX = 200 * 1024 * 1024
ARQ_MAX = 20000


def _limpa(v):
    return re.sub(r"\D", "", v or "")


def _percorre(nome, dados):
    """Gera (nome, bytes) para cada arquivo util, entrando em ZIP aninhado."""
    baixo = nome.lower()
    if baixo.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(dados)) as z:
                for it in z.infolist():
                    if it.is_dir() or it.file_size > 12 * 1024 * 1024:
                        continue
                    interno = it.filename
                    if interno.startswith("__MACOSX") or "/." in interno:
                        continue
                    yield from _percorre(interno, z.read(it))
        except zipfile.BadZipFile:
            yield (nome, None)
    elif baixo.endswith((".xml", ".pdf")):
        yield (nome, dados)


def _chave_do_pdf(nome):
    """Extrai a chave de 44 digitos do nome do arquivo PDF."""
    m = re.search(r"(\d{44})", nome or "")
    return m.group(1) if m else None


def _empresa_do_xml(raiz, mapa):
    """Descobre a qual empresa o documento pertence e em que papel."""
    emit = sefaz._busca(raiz, "emit")
    dest = sefaz._busca(raiz, "dest")
    rem  = sefaz._busca(raiz, "rem")
    toma = sefaz._busca(raiz, "toma3") or sefaz._busca(raiz, "toma4")

    cand = []
    for bloco, papel in ((dest, "destinatario"), (toma, "tomador"),
                         (rem, "remetente"), (emit, "emitente")):
        if bloco is None:
            continue
        c = _limpa(sefaz._txt(bloco, "CNPJ") or sefaz._txt(bloco, "CPF"))
        if c:
            cand.append((c, papel))

    for tag, papel in (("CNPJDest", "destinatario"), ("CNPJ", "emitente")):
        c = _limpa(sefaz._txt(raiz, tag))
        if c:
            cand.append((c, papel))

    for c, papel in cand:
        if c in mapa:
            return mapa[c], papel, c
    return None, None, (cand[0][0] if cand else None)


@router.post("")
async def importar(request: Request, arquivo: UploadFile = File(...),
                   u=Depends(auth.exige("importar"))):
    ini = time.monotonic()
    bruto = await arquivo.read()
    if not bruto:
        raise HTTPException(400, "Arquivo vazio.")
    if len(bruto) > TAM_MAX:
        raise HTTPException(400, "Arquivo acima de 200 MB.")

    escopo = auth.empresas_visiveis(u)
    ids = [e["id"] for e in escopo]
    if not ids:
        raise HTTPException(400, "Nenhuma empresa no seu escopo.")
    mapa = {r["cnpj"]: r["id"] for r in
            q("SELECT id,cnpj FROM empresas WHERE id = ANY(%s)", (ids,))}

    imp = q("""INSERT INTO importacoes (contabilidade_id,usuario_id,arquivo_nome,
                 arquivo_tamanho) VALUES (%s,%s,%s,%s) RETURNING id""",
            (u["contabilidade_id"], u["id"], arquivo.filename, len(bruto)), one=True)
    imp_id = imp["id"]

    total = gravados = duplicados = ignorados = erros = anexos = 0
    fora = {}
    falhas = []
    pdfs = []

    for nome, dados in _percorre(arquivo.filename or "upload", bruto):
        total += 1
        if total > ARQ_MAX:
            falhas.append({"arquivo": nome, "erro": "limite de arquivos atingido"})
            break
        if dados is None:
            erros += 1
            falhas.append({"arquivo": nome, "erro": "arquivo corrompido"})
            continue

        if nome.lower().endswith(".pdf"):
            pdfs.append((nome, dados))
            continue

        try:
            raiz = etree.fromstring(dados)
        except Exception:
            erros += 1
            falhas.append({"arquivo": nome, "erro": "XML invalido"})
            continue

        emp_id, papel, cnpj = _empresa_do_xml(raiz, mapa)
        if not emp_id:
            ignorados += 1
            if cnpj:
                fora[cnpj] = fora.get(cnpj, 0) + 1
            continue

        try:
            d = sefaz._extrai_doc(dados, None, emp_id, "importacao")
            d["papel"] = papel
            ja = q("""SELECT id FROM documentos
                      WHERE empresa_id=%s AND chave=%s AND tipo=%s""",
                   (emp_id, d["chave"], d["tipo"]), one=True)
            if ja:
                duplicados += 1
                continue
            sefaz._grava(d, dados)
            q("""UPDATE documentos SET importacao_id=%s, papel=%s
                 WHERE empresa_id=%s AND chave=%s AND tipo=%s""",
              (imp_id, papel, emp_id, d["chave"], d["tipo"]))
            gravados += 1
        except Exception as e:
            erros += 1
            falhas.append({"arquivo": nome, "erro": str(e)[:160]})

    for nome, dados in pdfs:
        chave = _chave_do_pdf(nome)
        if not chave:
            ignorados += 1
            falhas.append({"arquivo": nome,
                           "erro": "PDF sem chave de 44 digitos no nome"})
            continue
        doc = q("""SELECT id,empresa_id,emissao FROM documentos
                   WHERE chave=%s AND empresa_id = ANY(%s) LIMIT 1""",
                (chave, ids), one=True)
        if not doc:
            ignorados += 1
            fora[chave[6:20]] = fora.get(chave[6:20], 0) + 1
            continue
        pasta = Path(DIR_XML) / str(doc["empresa_id"]) / "pdf"
        pasta.mkdir(parents=True, exist_ok=True)
        caminho = pasta / f"{chave}.pdf"
        caminho.write_bytes(dados)
        q("UPDATE documentos SET pdf_path=%s WHERE id=%s", (str(caminho), doc["id"]))
        anexos += 1

    detalhe = {"fora_do_escopo": fora, "falhas": falhas[:80]}
    q("""UPDATE importacoes SET total=%s,gravados=%s,duplicados=%s,ignorados=%s,
         erros=%s,anexos=%s,detalhe=%s,duracao_ms=%s WHERE id=%s""",
      (total, gravados, duplicados, ignorados, erros, anexos,
       json.dumps(detalhe), int((time.monotonic() - ini) * 1000), imp_id))

    q("""INSERT INTO auditoria (usuario_id,contabilidade_id,acao,detalhe,ip)
         VALUES (%s,%s,'importacao',%s,%s)""",
      (u["id"], u["contabilidade_id"],
       json.dumps({"arquivo": arquivo.filename, "gravados": gravados,
                   "total": total}),
       request.client.host if request.client else None))

    return {"id": imp_id, "total": total, "gravados": gravados,
            "duplicados": duplicados, "ignorados": ignorados, "erros": erros,
            "anexos": anexos, "fora_do_escopo": fora, "falhas": falhas[:30],
            "duracao_ms": int((time.monotonic() - ini) * 1000)}


@router.get("/historico")
def historico(u=Depends(auth.usuario_atual)):
    return q("""SELECT i.id,i.arquivo_nome,i.arquivo_tamanho,i.total,i.gravados,
                       i.duplicados,i.ignorados,i.erros,i.anexos,i.duracao_ms,
                       i.criado_em,us.nome AS usuario
                  FROM importacoes i LEFT JOIN usuarios us ON us.id=i.usuario_id
                 WHERE i.contabilidade_id=%s
                 ORDER BY i.id DESC LIMIT 50""", (u["contabilidade_id"],))


@router.get("/{imp_id}")
def detalhe_imp(imp_id: int, u=Depends(auth.usuario_atual)):
    i = q("""SELECT * FROM importacoes WHERE id=%s AND contabilidade_id=%s""",
          (imp_id, u["contabilidade_id"]), one=True)
    if not i:
        raise HTTPException(404, "Importacao nao encontrada")
    return i
