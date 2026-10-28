from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import receita
from db import q
import auth

router = APIRouter(prefix="/api/empresas", tags=["empresas"])

def _aud(u, acao, empresa_id=None, detalhe=None, request=None):
    import json
    q("""INSERT INTO auditoria (usuario_id,contabilidade_id,empresa_id,acao,detalhe,ip)
         VALUES (%s,%s,%s,%s,%s,%s)""",
      (u["id"], u["contabilidade_id"], empresa_id, acao,
       json.dumps(detalhe or {}), request.client.host if request and request.client else None))

@router.get("/consultar-cnpj/{cnpj}")
def consultar(cnpj: str, u=Depends(auth.exige("empresa_escrever"))):
    c = receita.limpa(cnpj)
    ja = q("""SELECT e.id, e.razao_social, c.razao_social AS contabilidade
              FROM empresas e JOIN contabilidades c ON c.id=e.contabilidade_id
              WHERE e.cnpj=%s""", (c,), one=True)
    try:
        d = receita.consulta(c, conn_q=q)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    d.pop("bruto", None)
    d["ja_cadastrada"] = bool(ja)
    d["ja_cadastrada_em"] = ja["contabilidade"] if ja else None
    return d

class NovaEmpresa(BaseModel):
    cnpj: str
    regime_tributario: Optional[str] = None
    ie: Optional[str] = None
    im: Optional[str] = None
    observacoes: Optional[str] = None

@router.post("")
def criar(dados: NovaEmpresa, request: Request, u=Depends(auth.exige("empresa_escrever"))):
    c = receita.limpa(dados.cnpj)
    if len(c) != 14:
        raise HTTPException(400, "CNPJ invalido")
    if q("SELECT id FROM empresas WHERE cnpj=%s", (c,), one=True):
        raise HTTPException(409, "Este CNPJ ja esta cadastrado. Solicite a transferencia.")

    cont_id = u["contabilidade_id"]
    if u["perfil"] == "superadmin" and not cont_id:
        raise HTTPException(400, "Superadmin deve informar a contabilidade")

    lim = q("""SELECT limite_empresas,
                 (SELECT COUNT(*) FROM empresas WHERE contabilidade_id=%s) AS usadas
               FROM contabilidades WHERE id=%s""", (cont_id, cont_id), one=True)
    if lim and lim["usadas"] >= lim["limite_empresas"]:
        raise HTTPException(403, f"Limite de {lim['limite_empresas']} empresas atingido")

    try:
        d = receita.consulta(c, conn_q=q)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))

    import json
    regime = dados.regime_tributario or (
        "Simples Nacional" if d.get("simples_optante") else None)

    emp = q("""INSERT INTO empresas
      (contabilidade_id,razao_social,nome_fantasia,cnpj,cnpj_raiz,ie,im,
       municipio_ibge,municipio_nome,uf,regime_tributario,matriz_filial,
       situacao_cadastral,situacao_data,situacao_motivo,situacao_especial,abertura,
       natureza_juridica,natureza_juridica_cod,porte,capital_social,
       cnae_principal,cnae_principal_desc,logradouro,numero,complemento,bairro,cep,
       telefone1,telefone2,email,simples_optante,simples_desde,simples_ate,
       mei_optante,mei_desde,receita_bruto,receita_fonte,receita_consultado_em,observacoes)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
              %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s)
      RETURNING id, razao_social, cnpj""",
      (cont_id, d["razao_social"], d["nome_fantasia"], c, c[:8], dados.ie, dados.im,
       d["municipio_ibge"], d["municipio_nome"], d["uf"], regime, d["matriz_filial"],
       d["situacao_cadastral"], d["situacao_data"], d["situacao_motivo"],
       d["situacao_especial"], d["abertura"], d["natureza_juridica"],
       d["natureza_juridica_cod"], d["porte"], d["capital_social"],
       d["cnae_principal"], d["cnae_principal_desc"], d["logradouro"], d["numero"],
       d["complemento"], d["bairro"], d["cep"], d["telefone1"], d["telefone2"],
       d["email"], d["simples_optante"], d["simples_desde"], d["simples_ate"],
       d["mei_optante"], d["mei_desde"], json.dumps(d["bruto"]), d["fonte"],
       dados.observacoes), one=True)

    eid = emp["id"]
    if d["cnae_principal"]:
        q("""INSERT INTO empresa_cnaes (empresa_id,codigo,descricao,principal)
             VALUES (%s,%s,%s,TRUE)""", (eid, d["cnae_principal"], d["cnae_principal_desc"]))
    for cn in d["cnaes"]:
        q("""INSERT INTO empresa_cnaes (empresa_id,codigo,descricao,principal)
             VALUES (%s,%s,%s,FALSE)""", (eid, cn["codigo"], cn["descricao"]))
    for s in d["socios"]:
        q("""INSERT INTO empresa_socios
             (empresa_id,nome,documento,qualificacao,faixa_etaria,entrada,pais,
              representante_nome,representante_doc,representante_qualif)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (eid, s["nome"], s["documento"], s["qualificacao"], s["faixa_etaria"],
           s["entrada"], s["pais"], s["representante_nome"], s["representante_doc"],
           s["representante_qualif"]))
    if dados.ie:
        q("""INSERT INTO empresa_inscricoes (empresa_id,tipo,numero,uf)
             VALUES (%s,'ie',%s,%s)""", (eid, dados.ie, d["uf"]))
    if dados.im:
        q("""INSERT INTO empresa_inscricoes (empresa_id,tipo,numero,municipio_ibge)
             VALUES (%s,'im',%s,%s)""", (eid, dados.im, d["municipio_ibge"]))

    for origem in ("sefaz_nfe", "sefaz_cte", "adn"):
        q("""INSERT INTO cursores_dfe (empresa_id,origem) VALUES (%s,%s)
             ON CONFLICT DO NOTHING""", (eid, origem))

    _aud(u, "empresa_criada", eid, {"cnpj": c, "fonte": d["fonte"]}, request)
    return emp

@router.get("")
def listar(arquivadas: bool = False, u=Depends(auth.usuario_atual)):
    """Lista com indicadores do mes corrente. Uma query agregada, nao uma por empresa."""
    ids = [e["id"] for e in auth.empresas_visiveis(u)]
    if not ids:
        return []
    return q("""
      WITH mes AS (
        SELECT empresa_id,
               COUNT(*)                                   AS docs_mes,
               COALESCE(SUM(valor),0)                     AS valor_mes,
               COUNT(*) FILTER (WHERE manifestacao IS NULL
                                  AND NOT resumo)         AS pendentes
          FROM documentos
         WHERE empresa_id = ANY(%(ids)s)
           AND emissao >= date_trunc('month', NOW() AT TIME ZONE 'America/Sao_Paulo')
         GROUP BY empresa_id
      ), tot AS (
        SELECT empresa_id,
               COUNT(*)                       AS docs_total,
               COALESCE(SUM(valor),0)         AS valor_total,
               COUNT(*) FILTER (WHERE resumo) AS resumos
          FROM documentos
         WHERE empresa_id = ANY(%(ids)s)
         GROUP BY empresa_id
      ), cur AS (
        SELECT empresa_id,
               MAX(ultima_sync)                                        AS ultima_sync,
               MAX(ultimo_nsu) FILTER (WHERE origem='sefaz_nfe')       AS nsu_nfe,
               MAX(ultimo_nsu) FILTER (WHERE origem='sefaz_cte')       AS nsu_cte,
               BOOL_OR(pausado)                                        AS pausado
          FROM cursores_dfe
         WHERE empresa_id = ANY(%(ids)s)
         GROUP BY empresa_id
      )
      SELECT e.id, e.razao_social, e.nome_fantasia, e.cnpj, e.municipio_nome, e.uf,
             e.regime_tributario, e.porte, e.situacao_cadastral, e.status,
             c.valido_ate AS cert_ate, c.titular_cn AS cert_titular,
             (c.id IS NOT NULL) AS tem_cert,
             CASE WHEN c.id IS NULL THEN 'sem'
                  WHEN c.valido_ate < NOW() THEN 'vencido'
                  WHEN c.valido_ate < NOW() + INTERVAL '30 days' THEN 'vencendo'
                  ELSE 'ok' END AS cert_status,
             COALESCE(m.docs_mes,0)  AS docs_mes,
             COALESCE(m.valor_mes,0) AS valor_mes,
             COALESCE(m.pendentes,0) AS pendentes,
             COALESCE(t.docs_total,0)  AS docs_total,
             COALESCE(t.valor_total,0) AS valor_total,
             COALESCE(t.resumos,0)     AS resumos,
             cur.ultima_sync, cur.nsu_nfe, cur.nsu_cte,
             COALESCE(cur.pausado,FALSE) AS pausado,
             cf.janela_ativa, cf.janela_inicio, cf.janela_fim,
             cf.ciencia_auto, cf.janela_herdada, cf.ciencia_herdada,
             e.arquivada_em, (e.arquivada_em IS NOT NULL) AS arquivada
      FROM empresas e
      LEFT JOIN certificados c ON c.empresa_id=e.id AND c.ativo
      LEFT JOIN mes m   ON m.empresa_id=e.id
      LEFT JOIN tot t   ON t.empresa_id=e.id
      LEFT JOIN cur     ON cur.empresa_id=e.id
      LEFT JOIN config_efetiva cf ON cf.empresa_id=e.id
      WHERE e.id = ANY(%(ids)s)
        AND (%(arq)s OR e.arquivada_em IS NULL)
      ORDER BY e.razao_social""", {"ids": ids, "arq": arquivadas})


class ConfigSync(BaseModel):
    janela_ativa: Optional[bool] = None
    janela_inicio: Optional[str] = None
    janela_fim: Optional[str] = None
    ciencia_auto: Optional[bool] = None
    herdar: bool = False

@router.put("/{empresa_id}/sincronizacao")
def config_sync(empresa_id: int, dados: ConfigSync, request: Request,
                u=Depends(auth.exige("empresa_escrever"))):
    """Salva a configuracao da empresa. herdar=True limpa e volta ao padrao do escritorio."""
    auth.exige_empresa(u, empresa_id)
    if dados.herdar:
        q("""UPDATE empresas SET janela_ativa=NULL, janela_inicio=NULL,
             janela_fim=NULL, ciencia_auto=NULL WHERE id=%s""", (empresa_id,))
    else:
        if dados.janela_ativa and not (dados.janela_inicio and dados.janela_fim):
            raise HTTPException(400, "Informe inicio e fim da janela.")
        q("""UPDATE empresas SET janela_ativa=%s, janela_inicio=%s,
             janela_fim=%s, ciencia_auto=%s WHERE id=%s""",
          (dados.janela_ativa, dados.janela_inicio or None,
           dados.janela_fim or None, dados.ciencia_auto, empresa_id))
    _aud(u, "config_sincronizacao", empresa_id, dados.model_dump(), request)
    return q("SELECT * FROM config_efetiva WHERE empresa_id=%s", (empresa_id,), one=True)


class SwitchDfe(BaseModel):
    ligar: bool
    forcar: bool = False       # religa mesmo com pausa de motivo desconhecido


MARCA_SWITCH = "Desligado no painel"


@router.get("/{empresa_id}/dfe")
def dfe_situacao(empresa_id: int, u=Depends(auth.exige("ver"))):
    """Situacao das tres origens de documentos desta empresa."""
    auth.exige_empresa(u, empresa_id)
    cur = q("""SELECT origem, pausado, pausado_motivo, ultima_sync, ultimo_nsu,
                 caught_up
               FROM cursores_dfe WHERE empresa_id=%s ORDER BY origem""",
            (empresa_id,))
    if not cur:
        return {"ligado": False, "origens": [], "sem_cursor": True}

    pausadas = [c for c in cur if c["pausado"]]
    # pausa que NAO foi posta pelo switch e decisao deliberada de alguem
    externas = [c["pausado_motivo"] for c in pausadas
                if c["pausado_motivo"] and MARCA_SWITCH not in c["pausado_motivo"]]
    return {"ligado": not pausadas, "origens": cur,
            "motivo_externo": externas[0] if externas else None}


@router.post("/{empresa_id}/dfe")
def dfe_switch(empresa_id: int, dados: SwitchDfe, request: Request,
               u=Depends(auth.exige("empresa_escrever"))):
    """Liga ou desliga a busca de documentos (NF-e, CT-e e NFS-e de uma vez).

    Ao ligar, a sincronizacao comeca IMEDIATAMENTE (proxima_sync=now) - o
    usuario ve o resultado sem esperar a fila.

    Se a empresa estiver pausada por um motivo que nao veio deste switch
    (ex: "CNPJ ja consumido por outro sistema"), religar exige forcar=true:
    duas ferramentas puxando o mesmo NSU fazem uma perder documentos.
    """
    auth.exige_empresa(u, empresa_id)
    emp = q("SELECT razao_social FROM empresas WHERE id=%s", (empresa_id,), one=True)
    if not emp:
        raise HTTPException(404, "Empresa nao encontrada")

    cur = q("""SELECT origem, pausado, pausado_motivo FROM cursores_dfe
               WHERE empresa_id=%s""", (empresa_id,))
    if not cur:
        raise HTTPException(400,
            "Esta empresa ainda nao tem cursores de sincronizacao configurados.")

    if dados.ligar:
        externas = [c["pausado_motivo"] for c in cur
                    if c["pausado"] and c["pausado_motivo"]
                    and MARCA_SWITCH not in c["pausado_motivo"]]
        if externas and not dados.forcar:
            return {"ok": False, "confirmar": True, "motivo": externas[0],
                    "aviso": "Esta empresa foi pausada por outro motivo. "
                             "Confirme para religar mesmo assim."}
        if not q("""SELECT id FROM certificados
                    WHERE empresa_id=%s AND ativo""", (empresa_id,), one=True):
            raise HTTPException(400,
                "A empresa precisa de um certificado digital ativo para "
                "buscar documentos.")
        q("""UPDATE cursores_dfe SET pausado=false, pausado_motivo=NULL,
               proxima_sync=now() WHERE empresa_id=%s""", (empresa_id,))
    else:
        motivo = f"{MARCA_SWITCH} por {u['nome']}"
        q("""UPDATE cursores_dfe SET pausado=true, pausado_motivo=%s
             WHERE empresa_id=%s""", (motivo, empresa_id))

    _aud(u, "dfe_ligado" if dados.ligar else "dfe_desligado", empresa_id,
         {"empresa": emp["razao_social"], "forcado": dados.forcar}, request)
    return {"ok": True, "ligado": dados.ligar}


@router.get("/config/escritorio")
def config_escritorio(u=Depends(auth.usuario_atual)):
    return q("""SELECT janela_ativa, janela_inicio, janela_fim, ciencia_auto
                FROM contabilidades WHERE id=%s""", (u["contabilidade_id"],), one=True)

@router.put("/config/escritorio")
def salva_config_escritorio(dados: ConfigSync, request: Request,
                            u=Depends(auth.exige("usuario_escrever"))):
    """Padrao do escritorio. Vale para toda empresa que nao tenha config propria."""
    if dados.janela_ativa and not (dados.janela_inicio and dados.janela_fim):
        raise HTTPException(400, "Informe inicio e fim da janela.")
    q("""UPDATE contabilidades SET janela_ativa=%s, janela_inicio=%s,
         janela_fim=%s, ciencia_auto=%s WHERE id=%s""",
      (bool(dados.janela_ativa), dados.janela_inicio or None,
       dados.janela_fim or None, bool(dados.ciencia_auto), u["contabilidade_id"]))
    _aud(u, "config_escritorio", None, dados.model_dump(), request)
    return {"ok": True}

class EditaEmpresa(BaseModel):
    nome_fantasia: Optional[str] = None
    ie: Optional[str] = None
    im: Optional[str] = None
    regime_tributario: Optional[str] = None
    observacoes: Optional[str] = None

@router.put("/{empresa_id}")
def editar(empresa_id: int, dados: EditaEmpresa, request: Request,
           u=Depends(auth.exige("empresa_escrever"))):
    """Edita apenas o que nao vem da Receita Federal."""
    auth.exige_empresa(u, empresa_id)
    q("""UPDATE empresas SET nome_fantasia=%s, ie=%s, im=%s,
         regime_tributario=%s, observacoes=%s, atualizado_em=NOW()
         WHERE id=%s""",
      (dados.nome_fantasia or None, dados.ie or None, dados.im or None,
       dados.regime_tributario or None, dados.observacoes or None, empresa_id))
    _aud(u, "empresa_editada", empresa_id, dados.model_dump(), request)
    return q("""SELECT id,razao_social,nome_fantasia,ie,im,regime_tributario,observacoes
                FROM empresas WHERE id=%s""", (empresa_id,), one=True)


@router.post("/{empresa_id}/atualizar-receita")
def atualizar_receita(empresa_id: int, request: Request,
                      u=Depends(auth.exige("empresa_escrever"))):
    """Reconsulta a Receita e atualiza os campos oficiais."""
    auth.exige_empresa(u, empresa_id)
    emp = q("SELECT cnpj FROM empresas WHERE id=%s", (empresa_id,), one=True)
    try:
        d = receita.consulta(emp["cnpj"], conn_q=q)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))

    import json
    q("""UPDATE empresas SET razao_social=%s, municipio_ibge=%s, municipio_nome=%s,
         uf=%s, matriz_filial=%s, situacao_cadastral=%s, situacao_data=%s,
         situacao_motivo=%s, abertura=%s, natureza_juridica=%s, porte=%s,
         capital_social=%s, cnae_principal=%s, cnae_principal_desc=%s,
         logradouro=%s, numero=%s, complemento=%s, bairro=%s, cep=%s,
         telefone1=%s, telefone2=%s, email=%s, simples_optante=%s,
         simples_desde=%s, simples_ate=%s, mei_optante=%s, mei_desde=%s,
         receita_bruto=%s, receita_fonte=%s, receita_consultado_em=NOW(),
         atualizado_em=NOW() WHERE id=%s""",
      (d["razao_social"], d["municipio_ibge"], d["municipio_nome"], d["uf"],
       d["matriz_filial"], d["situacao_cadastral"], d["situacao_data"],
       d["situacao_motivo"], d["abertura"], d["natureza_juridica"], d["porte"],
       d["capital_social"], d["cnae_principal"], d["cnae_principal_desc"],
       d["logradouro"], d["numero"], d["complemento"], d["bairro"], d["cep"],
       d["telefone1"], d["telefone2"], d["email"], d["simples_optante"],
       d["simples_desde"], d["simples_ate"], d["mei_optante"], d["mei_desde"],
       json.dumps(d["bruto"]), d["fonte"], empresa_id))

    q("DELETE FROM empresa_cnaes WHERE empresa_id=%s", (empresa_id,))
    if d["cnae_principal"]:
        q("""INSERT INTO empresa_cnaes (empresa_id,codigo,descricao,principal)
             VALUES (%s,%s,%s,TRUE)""",
          (empresa_id, d["cnae_principal"], d["cnae_principal_desc"]))
    for cn in d["cnaes"]:
        q("""INSERT INTO empresa_cnaes (empresa_id,codigo,descricao,principal)
             VALUES (%s,%s,%s,FALSE)""", (empresa_id, cn["codigo"], cn["descricao"]))
    q("DELETE FROM empresa_socios WHERE empresa_id=%s", (empresa_id,))
    for so in d["socios"]:
        q("""INSERT INTO empresa_socios
             (empresa_id,nome,documento,qualificacao,faixa_etaria,entrada,pais,
              representante_nome,representante_doc,representante_qualif)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (empresa_id, so["nome"], so["documento"], so["qualificacao"],
           so["faixa_etaria"], so["entrada"], so["pais"], so["representante_nome"],
           so["representante_doc"], so["representante_qualif"]))

    _aud(u, "empresa_atualizada_receita", empresa_id, {"fonte": d["fonte"]}, request)
    return {"ok": True, "fonte": d["fonte"],
            "situacao": d["situacao_cadastral"], "razao_social": d["razao_social"]}


class Arquivar(BaseModel):
    motivo: Optional[str] = None

@router.post("/{empresa_id}/arquivar")
def arquivar(empresa_id: int, dados: Arquivar, request: Request,
             u=Depends(auth.exige("empresa_escrever"))):
    """Arquiva: some da lista e para de sincronizar. Nenhum dado e apagado."""
    auth.exige_empresa(u, empresa_id)
    e = q("SELECT razao_social, arquivada_em FROM empresas WHERE id=%s",
          (empresa_id,), one=True)
    if e["arquivada_em"]:
        raise HTTPException(400, "Esta empresa ja esta arquivada.")
    q("""UPDATE empresas SET arquivada_em=NOW(), arquivada_por=%s,
         arquivada_motivo=%s, status='arquivada' WHERE id=%s""",
      (u["id"], dados.motivo, empresa_id))
    q("""UPDATE cursores_dfe SET pausado=TRUE,
         pausado_motivo='Empresa arquivada' WHERE empresa_id=%s""", (empresa_id,))
    _aud(u, "empresa_arquivada", empresa_id, {"motivo": dados.motivo}, request)
    return {"ok": True, "razao_social": e["razao_social"]}


@router.post("/{empresa_id}/restaurar")
def restaurar(empresa_id: int, request: Request,
              u=Depends(auth.exige("empresa_escrever"))):
    auth.exige_empresa(u, empresa_id)
    q("""UPDATE empresas SET arquivada_em=NULL, arquivada_por=NULL,
         arquivada_motivo=NULL, status='ativa' WHERE id=%s""", (empresa_id,))
    q("""UPDATE cursores_dfe SET pausado=FALSE, pausado_motivo=NULL
         WHERE empresa_id=%s AND pausado_motivo='Empresa arquivada'""", (empresa_id,))
    _aud(u, "empresa_restaurada", empresa_id, None, request)
    return {"ok": True}


@router.delete("/{empresa_id}")
def excluir(empresa_id: int, confirmacao: str, request: Request,
            u=Depends(auth.exige("admin"))):
    """Exclusao definitiva. Superadmin apenas, exige o CNPJ como confirmacao."""
    e = q("SELECT cnpj, razao_social FROM empresas WHERE id=%s", (empresa_id,), one=True)
    if not e:
        raise HTTPException(404, "Empresa nao encontrada")
    if receita.limpa(confirmacao) != e["cnpj"]:
        raise HTTPException(400, "Confirmacao invalida: digite o CNPJ da empresa.")
    q("""INSERT INTO auditoria (usuario_id,contabilidade_id,acao,detalhe,ip)
         VALUES (%s,%s,'empresa_excluida',%s,%s)""",
      (u["id"], u["contabilidade_id"],
       __import__("json").dumps({"cnpj": e["cnpj"], "razao_social": e["razao_social"]}),
       request.client.host if request.client else None))
    q("DELETE FROM empresas WHERE id=%s", (empresa_id,))
    return {"ok": True}


class DadosFiscais(BaseModel):
    """Campos que NAO vem da Receita - sao digitados e sao criticos:
    sem inscricao municipal nao se emite NFS-e."""
    ie: str | None = None
    im: str | None = None
    regime_tributario: str | None = None
    simples_optante: bool | None = None
    telefone1: str | None = None
    email: str | None = None
    observacoes: str | None = None


@router.get("/{empresa_id}/ficha")
def ficha(empresa_id: int, u=Depends(auth.usuario_atual)):
    """Ficha cadastral completa + pendencias que impedem operar."""
    auth.exige_empresa(u, empresa_id)
    e = q("""SELECT e.*, m.provedor_nfse, m.giss_slug
             FROM empresas e
             LEFT JOIN municipios m ON m.codigo_ibge = e.municipio_ibge
             WHERE e.id=%s""", (empresa_id,), one=True)
    if not e:
        raise HTTPException(404, "Empresa nao encontrada")

    cnaes = q("""SELECT codigo, descricao, principal FROM empresa_cnaes
                 WHERE empresa_id=%s ORDER BY principal DESC, codigo""",
              (empresa_id,))
    try:
        socios = q("""SELECT * FROM empresa_socios WHERE empresa_id=%s
                      ORDER BY nome""", (empresa_id,))
    except Exception:
        socios = []

    cert = q("""SELECT id, titular_cn, valido_ate,
                  (valido_ate::date - current_date) AS dias
                FROM certificados WHERE empresa_id=%s AND ativo
                ORDER BY id DESC LIMIT 1""", (empresa_id,), one=True)

    pend = []
    if not cert:
        pend.append({"tipo": "erro", "txt": "Sem certificado digital ativo. "
                     "Sem ele não há busca de documentos nem emissão."})
    elif cert["dias"] is not None and cert["dias"] < 0:
        pend.append({"tipo": "erro", "txt": "Certificado digital vencido."})
    elif cert["dias"] is not None and cert["dias"] <= 30:
        pend.append({"tipo": "aviso",
                     "txt": f"Certificado vence em {cert['dias']} dia(s)."})
    if not e.get("im"):
        pend.append({"tipo": "aviso", "txt": "Sem inscrição municipal. "
                     "É obrigatória para emitir NFS-e."})
    if not e.get("municipio_ibge"):
        pend.append({"tipo": "erro", "txt": "Sem município definido."})
    elif not e.get("provedor_nfse"):
        pend.append({"tipo": "aviso",
                     "txt": f"O município {e.get('municipio_nome') or ''} ainda não "
                            f"tem provedor de NFS-e configurado no sistema."})
    sit = (e.get("situacao_cadastral") or "").upper()
    if sit and sit not in ("ATIVA", "ATIVO"):
        pend.append({"tipo": "erro",
                     "txt": f"Situação cadastral na Receita: {e['situacao_cadastral']}."})

    return {"empresa": e, "cnaes": cnaes, "socios": socios,
            "certificado": cert, "pendencias": pend}


@router.put("/{empresa_id}/fiscal")
def salvar_fiscal(empresa_id: int, d: DadosFiscais, request: Request,
                  u=Depends(auth.exige("empresa_escrever"))):
    """Salva o que a Receita nao fornece. Nao toca nos campos vindos do CNPJ:
    esses so mudam via 'atualizar pela Receita'."""
    auth.exige_empresa(u, empresa_id)
    r = q("""UPDATE empresas SET ie=%s, im=%s, regime_tributario=%s,
               simples_optante=COALESCE(%s, simples_optante),
               telefone1=%s, email=%s, observacoes=%s
             WHERE id=%s
             RETURNING id, ie, im, regime_tributario, simples_optante""",
          (d.ie or None, d.im or None, d.regime_tributario or None,
           d.simples_optante, d.telefone1 or None, d.email or None,
           d.observacoes or None, empresa_id), one=True)
    _aud(u, "dados_fiscais_alterados", empresa_id, d.model_dump(), request)
    return r


@router.get("/{empresa_id}/resumo")
def resumo(empresa_id: int, u=Depends(auth.usuario_atual)):
    """Tudo que a home da empresa precisa, numa chamada so."""
    auth.exige_empresa(u, empresa_id)
    e = q("""SELECT id,razao_social,nome_fantasia,cnpj,ie,im,municipio_nome,uf,
                    logradouro,numero,complemento,bairro,cep,telefone1,email,
                    regime_tributario,porte,situacao_cadastral,abertura,
                    cnae_principal,cnae_principal_desc,natureza_juridica,
                    capital_social,simples_optante,arquivada_em,observacoes
             FROM empresas WHERE id=%s""", (empresa_id,), one=True)
    if not e:
        raise HTTPException(404, "Empresa nao encontrada")

    mes = q("""SELECT COUNT(*) AS docs,
                      COALESCE(SUM(valor),0) AS valor,
                      COUNT(*) FILTER (WHERE manifestacao IS NULL AND NOT resumo)
                        AS pendentes,
                      COUNT(*) FILTER (WHERE resumo) AS resumos
                 FROM documentos WHERE empresa_id=%s
                  AND emissao >= date_trunc('month',
                      NOW() AT TIME ZONE 'America/Sao_Paulo')""",
            (empresa_id,), one=True)

    total = q("SELECT COUNT(*) AS n FROM documentos WHERE empresa_id=%s",
              (empresa_id,), one=True)

    cert = q("""SELECT titular_cn,cnpj_titular,valido_ate,
                       EXTRACT(DAY FROM valido_ate - NOW())::int AS dias
                  FROM certificados WHERE empresa_id=%s AND ativo""",
             (empresa_id,), one=True)

    cursores = q("""SELECT origem,ultimo_nsu,ultima_sync,caught_up,pausado,
                           pausado_motivo,ultimo_cstat
                      FROM cursores_dfe WHERE empresa_id=%s ORDER BY origem""",
                 (empresa_id,))

    ultimos = q("""SELECT id,chave,tipo,emitente_nome,emitente_cnpj,numero,serie,
                          emissao,valor,manifestacao,resumo,situacao
                     FROM documentos WHERE empresa_id=%s
                    ORDER BY emissao DESC NULLS LAST, id DESC LIMIT 10""",
                (empresa_id,))

    cfg = q("SELECT * FROM config_efetiva WHERE empresa_id=%s", (empresa_id,), one=True)
    socios = q("""SELECT nome,qualificacao FROM empresa_socios
                  WHERE empresa_id=%s ORDER BY nome""", (empresa_id,))

    alertas = []
    if e["arquivada_em"]:
        alertas.append({"nivel":"aviso", "txt":"Esta empresa está arquivada e não sincroniza."})
    if not cert:
        alertas.append({"nivel":"aviso",
                        "txt":"Sem certificado digital. A sincronização não roda sem ele."})
    elif cert["dias"] is not None and cert["dias"] < 0:
        alertas.append({"nivel":"erro", "txt":"O certificado digital está vencido."})
    elif cert["dias"] is not None and cert["dias"] <= 30:
        alertas.append({"nivel":"aviso",
                        "txt":f"O certificado vence em {cert['dias']} dias."})
    if e["situacao_cadastral"] and e["situacao_cadastral"] != "ATIVA":
        alertas.append({"nivel":"erro",
                        "txt":f"Situação cadastral na Receita: {e['situacao_cadastral']}."})
    if mes["pendentes"]:
        alertas.append({"nivel":"aviso",
                        "txt":f"{mes['pendentes']} documento(s) aguardando manifestação."})
    for c in cursores:
        if c["pausado"]:
            alertas.append({"nivel":"aviso",
                            "txt":f"Sincronização pausada ({c['origem']}): {c['pausado_motivo']}"})

    return {"empresa": e, "mes": mes, "total_docs": total["n"], "certificado": cert,
            "cursores": cursores, "ultimos": ultimos, "config": cfg,
            "socios": socios, "alertas": alertas}


@router.get("/{empresa_id}")
def detalhe(empresa_id: int, u=Depends(auth.usuario_atual)):
    auth.exige_empresa(u, empresa_id)
    e = q("SELECT * FROM empresas WHERE id=%s", (empresa_id,), one=True)
    if not e:
        raise HTTPException(404, "Empresa nao encontrada")
    e.pop("receita_bruto", None)
    e["cnaes"] = q("""SELECT codigo,descricao,principal FROM empresa_cnaes
                      WHERE empresa_id=%s ORDER BY principal DESC, codigo""", (empresa_id,))
    e["socios"] = q("""SELECT nome,documento,qualificacao,entrada FROM empresa_socios
                       WHERE empresa_id=%s ORDER BY nome""", (empresa_id,))
    e["inscricoes"] = q("""SELECT tipo,numero,uf,municipio_ibge,ativa
                           FROM empresa_inscricoes WHERE empresa_id=%s""", (empresa_id,))
    e["certificados"] = q("""SELECT id,titular_cn,cnpj_titular,valido_de,valido_ate,ativo,
                                    enviado_em FROM certificados
                             WHERE empresa_id=%s ORDER BY enviado_em DESC""", (empresa_id,))
    return e
