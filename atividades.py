"""Lista oficial de atividades municipais do GissOnline.

Cada prefeitura publica, sem autenticacao, a tabela de atividades com
codigo de tributacao, item da LC 116, aliquota e vigencia. E a fonte da
verdade - melhor que derivar o codigo por CNAE ou pedir ao usuario.

  https://gissv2-{IBGE}.giss.com.br/service-atividade/api/atividade/v2/lista-atividades/{IBGE}

Estrutura de cada registro:
  codigo         codigo de tributacao municipal
                 9 digitos = CNAE(7) + sequencial(2)  -> pessoa juridica
                 6 digitos = CBO                      -> profissional autonomo
  codigoServico  item da LC 116 sem ponto ("105" = 01.05, "1711" = 17.11)
  aliquota       aliquota de ISS do municipio, em percentual
  inicio / fim   vigencia (sem 'fim' = vigente)

O campo 'ativo' vem false em todos os registros - e flag interna do portal,
nao indica atividade desativada (o 620230002 usado numa NFS-e autorizada
vem com ativo=false). Por isso a vigencia e que manda.
"""
from datetime import date, datetime

import requests

from db import q

URL = ("https://gissv2-{ibge}.giss.com.br/service-atividade/api/atividade/v2/"
       "lista-atividades/{ibge}")
CABECALHO = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}


def _data(v):
    """'01/01/2021' -> date. Devolve None se vazio ou invalido."""
    if not v:
        return None
    try:
        return datetime.strptime(v.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _item_lc116(codigo_servico):
    """'105' -> '01.05' ; '1711' -> '17.11' ; '8.02' -> '08.02'.
    O item tem sempre 2 digitos de grupo + 2 de subitem."""
    s = (codigo_servico or "").replace(".", "").strip()
    if not s.isdigit() or len(s) < 3:
        return None
    s = s.zfill(4)
    if len(s) > 4:          # codigos com desdobramento (ex: 170204)
        s = s[:4]
    return f"{s[:2]}.{s[2:]}"


def baixar(ibge):
    """Baixa a lista crua do municipio. Levanta erro se o municipio nao
    estiver no GissOnline V2."""
    r = requests.get(URL.format(ibge=ibge), timeout=60, headers=CABECALHO)
    r.raise_for_status()
    return r.json().get("conteudo") or []


def importar(ibge, quando=None):
    """Baixa e sincroniza a lista de um municipio. Idempotente.
    Retorna resumo do que foi importado."""
    hoje = quando or date.today()
    linhas = baixar(ibge)
    if not linhas:
        return {"ok": False, "erro": "Municipio sem lista de atividades no GissOnline."}

    vigentes = novos = 0
    for a in linhas:
        codigo = (a.get("codigo") or "").strip()
        if not codigo:
            continue
        inicio, fim = _data(a.get("inicio")), _data(a.get("fim"))
        # so interessa o que vale hoje ou passa a valer
        if fim and fim < hoje:
            continue
        vigentes += 1
        r = q("""INSERT INTO atividades_municipais
                   (municipio_ibge, codigo, codigo_servico, item_lista_servico,
                    descricao, aliquota, vigencia_inicio, vigencia_fim,
                    tipo_codigo, atualizado_em)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                 ON CONFLICT (municipio_ibge, codigo,
                              COALESCE(vigencia_inicio,'1900-01-01')) DO UPDATE SET
                   codigo_servico=EXCLUDED.codigo_servico,
                   item_lista_servico=EXCLUDED.item_lista_servico,
                   descricao=EXCLUDED.descricao, aliquota=EXCLUDED.aliquota,
                   vigencia_fim=EXCLUDED.vigencia_fim, atualizado_em=now()
                 RETURNING (xmax = 0) AS inserido""",
              (str(ibge), codigo, (a.get("codigoServico") or "").strip(),
               _item_lc116(a.get("codigoServico")), (a.get("descricao") or "").strip(),
               a.get("aliquota"), inicio, fim,
               "cnae" if len(codigo) >= 9 else "cbo"), one=True)
        if r and r["inserido"]:
            novos += 1

    q("""UPDATE municipios SET atividades_atualizado_em = now() WHERE codigo_ibge = %s""",
      (str(ibge),))
    return {"ok": True, "municipio_ibge": str(ibge), "recebidos": len(linhas),
            "vigentes": vigentes, "novos": novos}


def para_empresa(empresa_id, item_lista_servico=None):
    """Atividades que a empresa pode usar: cruza a lista oficial do municipio
    com os CNAEs que ela tem na Receita.

    Devolve dois grupos:
      compativeis - CNAE da empresa bate com o codigo da atividade
      outras      - demais atividades vigentes do municipio (o cadastro
                    municipal pode ter atividade que nao esta no CNPJ)
    """
    emp = q("""SELECT id, municipio_ibge, cnae_principal FROM empresas WHERE id=%s""",
            (empresa_id,), one=True)
    if not emp or not emp["municipio_ibge"]:
        return {"compativeis": [], "outras": [], "total_municipio": 0}

    cnaes = q("SELECT codigo, principal FROM empresa_cnaes WHERE empresa_id=%s",
              (empresa_id,))
    lista_cnaes = [c["codigo"] for c in cnaes] or ([emp["cnae_principal"]]
                                                   if emp["cnae_principal"] else [])
    principal = next((c["codigo"] for c in cnaes if c["principal"]),
                     emp["cnae_principal"])

    filtro_item = ""
    p = [str(emp["municipio_ibge"])]
    if item_lista_servico:
        filtro_item = "AND item_lista_servico = %s"
        p.append(item_lista_servico)

    todas = q(f"""SELECT codigo, codigo_servico, item_lista_servico, descricao,
                    aliquota, vigencia_inicio, vigencia_fim, tipo_codigo
                  FROM atividades_municipais
                  WHERE municipio_ibge = %s {filtro_item}
                    AND (vigencia_fim IS NULL OR vigencia_fim >= current_date)
                    AND (vigencia_inicio IS NULL OR vigencia_inicio <= current_date)
                  ORDER BY codigo""", tuple(p))

    compativeis, outras = [], []
    for a in todas:
        cnae_da_atividade = a["codigo"][:7] if a["tipo_codigo"] == "cnae" else None
        if cnae_da_atividade and cnae_da_atividade in lista_cnaes:
            a["cnae"] = cnae_da_atividade
            a["cnae_principal"] = (cnae_da_atividade == principal)
            compativeis.append(a)
        else:
            outras.append(a)

    # CNAE principal primeiro, depois por codigo
    compativeis.sort(key=lambda x: (not x["cnae_principal"], x["codigo"]))
    return {"compativeis": compativeis, "outras": outras,
            "total_municipio": len(todas), "cnaes_empresa": lista_cnaes}


def buscar(municipio_ibge, termo="", limite=60):
    """Busca livre na lista do municipio, por codigo ou descricao."""
    if not termo:
        return q("""SELECT codigo, codigo_servico, item_lista_servico, descricao,
                      aliquota, tipo_codigo
                    FROM atividades_municipais
                    WHERE municipio_ibge=%s
                      AND (vigencia_fim IS NULL OR vigencia_fim >= current_date)
                    ORDER BY codigo LIMIT %s""", (str(municipio_ibge), limite))
    return q("""SELECT codigo, codigo_servico, item_lista_servico, descricao,
                  aliquota, tipo_codigo
                FROM atividades_municipais
                WHERE municipio_ibge=%s
                  AND (vigencia_fim IS NULL OR vigencia_fim >= current_date)
                  AND (codigo ILIKE %s OR descricao ILIKE %s
                       OR item_lista_servico ILIKE %s)
                ORDER BY codigo LIMIT %s""",
             (str(municipio_ibge), f"%{termo}%", f"%{termo}%", f"%{termo}%", limite))


def uma(municipio_ibge, codigo):
    """Detalhe de uma atividade especifica (vigente)."""
    return q("""SELECT * FROM atividades_municipais
                WHERE municipio_ibge=%s AND codigo=%s
                  AND (vigencia_fim IS NULL OR vigencia_fim >= current_date)
                ORDER BY vigencia_inicio DESC NULLS LAST LIMIT 1""",
             (str(municipio_ibge), codigo), one=True)
