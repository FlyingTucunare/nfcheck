"""Emissao de NFS-e pelo provedor GISS Online (padrao ABRASF 2.04 + IBS/CBS).

Fluxo: monta o RPS, assina individualmente, agrupa em lote, assina o lote
por cima (o lote SEMPRE por ultimo, senao quebra a assinatura dos RPS),
e transmite via SOAP.

NAMESPACES: o GISS nao usa o namespace generico da ABRASF. Cada mensagem
tem o seu proprio (enviar-lote-rps-envio, cabecalho, consultar-lote-rps...)
e todo elemento aninhado vive em tipos-v2_04.xsd. Confirmado nos XSD
oficiais e no retorno real do servidor de homologacao.

Espelha a interface publica de nfse.py (Emissor Nacional) para que
nfse_provedor.py possa alternar entre os dois sem mudar o chamador.
"""
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import zeep
from zeep.transports import Transport
from lxml import etree
from signxml import XMLSigner, methods
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption

import certificados
import sefaz
from db import q

# --- namespaces GISS ---
NS_TIPOS = "http://www.giss.com.br/tipos-v2_04.xsd"
NS_CABECALHO = "http://www.giss.com.br/cabecalho-v2_04.xsd"
NS_ENVIO_LOTE = "http://www.giss.com.br/enviar-lote-rps-envio-v2_04.xsd"
NS_ENVIO_LOTE_SINC = "http://www.giss.com.br/enviar-lote-rps-sincrono-envio-v2_04.xsd"
NS_CONSULTA_LOTE = "http://www.giss.com.br/consultar-lote-rps-envio-v2_04.xsd"
NS_CANCELAR = "http://www.giss.com.br/cancelar-nfse-envio-v2_04.xsd"
NS_DSIG = "http://www.w3.org/2000/09/xmldsig#"

BRT = timezone(timedelta(hours=-3))
VERSAO_DADOS = "2.04"

# Valor de municipios.schema_versao_giss que ativa os campos de IBS/CBS.
SCHEMA_COM_IBSCBS = "ibscbs_v1"


def usa_ibscbs(municipio):
    """O municipio ja exige os campos da Reforma Tributaria?"""
    return (municipio or {}).get("schema_versao_giss") == SCHEMA_COM_IBSCBS

# ATENCAO: o Manual V1.6 indica "ws-homologacao.giss.com.br", mas essa URL
# devolve a pagina HTML do portal, nao um WSDL (verificado 12/08/2026). O
# webservice de homologacao que responde de fato e o "v2-ws-homologacao".
WSDL_HOMOLOGACAO = "https://v2-ws-homologacao.giss.com.br/service-ws/nf/nfse-ws?wsdl"

# cClassTrib -> CST (situacao tributaria IBS/CBS). So temos o caso padrao
# mapeado com confianca (tributacao integral = a grande maioria dos servicos
# comuns). Qualquer cClassTrib fora dessa lista levanta ValueError e precisa
# ser completado aqui antes de emitir esse tipo de servico.
CST_POR_CCLASSTRIB = {
    "000001": "000",  # Situacoes tributadas integralmente pelo IBS e CBS
}


def _d(v):
    """Valor monetario: ponto decimal, 2 casas."""
    if v is None:
        return None
    return f"{Decimal(str(v)):.2f}"


def _perc(v):
    """Aliquota em FRACAO com 4 casas (manual V1.6, item 8.1: 2% = 0.0200).
    O XML de retorno de uma NFS-e mostra o percentual (5), mas formato de
    retorno nao e formato de envio - quem manda no envio e o manual/XSD."""
    if v is None:
        return None
    return f"{Decimal(str(v)):.4f}"


def _item_lista(item):
    """O XSD de envio exige o formato com ponto e 2 digitos: '01.05'."""
    s = str(item).strip()
    if "." in s:
        a, b = s.split(".", 1)
        return f"{int(a):02d}.{b}"
    return s


def _wsdl_url(municipio):
    return f"https://ws-{municipio['giss_slug']}.giss.com.br/service-ws/nf/nfse-ws?wsdl"


def _t(tag, parent=None, text=None, **attribs):
    """Elemento no namespace de TIPOS (usado por tudo que e aninhado)."""
    return _ns(NS_TIPOS, tag, parent, text, **attribs)


def _ns(namespace, tag, parent=None, text=None, **attribs):
    if parent is not None:
        e = etree.SubElement(parent, f"{{{namespace}}}{tag}")
    else:
        e = etree.Element(f"{{{namespace}}}{tag}",
                          nsmap={"p": namespace, "p1": NS_TIPOS, "ds": NS_DSIG})
    if text is not None:
        e.text = str(text)
    for k, v in attribs.items():
        e.set(k, str(v))
    return e


def montar_cabecalho(versao=VERSAO_DADOS):
    """Todo metodo do GISS recebe DOIS parametros: nfseCabecMsg (este) e
    nfseDadosMsg. Confirmado no WSDL real de homologacao."""
    cab = etree.Element(f"{{{NS_CABECALHO}}}cabecalho",
                        nsmap={"p": NS_CABECALHO, "p1": NS_TIPOS})
    cab.set("versao", versao)
    v = etree.SubElement(cab, f"{{{NS_CABECALHO}}}versaoDados")
    v.text = versao
    return etree.tostring(cab, encoding="unicode")


# Local de incidencia do IBS/CBS por cIndOp (Anexo VII v1.02.00, art. 11
# LC 214/2025). Independente do municipio de incidencia do ISS.
# 'prestador' = estabelecimento do fornecedor | 'tomador' = domicilio do
# adquirente/destinatario (NFCheck emite com indDest=0) | 'local' = local da
# prestacao/imovel/evento/entrega (municipio_incidencia do servico).
LOCAL_IBSCBS_POR_CINDOP = {
    "010101": "prestador", "030101": "prestador", "050101": "prestador",
    "130101": "prestador",
    "010106": "tomador", "010201": "tomador", "010202": "tomador",
    "090102": "tomador", "100101": "tomador", "100102": "tomador",
    "100201": "tomador", "100301": "tomador", "100302": "tomador",
    "100401": "tomador", "100501": "tomador", "100502": "tomador",
    "100601": "tomador", "110201": "tomador", "130201": "tomador",
    "010102": "local", "010103": "local", "010104": "local", "010105": "local",
    "020101": "local", "020201": "local", "020202": "local", "020301": "local",
    "020401": "local", "030102": "local", "040101": "local", "050102": "local",
    "050201": "local", "060101": "local", "070101": "local", "070102": "local",
    "080101": "local", "090101": "local", "110101": "local", "120101": "local",
}


def localidade_ibscbs(dados):
    """IBGE da localidade de incidencia do IBS/CBS conforme o cIndOp."""
    cind = str(dados.get("cind_op") or "").strip().zfill(6)
    fonte = LOCAL_IBSCBS_POR_CINDOP.get(cind)
    if fonte is None:
        raise ValueError(
            f"cIndOp {cind!r} sem regra de local em LOCAL_IBSCBS_POR_CINDOP "
            f"(nfse_giss.py) - revise o servico antes de emitir.")
    if fonte == "tomador":
        if not dados.get("tomador_municipio_ibge"):
            raise ValueError("Tomador sem municipio (IBGE) no cadastro - "
                             "obrigatorio para o local do IBS/CBS.")
        return dados["tomador_municipio_ibge"]
    if fonte == "prestador":
        return dados.get("prestador_municipio_ibge") or dados["municipio_prestacao_ibge"]
    return dados["municipio_prestacao_ibge"]


def _montar_ibscbs(pai, dados):
    """Bloco IBSCBS (Reforma Tributaria), obrigatorio no leiaute atual.
    Estrutura conforme exemplo oficial: finNFSe, indFinal, cIndOp, indDest
    e o grupo 'valores' com trib>gIBSCBS, cLocalidadeIncid, pRedutor, vBC."""
    cclass_trib = dados["cclass_trib"]
    cst = CST_POR_CCLASSTRIB.get(cclass_trib)
    if cst is None:
        raise ValueError(
            f"cClassTrib {cclass_trib!r} sem CST mapeado em CST_POR_CCLASSTRIB "
            f"(nfse_giss.py) - adicione o mapeamento antes de emitir esse servico."
        )

    ibscbs = _t("IBSCBS", pai)
    _t("finNFSe", ibscbs, "0")   # 0 = NFS-e regular
    _t("indFinal", ibscbs, "0")  # 0 = nao e uso/consumo pessoal (art. 57)
    _t("cIndOp", ibscbs, dados["cind_op"])
    _t("indDest", ibscbs, "0")   # 0 = tomador = adquirente = destinatario

    valores = _t("valores", ibscbs)
    trib = _t("trib", valores)
    gibscbs = _t("gIBSCBS", trib)
    _t("CST", gibscbs, cst)
    _t("cClassTrib", gibscbs, cclass_trib)

    # base de calculo = servico - deducoes - desconto incondicionado
    bc = Decimal(str(dados["valor_servico"]))
    bc -= Decimal(str(dados.get("valor_deducoes") or 0))
    bc -= Decimal(str(dados.get("valor_desconto") or 0))

    _t("cLocalidadeIncid", valores, localidade_ibscbs(dados))
    _t("pRedutor", valores, "0")  # sem reducao (compra governamental)
    _t("vBC", valores, _d(bc))


def montar_rps(dados, rps_id, incluir_ibscbs=False):
    """Monta o elemento Rps (tcDeclaracaoPrestacaoServico) SEM assinatura.
    rps_id: valor do atributo Id de InfDeclaracaoPrestacaoServico, que e o
    alvo da assinatura individual do RPS."""
    rps_root = _t("Rps")
    inf = _t("InfDeclaracaoPrestacaoServico", rps_root, Id=rps_id)

    # nivel intermediario 'Rps' (tcInfRps) - obrigatorio pelo leiaute
    rps_inf = _t("Rps", inf, Id=f"{rps_id}_inf")
    ident = _t("IdentificacaoRps", rps_inf)
    _t("Numero", ident, dados["numero_rps"])
    _t("Serie", ident, dados["serie_rps"])
    _t("Tipo", ident, "1")  # 1 = RPS
    _t("DataEmissao", rps_inf, dados["data_emissao"].strftime("%Y-%m-%d"))
    _t("Status", rps_inf, "1")  # 1 = Normal

    _t("Competencia", inf, dados["competencia"].strftime("%Y-%m-%d"))

    # --- Servico ---
    serv = _t("Servico", inf)
    valores = _t("Valores", serv)
    _t("ValorServicos", valores, _d(dados["valor_servico"]))
    if dados.get("valor_deducoes"):
        _t("ValorDeducoes", valores, _d(dados["valor_deducoes"]))
    if dados.get("valor_pis"):
        _t("ValorPis", valores, _d(dados["valor_pis"]))
    if dados.get("valor_cofins"):
        _t("ValorCofins", valores, _d(dados["valor_cofins"]))
    if dados.get("valor_inss"):
        _t("ValorInss", valores, _d(dados["valor_inss"]))
    if dados.get("valor_ir"):
        _t("ValorIr", valores, _d(dados["valor_ir"]))
    if dados.get("valor_csll"):
        _t("ValorCsll", valores, _d(dados["valor_csll"]))
    if dados.get("aliquota_iss") is not None:
        _t("Aliquota", valores, _perc(dados["aliquota_iss"]))
    if dados.get("valor_desconto"):
        _t("DescontoIncondicionado", valores, _d(dados["valor_desconto"]))

    # Bloco da Reforma Tributaria. So entra quando o municipio ja estiver no
    # schema novo (municipios.schema_versao_giss = 'ibscbs_v1'). O schema
    # legado, ainda em uso, rejeita esses campos com E160.
    if incluir_ibscbs:
        trib = _t("trib", valores)
        tot = _t("totTrib", trib)
        if dados.get("optante_simples"):
            _t("pTotTribSN", tot, _d(dados.get("perc_trib_sn") or 0))
        else:
            p = _t("pTotTrib", tot)
            _t("pTotTribFed", p, "0")
            _t("pTotTribEst", p, "0")
            _t("pTotTribMun", p, "0")
        _montar_ibscbs(valores, dados)

    _t("IssRetido", serv, "1" if dados.get("iss_retido") else "2")
    _t("ItemListaServico", serv, _item_lista(dados["item_lista_servico"]))
    if dados.get("codigo_tributacao"):
        _t("CodigoTributacaoMunicipio", serv, dados["codigo_tributacao"])
    if dados.get("codigo_nbs"):
        _t("CodigoNbs", serv, str(dados["codigo_nbs"]).replace(".", ""))
    _t("Discriminacao", serv, dados["descricao"])
    _t("CodigoMunicipio", serv, dados["municipio_prestacao_ibge"])
    _t("CodigoPais", serv, "0076")  # Brasil
    _t("ExigibilidadeISS", serv, "1")  # 1 = Exigivel
    _t("MunicipioIncidencia", serv, dados["municipio_prestacao_ibge"])

    # --- Prestador ---
    prest = _t("Prestador", inf)
    cpfcnpj = _t("CpfCnpj", prest)
    _t("Cnpj", cpfcnpj, dados["prestador_cnpj"])
    if dados.get("prestador_im"):
        _t("InscricaoMunicipal", prest, dados["prestador_im"])

    # --- TomadorServico ---
    if dados.get("tomador_documento"):
        tom = _t("TomadorServico", inf)
        ident_tom = _t("IdentificacaoTomador", tom)
        cpfcnpj_tom = _t("CpfCnpj", ident_tom)
        if dados["tomador_tipo_doc"] == "cnpj":
            _t("Cnpj", cpfcnpj_tom, dados["tomador_documento"])
        else:
            _t("Cpf", cpfcnpj_tom, dados["tomador_documento"])
        if dados.get("tomador_im"):
            _t("InscricaoMunicipal", ident_tom, dados["tomador_im"])
        _t("RazaoSocial", tom, dados["tomador_razao_social"])
        if dados.get("tomador_logradouro"):
            end = _t("Endereco", tom)
            _t("Endereco", end, dados["tomador_logradouro"])
            _t("Numero", end, dados.get("tomador_numero") or "S/N")
            if dados.get("tomador_complemento"):
                _t("Complemento", end, dados["tomador_complemento"])
            _t("Bairro", end, dados.get("tomador_bairro") or "Centro")
            _t("CodigoMunicipio", end, dados["tomador_municipio_ibge"])
            _t("Uf", end, dados["tomador_uf"])
            _t("Cep", end, dados["tomador_cep"])
        if dados.get("tomador_email"):
            contato = _t("Contato", tom)
            _t("Email", contato, dados["tomador_email"])

    if dados.get("regime_especial"):
        _t("RegimeEspecialTributacao", inf, dados["regime_especial"])
    _t("OptanteSimplesNacional", inf, "1" if dados.get("optante_simples") else "2")
    _t("IncentivoFiscal", inf, "2")  # 2 = nao incentivador

    return rps_root


def _carrega_chave_cert_pem(empresa_id):
    """Extrai chave privada + certificado do .pfx da empresa, em PEM."""
    pfx_bytes, senha = certificados.carrega(empresa_id)
    senha_bytes = senha.encode() if isinstance(senha, str) else senha
    chave, cert, _ = pkcs12.load_key_and_certificates(pfx_bytes, senha_bytes)
    chave_pem = chave.private_bytes(
        encoding=Encoding.PEM, format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    return chave_pem, cert.public_bytes(Encoding.PEM)


class _AssinadorAbrasf(XMLSigner):
    """O leiaute ABRASF exige RSA-SHA1/SHA1, que o signxml 5.x bloqueia por
    padrao (algoritmos depreciados). Essa sobrescrita libera o uso - e o
    unico jeito de bater com o schema oficial."""
    def check_deprecated_methods(self):
        pass


def assinar(empresa_id, elemento, id_referencia):
    """Assinatura enveloped: <Signature> entra como ultimo filho do elemento,
    referenciando o Id informado."""
    chave_pem, cert_pem = _carrega_chave_cert_pem(empresa_id)
    signer = _AssinadorAbrasf(
        method=methods.enveloped,
        signature_algorithm="rsa-sha1",
        digest_algorithm="sha1",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )
    return signer.sign(elemento, key=chave_pem, cert=cert_pem,
                       reference_uri=f"#{id_referencia}")


def montar_e_assinar(empresa_id, numero_lote, prestador_cnpj, prestador_im,
                     rps_list, sincrono=False, assinar_cada_rps=True):
    """Caminho correto de emissao: monta o lote com os RPS SEM assinatura,
    assina cada RPS ja dentro da arvore e por fim assina o lote.

    A ordem importa: assinar um RPS solto e depois anexa-lo quebra o digest
    (namespaces sao reescritos no append) -> a prefeitura devolve E172.
    E o lote e sempre o ultimo a ser assinado, senao quebra os RPS.
    """
    envio, lote_id = montar_lote(numero_lote, prestador_cnpj, prestador_im,
                                 rps_list, sincrono=sincrono)
    # RecepcionarLoteRps (assincrono) e o unico metodo de emissao documentado
    # no manual vigente V1.6. Sincrono e GerarNfse existem no WSDL mas nao
    # constam do manual.
    # E174 na pratica: o servidor exige assinatura individual do RPS, apesar
    # de o manual V1.6 (item 6.3) dizer que assinar o lote seria suficiente.
    if assinar_cada_rps:
        lista = envio.find(f".//{{{NS_TIPOS}}}ListaRps")
        for rps in list(lista):
            inf = rps.find(f"{{{NS_TIPOS}}}InfDeclaracaoPrestacaoServico")
            lista.replace(rps, assinar(empresa_id, rps, inf.get("Id")))
    return assinar(empresa_id, envio, lote_id)


def assinar_documento(empresa_id, elemento):
    """Assinatura do documento inteiro (URI vazia), usada nas consultas e no
    cancelamento - mensagens que nao tem atributo Id para referenciar."""
    chave_pem, cert_pem = _carrega_chave_cert_pem(empresa_id)
    signer = _AssinadorAbrasf(
        method=methods.enveloped,
        signature_algorithm="rsa-sha1",
        digest_algorithm="sha1",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )
    return signer.sign(elemento, key=chave_pem, cert=cert_pem)


def montar_lote(numero_lote, prestador_cnpj, prestador_im, rps_assinados,
                sincrono=True):
    """Agrupa RPS ja assinados no envelope de envio. O retorno ainda precisa
    ser assinado (assinatura do lote) - e sempre POR ULTIMO.

    O envio sincrono e o assincrono tem elemento raiz e namespace DIFERENTES."""
    ns = NS_ENVIO_LOTE_SINC if sincrono else NS_ENVIO_LOTE
    raiz = "EnviarLoteRpsSincronoEnvio" if sincrono else "EnviarLoteRpsEnvio"
    envio = _ns(ns, raiz)
    lote = _ns(ns, "LoteRps", envio,
               Id=f"lote_{numero_lote}", versao=VERSAO_DADOS)
    _t("NumeroLote", lote, numero_lote)
    prest = _t("Prestador", lote)
    cpfcnpj = _t("CpfCnpj", prest)
    _t("Cnpj", cpfcnpj, prestador_cnpj)
    if prestador_im:
        _t("InscricaoMunicipal", prest, prestador_im)
    _t("QuantidadeRps", lote, len(rps_assinados))
    lista = _t("ListaRps", lote)
    for rps in rps_assinados:
        lista.append(rps)
    return envio, f"lote_{numero_lote}"


DIR_SCHEMAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas_giss")

_SCHEMA_POR_RAIZ = {
    f"{{{NS_ENVIO_LOTE}}}EnviarLoteRpsEnvio": "enviar-lote-rps-envio-v2_04.xsd",
    f"{{{NS_ENVIO_LOTE_SINC}}}EnviarLoteRpsSincronoEnvio": "enviar-lote-rps-sincrono-envio-v2_04.xsd",
    f"{{{NS_CONSULTA_LOTE}}}ConsultarLoteRpsEnvio": "consultar-lote-rps-envio-v2_04.xsd",
    f"{{{NS_CANCELAR}}}CancelarNfseEnvio": "cancelar-nfse-envio-v2_04.xsd",
}


def validar(elemento):
    """Valida contra o XSD oficial ANTES de transmitir. Sem isso a prefeitura
    devolve so 'E160 - Arquivo em desacordo com o XML Schema', sem dizer qual
    campo. Retorna lista de erros (vazia = valido)."""
    raiz = elemento.tag
    arquivo = _SCHEMA_POR_RAIZ.get(raiz)
    if not arquivo:
        return []
    caminho = os.path.join(DIR_SCHEMAS, arquivo)
    if not os.path.exists(caminho):
        return []
    schema = etree.XMLSchema(etree.parse(caminho))
    if schema.validate(elemento):
        return []
    return [f"{e.message}" for e in schema.error_log]


def _chamar(empresa_id, municipio, ambiente, metodo, xml_dados):
    """Executa um metodo do webservice GISS com mTLS.

    O certificado temporario (.pem) so existe dentro do bloco 'with' do
    CertTemp - por isso a chamada inteira acontece aqui dentro. Retornar o
    client e chamar depois falha com "Could not find the TLS certificate file".
    """
    import requests
    url = WSDL_HOMOLOGACAO if ambiente == "2" else _wsdl_url(municipio)
    with sefaz.CertTemp(empresa_id) as (certfile, keyfile):
        session = requests.Session()
        session.cert = (certfile, keyfile)
        session.verify = False
        transport = Transport(session=session, timeout=60)
        client = zeep.Client(wsdl=url, transport=transport)
        return getattr(client.service, metodo)(montar_cabecalho(), xml_dados)


def _xml(elemento):
    return etree.tostring(elemento, encoding="unicode")


def enviar_lote(empresa_id, municipio, envio_assinado, ambiente="2", sincrono=False):
    """Transmite o lote de RPS.

    sincrono=True  -> RecepcionarLoteRpsSincrono: devolve a NFS-e na hora.
    sincrono=False -> RecepcionarLoteRps: devolve so o protocolo; o resultado
                      vem depois via consultar_lote().
    """
    erros = validar(envio_assinado)
    if erros:
        return {"ok": False, "erro": "XML invalido pelo schema oficial (nao transmitido): "
                                     + " | ".join(erros[:5]), "erros_schema": erros}
    metodo = "RecepcionarLoteRpsSincrono" if sincrono else "RecepcionarLoteRps"
    try:
        resposta = _chamar(empresa_id, municipio, ambiente, metodo,
                           _xml(envio_assinado))
        return {"ok": True, "sincrono": sincrono, "retorno": str(resposta)}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


def consultar_lote(empresa_id, municipio, prestador_cnpj, protocolo, ambiente="2"):
    envio = _ns(NS_CONSULTA_LOTE, "ConsultarLoteRpsEnvio")
    prest = _ns(NS_CONSULTA_LOTE, "Prestador", envio)
    cpfcnpj = _t("CpfCnpj", prest)
    _t("Cnpj", cpfcnpj, prestador_cnpj)
    _ns(NS_CONSULTA_LOTE, "Protocolo", envio, protocolo)
    envio = assinar_documento(empresa_id, envio)
    try:
        resposta = _chamar(empresa_id, municipio, ambiente,
                           "ConsultarLoteRps", _xml(envio))
        return {"ok": True, "retorno": str(resposta)}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


def montar_pedido_cancelamento(numero_nfse, prestador_cnpj, prestador_im,
                               municipio_ibge, codigo_cancelamento, pedido_id):
    """Monta o CancelarNfseEnvio.

    Devolve (envio, pedido, pedido_id): o 'pedido' e o elemento que deve ser
    assinado, e o 'envio' e o que vai para o webservice.

    codigo_cancelamento: 1=Erro na emissao, 2=Servico nao prestado,
    4=Duplicidade (3 e 5 sao de uso exclusivo da Prefeitura)."""
    envio = _ns(NS_CANCELAR, "CancelarNfseEnvio")
    pedido = _ns(NS_CANCELAR, "Pedido", envio)
    inf = _t("InfPedidoCancelamento", pedido, Id=pedido_id)
    ident = _t("IdentificacaoNfse", inf)
    _t("Numero", ident, numero_nfse)
    cpfcnpj = _t("CpfCnpj", ident)
    _t("Cnpj", cpfcnpj, prestador_cnpj)
    if prestador_im:
        _t("InscricaoMunicipal", ident, prestador_im)
    _t("CodigoMunicipio", ident, municipio_ibge)
    _t("CodigoCancelamento", inf, codigo_cancelamento)
    # a assinatura vai DENTRO do <Pedido> (tcPedidoCancelamento = 
    # InfPedidoCancelamento + Signature), nao no envelope - assinar o envelope
    # da E160. Mesmo padrao do RPS.
    return envio, pedido, pedido_id


def montar_e_assinar_cancelamento(empresa_id, numero_nfse, prestador_cnpj,
                                  prestador_im, municipio_ibge,
                                  codigo_cancelamento, pedido_id):
    """Monta o pedido de cancelamento com a assinatura na posicao correta."""
    envio, pedido, pid = montar_pedido_cancelamento(
        numero_nfse, prestador_cnpj, prestador_im, municipio_ibge,
        codigo_cancelamento, pedido_id)
    envio.replace(pedido, assinar(empresa_id, pedido, pid))
    return envio


def cancelar_nfse(empresa_id, municipio, xml_pedido_assinado, ambiente="2"):
    # o pedido de cancelamento ja deve chegar assinado (assinar_documento)
    try:
        resposta = _chamar(empresa_id, municipio, ambiente,
                           "CancelarNfse", _xml(xml_pedido_assinado))
        return {"ok": True, "retorno": str(resposta)}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


def extrair_mensagens(xml_retorno):
    """Le as MensagemRetorno de uma resposta do GISS e enriquece cada uma com
    a solucao catalogada em giss_erros_alertas."""
    try:
        raiz = etree.fromstring(xml_retorno.encode("utf-8")
                                if isinstance(xml_retorno, str) else xml_retorno)
    except Exception:
        return []
    saida = []
    for m in raiz.iter(f"{{{NS_TIPOS}}}MensagemRetorno"):
        codigo = m.findtext(f"{{{NS_TIPOS}}}Codigo")
        saida.append({
            "codigo": codigo,
            "mensagem": m.findtext(f"{{{NS_TIPOS}}}Mensagem"),
            "correcao": m.findtext(f"{{{NS_TIPOS}}}Correcao"),
            "solucao": (mensagem_erro(codigo) or {}).get("solucao") if codigo else None,
        })
    return saida


def mensagem_erro(codigo):
    """Busca mensagem amigavel na tabela giss_erros_alertas."""
    r = q("SELECT mensagem, solucao FROM giss_erros_alertas WHERE codigo = %s",
          (codigo,), one=True)
    if not r:
        return {"codigo": codigo, "mensagem": f"Codigo {codigo} nao catalogado",
                "solucao": None}
    return {"codigo": codigo, "mensagem": r["mensagem"], "solucao": r["solucao"]}
