"""Manifestacao do destinatario. Gera, assina e transmite o evento a SEFAZ.
Eventos irreversiveis: cada envio fica registrado em manifestacoes e auditoria."""
import io, time, warnings
from datetime import datetime, timezone, timedelta
from lxml import etree
from signxml import XMLSigner, methods
from signxml.algorithms import (SignatureMethod, DigestAlgorithm,
                                CanonicalizationMethod)
from cryptography.hazmat.primitives.serialization import pkcs12
import requests
import urllib3
# a PyNFe desativa a verificacao TLS; o aviso repetido polui o log
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from db import q
import certificados
import sefaz

NS = "http://www.portalfiscal.inf.br/nfe"
BRT = timezone(timedelta(hours=-3))

# Eventos de manifestacao do destinatario (familia 2102xx).
# Nao confundir com 1102xx, que sao cancelamento e carta de correcao.
EVENTOS = {
    "210210": ("Ciencia da Operacao",         "Ciencia da Operacao"),
    "210200": ("Confirmacao da Operacao",     "Confirmacao da Operacao"),
    "210220": ("Desconhecimento da Operacao", "Desconhecimento da Operacao"),
    "210240": ("Operacao nao Realizada",      "Operacao nao Realizada"),
}
EXIGE_JUSTIFICATIVA = {"210240"}

URL_EVENTO = {
    "1": "https://www1.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx",
    "2": "https://hom1.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx",
}
WSDL = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4"


def _xml_evento(cnpj, chave, tp_evento, seq, ambiente, justificativa=None):
    agora = datetime.now(BRT).strftime("%Y-%m-%dT%H:%M:%S%z")
    agora = agora[:-2] + ":" + agora[-2:]
    id_evento = f"ID{tp_evento}{chave}{str(seq).zfill(2)}"
    desc = EVENTOS[tp_evento][1]
    just = f"<xJust>{justificativa}</xJust>" if justificativa else ""
    return (
      f'<evento xmlns="{NS}" versao="1.00">'
      f'<infEvento Id="{id_evento}">'
      f'<cOrgao>91</cOrgao><tpAmb>{ambiente}</tpAmb><CNPJ>{cnpj}</CNPJ>'
      f'<chNFe>{chave}</chNFe><dhEvento>{agora}</dhEvento>'
      f'<tpEvento>{tp_evento}</tpEvento><nSeqEvento>{seq}</nSeqEvento>'
      f'<verEvento>1.00</verEvento>'
      f'<detEvento versao="1.00"><descEvento>{desc}</descEvento>{just}</detEvento>'
      f'</infEvento></evento>')


def _assina_e_envia(empresa_id, xml_evento, ambiente):
    """Assina e transmite via PyNFe, que ja trata as particularidades do
    envelope SOAP e da assinatura exigidas pela SEFAZ."""
    import tempfile, os
    from pynfe.processamento.assinatura import AssinaturaA1
    from pynfe.processamento.comunicacao import ComunicacaoSefaz

    pfx, senha = certificados.carrega(empresa_id)
    arq = tempfile.NamedTemporaryFile(suffix=".pfx", delete=False)
    arq.write(pfx)
    arq.close()
    os.chmod(arq.name, 0o600)
    try:
        raiz = etree.fromstring(xml_evento.encode("utf-8"))
        assinado = AssinaturaA1(arq.name, senha).assinar(raiz)
        uf = q("SELECT uf FROM empresas WHERE id=%s", (empresa_id,), one=True)["uf"]
        com = ComunicacaoSefaz(uf or "SP", arq.name, senha, ambiente == "2")
        return com.evento(modelo="nfe", evento=assinado, id_lote=int(time.time()))
    finally:
        try:
            os.unlink(arq.name)
        except OSError:
            pass


def enviar(empresa_id, chave, tp_evento, usuario_id, automatica=False,
           justificativa=None, ambiente="1"):
    """Envia um evento. Retorna dict com cstat, motivo e protocolo."""
    if tp_evento not in EVENTOS:
        return {"ok": False, "motivo": "Evento invalido"}
    if tp_evento in EXIGE_JUSTIFICATIVA and not justificativa:
        return {"ok": False, "motivo": "Este evento exige justificativa"}
    if justificativa and len(justificativa) < 15:
        return {"ok": False, "motivo": "A justificativa precisa de ao menos 15 caracteres"}

    emp = q("SELECT cnpj FROM empresas WHERE id=%s", (empresa_id,), one=True)
    ja = q("""SELECT COUNT(*) AS n FROM manifestacoes
              WHERE chave=%s AND evento=%s AND cstat IN ('135','136','573')""",
           (chave, tp_evento), one=True)
    if ja["n"]:
        return {"ok": False, "motivo": "Este evento ja foi registrado para o documento",
                "duplicado": True}

    # Manifestacao do destinatario aceita apenas uma ocorrencia por evento:
    # nSeqEvento e sempre 1. Sequencia maior existe para cancelamento e CC-e.
    seq = 1

    xml = _xml_evento(emp["cnpj"], chave, tp_evento, seq, ambiente, justificativa)

    try:
        r = _assina_e_envia(empresa_id, xml, ambiente)
        r.raise_for_status()
    except Exception as e:
        return {"ok": False, "motivo": "Envio: " + str(e)[:140]}

    resp = etree.fromstring(r.content)
    _r = sefaz._busca(resp, "retEvento")
    ret = _r if _r is not None else resp
    cstat = sefaz._txt(ret, "cStat", "")
    motivo = sefaz._txt(ret, "xMotivo", "")
    prot = sefaz._txt(ret, "nProt")
    ok = cstat in ("135", "136", "573")

    doc = q("SELECT id FROM documentos WHERE chave=%s AND empresa_id=%s",
            (chave, empresa_id), one=True)
    q("""INSERT INTO manifestacoes (empresa_id,documento_id,chave,evento,automatica,
           usuario_id,cstat,motivo,protocolo)
         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
      (empresa_id, doc["id"] if doc else None, chave, tp_evento, automatica,
       usuario_id, cstat, motivo[:300], prot))

    if ok and doc:
        q("""UPDATE documentos SET manifestacao=%s, manifestacao_em=NOW()
             WHERE id=%s""", (EVENTOS[tp_evento][0], doc["id"]))

    return {"ok": ok, "cstat": cstat, "motivo": motivo, "protocolo": prot}
