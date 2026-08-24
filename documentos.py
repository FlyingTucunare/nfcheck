"""Consulta dos documentos fiscais recebidos."""
import io, zipfile
from typing import Optional
from pydantic import BaseModel
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from lxml import etree
from db import q
import auth
import sefaz

router = APIRouter(prefix="/api/documentos", tags=["documentos"])

ROTULO = {
    "nfeProc":"NF-e", "NFe":"NF-e", "resNFe":"NF-e (resumo)",
    "cteProc":"CT-e", "CTe":"CT-e", "resCTe":"CT-e (resumo)",
    "procEventoNFe":"Evento", "resEvento":"Evento", "procEventoCTe":"Evento",
    "nfseProc":"NFS-e",
}

@router.get("")
def listar(empresa_id: int, de: Optional[str] = None, ate: Optional[str] = None,
           tipo: Optional[str] = None, situacao: Optional[str] = None,
           busca: Optional[str] = None, limite: int = 500,
           u=Depends(auth.usuario_atual)):
    auth.exige_empresa(u, empresa_id)
    cond = ["d.empresa_id = %(emp)s"]
    p = {"emp": empresa_id, "lim": min(limite, 3000)}

    if de:  cond.append("d.emissao >= %(de)s");  p["de"] = de
    if ate: cond.append("d.emissao < (%(ate)s::date + 1)"); p["ate"] = ate
    if tipo == "nfe": cond.append("d.tipo LIKE '%%NFe%%' OR d.tipo LIKE 'nfe%%'")
    elif tipo == "cte": cond.append("d.tipo LIKE '%%CTe%%' OR d.tipo LIKE 'cte%%'")
    elif tipo == "evento": cond.append("d.tipo LIKE '%%Evento%%'")
    if situacao == "pendente":
        cond.append("d.manifestacao IS NULL AND NOT d.resumo")
    elif situacao == "manifestado":
        cond.append("d.manifestacao IS NOT NULL")
    elif situacao == "resumo":
        cond.append("d.resumo")
    if busca:
        cond.append("""(d.emitente_nome ILIKE %(b)s OR d.chave LIKE %(b2)s
                        OR d.numero = %(bn)s OR d.emitente_cnpj LIKE %(b2)s)""")
        p["b"] = f"%{busca}%"
        p["b2"] = f"%{''.join(ch for ch in busca if ch.isdigit())}%"
        p["bn"] = "".join(ch for ch in busca if ch.isdigit()) or "-"

    onde = " AND ".join(f"({c})" for c in cond)
    itens = q(f"""SELECT d.id,d.chave,d.tipo,d.numero,d.serie,d.emissao,d.valor,
                         d.emitente_nome,d.emitente_cnpj,d.manifestacao,
                         d.manifestacao_em,d.resumo,d.situacao,d.papel,d.origem,
                         (d.xml_path IS NOT NULL) AS tem_xml,
                         (d.pdf_path IS NOT NULL) AS tem_pdf
                    FROM documentos d WHERE {onde}
                   ORDER BY d.emissao DESC NULLS LAST, d.id DESC
                   LIMIT %(lim)s""", p)
    tot = q(f"""SELECT COUNT(*) AS n, COALESCE(SUM(d.valor),0) AS soma,
                       COUNT(*) FILTER (WHERE d.manifestacao IS NULL
                                          AND NOT d.resumo) AS pendentes,
                       COUNT(*) FILTER (WHERE d.resumo) AS resumos
                  FROM documentos d WHERE {onde}""", p, one=True)
    for i in itens:
        i["tipo_rotulo"] = ROTULO.get(i["tipo"], i["tipo"])
    return {"itens": itens, "totais": tot, "truncado": len(itens) >= p["lim"]}


@router.get("/{doc_id}")
def detalhe(doc_id: int, u=Depends(auth.usuario_atual)):
    d = q("SELECT * FROM documentos WHERE id=%s", (doc_id,), one=True)
    if not d:
        raise HTTPException(404, "Documento nao encontrado")
    auth.exige_empresa(u, d["empresa_id"])
    d["tipo_rotulo"] = ROTULO.get(d["tipo"], d["tipo"])
    d["manifestacoes"] = q("""SELECT evento,automatica,cstat,motivo,criado_em
                              FROM manifestacoes WHERE chave=%s
                              ORDER BY criado_em DESC""", (d["chave"],))
    return d


@router.get("/{doc_id}/xml")
def baixar_xml(doc_id: int, u=Depends(auth.exige("baixar"))):
    d = q("SELECT empresa_id,chave,tipo,xml_path FROM documentos WHERE id=%s",
          (doc_id,), one=True)
    if not d:
        raise HTTPException(404, "Documento nao encontrado")
    auth.exige_empresa(u, d["empresa_id"])
    if not d["xml_path"] or not Path(d["xml_path"]).exists():
        raise HTTPException(404, "XML indisponivel para este documento.")
    return FileResponse(d["xml_path"], media_type="application/xml",
                        filename=f"{d['chave'] or d['id']}.xml")


@router.get("/{doc_id}/pdf")
def baixar_pdf(doc_id: int, u=Depends(auth.exige("baixar"))):
    d = q("SELECT empresa_id,chave,pdf_path FROM documentos WHERE id=%s",
          (doc_id,), one=True)
    if not d:
        raise HTTPException(404, "Documento nao encontrado")
    auth.exige_empresa(u, d["empresa_id"])
    if not d["pdf_path"] or not Path(d["pdf_path"]).exists():
        raise HTTPException(404, "PDF indisponivel para este documento.")
    return FileResponse(d["pdf_path"], media_type="application/pdf",
                        filename=f"{d['chave']}.pdf")


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


@router.get("/{doc_id}/danfe")
def gerar_danfe(doc_id: int, u=Depends(auth.exige("baixar"))):
    """Gera o documento auxiliar sob demanda. Nada e guardado em disco."""
    d = q("SELECT empresa_id,chave,tipo,numero,xml_path FROM documentos WHERE id=%s",
          (doc_id,), one=True)
    if not d:
        raise HTTPException(404, "Documento nao encontrado")
    auth.exige_empresa(u, d["empresa_id"])
    if not d["xml_path"] or not Path(d["xml_path"]).exists():
        raise HTTPException(404, "XML indisponivel para este documento.")

    tipo = (d["tipo"] or "").lower()
    if "res" in tipo or "evento" in tipo:
        raise HTTPException(400,
            "Este documento e apenas um resumo. O auxiliar exige o XML completo, "
            "que so fica disponivel apos a manifestacao.")

    xml = Path(d["xml_path"]).read_text(encoding="utf-8")
    try:
        if "cte" in tipo:
            from brazilfiscalreport.dacte import Dacte
            doc, sigla = Dacte(xml=xml), "DACTE"
        else:
            from brazilfiscalreport.danfe import Danfe
            doc, sigla = Danfe(xml=xml), "DANFE"
        buf = io.BytesIO()
        doc.output(buf)
        pdf = buf.getvalue()
    except Exception as e:
        raise HTTPException(500,
            f"Nao foi possivel gerar o documento auxiliar: {str(e)[:150]}")

    nome = f"{sigla}_{d['numero'] or d['chave'] or d['id']}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{nome}"'})


@router.get("/{doc_id}/conteudo")
def conteudo(doc_id: int, u=Depends(auth.usuario_atual)):
    """Le o XML e devolve itens, impostos, transporte e cobranca."""
    d = q("SELECT empresa_id,tipo,xml_path FROM documentos WHERE id=%s",
          (doc_id,), one=True)
    if not d:
        raise HTTPException(404, "Documento nao encontrado")
    auth.exige_empresa(u, d["empresa_id"])
    if not d["xml_path"] or not Path(d["xml_path"]).exists():
        return {"disponivel": False}

    raiz = etree.fromstring(Path(d["xml_path"]).read_bytes())
    t = sefaz._txt

    def bloco(nome):
        b = sefaz._busca(raiz, nome)
        if b is None:
            return None
        ender = sefaz._busca(b, "enderEmit") or sefaz._busca(b, "enderDest")
        return {
            "nome": t(b, "xNome"), "fantasia": t(b, "xFant"),
            "cnpj": t(b, "CNPJ") or t(b, "CPF"),
            "ie": t(b, "IE"),
            "endereco": ", ".join(x for x in [
                t(ender, "xLgr") if ender is not None else None,
                t(ender, "nro") if ender is not None else None,
                t(ender, "xBairro") if ender is not None else None] if x),
            "municipio": t(ender, "xMun") if ender is not None else None,
            "uf": t(ender, "UF") if ender is not None else None,
            "cep": t(ender, "CEP") if ender is not None else None,
            "fone": t(ender, "fone") if ender is not None else None,
        }

    itens = []
    for det in raiz.iter():
        if sefaz._tag(det) != "det":
            continue
        prod = sefaz._busca(det, "prod")
        imp = sefaz._busca(det, "imposto")
        if prod is None:
            continue
        icms = sefaz._busca(imp, "ICMS") if imp is not None else None
        itens.append({
            "n": det.get("nItem"), "codigo": t(prod, "cProd"),
            "descricao": t(prod, "xProd"), "ncm": t(prod, "NCM"),
            "cfop": t(prod, "CFOP"), "unidade": t(prod, "uCom"),
            "quantidade": _num(t(prod, "qCom")),
            "unitario": _num(t(prod, "vUnCom")),
            "total": _num(t(prod, "vProd")),
            "cst": t(icms, "CST") or t(icms, "CSOSN") if icms is not None else None,
            "base_icms": _num(t(icms, "vBC")) if icms is not None else None,
            "aliq_icms": _num(t(icms, "pICMS")) if icms is not None else None,
            "valor_icms": _num(t(icms, "vICMS")) if icms is not None else None,
        })

    tot = sefaz._busca(raiz, "ICMSTot")
    totais = {k: _num(t(tot, k)) for k in
              ("vBC","vICMS","vICMSDeson","vBCST","vST","vProd","vFrete","vSeg",
               "vDesc","vIPI","vPIS","vCOFINS","vOutro","vNF")} if tot is not None else {}

    transp = sefaz._busca(raiz, "transp")
    volumes = []
    if transp is not None:
        for v in transp.iter():
            if sefaz._tag(v) == "vol":
                volumes.append({"qtd": t(v, "qVol"), "especie": t(v, "esp"),
                                "marca": t(v, "marca"),
                                "peso_liquido": _num(t(v, "pesoL")),
                                "peso_bruto": _num(t(v, "pesoB"))})
    transportadora = None
    tb = sefaz._busca(raiz, "transporta") if transp is not None else None
    if tb is not None:
        transportadora = {"nome": t(tb, "xNome"), "cnpj": t(tb, "CNPJ") or t(tb, "CPF"),
                          "ie": t(tb, "IE"), "municipio": t(tb, "xMunicipio"),
                          "uf": t(tb, "UF")}

    dups = []
    for dp in raiz.iter():
        if sefaz._tag(dp) == "dup":
            dups.append({"numero": t(dp, "nDup"), "vencimento": t(dp, "dVenc"),
                         "valor": _num(t(dp, "vDup"))})

    ide = sefaz._busca(raiz, "ide")
    prot = sefaz._busca(raiz, "infProt")
    return {
        "disponivel": True,
        "emitente": bloco("emit"), "destinatario": bloco("dest"),
        "itens": itens, "totais": totais, "volumes": volumes,
        "transportadora": transportadora, "duplicatas": dups,
        "natureza": t(ide, "natOp") if ide is not None else None,
        "modalidade_frete": t(transp, "modFrete") if transp is not None else None,
        "informacoes": t(raiz, "infCpl"),
        "protocolo": t(prot, "nProt") if prot is not None else None,
        "protocolo_data": t(prot, "dhRecbto") if prot is not None else None,
        "status": t(prot, "xMotivo") if prot is not None else None,
    }


class Lote(BaseModel):
    ids: list[int]
    formato: str = "xml"

@router.post("/lote")
def exportar_lote(dados: Lote, u=Depends(auth.exige("baixar"))):
    """Compacta XML ou documentos auxiliares dos IDs escolhidos."""
    if not dados.ids:
        raise HTTPException(400, "Nenhum documento selecionado.")
    if len(dados.ids) > 2000:
        raise HTTPException(400, "Selecione no maximo 2000 documentos por vez.")
    if dados.formato not in ("xml", "pdf"):
        raise HTTPException(400, "Formato invalido.")

    docs = q("""SELECT id,empresa_id,chave,tipo,numero,serie,emissao,xml_path,resumo
                  FROM documentos WHERE id = ANY(%s)""", (dados.ids,))
    if not docs:
        raise HTTPException(404, "Documentos nao encontrados.")

    permitidas = {e["id"] for e in auth.empresas_visiveis(u)}
    if any(d["empresa_id"] not in permitidas for d in docs):
        raise HTTPException(403, "Ha documentos fora do seu escopo.")

    # Mesma chave pode ter linha de resumo e linha completa; mantem so a completa.
    por_chave = {}
    for d in docs:
        chave = d["chave"] or f"__sem_chave_{d['id']}"
        atual = por_chave.get(chave)
        if atual is None or (atual["resumo"] and not d["resumo"]):
            por_chave[chave] = d
    docs = list(por_chave.values())

    buf = io.BytesIO()
    incluidos = falhas = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for d in docs:
            if not d["xml_path"] or not Path(d["xml_path"]).exists():
                falhas += 1
                continue
            mes = (d["emissao"].strftime("%Y-%m") if d["emissao"] else "sem-data")
            base = d["chave"] or f"doc{d['id']}"
            try:
                if dados.formato == "xml":
                    z.write(d["xml_path"], f"{mes}/{base}.xml")
                else:
                    if d["resumo"] or "res" in (d["tipo"] or "").lower():
                        falhas += 1
                        continue
                    xml = Path(d["xml_path"]).read_text(encoding="utf-8")
                    tipo = (d["tipo"] or "").lower()
                    if "cte" in tipo:
                        from brazilfiscalreport.dacte import Dacte
                        aux = Dacte(xml=xml)
                    else:
                        from brazilfiscalreport.danfe import Danfe
                        aux = Danfe(xml=xml)
                    p = io.BytesIO()
                    aux.output(p)
                    z.writestr(f"{mes}/{base}.pdf", p.getvalue())
                incluidos += 1
            except Exception:
                falhas += 1

    if not incluidos:
        raise HTTPException(400,
            "Nenhum documento pode ser exportado neste formato. "
            "Resumos nao geram documento auxiliar.")

    nome = f"nfcheck_{dados.formato}_{incluidos}docs.zip"
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"',
                             "X-Incluidos": str(incluidos), "X-Falhas": str(falhas)})


class Manifestar(BaseModel):
    ids: list[int]
    evento: str
    justificativa: Optional[str] = None
    senha: Optional[str] = None

@router.post("/manifestar")
def manifestar(dados: Manifestar, request: Request,
               u=Depends(auth.exige("manifestar"))):
    """Envia eventos a SEFAZ. Confirmacao em lote exige a senha do usuario."""
    import manifestacao as mf
    if dados.evento not in mf.EVENTOS:
        raise HTTPException(400, "Evento invalido.")
    if not dados.ids:
        raise HTTPException(400, "Nenhum documento selecionado.")
    if len(dados.ids) > 1 and dados.evento not in ("210210", "210200"):
        raise HTTPException(400,
            "Apenas ciencia e confirmacao podem ser enviadas em lote.")
    if len(dados.ids) > 1 and dados.evento == "210200":
        if not dados.senha:
            raise HTTPException(400, "Confirme sua senha para manifestar em lote.")
        row = q("SELECT senha_hash FROM usuarios WHERE id=%s", (u["id"],), one=True)
        if not auth.confere(dados.senha, row["senha_hash"]):
            raise HTTPException(403, "Senha incorreta.")

    docs = q("""SELECT id,empresa_id,chave,numero,resumo FROM documentos
                WHERE id = ANY(%s)""", (dados.ids,))
    permitidas = {e["id"] for e in auth.empresas_visiveis(u)}
    if any(d["empresa_id"] not in permitidas for d in docs):
        raise HTTPException(403, "Ha documentos fora do seu escopo.")

    res = []
    for d in docs:
        if not d["chave"]:
            res.append({"id": d["id"], "ok": False, "motivo": "Documento sem chave"})
            continue
        r = mf.enviar(d["empresa_id"], d["chave"], dados.evento, u["id"],
                      justificativa=dados.justificativa)
        res.append({"id": d["id"], "numero": d["numero"], **r})

    ok = sum(1 for x in res if x.get("ok"))
    import json
    q("""INSERT INTO auditoria (usuario_id,contabilidade_id,acao,detalhe,ip)
         VALUES (%s,%s,'manifestacao',%s,%s)""",
      (u["id"], u["contabilidade_id"],
       json.dumps({"evento": dados.evento, "total": len(docs), "ok": ok}),
       request.client.host if request.client else None))
    return {"total": len(docs), "ok": ok, "resultados": res}


@router.get("/resumo/emitentes")
def por_emitente(empresa_id: int, de: Optional[str] = None,
                 ate: Optional[str] = None, u=Depends(auth.usuario_atual)):
    auth.exige_empresa(u, empresa_id)
    cond = ["empresa_id = %(emp)s"]
    p = {"emp": empresa_id}
    if de:  cond.append("emissao >= %(de)s");  p["de"] = de
    if ate: cond.append("emissao < (%(ate)s::date + 1)"); p["ate"] = ate
    return q(f"""SELECT emitente_cnpj, emitente_nome, COUNT(*) AS docs,
                        COALESCE(SUM(valor),0) AS total
                   FROM documentos WHERE {" AND ".join(cond)}
                    AND emitente_nome IS NOT NULL
                  GROUP BY 1,2 ORDER BY total DESC LIMIT 50""", p)
