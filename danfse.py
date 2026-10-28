"""DANFSe - Documento Auxiliar da NFS-e (padrao ABRASF / GissOnline).

Gera o PDF a partir do XML da NFS-e autorizada, via HTML + WeasyPrint.
Escrito de forma generica (le o XML, nao depende de municipio), entao
serve para qualquer prefeitura no padrao ABRASF.
"""
import re
from datetime import datetime
from decimal import Decimal

from lxml import etree
from weasyprint import HTML

from db import q

NS = "http://www.giss.com.br/tipos-v2_04.xsd"
NS_ABRASF = "http://www.abrasf.org.br/nfse.xsd"

# paleta do NFCheck (static/nucleo/tokens.css)
TINTA = "#061E38"
AZUL = "#0B3A66"
LARANJA = "#DE6127"
AMBAR = "#EFA33A"
CINZA = "#5B6B7C"
LINHA = "#D6DEE6"

LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 76" width="150" height="38">
  <rect x="2"  y="22" width="9" height="30" rx="4.5" fill="#061E38"/>
  <rect x="18" y="34" width="9" height="30" rx="4.5" fill="#0B3A66"/>
  <rect x="34" y="48" width="9" height="30" rx="4.5" fill="#1663A8"/>
  <rect x="50" y="34" width="9" height="30" rx="4.5" fill="#B34718"/>
  <rect x="66" y="16" width="9" height="30" rx="4.5" fill="#DE6127"/>
  <rect x="82" y="0"  width="9" height="30" rx="4.5" fill="#EFA33A"/>
  <text x="108" y="52" font-family="Helvetica,Arial,sans-serif" font-size="38"
        font-weight="700" fill="#061E38" letter-spacing="-1">NF</text>
  <text x="160" y="52" font-family="Helvetica,Arial,sans-serif" font-size="38"
        font-weight="400" fill="#DE6127" letter-spacing="-1">Check</text>
</svg>"""


def _t(el, caminho):
    """Busca texto de um caminho, tentando os dois namespaces do padrao."""
    if el is None:
        return None
    for ns in (NS, NS_ABRASF):
        achado = el.find(caminho.replace("{}", ns))
        if achado is not None and achado.text:
            return achado.text.strip()
    return None


def _busca(raiz, tag):
    """Primeiro elemento com essa tag local, em qualquer namespace."""
    for el in raiz.iter():
        if etree.QName(el).localname == tag:
            return el
    return None


def _txt(raiz, tag, padrao=""):
    el = _busca(raiz, tag)
    return el.text.strip() if el is not None and el.text else padrao


def _dinheiro(v):
    if v in (None, ""):
        return "0,00"
    d = Decimal(str(v))
    return f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _doc(numero):
    """Formata CPF (11) ou CNPJ (14)."""
    n = re.sub(r"\D", "", numero or "")
    if len(n) == 14:
        return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}"
    if len(n) == 11:
        return f"{n[:3]}.{n[3:6]}.{n[6:9]}-{n[9:]}"
    return numero or "-"


def _cep(v):
    n = re.sub(r"\D", "", v or "")
    return f"{n[:5]}-{n[5:]}" if len(n) == 8 else (v or "")


def _data_hora(v):
    if not v:
        return ""
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return v[:10]


def _data(v):
    if not v:
        return ""
    try:
        return datetime.fromisoformat(v[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return v[:10]


def extrair(xml):
    """Le o XML da NFS-e e devolve um dicionario plano com o que o DANFSe usa."""
    raiz = etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)

    inf = _busca(raiz, "InfNfse")
    if inf is None:
        raise ValueError("XML nao contem InfNfse - nao e uma NFS-e autorizada.")

    prestador = _busca(inf, "PrestadorServico")
    declaracao = _busca(inf, "DeclaracaoPrestacaoServico")
    servico = _busca(declaracao, "Servico") if declaracao is not None else None
    tomador = _busca(declaracao, "TomadorServico") if declaracao is not None else None
    valores_nfse = _busca(inf, "ValoresNfse")
    valores_serv = _busca(servico, "Valores") if servico is not None else None
    orgao = _busca(inf, "OrgaoGerador")

    def endereco_de(no):
        if no is None:
            return {}
        end = _busca(no, "Endereco")
        if end is None:
            return {}
        # <Endereco> pai contem outro <Endereco> (logradouro)
        filhos = [e for e in end.iter() if etree.QName(e).localname == "Endereco"]
        logradouro = filhos[-1].text if len(filhos) > 1 else _txt(end, "Endereco")
        return {
            "logradouro": (logradouro or "").strip(),
            "numero": _txt(end, "Numero"),
            "complemento": _txt(end, "Complemento"),
            "bairro": _txt(end, "Bairro"),
            "municipio": _txt(end, "CodigoMunicipio"),
            "uf": _txt(end, "Uf"),
            "cep": _cep(_txt(end, "Cep")),
        }

    def identificacao_de(no):
        if no is None:
            return {"documento": "", "im": ""}
        ident = _busca(no, "IdentificacaoTomador") or no
        cpfcnpj = _busca(ident, "CpfCnpj")
        doc = ""
        if cpfcnpj is not None:
            doc = _txt(cpfcnpj, "Cnpj") or _txt(cpfcnpj, "Cpf")
        return {"documento": doc, "im": _txt(ident, "InscricaoMunicipal")}

    ident_prest = _busca(declaracao, "Prestador") if declaracao is not None else None

    dados = {
        "numero": _txt(inf, "Numero"),
        "codigo_verificacao": _txt(inf, "CodigoVerificacao"),
        "data_emissao": _data_hora(_txt(inf, "DataEmissao")),
        "competencia": _data(_txt(declaracao, "Competencia") if declaracao is not None else ""),
        "municipio_gerador": _txt(orgao, "CodigoMunicipio"),
        "uf_gerador": _txt(orgao, "Uf"),

        "prest_nome": _txt(prestador, "RazaoSocial"),
        "prest_fantasia": _txt(prestador, "NomeFantasia"),
        "prest_doc": _doc(identificacao_de(ident_prest)["documento"]),
        "prest_im": identificacao_de(ident_prest)["im"],
        "prest_end": endereco_de(prestador),

        "tom_nome": _txt(tomador, "RazaoSocial"),
        "tom_doc": _doc(identificacao_de(tomador)["documento"]),
        "tom_im": identificacao_de(tomador)["im"],
        "tom_end": endereco_de(tomador),
        "tom_email": _txt(tomador, "Email"),

        "discriminacao": _txt(servico, "Discriminacao"),
        "item_lista": _txt(servico, "ItemListaServico"),
        "cod_tributacao": _txt(servico, "CodigoTributacaoMunicipio"),
        "desc_tributacao": _txt(inf, "DescricaoCodigoTributacaoMunicipio"),
        "codigo_nbs": _txt(servico, "CodigoNbs"),
        "municipio_prestacao": _txt(servico, "CodigoMunicipio"),
        "iss_retido": _txt(servico, "IssRetido") == "1",

        "valor_servicos": _txt(valores_serv, "ValorServicos", "0"),
        "deducoes": _txt(valores_serv, "ValorDeducoes", "0"),
        "desconto_incond": _txt(valores_serv, "DescontoIncondicionado", "0"),
        "pis": _txt(valores_serv, "ValorPis", "0"),
        "cofins": _txt(valores_serv, "ValorCofins", "0"),
        "inss": _txt(valores_serv, "ValorInss", "0"),
        "ir": _txt(valores_serv, "ValorIr", "0"),
        "csll": _txt(valores_serv, "ValorCsll", "0"),

        "base_calculo": _txt(valores_nfse, "BaseCalculo", "0"),
        "aliquota": _txt(valores_nfse, "Aliquota", "0"),
        "valor_iss": _txt(valores_nfse, "ValorIss", "0"),
        "valor_liquido": _txt(valores_nfse, "ValorLiquidoNfse", "0"),

        "optante_simples": _txt(declaracao, "OptanteSimplesNacional") == "1",
    }
    return dados


def _linha_endereco(end):
    if not end:
        return "-"
    p1 = ", ".join(x for x in [end.get("logradouro"), end.get("numero")] if x)
    if end.get("complemento"):
        p1 += f" - {end['complemento']}"
    p2 = " - ".join(x for x in [end.get("bairro"), end.get("uf")] if x)
    cep = f"CEP {end['cep']}" if end.get("cep") else ""
    return " · ".join(x for x in [p1, p2, cep] if x)


def montar_html(d, municipio_nome="", url_verificacao=""):
    aliq = Decimal(str(d["aliquota"] or 0))
    aliq_txt = f"{aliq:.2f}".replace(".", ",") + "%" if aliq else "-"

    nota_simples = ""
    if d["optante_simples"] and Decimal(str(d["valor_iss"] or 0)) == 0:
        nota_simples = (
            "<div class='aviso'>Prestador optante pelo Simples Nacional. "
            "O ISSQN desta nota é recolhido no documento único de arrecadação (DAS), "
            "conforme a LC 123/2006 &mdash; por isso o valor do ISS consta zerado.</div>"
        )

    retencoes = [
        ("PIS", d["pis"]), ("COFINS", d["cofins"]), ("INSS", d["inss"]),
        ("IR", d["ir"]), ("CSLL", d["csll"]),
    ]
    linhas_ret = "".join(
        f"<div class='v'><span>{nome}</span><b>R$ {_dinheiro(val)}</b></div>"
        for nome, val in retencoes if Decimal(str(val or 0)) > 0
    )

    verif = ""
    if url_verificacao:
        verif = f"<div class='verif'>Verifique a autenticidade em<br><b>{url_verificacao}</b></div>"

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 12mm 10mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: Helvetica, Arial, sans-serif; font-size: 8.5pt;
        color: {TINTA}; margin: 0; }}
.topo {{ display: flex; border: 1.5px solid {TINTA}; border-radius: 4px; overflow: hidden; }}
.topo .marca {{ width: 42%; padding: 10px 12px; border-right: 1px solid {LINHA}; }}
.topo .marca .tit {{ font-size: 13pt; font-weight: 700; letter-spacing: -.4px;
                     line-height: 1.15; margin-top: 6px; }}
.topo .marca .sub {{ color: {CINZA}; font-size: 7.5pt; margin-top: 3px; }}
.topo .num {{ flex: 1; padding: 10px 12px; background: {TINTA}; color: #fff; }}
.topo .num .rot {{ font-size: 7pt; opacity: .75; text-transform: uppercase;
                   letter-spacing: .6px; }}
.topo .num .big {{ font-size: 22pt; font-weight: 700; line-height: 1; margin: 2px 0 8px; }}
.topo .num .par {{ display: flex; gap: 18px; }}
.topo .num .par div {{ font-size: 8pt; }}
.topo .num .par b {{ display: block; font-size: 9.5pt; }}
h2 {{ font-size: 8pt; text-transform: uppercase; letter-spacing: 1px;
      color: #fff; background: {AZUL}; margin: 9px 0 0; padding: 4px 9px;
      border-radius: 3px 3px 0 0; }}
.bloco {{ border: 1px solid {LINHA}; border-top: none; border-radius: 0 0 3px 3px;
          padding: 8px 9px; }}
.grid {{ display: flex; flex-wrap: wrap; gap: 4px 18px; }}
.c {{ min-width: 30%; }}
.c .r {{ font-size: 6.8pt; color: {CINZA}; text-transform: uppercase;
         letter-spacing: .5px; }}
.c .d {{ font-size: 9pt; font-weight: 600; }}
.full {{ width: 100%; }}
.disc {{ white-space: pre-wrap; line-height: 1.45; font-size: 9pt; }}
.valores {{ display: flex; gap: 10px; align-items: stretch; margin-top: 9px; }}
.valores .col {{ flex: 1; border: 1px solid {LINHA}; border-radius: 3px; padding: 8px 9px; }}
.v {{ display: flex; justify-content: space-between; padding: 2.5px 0;
      border-bottom: 1px dotted {LINHA}; }}
.v:last-child {{ border-bottom: none; }}
.v span {{ color: {CINZA}; }}
.liq {{ background: {TINTA}; color: #fff; border-radius: 3px; padding: 10px 12px;
        min-width: 34%; display: flex; flex-direction: column; justify-content: center; }}
.liq .r {{ font-size: 7pt; opacity: .8; text-transform: uppercase; letter-spacing: .8px; }}
.liq .n {{ font-size: 19pt; font-weight: 700; line-height: 1.1; }}
.aviso {{ margin-top: 8px; padding: 7px 9px; font-size: 8pt; line-height: 1.4;
          background: rgba(239,163,58,.14); border-left: 3px solid {AMBAR};
          border-radius: 0 3px 3px 0; }}
.verif {{ margin-top: 8px; font-size: 7.5pt; color: {CINZA}; text-align: center;
          line-height: 1.5; }}
.rodape {{ margin-top: 14px; padding-top: 8px; border-top: 1px solid {LINHA};
           display: flex; justify-content: space-between; align-items: center; }}
.rodape .txt {{ font-size: 7pt; color: {CINZA}; line-height: 1.5; }}
.rodape .txt b {{ color: {TINTA}; }}
</style></head><body>

<div class="topo">
  <div class="marca">
    <div class="tit">Nota Fiscal de Serviços<br>Eletrônica - NFS-e</div>
    <div class="sub">{municipio_nome or ''}{' / ' + d['uf_gerador'] if d['uf_gerador'] else ''}</div>
  </div>
  <div class="num">
    <div class="rot">Número da NFS-e</div>
    <div class="big">{d['numero']}</div>
    <div class="par">
      <div><span class="rot">Código de verificação</span><b>{d['codigo_verificacao']}</b></div>
      <div><span class="rot">Emissão</span><b>{d['data_emissao']}</b></div>
      <div><span class="rot">Competência</span><b>{d['competencia']}</b></div>
    </div>
  </div>
</div>

<h2>Prestador do serviço</h2>
<div class="bloco"><div class="grid">
  <div class="c full"><div class="r">Razão social</div><div class="d">{d['prest_nome'] or '-'}</div></div>
  <div class="c"><div class="r">CNPJ</div><div class="d">{d['prest_doc']}</div></div>
  <div class="c"><div class="r">Inscrição municipal</div><div class="d">{d['prest_im'] or '-'}</div></div>
  <div class="c full"><div class="r">Endereço</div><div class="d">{_linha_endereco(d['prest_end'])}</div></div>
</div></div>

<h2>Tomador do serviço</h2>
<div class="bloco"><div class="grid">
  <div class="c full"><div class="r">Razão social</div><div class="d">{d['tom_nome'] or '-'}</div></div>
  <div class="c"><div class="r">CNPJ / CPF</div><div class="d">{d['tom_doc']}</div></div>
  <div class="c"><div class="r">Inscrição municipal</div><div class="d">{d['tom_im'] or '-'}</div></div>
  <div class="c full"><div class="r">Endereço</div><div class="d">{_linha_endereco(d['tom_end'])}</div></div>
</div></div>

<h2>Discriminação dos serviços</h2>
<div class="bloco">
  <div class="disc">{d['discriminacao'] or '-'}</div>
</div>

<h2>Classificação do serviço</h2>
<div class="bloco"><div class="grid">
  <div class="c"><div class="r">Item da lista (LC 116)</div><div class="d">{d['item_lista'] or '-'}</div></div>
  <div class="c"><div class="r">Código de tributação</div><div class="d">{d['cod_tributacao'] or '-'}</div></div>
  <div class="c"><div class="r">Código NBS</div><div class="d">{d['codigo_nbs'] or '-'}</div></div>
  <div class="c full"><div class="r">Atividade</div><div class="d">{d['desc_tributacao'] or '-'}</div></div>
</div></div>

<div class="valores">
  <div class="col">
    <div class="v"><span>Valor dos serviços</span><b>R$ {_dinheiro(d['valor_servicos'])}</b></div>
    <div class="v"><span>Deduções</span><b>R$ {_dinheiro(d['deducoes'])}</b></div>
    <div class="v"><span>Desconto incondicionado</span><b>R$ {_dinheiro(d['desconto_incond'])}</b></div>
    {linhas_ret}
  </div>
  <div class="col">
    <div class="v"><span>Base de cálculo</span><b>R$ {_dinheiro(d['base_calculo'])}</b></div>
    <div class="v"><span>Alíquota ISSQN</span><b>{aliq_txt}</b></div>
    <div class="v"><span>Valor do ISSQN</span><b>R$ {_dinheiro(d['valor_iss'])}</b></div>
    <div class="v"><span>ISS retido na fonte</span><b>{'SIM' if d['iss_retido'] else 'NÃO'}</b></div>
  </div>
  <div class="liq">
    <div class="r">Valor líquido da NFS-e</div>
    <div class="n">R$ {_dinheiro(d['valor_liquido'])}</div>
  </div>
</div>

{nota_simples}
{verif}

<div class="rodape">
  {LOGO}
  <div class="txt">
    Documento Auxiliar da NFS-e &mdash; representação do documento fiscal eletrônico.<br>
    Emitido por <b>NFCheck</b> &mdash; by <b>Órbita Softwares</b>
  </div>
</div>

</body></html>"""


def gerar(nfse_id, url_verificacao=""):
    """Gera o PDF do DANFSe de uma nota autorizada. Retorna bytes."""
    nota = q("""SELECT n.xml_nfse, n.situacao, e.municipio_nome
                FROM nfse_emitidas n JOIN empresas e ON e.id = n.empresa_id
                WHERE n.id = %s""", (nfse_id,), one=True)
    if not nota:
        raise ValueError(f"NFS-e {nfse_id} nao encontrada.")
    if not nota["xml_nfse"]:
        raise ValueError(f"NFS-e {nfse_id} nao tem XML - so notas autorizadas geram DANFSe.")

    d = extrair(nota["xml_nfse"])
    html = montar_html(d, municipio_nome=nota["municipio_nome"] or "",
                       url_verificacao=url_verificacao)
    return HTML(string=html).write_pdf()
