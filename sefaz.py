"""Distribuicao DFe da SEFAZ (NF-e e CT-e), multi-tenant.
Licoes herdadas do Orbita LOG: fuso explicito, cursor so avanca sobre o que foi
gravado, parser agnostico de namespace, distincao entre 'aguardar' e 'halt'."""
import os, gzip, base64, tempfile, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from lxml import etree
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption
from db import q, DIR_XML
import certificados

BRT = timezone(timedelta(hours=-3))

WS = {
  "sefaz_nfe": {
    "url": {"1": "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
            "2": "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"},
    "wsdl": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe",
    "ns": "http://www.portalfiscal.inf.br/nfe",
    "op": "nfeDistDFeInteresse",
  },
  "sefaz_cte": {
    "url": {"1": "https://www1.cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx",
            "2": "https://hom1.cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx"},
    "wsdl": "http://www.portalfiscal.inf.br/cte/wsdl/CTeDistribuicaoDFe",
    "ns": "http://www.portalfiscal.inf.br/cte",
    "op": "cteDistDFeInteresse",
  },
}

UF_COD = {"AC":12,"AL":27,"AP":16,"AM":13,"BA":29,"CE":23,"DF":53,"ES":32,"GO":52,
          "MA":21,"MT":51,"MS":50,"MG":31,"PA":15,"PB":25,"PR":41,"PE":26,"PI":22,
          "RJ":33,"RN":24,"RS":43,"RO":11,"RR":14,"SC":42,"SP":35,"SE":28,"TO":17}


def agora_brt():
    return datetime.now(timezone.utc).astimezone(BRT)


def _tag(el):
    """Nome da tag sem namespace."""
    return etree.QName(el).localname


def _busca(raiz, nome):
    for el in raiz.iter():
        if _tag(el) == nome:
            return el
    return None


def _txt(raiz, nome, padrao=None):
    el = _busca(raiz, nome)
    return el.text if el is not None and el.text else padrao


class CertTemp:
    """Extrai o .pfx para PEM temporario; apaga ao sair do contexto."""
    def __init__(self, empresa_id):
        self.empresa_id = empresa_id
        self.cert = self.chave = None

    def __enter__(self):
        pfx, senha = certificados.carrega(self.empresa_id)
        k, c, _ = pkcs12.load_key_and_certificates(pfx, senha.encode())
        fc = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        fc.write(c.public_bytes(Encoding.PEM)); fc.close()
        fk = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        fk.write(k.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())); fk.close()
        os.chmod(fc.name, 0o600); os.chmod(fk.name, 0o600)
        self.cert, self.chave = fc.name, fk.name
        return (self.cert, self.chave)

    def __exit__(self, *a):
        for f in (self.cert, self.chave):
            try:
                if f: os.unlink(f)
            except OSError:
                pass


def _envelope(origem, ambiente, cuf, cnpj, ult_nsu):
    w = WS[origem]
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">
 <soap12:Body>
  <{w['op']} xmlns="{w['wsdl']}">
   <nfeDadosMsg>
    <distDFeInt xmlns="{w['ns']}" versao="1.01">
     <tpAmb>{ambiente}</tpAmb>
     <cUFAutor>{cuf}</cUFAutor>
     <CNPJ>{cnpj}</CNPJ>
     <distNSU><ultNSU>{str(ult_nsu).zfill(15)}</ultNSU></distNSU>
    </distDFeInt>
   </nfeDadosMsg>
  </{w['op']}>
 </soap12:Body>
</soap12:Envelope>"""


def _extrai_doc(xml_bytes, nsu, empresa_id, origem):
    """Le um docZip descompactado e devolve os campos do documento."""
    raiz = etree.fromstring(xml_bytes)
    tipo = _tag(raiz)

    d = {"empresa_id": empresa_id, "nsu": nsu, "origem": origem,
         "tipo": tipo, "schema_xml": tipo, "resumo": tipo.startswith("resNFe")
         or tipo.startswith("resCTe") or tipo.startswith("resEvento")}

    d["chave"] = _txt(raiz, "chNFe") or _txt(raiz, "chCTe")
    if not d["chave"]:
        inf = _busca(raiz, "infNFe") or _busca(raiz, "infCte") or _busca(raiz, "infCTe")
        if inf is not None:
            cid = inf.get("Id") or ""
            d["chave"] = cid[3:] if len(cid) > 3 else None

    emit = _busca(raiz, "emit")
    if emit is not None:
        d["emitente_cnpj"] = _txt(emit, "CNPJ") or _txt(emit, "CPF")
        d["emitente_nome"] = _txt(emit, "xNome")
    else:
        d["emitente_cnpj"] = _txt(raiz, "CNPJ")
        d["emitente_nome"] = _txt(raiz, "xNome")

    dest = _busca(raiz, "dest")
    d["destinatario_cnpj"] = _txt(dest, "CNPJ") if dest is not None else None

    ide = _busca(raiz, "ide")
    if ide is not None:
        d["numero"] = _txt(ide, "nNF") or _txt(ide, "nCT")
        d["serie"] = _txt(ide, "serie")
        d["emissao"] = _txt(ide, "dhEmi") or _txt(ide, "dEmi")
    else:
        d["numero"] = d["serie"] = None
        d["emissao"] = _txt(raiz, "dhEmi")

    v = (_txt(raiz, "vNF") or _txt(raiz, "vTPrest") or _txt(raiz, "vRec"))
    try:
        d["valor"] = float(v) if v else None
    except ValueError:
        d["valor"] = None

    d["situacao"] = _txt(raiz, "cSitNFe") or _txt(raiz, "cSitCTe")
    return d


def _grava(d, xml_bytes):
    pasta = Path(DIR_XML) / str(d["empresa_id"]) / (d["emissao"] or "")[:7]
    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"{d['chave'] or ('nsu' + str(d['nsu']))}_{d['tipo']}.xml"
    caminho = pasta / nome
    caminho.write_bytes(xml_bytes)

    q("""INSERT INTO documentos
      (empresa_id,chave,nsu,origem,tipo,schema_xml,emitente_cnpj,emitente_nome,
       destinatario_cnpj,numero,serie,emissao,valor,situacao,resumo,xml_path)
      VALUES (%(empresa_id)s,%(chave)s,%(nsu)s,%(origem)s,%(tipo)s,%(schema_xml)s,
              %(emitente_cnpj)s,%(emitente_nome)s,%(destinatario_cnpj)s,%(numero)s,
              %(serie)s,%(emissao)s,%(valor)s,%(situacao)s,%(resumo)s,%(xml_path)s)
      ON CONFLICT (empresa_id,chave,tipo) DO NOTHING""",
      {**d, "xml_path": str(caminho)})


def sincronizar(empresa_id, origem, ambiente="1"):
    """Um ciclo. Retorna dict com cstat, novos, ultimo_nsu, caught_up, aguardar, halt."""
    ini = time.monotonic()
    emp = q("SELECT cnpj, uf FROM empresas WHERE id=%s", (empresa_id,), one=True)
    cur = q("""SELECT ultimo_nsu, ultima_vazia, pausado, pausado_motivo
               FROM cursores_dfe WHERE empresa_id=%s AND origem=%s""",
            (empresa_id, origem), one=True)
    if not cur:
        return {"halt": True, "mensagem": "cursor inexistente"}
    if cur["pausado"]:
        return {"halt": True, "mensagem": f"pausado: {cur['pausado_motivo']}"}

    # trava de 1h apos consulta vazia: evita cStat 656 (consumo indevido)
    if cur["ultima_vazia"]:
        falta = timedelta(hours=1) - (datetime.now(timezone.utc) - cur["ultima_vazia"])
        if falta.total_seconds() > 0:
            return {"aguardar": True, "faltam_seg": int(falta.total_seconds())}

    nsu = cur["ultimo_nsu"] or 0
    cuf = UF_COD.get((emp["uf"] or "SP").upper(), 35)
    corpo = _envelope(origem, ambiente, cuf, emp["cnpj"], nsu)

    with CertTemp(empresa_id) as (c, k):
        try:
            r = requests.post(WS[origem]["url"][ambiente], data=corpo.encode("utf-8"),
                              headers={"Content-Type": "application/soap+xml; charset=utf-8"},
                              cert=(c, k), timeout=60)
            r.raise_for_status()
        except Exception as e:
            q("""UPDATE cursores_dfe SET status='erro', erro_msg=%s WHERE empresa_id=%s
                 AND origem=%s""", (str(e)[:400], empresa_id, origem))
            return {"halt": True, "mensagem": str(e)[:200]}

    raiz = etree.fromstring(r.content)
    cstat = _txt(raiz, "cStat", "")
    motivo = _txt(raiz, "xMotivo", "")
    ult = _txt(raiz, "ultNSU")
    mx = _txt(raiz, "maxNSU")

    if cstat == "656":
        q("""UPDATE cursores_dfe SET pausado=TRUE, pausado_motivo=%s, ultimo_cstat=%s
             WHERE empresa_id=%s AND origem=%s""",
          ("Consumo indevido. Aguarde 1 hora.", cstat, empresa_id, origem))
        return {"halt": True, "cstat": cstat, "mensagem": motivo}

    novos = 0
    maior_gravado = nsu
    for doc in raiz.iter():
        if _tag(doc) != "docZip":
            continue
        nsu_doc = int(doc.get("NSU") or 0)
        try:
            xml = gzip.decompress(base64.b64decode(doc.text))
            d = _extrai_doc(xml, nsu_doc, empresa_id, origem)
            _grava(d, xml)
            novos += 1
            # cursor so avanca sobre o que foi efetivamente gravado
            maior_gravado = max(maior_gravado, nsu_doc)
        except Exception as e:
            q("""INSERT INTO sync_log (empresa_id,origem,cstat,motivo,nsu_inicial,novos)
                 VALUES (%s,%s,'ERRO',%s,%s,0)""",
              (empresa_id, origem, f"NSU {nsu_doc}: {str(e)[:200]}", nsu_doc))
            break

    novo_nsu = maior_gravado if novos else (int(ult) if ult else nsu)
    caught_up = bool(mx and ult and int(ult) >= int(mx))

    q("""UPDATE cursores_dfe SET ultimo_nsu=%s, max_nsu=%s, ultimo_cstat=%s,
           caught_up=%s, ultima_sync=NOW(), status='ok', erro_msg=NULL,
           ultima_vazia = CASE WHEN %s=0 THEN NOW() ELSE ultima_vazia END,
           ultima_com_resultado = CASE WHEN %s>0 THEN NOW() ELSE ultima_com_resultado END
         WHERE empresa_id=%s AND origem=%s""",
      (novo_nsu, int(mx) if mx else None, cstat, caught_up, novos, novos,
       empresa_id, origem))

    q("""INSERT INTO sync_log (empresa_id,origem,cstat,motivo,nsu_inicial,nsu_final,
                               novos,duracao_ms)
         VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
      (empresa_id, origem, cstat, motivo[:300], nsu, novo_nsu, novos,
       int((time.monotonic() - ini) * 1000)))

    return {"cstat": cstat, "motivo": motivo, "novos": novos,
            "ultimo_nsu": novo_nsu, "max_nsu": mx, "caught_up": caught_up}
