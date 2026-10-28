"""Emissao de NFS-e pelo Emissor Nacional (Sefin Nacional).
Fluxo: monta a DPS em XML, assina, compacta em GZip+Base64 e envia por POST.
O retorno sincrono ja traz a NFS-e gerada."""
import gzip, base64, json, tempfile, os
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from lxml import etree
import requests
import urllib3
from db import q
import certificados
import sefaz

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

NS = "http://www.sped.fazenda.gov.br/nfse"
BRT = timezone(timedelta(hours=-3))

BASE = {
    "1": "https://sefin.nfse.gov.br/SefinNacional",
    "2": "https://sefin.producaorestrita.nfse.gov.br/SefinNacional",
}
BASE_ADN = {
    "1": "https://adn.nfse.gov.br",
    "2": "https://adn.producaorestrita.nfse.gov.br",
}


def _d(v):
    """Formata numero no padrao do leiaute: ponto decimal, sem separador."""
    if v is None:
        return None
    return f"{Decimal(str(v)):.2f}"


def _url(ambiente, rota):
    return BASE[ambiente] + rota


def id_dps(municipio_ibge, cnpj, serie, numero):
    """Identificador da DPS: IBGE(7) + tipo(1) + inscricao(14) + serie(5) + num(15)."""
    return ("DPS" + str(municipio_ibge).zfill(7) + "2" +
            str(cnpj).zfill(14) + str(serie).zfill(5) + str(numero).zfill(15))


def montar_dps(dados):
    """Monta o XML da DPS a partir do dicionario de emissao."""
    agora = datetime.now(BRT).strftime("%Y-%m-%dT%H:%M:%S%z")
    agora = agora[:-2] + ":" + agora[-2:]
    ident = id_dps(dados["municipio_emissor"], dados["prestador_cnpj"],
                   dados["serie"], dados["numero"])

    raiz = etree.Element("DPS", xmlns=NS, versao="1.00")
    inf = etree.SubElement(raiz, "infDPS", Id=ident)

    etree.SubElement(inf, "tpAmb").text = dados["ambiente"]
    etree.SubElement(inf, "dhEmi").text = agora
    etree.SubElement(inf, "verAplic").text = "NFCheck1.0"
    etree.SubElement(inf, "serie").text = str(dados["serie"]).zfill(5)
    etree.SubElement(inf, "nDPS").text = str(dados["numero"])
    etree.SubElement(inf, "dCompet").text = dados["competencia"]
    etree.SubElement(inf, "tpEmit").text = "1"
    etree.SubElement(inf, "cLocEmi").text = str(dados["municipio_emissor"])

    # prestador
    prest = etree.SubElement(inf, "prest")
    etree.SubElement(prest, "CNPJ").text = dados["prestador_cnpj"]
    if dados.get("prestador_im"):
        etree.SubElement(prest, "IM").text = dados["prestador_im"]
    reg = etree.SubElement(prest, "regTrib")
    etree.SubElement(reg, "opSimpNac").text = dados.get("op_simples", "1")
    etree.SubElement(reg, "regEspTrib").text = dados.get("reg_especial", "0")

    # tomador
    tom = etree.SubElement(inf, "toma")
    if dados["tomador_tipo"] == "cnpj":
        etree.SubElement(tom, "CNPJ").text = dados["tomador_doc"]
    else:
        etree.SubElement(tom, "CPF").text = dados["tomador_doc"]
    etree.SubElement(tom, "xNome").text = dados["tomador_nome"]
    if dados.get("tomador_logradouro"):
        end = etree.SubElement(tom, "end")
        endnac = etree.SubElement(end, "endNac")
        etree.SubElement(endnac, "cMun").text = str(dados["tomador_ibge"])
        etree.SubElement(endnac, "CEP").text = dados["tomador_cep"]
        etree.SubElement(end, "xLgr").text = dados["tomador_logradouro"]
        etree.SubElement(end, "nro").text = dados.get("tomador_numero") or "S/N"
        if dados.get("tomador_complemento"):
            etree.SubElement(end, "xCpl").text = dados["tomador_complemento"]
        etree.SubElement(end, "xBairro").text = dados.get("tomador_bairro") or "Centro"
    if dados.get("tomador_email"):
        etree.SubElement(tom, "email").text = dados["tomador_email"]

    # servico
    serv = etree.SubElement(inf, "serv")
    loc = etree.SubElement(serv, "locPrest")
    etree.SubElement(loc, "cLocPrestacao").text = str(
        dados.get("municipio_incidencia") or dados["municipio_emissor"])
    cs = etree.SubElement(serv, "cServ")
    etree.SubElement(cs, "cTribNac").text = dados["codigo_tributacao"]
    etree.SubElement(cs, "xDescServ").text = dados["descricao"]
    if dados.get("cnae"):
        etree.SubElement(cs, "cNBS").text = dados["cnae"]

    # valores
    valores = etree.SubElement(inf, "valores")
    vserv = etree.SubElement(valores, "vServPrest")
    etree.SubElement(vserv, "vServ").text = _d(dados["valor_servico"])
    if dados.get("valor_desconto"):
        vdesc = etree.SubElement(valores, "vDescCondIncond")
        etree.SubElement(vdesc, "vDescIncond").text = _d(dados["valor_desconto"])

    trib = etree.SubElement(valores, "trib")
    tribmun = etree.SubElement(trib, "tribMun")
    etree.SubElement(tribmun, "tribISSQN").text = dados.get("trib_issqn", "1")
    if dados.get("aliquota_iss") is not None:
        etree.SubElement(tribmun, "pAliq").text = _d(dados["aliquota_iss"])
    etree.SubElement(tribmun, "tpRetISSQN").text = (
        "2" if dados.get("iss_retido") else "1")

    tot = etree.SubElement(trib, "totTrib")
    etree.SubElement(tot, "indTotTrib").text = "0"

    return etree.tostring(raiz, encoding="unicode")


def _com_declaracao(xml):
    """A SEFIN exige a declaracao XML explicita com encoding UTF-8."""
    if xml.lstrip().startswith("<?xml"):
        return xml
    return '<?xml version="1.0" encoding="UTF-8"?>' + xml


def assinar(empresa_id, xml_dps):
    """Assina a DPS com o certificado da empresa, no padrao da SEFIN."""
    from pynfe.processamento.assinatura import AssinaturaA1

    pfx, senha = certificados.carrega(empresa_id)
    arq = tempfile.NamedTemporaryFile(suffix=".pfx", delete=False)
    arq.write(pfx)
    arq.close()
    os.chmod(arq.name, 0o600)
    try:
        raiz = etree.fromstring(xml_dps.encode("utf-8"))
        assinado = AssinaturaA1(arq.name, senha).assinar(raiz)
        return _com_declaracao(etree.tostring(assinado, encoding="unicode"))
    finally:
        try:
            os.unlink(arq.name)
        except OSError:
            pass


def _compacta(xml):
    return base64.b64encode(
        gzip.compress(_com_declaracao(xml).encode("utf-8"))).decode()


def transmitir(empresa_id, xml_assinado, ambiente="2"):
    """Envia a DPS. Retorno sincrono traz a NFS-e ou os erros."""
    corpo = {"dpsXmlGZipB64": _compacta(xml_assinado)}
    with sefaz.CertTemp(empresa_id) as (c, k):
        r = requests.post(_url(ambiente, "/nfse"), json=corpo,
                          cert=(c, k), timeout=60, verify=False)
    try:
        d = r.json()
    except ValueError:
        return {"ok": False, "http": r.status_code,
                "erros": [{"Descricao": r.text[:250]}]}
    if r.status_code in (200, 201):
        xml_nfse = None
        if d.get("nfseXmlGZipB64"):
            xml_nfse = gzip.decompress(
                base64.b64decode(d["nfseXmlGZipB64"])).decode("utf-8")
        return {"ok": True, "http": r.status_code, "chave": d.get("chaveAcesso"),
                "xml": xml_nfse, "retorno": d}
    return {"ok": False, "http": r.status_code,
            "erros": d.get("erros") or [{"Descricao": str(d)[:250]}], "retorno": d}


def consultar(empresa_id, chave, ambiente="2"):
    with sefaz.CertTemp(empresa_id) as (c, k):
        r = requests.get(_url(ambiente, f"/nfse/{chave}"), cert=(c, k),
                         timeout=40, verify=False)
    if r.status_code != 200:
        return {"ok": False, "http": r.status_code, "texto": r.text[:250]}
    d = r.json()
    xml = None
    if d.get("nfseXmlGZipB64"):
        xml = gzip.decompress(base64.b64decode(d["nfseXmlGZipB64"])).decode("utf-8")
    return {"ok": True, "xml": xml, "retorno": d}


def danfse(empresa_id, chave, ambiente="2"):
    """Baixa o PDF da DANFSe pelo ADN."""
    url = BASE_ADN[ambiente] + f"/danfse/{chave}"
    with sefaz.CertTemp(empresa_id) as (c, k):
        r = requests.get(url, cert=(c, k), timeout=60, verify=False)
    if r.status_code == 200 and r.content[:4] == b"%PDF":
        return r.content
    return None


def evento(empresa_id, chave, xml_evento, ambiente="2"):
    """Registra evento na NFS-e: cancelamento, correcao ou manifestacao."""
    corpo = {"pedidoRegistroEventoXmlGZipB64": _compacta(xml_evento)}
    with sefaz.CertTemp(empresa_id) as (c, k):
        r = requests.post(_url(ambiente, f"/nfse/{chave}/eventos"), json=corpo,
                          cert=(c, k), timeout=60, verify=False)
    try:
        d = r.json()
    except ValueError:
        return {"ok": False, "http": r.status_code, "texto": r.text[:250]}
    return {"ok": r.status_code in (200, 201), "http": r.status_code, "retorno": d}
