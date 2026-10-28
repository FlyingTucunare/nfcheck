"""Rotas de NFS-e: cadastro de servicos e tomadores, configuracao,
emissao, consulta, cancelamento, DANFSe e XML.

A emissao e SINCRONA: transmite o lote e ja consulta o protocolo, para o
usuario ver o numero da nota na hora. Se a transmissao der certo mas a
consulta falhar, a nota fica 'processando' com o protocolo salvo e pode ser
recuperada por POST /notas/{id}/consultar - nunca se perde uma nota que a
prefeitura ja autorizou.
"""
import re
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from lxml import etree
from pydantic import BaseModel

from db import q
import auth
import receita
import nfse_provedor
import nfse_giss
import danfse
import atividades
import atividades

router = APIRouter(prefix="/api/nfse", tags=["nfse"])

NS = "{http://www.giss.com.br/tipos-v2_04.xsd}"


# ---------------------------------------------------------------- modelos
class ServicoEntrada(BaseModel):
    empresa_id: int
    apelido: str
    descricao: str
    item_lista_servico: str | None = None
    codigo_tributacao: str | None = None
    codigo_nbs: str | None = None
    cind_op: str | None = None
    cclass_trib: str | None = None
    valor_padrao: float | None = None
    aliquota_iss: float | None = None
    iss_retido: bool = False
    municipio_incidencia: str | None = None
    favorito: bool = False


class TomadorEntrada(BaseModel):
    empresa_id: int
    tipo_doc: str = "cnpj"
    documento: str
    razao_social: str
    nome_fantasia: str | None = None
    im: str | None = None
    email: str | None = None
    telefone: str | None = None
    logradouro: str | None = None
    numero: str | None = None
    complemento: str | None = None
    bairro: str | None = None
    municipio_ibge: str | None = None
    municipio_nome: str | None = None
    uf: str | None = None
    cep: str | None = None


class ConfigEntrada(BaseModel):
    empresa_id: int
    ambiente: str = "1"
    serie_dps: str = "00001"
    proximo_numero: int | None = None
    regime_especial: str | None = None
    optante_simples: bool = False
    incentivo_fiscal: bool = False
    aliquota_iss: float | None = None
    iss_retido_padrao: bool = False
    observacao_padrao: str | None = None
    ativo: bool = True


class EmissaoEntrada(BaseModel):
    empresa_id: int
    tomador_id: int
    servico_id: int
    valor_servico: float
    competencia: str                      # AAAA-MM-DD
    descricao: str | None = None          # sobrescreve a do servico
    valor_deducoes: float = 0
    valor_desconto: float = 0
    valor_pis: float = 0
    valor_cofins: float = 0
    valor_inss: float = 0
    valor_ir: float = 0
    valor_csll: float = 0
    iss_retido: bool | None = None
    aliquota_iss: float | None = None


class CancelamentoEntrada(BaseModel):
    codigo: str = "1"                     # 1=erro emissao 2=servico nao prestado 4=duplicidade
    motivo: str | None = None


# ---------------------------------------------------------------- apoio
def _limpa(v):
    return re.sub(r"\D", "", v or "")


def _dec(v):
    return Decimal(str(v or 0))


def _nota_no_escopo(u, nfse_id):
    n = q("SELECT * FROM nfse_emitidas WHERE id=%s", (nfse_id,), one=True)
    if not n:
        raise HTTPException(404, "Nota nao encontrada")
    auth.exige_empresa(u, n["empresa_id"])
    return n


# ---------------------------------------------------------------- servicos
@router.get("/servicos")
def listar_servicos(empresa_id: int, u=Depends(auth.exige("ver"))):
    auth.exige_empresa(u, empresa_id)
    return q("""SELECT * FROM servicos WHERE empresa_id=%s AND ativo
                ORDER BY favorito DESC, apelido""", (empresa_id,))


@router.post("/servicos")
def criar_servico(d: ServicoEntrada, u=Depends(auth.exige("emitir"))):
    auth.exige_empresa(u, d.empresa_id)
    r = q("""INSERT INTO servicos (empresa_id, apelido, descricao, item_lista_servico,
               codigo_tributacao, codigo_nbs, cind_op, cclass_trib, valor_padrao,
               aliquota_iss, iss_retido, municipio_incidencia, favorito)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
          (d.empresa_id, d.apelido, d.descricao, d.item_lista_servico,
           d.codigo_tributacao, d.codigo_nbs, d.cind_op, d.cclass_trib,
           d.valor_padrao, d.aliquota_iss, d.iss_retido,
           d.municipio_incidencia, d.favorito), one=True)
    return r


@router.put("/servicos/{sid}")
def editar_servico(sid: int, d: ServicoEntrada, u=Depends(auth.exige("emitir"))):
    auth.exige_empresa(u, d.empresa_id)
    r = q("""UPDATE servicos SET apelido=%s, descricao=%s, item_lista_servico=%s,
               codigo_tributacao=%s, codigo_nbs=%s, cind_op=%s, cclass_trib=%s,
               valor_padrao=%s, aliquota_iss=%s, iss_retido=%s,
               municipio_incidencia=%s, favorito=%s
             WHERE id=%s AND empresa_id=%s RETURNING *""",
          (d.apelido, d.descricao, d.item_lista_servico, d.codigo_tributacao,
           d.codigo_nbs, d.cind_op, d.cclass_trib, d.valor_padrao, d.aliquota_iss,
           d.iss_retido, d.municipio_incidencia, d.favorito, sid, d.empresa_id), one=True)
    if not r:
        raise HTTPException(404, "Servico nao encontrado")
    return r


@router.delete("/servicos/{sid}")
def inativar_servico(sid: int, empresa_id: int, u=Depends(auth.exige("emitir"))):
    auth.exige_empresa(u, empresa_id)
    q("UPDATE servicos SET ativo=false WHERE id=%s AND empresa_id=%s", (sid, empresa_id))
    return {"ok": True}


@router.get("/itens-lc116")
def itens_lc116(busca: str = "", u=Depends(auth.exige("ver"))):
    """Itens da LC 116 com descricao, a partir da correlacao oficial."""
    if busca:
        return q("""SELECT DISTINCT item_lista_servico AS item, descricao_item AS descricao
                    FROM correlacao_nbs_ibscbs
                    WHERE item_lista_servico ILIKE %s OR descricao_item ILIKE %s
                    ORDER BY item LIMIT 60""", (f"%{busca}%", f"%{busca}%"))
    return q("""SELECT DISTINCT item_lista_servico AS item, descricao_item AS descricao
                FROM correlacao_nbs_ibscbs ORDER BY item""")


@router.get("/sugestao")
def sugestao(item: str, codigo_nbs: str = "", u=Depends(auth.exige("ver"))):
    """NBS validos e classificacao IBS/CBS sugerida para um item da LC 116."""
    return {
        "nbs": nfse_provedor.nbs_do_item(item),
        "classificacao": nfse_provedor.sugerir_classificacao(item, codigo_nbs or None),
    }


@router.get("/atividades")
def listar_atividades(empresa_id: int, item: str = "", u=Depends(auth.exige("ver"))):
    """Atividades do municipio que a empresa pode usar, ja cruzadas com os
    CNAEs dela na Receita. E a lista oficial da prefeitura - traz o codigo de
    tributacao, o item da LC 116 e a aliquota corretos."""
    auth.exige_empresa(u, empresa_id)
    emp = q("SELECT municipio_ibge, municipio_nome FROM empresas WHERE id=%s",
            (empresa_id,), one=True)
    if not emp or not emp["municipio_ibge"]:
        return {"compativeis": [], "outras": [], "aviso": "Empresa sem municipio."}

    d = atividades.para_empresa(empresa_id, item or None)
    if not d["total_municipio"]:
        # primeira vez neste municipio: tenta importar na hora
        try:
            atividades.importar(emp["municipio_ibge"])
            d = atividades.para_empresa(empresa_id, item or None)
        except Exception:
            d["aviso"] = (f"O municipio {emp['municipio_nome']} nao publica a lista "
                          f"de atividades. Informe o codigo de tributacao manualmente.")
    return d


@router.get("/atividades/buscar")
def buscar_atividades(empresa_id: int, termo: str = "", u=Depends(auth.exige("ver"))):
    """Busca livre na lista completa do municipio."""
    auth.exige_empresa(u, empresa_id)
    emp = q("SELECT municipio_ibge FROM empresas WHERE id=%s", (empresa_id,), one=True)
    if not emp or not emp["municipio_ibge"]:
        return []
    return atividades.buscar(emp["municipio_ibge"], termo)


@router.post("/atividades/atualizar")
def atualizar_atividades(empresa_id: int, u=Depends(auth.exige("emitir"))):
    """Rebaixa a lista do municipio (o municipio publica alteracoes de tempos
    em tempos - ha regras entrando em vigor em 01/01/2027)."""
    auth.exige_empresa(u, empresa_id)
    emp = q("SELECT municipio_ibge FROM empresas WHERE id=%s", (empresa_id,), one=True)
    try:
        return atividades.importar(emp["municipio_ibge"])
    except Exception as e:
        raise HTTPException(502, f"Nao foi possivel baixar a lista: {e}")


@router.get("/atividades")
def listar_atividades(empresa_id: int, item: str = "", u=Depends(auth.exige("ver"))):
    """Atividades do municipio que a empresa pode usar, ja cruzadas com os
    CNAEs dela na Receita. E a lista oficial da prefeitura - traz o codigo de
    tributacao, o item da LC 116 e a aliquota corretos."""
    auth.exige_empresa(u, empresa_id)
    emp = q("SELECT municipio_ibge, municipio_nome FROM empresas WHERE id=%s",
            (empresa_id,), one=True)
    if not emp or not emp["municipio_ibge"]:
        return {"compativeis": [], "outras": [], "aviso": "Empresa sem municipio."}

    d = atividades.para_empresa(empresa_id, item or None)
    if not d["total_municipio"]:
        # primeira vez neste municipio: tenta importar na hora
        try:
            atividades.importar(emp["municipio_ibge"])
            d = atividades.para_empresa(empresa_id, item or None)
        except Exception:
            d["aviso"] = (f"O municipio {emp['municipio_nome']} nao publica a lista "
                          f"de atividades. Informe o codigo de tributacao manualmente.")
    return d


@router.get("/atividades/buscar")
def buscar_atividades(empresa_id: int, termo: str = "", u=Depends(auth.exige("ver"))):
    """Busca livre na lista completa do municipio."""
    auth.exige_empresa(u, empresa_id)
    emp = q("SELECT municipio_ibge FROM empresas WHERE id=%s", (empresa_id,), one=True)
    if not emp or not emp["municipio_ibge"]:
        return []
    return atividades.buscar(emp["municipio_ibge"], termo)


@router.post("/atividades/atualizar")
def atualizar_atividades(empresa_id: int, u=Depends(auth.exige("emitir"))):
    """Rebaixa a lista do municipio (o municipio publica alteracoes de tempos
    em tempos - ha regras entrando em vigor em 01/01/2027)."""
    auth.exige_empresa(u, empresa_id)
    emp = q("SELECT municipio_ibge FROM empresas WHERE id=%s", (empresa_id,), one=True)
    try:
        return atividades.importar(emp["municipio_ibge"])
    except Exception as e:
        raise HTTPException(502, f"Nao foi possivel baixar a lista: {e}")


# ---------------------------------------------------------------- tomadores
@router.get("/tomadores")
def listar_tomadores(empresa_id: int, busca: str = "", u=Depends(auth.exige("ver"))):
    auth.exige_empresa(u, empresa_id)
    if busca:
        return q("""SELECT * FROM tomadores WHERE empresa_id=%s AND ativo
                    AND (razao_social ILIKE %s OR documento ILIKE %s)
                    ORDER BY razao_social LIMIT 50""",
                 (empresa_id, f"%{busca}%", f"%{_limpa(busca)}%"))
    return q("""SELECT * FROM tomadores WHERE empresa_id=%s AND ativo
                ORDER BY razao_social""", (empresa_id,))


@router.get("/tomadores/receita/{cnpj}")
def tomador_pela_receita(cnpj: str, u=Depends(auth.exige("emitir"))):
    """Puxa os dados do CNPJ na Receita para preencher o cadastro."""
    try:
        return receita.consulta(cnpj, conn_q=q)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@router.post("/tomadores")
def criar_tomador(d: TomadorEntrada, u=Depends(auth.exige("emitir"))):
    auth.exige_empresa(u, d.empresa_id)
    doc = _limpa(d.documento)
    return q("""INSERT INTO tomadores (empresa_id, tipo_doc, documento, razao_social,
                  nome_fantasia, im, email, telefone, logradouro, numero, complemento,
                  bairro, municipio_ibge, municipio_nome, uf, cep)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (empresa_id, documento) DO UPDATE SET
                  razao_social=EXCLUDED.razao_social, nome_fantasia=EXCLUDED.nome_fantasia,
                  im=EXCLUDED.im, email=EXCLUDED.email, telefone=EXCLUDED.telefone,
                  logradouro=EXCLUDED.logradouro, numero=EXCLUDED.numero,
                  complemento=EXCLUDED.complemento, bairro=EXCLUDED.bairro,
                  municipio_ibge=EXCLUDED.municipio_ibge,
                  municipio_nome=EXCLUDED.municipio_nome, uf=EXCLUDED.uf,
                  cep=EXCLUDED.cep, ativo=true
                RETURNING *""",
             (d.empresa_id, d.tipo_doc, doc, d.razao_social, d.nome_fantasia, d.im,
              d.email, d.telefone, d.logradouro, d.numero, d.complemento, d.bairro,
              d.municipio_ibge, d.municipio_nome, d.uf, _limpa(d.cep)), one=True)


@router.put("/tomadores/{tid}")
def editar_tomador(tid: int, d: TomadorEntrada, u=Depends(auth.exige("emitir"))):
    auth.exige_empresa(u, d.empresa_id)
    r = q("""UPDATE tomadores SET razao_social=%s, nome_fantasia=%s, im=%s, email=%s,
               telefone=%s, logradouro=%s, numero=%s, complemento=%s, bairro=%s,
               municipio_ibge=%s, municipio_nome=%s, uf=%s, cep=%s
             WHERE id=%s AND empresa_id=%s RETURNING *""",
          (d.razao_social, d.nome_fantasia, d.im, d.email, d.telefone, d.logradouro,
           d.numero, d.complemento, d.bairro, d.municipio_ibge, d.municipio_nome,
           d.uf, _limpa(d.cep), tid, d.empresa_id), one=True)
    if not r:
        raise HTTPException(404, "Tomador nao encontrado")
    return r


@router.delete("/tomadores/{tid}")
def inativar_tomador(tid: int, empresa_id: int, u=Depends(auth.exige("emitir"))):
    auth.exige_empresa(u, empresa_id)
    q("UPDATE tomadores SET ativo=false WHERE id=%s AND empresa_id=%s", (tid, empresa_id))
    return {"ok": True}


# ---------------------------------------------------------------- config
@router.get("/config")
def ver_config(empresa_id: int, u=Depends(auth.exige("ver"))):
    auth.exige_empresa(u, empresa_id)
    cfg = q("SELECT * FROM nfse_config WHERE empresa_id=%s", (empresa_id,), one=True)
    emp = q("""SELECT e.id, e.razao_social, e.cnpj, e.im, e.municipio_ibge,
                 e.municipio_nome, e.uf, e.simples_optante,
                 m.provedor_nfse, m.giss_slug, m.schema_versao_giss
               FROM empresas e
               LEFT JOIN municipios m ON m.codigo_ibge = e.municipio_ibge
               WHERE e.id=%s""", (empresa_id,), one=True)
    cert = q("""SELECT id, titular_cn, valido_de, valido_ate,
                  (valido_ate::date - current_date) AS dias_para_vencer
                FROM certificados
                WHERE empresa_id=%s AND ativo ORDER BY id DESC LIMIT 1""",
             (empresa_id,), one=True)
    pendencias = []
    if not emp or not emp["municipio_ibge"]:
        pendencias.append("Empresa sem municipio definido.")
    elif not emp["provedor_nfse"]:
        pendencias.append(
            f"O municipio {emp['municipio_nome']}/{emp['uf']} ainda nao tem provedor "
            f"de NFS-e configurado no sistema.")
    if not cert:
        pendencias.append("Empresa sem certificado digital ativo.")
    elif cert["dias_para_vencer"] is not None and cert["dias_para_vencer"] < 0:
        pendencias.append("Certificado digital VENCIDO - a emissao vai falhar.")
    elif cert["dias_para_vencer"] is not None and cert["dias_para_vencer"] <= 30:
        pendencias.append(
            f"Certificado digital vence em {cert['dias_para_vencer']} dia(s). "
            f"Renove para nao interromper a emissao.")
    if not emp or not emp["im"]:
        pendencias.append("Empresa sem inscricao municipal.")
    if not cfg or not cfg["ativo"]:
        pendencias.append("Emissao de NFS-e ainda nao configurada.")
    return {"config": cfg, "empresa": emp, "certificado": cert, "pendencias": pendencias}


@router.put("/config")
def salvar_config(d: ConfigEntrada, u=Depends(auth.exige("emitir"))):
    auth.exige_empresa(u, d.empresa_id)
    atual = q("SELECT proximo_numero FROM nfse_config WHERE empresa_id=%s",
              (d.empresa_id,), one=True)
    prox = d.proximo_numero if d.proximo_numero is not None else \
        (atual["proximo_numero"] if atual else 1)
    return q("""INSERT INTO nfse_config (empresa_id, ambiente, serie_dps, proximo_numero,
                  regime_especial, optante_simples, incentivo_fiscal, aliquota_iss,
                  iss_retido_padrao, observacao_padrao, ativo, atualizado_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (empresa_id) DO UPDATE SET
                  ambiente=EXCLUDED.ambiente, serie_dps=EXCLUDED.serie_dps,
                  proximo_numero=EXCLUDED.proximo_numero,
                  regime_especial=EXCLUDED.regime_especial,
                  optante_simples=EXCLUDED.optante_simples,
                  incentivo_fiscal=EXCLUDED.incentivo_fiscal,
                  aliquota_iss=EXCLUDED.aliquota_iss,
                  iss_retido_padrao=EXCLUDED.iss_retido_padrao,
                  observacao_padrao=EXCLUDED.observacao_padrao,
                  ativo=EXCLUDED.ativo, atualizado_em=now()
                RETURNING *""",
             (d.empresa_id, d.ambiente, d.serie_dps, prox, d.regime_especial,
              d.optante_simples, d.incentivo_fiscal, d.aliquota_iss,
              d.iss_retido_padrao, d.observacao_padrao, d.ativo), one=True)


# ---------------------------------------------------------------- emissao
def _le_retorno(xml):
    """Extrai numero/codigo/situacao/mensagens do retorno da consulta de lote."""
    raiz = etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    situacao = next((e.text for e in raiz.iter()
                     if etree.QName(e).localname == "Situacao"), None)
    numero = raiz.find(f".//{NS}Numero")
    codigo = raiz.find(f".//{NS}CodigoVerificacao")
    return {
        "situacao": situacao,
        "numero": numero.text if numero is not None else None,
        "codigo_verificacao": codigo.text if codigo is not None else None,
        "mensagens": nfse_giss.extrair_mensagens(xml),
    }


@router.post("/emitir")
def emitir(d: EmissaoEntrada, u=Depends(auth.exige("emitir"))):
    auth.exige_empresa(u, d.empresa_id)

    emp = q("SELECT * FROM empresas WHERE id=%s", (d.empresa_id,), one=True)
    srv = q("SELECT * FROM servicos WHERE id=%s AND empresa_id=%s",
            (d.servico_id, d.empresa_id), one=True)
    tom = q("SELECT * FROM tomadores WHERE id=%s AND empresa_id=%s",
            (d.tomador_id, d.empresa_id), one=True)
    cfg = q("SELECT * FROM nfse_config WHERE empresa_id=%s", (d.empresa_id,), one=True)
    if not srv:
        raise HTTPException(400, "Servico nao encontrado")
    if not tom:
        raise HTTPException(400, "Tomador nao encontrado")
    if not cfg or not cfg["ativo"]:
        raise HTTPException(400,
            "Emissao de NFS-e nao configurada para esta empresa.")

    try:
        municipio = nfse_provedor.provedor_do_municipio(emp["municipio_ibge"])
    except nfse_provedor.ProvedorNaoConfigurado as e:
        raise HTTPException(400, str(e))

    # reserva o numero de forma atomica (nunca duplica em emissao concorrente)
    reserva = q("""UPDATE nfse_config SET proximo_numero = proximo_numero + 1
                   WHERE empresa_id=%s
                   RETURNING proximo_numero - 1 AS numero, serie_dps, ambiente""",
                (d.empresa_id,), one=True)
    numero_rps, serie, ambiente = reserva["numero"], reserva["serie_dps"], reserva["ambiente"]

    aliquota = d.aliquota_iss if d.aliquota_iss is not None else \
        (srv["aliquota_iss"] if srv["aliquota_iss"] is not None else cfg["aliquota_iss"])
    iss_retido = d.iss_retido if d.iss_retido is not None else bool(srv["iss_retido"])
    descricao = (d.descricao or srv["descricao"] or "").strip()
    competencia = date.fromisoformat(d.competencia)

    liquido = (_dec(d.valor_servico) - _dec(d.valor_desconto) - _dec(d.valor_pis)
               - _dec(d.valor_cofins) - _dec(d.valor_inss) - _dec(d.valor_ir)
               - _dec(d.valor_csll))

    nota = q("""INSERT INTO nfse_emitidas (empresa_id, tomador_id, servico_id, situacao,
                  provedor, serie_rps, numero_rps, competencia, descricao,
                  codigo_tributacao, valor_servico, valor_deducoes, valor_desconto,
                  aliquota_iss, iss_retido, valor_pis, valor_cofins, valor_inss,
                  valor_ir, valor_csll, valor_liquido, criado_por)
                VALUES (%s,%s,%s,'processando',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s)
                RETURNING id""",
             (d.empresa_id, d.tomador_id, d.servico_id, municipio["provedor_nfse"],
              serie, numero_rps, competencia, descricao, srv["codigo_tributacao"],
              d.valor_servico, d.valor_deducoes, d.valor_desconto, aliquota,
              iss_retido, d.valor_pis, d.valor_cofins, d.valor_inss, d.valor_ir,
              d.valor_csll, liquido, u["id"]), one=True)
    nid = nota["id"]

    dados = {
        "numero_rps": numero_rps, "serie_rps": serie,
        "data_emissao": date.today(), "competencia": competencia,
        "valor_servico": d.valor_servico, "valor_deducoes": d.valor_deducoes,
        "valor_desconto": d.valor_desconto, "valor_pis": d.valor_pis,
        "valor_cofins": d.valor_cofins, "valor_inss": d.valor_inss,
        "valor_ir": d.valor_ir, "valor_csll": d.valor_csll,
        "iss_retido": iss_retido, "aliquota_iss": aliquota,
        "item_lista_servico": srv["item_lista_servico"], "codigo_nbs": srv["codigo_nbs"],
        "cind_op": srv["cind_op"], "cclass_trib": srv["cclass_trib"],
        "codigo_tributacao": srv["codigo_tributacao"], "descricao": descricao,
        "municipio_prestacao_ibge": srv["municipio_incidencia"] or emp["municipio_ibge"],
        "prestador_cnpj": emp["cnpj"], "prestador_im": emp["im"], "prestador_municipio_ibge": emp["municipio_ibge"],
        "tomador_tipo_doc": tom["tipo_doc"], "tomador_documento": tom["documento"],
        "tomador_razao_social": tom["razao_social"], "tomador_im": tom["im"],
        "tomador_email": tom["email"], "tomador_logradouro": tom["logradouro"],
        "tomador_numero": tom["numero"], "tomador_complemento": tom["complemento"],
        "tomador_bairro": tom["bairro"], "tomador_municipio_ibge": tom["municipio_ibge"],
        "tomador_uf": tom["uf"], "tomador_cep": tom["cep"],
        "optante_simples": bool(cfg["optante_simples"]),
        "regime_especial": cfg["regime_especial"],
    }

    def rejeita(motivo, cstat=None):
        q("UPDATE nfse_emitidas SET situacao='rejeitada', motivo=%s, cstat=%s WHERE id=%s",
          (motivo[:500], cstat, nid))
        return {"ok": False, "nfse_id": nid, "situacao": "rejeitada", "erro": motivo}

    try:
        rps = nfse_giss.montar_rps(dados, f"rps_{nid}",
                                   incluir_ibscbs=nfse_giss.usa_ibscbs(municipio))
        envio = nfse_giss.montar_e_assinar(d.empresa_id, numero_rps, emp["cnpj"],
                                           emp["im"], [rps], sincrono=False)
    except ValueError as e:
        return rejeita(str(e))

    erros_schema = nfse_giss.validar(envio)
    if erros_schema:
        return rejeita("XML invalido pelo schema oficial: " + " | ".join(erros_schema[:3]))

    r = nfse_giss.enviar_lote(d.empresa_id, municipio, envio,
                              ambiente=ambiente, sincrono=False)
    if not r["ok"]:
        return rejeita(r["erro"])

    msgs = nfse_giss.extrair_mensagens(r["retorno"])
    if msgs:
        return rejeita(" | ".join(f"[{m['codigo']}] {m['mensagem']}" for m in msgs),
                       msgs[0]["codigo"])

    prot = re.search(r"<[^>]*Protocolo>([^<]+)<", r["retorno"])
    protocolo = prot.group(1) if prot else None
    q("UPDATE nfse_emitidas SET protocolo_lote=%s WHERE id=%s", (protocolo, nid))

    # consulta o lote na sequencia (emissao sincrona para o usuario)
    return _consultar_e_gravar(nid, d.empresa_id, emp, municipio, protocolo, ambiente)


def _consultar_e_gravar(nid, empresa_id, emp, municipio, protocolo, ambiente):
    """Consulta o lote e grava o desfecho. Se a consulta falhar, a nota fica
    'processando' com o protocolo salvo - recuperavel depois."""
    c = nfse_giss.consultar_lote(empresa_id, municipio, emp["cnpj"], protocolo,
                                 ambiente=ambiente)
    if not c["ok"]:
        return {"ok": True, "nfse_id": nid, "situacao": "processando",
                "protocolo": protocolo,
                "aviso": "Lote transmitido, mas a consulta falhou. Use 'Consultar' "
                         "para verificar o resultado. " + c["erro"][:200]}

    info = _le_retorno(c["retorno"])

    # A01/A02 sao falhas TRANSITORIAS da consulta (servico ocupado, consulta
    # concorrente), nao rejeicao da nota. Marcar como rejeitada faria o usuario
    # reemitir e gerar nota em duplicidade.
    transitorios = {"A01", "A02", "A03"}
    codigos = {m["codigo"] for m in info["mensagens"] if m.get("codigo")}
    if codigos and codigos <= transitorios:
        return {"ok": True, "nfse_id": nid, "situacao": "processando",
                "protocolo": protocolo,
                "aviso": "A prefeitura esta processando outra consulta desta "
                         "empresa. Aguarde alguns segundos e consulte de novo."}

    if info["numero"]:
        q("""UPDATE nfse_emitidas SET situacao='autorizada', numero_nfse=%s,
               xml_nfse=%s, emissao=now(), motivo=NULL, cstat=NULL WHERE id=%s""",
          (info["numero"], c["retorno"], nid))
        return {"ok": True, "nfse_id": nid, "situacao": "autorizada",
                "numero_nfse": info["numero"],
                "codigo_verificacao": info["codigo_verificacao"],
                "protocolo": protocolo}

    if info["situacao"] == "2":
        return {"ok": True, "nfse_id": nid, "situacao": "processando",
                "protocolo": protocolo,
                "aviso": "Lote recebido e aguardando processamento na prefeitura."}

    motivo = " | ".join(f"[{m['codigo']}] {m['mensagem']}" for m in info["mensagens"]) \
        or "Lote processado com erro."
    q("UPDATE nfse_emitidas SET situacao='rejeitada', motivo=%s, cstat=%s, xml_nfse=%s "
      "WHERE id=%s",
      (motivo[:500], info["mensagens"][0]["codigo"] if info["mensagens"] else None,
       c["retorno"], nid))
    return {"ok": False, "nfse_id": nid, "situacao": "rejeitada", "erro": motivo,
            "mensagens": info["mensagens"]}


@router.post("/notas/{nid}/consultar")
def consultar_nota(nid: int, u=Depends(auth.exige("ver"))):
    """Reconsulta o protocolo de uma nota que ficou em processamento."""
    n = _nota_no_escopo(u, nid)
    if not n["protocolo_lote"]:
        raise HTTPException(400, "Nota sem protocolo - nao chegou a ser transmitida.")
    emp = q("SELECT * FROM empresas WHERE id=%s", (n["empresa_id"],), one=True)
    cfg = q("SELECT ambiente FROM nfse_config WHERE empresa_id=%s",
            (n["empresa_id"],), one=True)
    municipio = nfse_provedor.provedor_do_municipio(emp["municipio_ibge"])
    return _consultar_e_gravar(nid, n["empresa_id"], emp, municipio,
                               n["protocolo_lote"], (cfg or {}).get("ambiente", "1"))


# ---------------------------------------------------------------- notas
@router.get("/notas")
def listar_notas(empresa_id: int, situacao: str = "", inicio: str = "",
                 fim: str = "", busca: str = "", u=Depends(auth.exige("ver"))):
    auth.exige_empresa(u, empresa_id)
    sql = ["""SELECT n.*, t.razao_social AS tomador_nome, t.documento AS tomador_doc,
                s.apelido AS servico_apelido
              FROM nfse_emitidas n
              LEFT JOIN tomadores t ON t.id = n.tomador_id
              LEFT JOIN servicos  s ON s.id = n.servico_id
              WHERE n.empresa_id = %s"""]
    p = [empresa_id]
    if situacao:
        sql.append("AND n.situacao = %s"); p.append(situacao)
    if inicio:
        sql.append("AND n.competencia >= %s"); p.append(inicio)
    if fim:
        sql.append("AND n.competencia <= %s"); p.append(fim)
    if busca:
        sql.append("AND (t.razao_social ILIKE %s OR n.numero_nfse ILIKE %s "
                   "OR n.descricao ILIKE %s)")
        p += [f"%{busca}%"] * 3
    sql.append("ORDER BY n.id DESC LIMIT 500")
    linhas = q(" ".join(sql), tuple(p))

    resumo = q("""SELECT situacao, count(*) AS qtd, coalesce(sum(valor_servico),0) AS total
                  FROM nfse_emitidas WHERE empresa_id=%s GROUP BY situacao""",
               (empresa_id,))
    return {"notas": linhas, "resumo": {r["situacao"]: r for r in resumo}}


@router.get("/notas/{nid}")
def ver_nota(nid: int, u=Depends(auth.exige("ver"))):
    n = _nota_no_escopo(u, nid)
    n["tomador"] = q("SELECT * FROM tomadores WHERE id=%s", (n["tomador_id"],), one=True)
    n["servico"] = q("SELECT * FROM servicos WHERE id=%s", (n["servico_id"],), one=True)
    return n


@router.get("/notas/{nid}/danfse")
def baixar_danfse(nid: int, u=Depends(auth.exige("ver"))):
    n = _nota_no_escopo(u, nid)
    if n["situacao"] != "autorizada":
        raise HTTPException(400, "So notas autorizadas geram DANFSe.")
    emp = q("""SELECT m.giss_slug FROM empresas e
               LEFT JOIN municipios m ON m.codigo_ibge = e.municipio_ibge
               WHERE e.id=%s""", (n["empresa_id"],), one=True)
    url = (f"{emp['giss_slug']}.giss.com.br/portal/home#/verificacao-autenticidade-nfse"
           if emp and emp.get("giss_slug") else "")
    pdf = danfse.gerar(nid, url_verificacao=url)
    nome = f"NFSe_{n['numero_nfse'] or nid}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{nome}"'})


@router.get("/notas/{nid}/xml")
def baixar_xml(nid: int, u=Depends(auth.exige("ver"))):
    n = _nota_no_escopo(u, nid)
    if not n["xml_nfse"]:
        raise HTTPException(404, "Nota sem XML.")
    nome = f"NFSe_{n['numero_nfse'] or nid}.xml"
    return Response(n["xml_nfse"], media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


# ---------------------------------------------------------------- cancelamento
@router.post("/notas/{nid}/cancelar")
def cancelar(nid: int, d: CancelamentoEntrada, u=Depends(auth.exige("emitir"))):
    """Cancela a NFS-e na prefeitura. Codigos 3 e 5 sao de uso exclusivo do
    municipio - so 1, 2 e 4 podem partir do contribuinte."""
    n = _nota_no_escopo(u, nid)
    if n["situacao"] != "autorizada":
        raise HTTPException(400, "So notas autorizadas podem ser canceladas.")
    if d.codigo not in ("1", "2", "4"):
        raise HTTPException(400,
            "Codigo invalido. Use 1 (erro na emissao), 2 (servico nao prestado) "
            "ou 4 (duplicidade).")

    emp = q("SELECT * FROM empresas WHERE id=%s", (n["empresa_id"],), one=True)
    cfg = q("SELECT ambiente FROM nfse_config WHERE empresa_id=%s",
            (n["empresa_id"],), one=True)
    municipio = nfse_provedor.provedor_do_municipio(emp["municipio_ibge"])

    # a assinatura vai dentro do <Pedido>; assinar o envelope da E160
    assinado = nfse_giss.montar_e_assinar_cancelamento(
        n["empresa_id"], n["numero_nfse"], emp["cnpj"], emp["im"],
        emp["municipio_ibge"], d.codigo, f"canc_{nid}")

    r = nfse_giss.cancelar_nfse(n["empresa_id"], municipio, assinado,
                                ambiente=(cfg or {}).get("ambiente", "1"))
    if not r["ok"]:
        raise HTTPException(502, f"Falha ao cancelar: {r['erro'][:300]}")

    msgs = nfse_giss.extrair_mensagens(r["retorno"])
    if msgs:
        return {"ok": False, "erro": " | ".join(
            f"[{m['codigo']}] {m['mensagem']}" for m in msgs), "mensagens": msgs}

    q("""UPDATE nfse_emitidas SET situacao='cancelada', cancelada_em=now(),
           cancelamento_motivo=%s WHERE id=%s""",
      (d.motivo or {"1": "Erro na emissao", "2": "Servico nao prestado",
                    "4": "Duplicidade da nota"}[d.codigo], nid))
    q("""INSERT INTO nfse_eventos (nfse_id, tipo, motivo, xml, retorno, usuario_id)
         VALUES (%s,'cancelamento',%s,%s,%s,%s)""",
      (nid, d.motivo, etree.tostring(assinado, encoding="unicode"),
       r["retorno"], u["id"]))
    return {"ok": True, "situacao": "cancelada"}
