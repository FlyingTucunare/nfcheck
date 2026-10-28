"""Roteador de provedor de NFS-e.

Decide, pelo municipio da empresa emitente, se a nota sai pelo Emissor
Nacional (nfse.py) ou pelo GISS Online / padrao ABRASF (nfse_giss.py),
e normaliza os dados de emissao para o formato que cada motor espera.

Motivo de existir: Guarulhos aderiu ao ADN mas nao parametrizou o Emissor
Nacional (erro E0039), entao precisa sair pelo GISS. Quando a prefeitura
migrar, basta trocar municipios.provedor_nfse para 'emissor_nacional' -
nenhuma mudanca de codigo.
"""
from datetime import date

from db import q
import nfse
import nfse_giss

EMISSOR_NACIONAL = "emissor_nacional"
GISS_ABRASF = "giss_abrasf"


class ProvedorNaoConfigurado(Exception):
    """Municipio sem provedor definido na tabela municipios."""


def provedor_do_municipio(codigo_ibge):
    """Devolve a linha de municipios com a config de provedor.
    Levanta ProvedorNaoConfigurado se o municipio nao estiver mapeado."""
    m = q(
        "SELECT codigo_ibge, nome, uf, provedor_nfse, giss_slug, schema_versao_giss "
        "FROM municipios WHERE codigo_ibge = %s",
        (str(codigo_ibge),), one=True,
    )
    if not m:
        raise ProvedorNaoConfigurado(
            f"Municipio {codigo_ibge} nao encontrado na tabela municipios."
        )
    if not m["provedor_nfse"]:
        raise ProvedorNaoConfigurado(
            f"Municipio {m['nome']}/{m['uf']} ainda nao tem provedor de NFS-e "
            f"configurado. Defina municipios.provedor_nfse antes de emitir."
        )
    if m["provedor_nfse"] == GISS_ABRASF and not m["giss_slug"]:
        raise ProvedorNaoConfigurado(
            f"Municipio {m['nome']}/{m['uf']} esta marcado como GISS mas nao "
            f"tem giss_slug definido (necessario para montar a URL do webservice)."
        )
    return m


def provedor_da_empresa(empresa_id):
    """Atalho: resolve o provedor a partir do municipio da empresa."""
    e = q(
        "SELECT id, municipio_ibge, municipio_nome FROM empresas WHERE id = %s",
        (empresa_id,), one=True,
    )
    if not e:
        raise ProvedorNaoConfigurado(f"Empresa {empresa_id} nao encontrada.")
    if not e["municipio_ibge"]:
        raise ProvedorNaoConfigurado(
            f"Empresa {empresa_id} sem municipio_ibge preenchido."
        )
    return provedor_do_municipio(e["municipio_ibge"])


def carregar_dados_emissao(nfse_id):
    """Monta o dicionario completo de uma nota a emitir, juntando
    nfse_emitidas + empresas + tomadores + servicos + nfse_config.
    Formato neutro - cada motor traduz pro seu leiaute."""
    d = q(
        """
        SELECT
            n.id, n.empresa_id, n.competencia, n.descricao, n.codigo_tributacao,
            n.valor_servico, n.valor_deducoes, n.valor_desconto,
            n.aliquota_iss, n.iss_retido,
            n.valor_pis, n.valor_cofins, n.valor_inss, n.valor_ir, n.valor_csll,
            n.serie_dps, n.numero_dps, n.serie_rps, n.numero_rps,
            e.cnpj    AS prestador_cnpj,
            e.im      AS prestador_im,
            e.municipio_ibge AS municipio_emissor,
            t.tipo_doc       AS tomador_tipo_doc,
            t.documento      AS tomador_documento,
            t.razao_social   AS tomador_razao_social,
            t.im             AS tomador_im,
            t.email          AS tomador_email,
            t.logradouro     AS tomador_logradouro,
            t.numero         AS tomador_numero,
            t.complemento    AS tomador_complemento,
            t.bairro         AS tomador_bairro,
            t.municipio_ibge AS tomador_municipio_ibge,
            t.uf             AS tomador_uf,
            t.cep            AS tomador_cep,
            s.item_lista_servico, s.codigo_nbs, s.cind_op, s.cclass_trib,
            s.municipio_incidencia,
            c.ambiente, c.optante_simples, c.regime_especial
        FROM nfse_emitidas n
        JOIN empresas e     ON e.id = n.empresa_id
        LEFT JOIN tomadores t ON t.id = n.tomador_id
        LEFT JOIN servicos  s ON s.id = n.servico_id
        LEFT JOIN nfse_config c ON c.empresa_id = n.empresa_id
        WHERE n.id = %s
        """,
        (nfse_id,), one=True,
    )
    if not d:
        raise ValueError(f"NFS-e {nfse_id} nao encontrada.")
    return d


def _validar_campos_giss(d):
    """O leiaute GISS com IBS/CBS exige campos que o Emissor Nacional nao usa.
    Falha cedo e com mensagem clara em vez de deixar a SEFAZ rejeitar."""
    faltando = []
    if not d.get("item_lista_servico"):
        faltando.append("item_lista_servico (item da LC 116)")
    if not d.get("cind_op"):
        faltando.append("cind_op (codigo indicador da operacao)")
    if not d.get("cclass_trib"):
        faltando.append("cclass_trib (classificacao tributaria IBS/CBS)")
    if faltando:
        raise ValueError(
            "Servico incompleto para emissao no padrao ABRASF/IBS-CBS. "
            "Faltam: " + ", ".join(faltando) +
            ". Complete o cadastro do servico (a sugestao automatica vem da "
            "tabela correlacao_nbs_ibscbs)."
        )


def _dados_para_nacional(d):
    """Traduz o dicionario neutro para o formato de nfse.montar_dps()."""
    return {
        "ambiente": d.get("ambiente") or "2",
        "municipio_emissor": d["municipio_emissor"],
        "prestador_cnpj": d["prestador_cnpj"],
        "prestador_im": d.get("prestador_im"),
        "op_simples": "1" if d.get("optante_simples") else "2",
        "reg_especial": d.get("regime_especial") or "0",
        "serie": d.get("serie_dps") or "00001",
        "numero": d["numero_dps"],
        "competencia": d["competencia"].strftime("%Y-%m-%d"),
        "tomador_tipo": d.get("tomador_tipo_doc") or "cnpj",
        "tomador_doc": d.get("tomador_documento"),
        "tomador_nome": d.get("tomador_razao_social"),
        "tomador_ibge": d.get("tomador_municipio_ibge"),
        "tomador_cep": d.get("tomador_cep"),
        "tomador_logradouro": d.get("tomador_logradouro"),
        "tomador_numero": d.get("tomador_numero"),
        "tomador_complemento": d.get("tomador_complemento"),
        "tomador_bairro": d.get("tomador_bairro"),
        "tomador_email": d.get("tomador_email"),
        "codigo_tributacao": d.get("codigo_tributacao"),
        "cnae": d.get("codigo_nbs"),
        "descricao": d["descricao"],
        "valor_servico": d["valor_servico"],
        "valor_desconto": d.get("valor_desconto"),
        "aliquota_iss": d.get("aliquota_iss"),
        "iss_retido": d.get("iss_retido"),
        "municipio_incidencia": d.get("municipio_incidencia"),
        "trib_issqn": "1",
    }


def _dados_para_giss(d):
    """Traduz o dicionario neutro para o formato de nfse_giss.montar_rps()."""
    _validar_campos_giss(d)
    return {
        "numero_rps": d["numero_rps"],
        "serie_rps": d.get("serie_rps") or "00001",
        "data_emissao": date.today(),
        "competencia": d["competencia"],
        "valor_servico": d["valor_servico"],
        "valor_deducoes": d.get("valor_deducoes"),
        "valor_desconto": d.get("valor_desconto"),
        "valor_pis": d.get("valor_pis"),
        "valor_cofins": d.get("valor_cofins"),
        "valor_inss": d.get("valor_inss"),
        "valor_ir": d.get("valor_ir"),
        "valor_csll": d.get("valor_csll"),
        "iss_retido": d.get("iss_retido"),
        "item_lista_servico": d["item_lista_servico"],
        "codigo_nbs": d.get("codigo_nbs"),
        "cind_op": d["cind_op"],
        "cclass_trib": d["cclass_trib"],
        "codigo_tributacao": d.get("codigo_tributacao"),
        "descricao": d["descricao"],
        "municipio_prestacao_ibge": d.get("municipio_incidencia") or d["municipio_emissor"],
        "prestador_cnpj": d["prestador_cnpj"],
        "prestador_im": d.get("prestador_im"),
        "tomador_tipo_doc": d.get("tomador_tipo_doc") or "cnpj",
        "tomador_documento": d.get("tomador_documento"),
        "tomador_razao_social": d.get("tomador_razao_social"),
        "tomador_im": d.get("tomador_im"),
        "tomador_email": d.get("tomador_email"),
        "tomador_logradouro": d.get("tomador_logradouro"),
        "tomador_numero": d.get("tomador_numero"),
        "tomador_complemento": d.get("tomador_complemento"),
        "tomador_bairro": d.get("tomador_bairro"),
        "tomador_municipio_ibge": d.get("tomador_municipio_ibge"),
        "tomador_uf": d.get("tomador_uf"),
        "tomador_cep": d.get("tomador_cep"),
        "optante_simples": d.get("optante_simples"),
    }


def proximo_numero(empresa_id, provedor):
    """Reserva o proximo numero (DPS ou RPS conforme o provedor) de forma
    atomica, para nao gerar numero duplicado em emissoes concorrentes."""
    r = q(
        "UPDATE nfse_config SET proximo_numero = proximo_numero + 1 "
        "WHERE empresa_id = %s RETURNING proximo_numero - 1 AS numero, serie_dps",
        (empresa_id,), one=True,
    )
    if not r:
        raise ValueError(
            f"Empresa {empresa_id} sem nfse_config. Configure a emissao de "
            f"NFS-e antes de emitir."
        )
    return r["numero"], r["serie_dps"]


def emitir(nfse_id):
    """Emite a NFS-e pelo provedor correto do municipio da empresa.

    Retorna dict padronizado:
      {"ok": bool, "provedor": str, ...campos especificos do provedor}

    Para o Emissor Nacional o retorno e sincrono (ja traz a chave).
    Para o GISS o envio e ASSINCRONO: devolve o protocolo, e o numero
    da NFS-e so vem depois via consultar().
    """
    d = carregar_dados_emissao(nfse_id)
    municipio = provedor_do_municipio(d["municipio_emissor"])
    empresa_id = d["empresa_id"]
    ambiente = d.get("ambiente") or "2"

    if municipio["provedor_nfse"] == EMISSOR_NACIONAL:
        dados = _dados_para_nacional(d)
        xml = nfse.montar_dps(dados)
        assinado = nfse.assinar(empresa_id, xml)
        r = nfse.transmitir(empresa_id, assinado, ambiente)
        r["provedor"] = EMISSOR_NACIONAL
        r["xml_enviado"] = assinado
        return r

    # --- GISS / ABRASF ---
    dados = _dados_para_giss(d)
    rps_id = f"rps_{nfse_id}"
    rps = nfse_giss.montar_rps(dados, rps_id)
    rps_assinado = nfse_giss.assinar(empresa_id, rps, rps_id)

    # Lote de 1 RPS. O leiaute aceita ate 50 - emissao em lote maior
    # entra depois, na tela de emissao por planilha.
    numero_lote = dados["numero_rps"]
    envio, lote_id = nfse_giss.montar_lote(
        numero_lote, dados["prestador_cnpj"], dados.get("prestador_im"),
        [rps_assinado],
    )
    # O lote e assinado POR ULTIMO - assinar antes quebra a assinatura dos RPS.
    envio_assinado = nfse_giss.assinar(empresa_id, envio, lote_id)

    r = nfse_giss.enviar_lote(empresa_id, municipio, envio_assinado, ambiente)
    r["provedor"] = GISS_ABRASF
    r["numero_lote"] = numero_lote
    return r


def consultar(nfse_id):
    """Consulta a situacao de uma nota ja transmitida.
    No GISS, e o passo que converte protocolo -> numero de NFS-e."""
    d = carregar_dados_emissao(nfse_id)
    municipio = provedor_do_municipio(d["municipio_emissor"])
    ambiente = d.get("ambiente") or "2"

    if municipio["provedor_nfse"] == EMISSOR_NACIONAL:
        chave = q(
            "SELECT chave_acesso FROM nfse_emitidas WHERE id = %s",
            (nfse_id,), one=True,
        )
        if not chave or not chave["chave_acesso"]:
            return {"ok": False, "erro": "Nota sem chave de acesso - nao foi transmitida."}
        r = nfse.consultar(d["empresa_id"], chave["chave_acesso"], ambiente)
        r["provedor"] = EMISSOR_NACIONAL
        return r

    protocolo = q(
        "SELECT protocolo_lote FROM nfse_emitidas WHERE id = %s",
        (nfse_id,), one=True,
    )
    if not protocolo or not protocolo["protocolo_lote"]:
        return {"ok": False, "erro": "Nota sem protocolo de lote - nao foi transmitida."}
    r = nfse_giss.consultar_lote(
        d["empresa_id"], municipio, d["prestador_cnpj"],
        protocolo["protocolo_lote"], ambiente,
    )
    r["provedor"] = GISS_ABRASF
    return r


def sugerir_classificacao(item_lista_servico, codigo_nbs=None):
    """Sugere cind_op / cclass_trib a partir da tabela de correlacao oficial.
    Usado no cadastro de servico. Devolve lista de opcoes (pode haver mais
    de uma cClassTrib para o mesmo item - ex: regra geral + Anexo XI)."""
    if codigo_nbs:
        linhas = q(
            "SELECT DISTINCT codigo_nbs, descricao_nbs, cind_op, local_incidencia, "
            "cclass_trib, nome_cclass_trib "
            "FROM correlacao_nbs_ibscbs "
            "WHERE item_lista_servico = %s AND codigo_nbs = %s "
            "AND cclass_trib IS NOT NULL AND cclass_trib <> '' "
            "ORDER BY cclass_trib",
            (item_lista_servico, codigo_nbs),
        )
        if linhas:
            return linhas
    return q(
        "SELECT DISTINCT codigo_nbs, descricao_nbs, cind_op, local_incidencia, "
        "cclass_trib, nome_cclass_trib "
        "FROM correlacao_nbs_ibscbs "
        "WHERE item_lista_servico = %s "
        "AND cclass_trib IS NOT NULL AND cclass_trib <> '' "
        "ORDER BY cclass_trib",
        (item_lista_servico,),
    )


def nbs_do_item(item_lista_servico):
    """Lista os codigos NBS validos para um item da LC 116 (para o combo
    de cadastro de servico)."""
    return q(
        "SELECT DISTINCT codigo_nbs, descricao_nbs "
        "FROM correlacao_nbs_ibscbs "
        "WHERE item_lista_servico = %s AND codigo_nbs IS NOT NULL "
        "AND codigo_nbs <> '' ORDER BY codigo_nbs",
        (item_lista_servico,),
    )
