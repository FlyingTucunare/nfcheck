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

    for origem in ("sefaz", "adn"):
        q("""INSERT INTO cursores_dfe (empresa_id,origem) VALUES (%s,%s)
             ON CONFLICT DO NOTHING""", (eid, origem))

    _aud(u, "empresa_criada", eid, {"cnpj": c, "fonte": d["fonte"]}, request)
    return emp

@router.get("")
def listar(u=Depends(auth.usuario_atual)):
    ids = [e["id"] for e in auth.empresas_visiveis(u)]
    if not ids:
        return []
    return q("""
      SELECT e.id, e.razao_social, e.nome_fantasia, e.cnpj, e.municipio_nome, e.uf,
             e.regime_tributario, e.porte, e.situacao_cadastral, e.status,
             c.valido_ate AS cert_ate, c.titular_cn AS cert_titular,
             (c.id IS NOT NULL) AS tem_cert,
             CASE WHEN c.id IS NULL THEN 'sem'
                  WHEN c.valido_ate < NOW() THEN 'vencido'
                  WHEN c.valido_ate < NOW() + INTERVAL '30 days' THEN 'vencendo'
                  ELSE 'ok' END AS cert_status,
             (SELECT MAX(ultima_sync) FROM cursores_dfe WHERE empresa_id=e.id) AS ultima_sync
      FROM empresas e
      LEFT JOIN certificados c ON c.empresa_id=e.id AND c.ativo
      WHERE e.id = ANY(%s)
      ORDER BY e.razao_social""", (ids,))

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
