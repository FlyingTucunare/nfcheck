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
def listar(u=Depends(auth.usuario_atual)):
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
             cur.ultima_sync, cur.nsu_nfe, cur.nsu_cte,
             COALESCE(cur.pausado,FALSE) AS pausado,
             cf.janela_ativa, cf.janela_inicio, cf.janela_fim,
             cf.ciencia_auto, cf.janela_herdada, cf.ciencia_herdada
      FROM empresas e
      LEFT JOIN certificados c ON c.empresa_id=e.id AND c.ativo
      LEFT JOIN mes m   ON m.empresa_id=e.id
      LEFT JOIN cur     ON cur.empresa_id=e.id
      LEFT JOIN config_efetiva cf ON cf.empresa_id=e.id
      WHERE e.id = ANY(%(ids)s)
      ORDER BY e.razao_social""", {"ids": ids})


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
