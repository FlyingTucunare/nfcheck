"""Deteccao de problemas que impedem a contabilidade de operar.

A regra que rege este modulo: falha silenciosa vira nota faltando na
apuracao. Se o certificado vence, se a sincronizacao para, se o documento
fica sem XML - alguem precisa saber ANTES do cliente reclamar.

Como funciona: a cada varredura, monta a lista do que esta errado agora e
compara com o que ja esta aberto. O que continua errado nao duplica (o
indice unico da tabela garante); o que deixou de estar errado e RESOLVIDO
automaticamente - certificado renovado fecha o alerta sozinho.
"""
from datetime import datetime, timedelta, timezone

from db import q

# quanto tempo sem sincronizar ate virar problema
HORAS_SEM_SYNC = 6
DIAS_CERT_AVISO = 30
# resumos acumulados que justificam avisar sobre ciencia automatica
MINIMO_RESUMOS = 20


def _detecta():
    """Levanta tudo que esta errado agora. Uma consulta por tipo, para que
    um erro em uma nao derrube as outras."""
    achados = []

    # --- certificados ---
    for c in q("""SELECT e.id, e.razao_social, e.contabilidade_id,
                    ct.valido_ate, (ct.valido_ate::date - current_date) AS dias
                  FROM empresas e
                  JOIN certificados ct ON ct.empresa_id = e.id AND ct.ativo
                  WHERE e.arquivada_em IS NULL"""):
        if c["dias"] is None:
            continue
        if c["dias"] < 0:
            achados.append(dict(
                empresa_id=c["id"], contabilidade_id=c["contabilidade_id"],
                tipo="cert_vencido", nivel="erro",
                titulo=f"Certificado digital vencido: {c['razao_social']}",
                detalhe=f"Venceu há {abs(c['dias'])} dia(s). Sem certificado válido "
                        f"não há busca de documentos nem emissão de nota.",
                referencia=str(c["valido_ate"])))
        elif c["dias"] <= DIAS_CERT_AVISO:
            achados.append(dict(
                empresa_id=c["id"], contabilidade_id=c["contabilidade_id"],
                tipo="cert_vencendo", nivel="aviso",
                titulo=f"Certificado vence em {c['dias']} dia(s): {c['razao_social']}",
                detalhe=f"Renove antes de {c['valido_ate']:%d/%m/%Y} para não "
                        f"interromper a operação.",
                referencia=str(c["valido_ate"])))

    # --- empresa buscando documentos sem certificado ---
    for e in q("""SELECT e.id, e.razao_social, e.contabilidade_id
                  FROM empresas e
                  WHERE e.arquivada_em IS NULL
                    AND EXISTS (SELECT 1 FROM cursores_dfe c
                                 WHERE c.empresa_id = e.id AND NOT c.pausado)
                    AND NOT EXISTS (SELECT 1 FROM certificados ct
                                     WHERE ct.empresa_id = e.id AND ct.ativo)"""):
        achados.append(dict(
            empresa_id=e["id"], contabilidade_id=e["contabilidade_id"],
            tipo="sem_certificado", nivel="erro",
            titulo=f"Sem certificado digital: {e['razao_social']}",
            detalhe="A busca de documentos está ligada, mas não há certificado "
                    "ativo — nenhum documento será recebido.",
            referencia=None))

    # --- sincronizacao parada ---
    limite = datetime.now(timezone.utc) - timedelta(hours=HORAS_SEM_SYNC)
    for s in q("""SELECT e.id, e.razao_social, e.contabilidade_id,
                    max(c.ultima_sync) AS ultima
                  FROM empresas e
                  JOIN cursores_dfe c ON c.empresa_id = e.id
                  WHERE e.arquivada_em IS NULL AND NOT c.pausado
                    AND c.origem IN ('sefaz_nfe','sefaz_cte')
                    AND EXISTS (SELECT 1 FROM certificados ct
                                 WHERE ct.empresa_id = e.id AND ct.ativo
                                   AND ct.valido_ate > now())
                  GROUP BY e.id, e.razao_social, e.contabilidade_id
                  HAVING max(c.ultima_sync) IS NULL
                      OR max(c.ultima_sync) < %s""", (limite,)):
        quando = (f"desde {s['ultima']:%d/%m %H:%M}" if s["ultima"]
                  else "nunca sincronizou")
        achados.append(dict(
            empresa_id=s["id"], contabilidade_id=s["contabilidade_id"],
            tipo="sync_parada", nivel="erro",
            titulo=f"Busca de documentos parada: {s['razao_social']}",
            detalhe=f"Sem sincronização há mais de {HORAS_SEM_SYNC} horas "
                    f"({quando}). Documentos novos podem não estar chegando.",
            referencia=None))

    # --- consumo indevido recorrente ---
    for b in q("""SELECT e.id, e.razao_social, e.contabilidade_id, count(*) AS n
                  FROM sync_log s
                  JOIN empresas e ON e.id = s.empresa_id
                  WHERE s.cstat = '656' AND s.criado_em > now() - interval '24 hours'
                  GROUP BY e.id, e.razao_social, e.contabilidade_id
                  HAVING count(*) >= 3"""):
        achados.append(dict(
            empresa_id=b["id"], contabilidade_id=b["contabilidade_id"],
            tipo="consumo_indevido", nivel="aviso",
            titulo=f"Consultas recusadas pela SEFAZ: {b['razao_social']}",
            detalhe=f"{b['n']} rejeições por consumo indevido nas últimas 24h. "
                    f"Pode haver outro sistema consumindo o mesmo CNPJ — a SEFAZ "
                    f"não permite dois, e ambos perdem documentos.",
            referencia=None))

    # --- documentos sem XML por falta de manifestacao ---
    for r in q("""SELECT e.id, e.razao_social, e.contabilidade_id,
                    count(*) AS n
                  FROM documentos d
                  JOIN empresas e ON e.id = d.empresa_id
                  LEFT JOIN config_efetiva cf ON cf.empresa_id = e.id
                  WHERE d.resumo AND d.manifestacao IS NULL
                    AND e.arquivada_em IS NULL
                    AND COALESCE(cf.ciencia_auto, false) = false
                  GROUP BY e.id, e.razao_social, e.contabilidade_id
                  HAVING count(*) >= %s""", (MINIMO_RESUMOS,)):
        achados.append(dict(
            empresa_id=r["id"], contabilidade_id=r["contabilidade_id"],
            tipo="sem_xml", nivel="aviso",
            titulo=f"{r['n']} documentos sem XML: {r['razao_social']}",
            detalhe="Chegaram apenas como resumo. O XML completo só é liberado "
                    "após a manifestação de ciência — ligue a ciência automática "
                    "para resolver sozinho.",
            referencia=None))

    # --- NFS-e rejeitada ---
    for n in q("""SELECT e.id, e.razao_social, e.contabilidade_id, count(*) AS n
                  FROM nfse_emitidas ne
                  JOIN empresas e ON e.id = ne.empresa_id
                  WHERE ne.situacao = 'rejeitada'
                    AND ne.criado_em > now() - interval '7 days'
                  GROUP BY e.id, e.razao_social, e.contabilidade_id"""):
        achados.append(dict(
            empresa_id=n["id"], contabilidade_id=n["contabilidade_id"],
            tipo="nfse_rejeitada", nivel="aviso",
            titulo=f"{n['n']} NFS-e rejeitada(s): {n['razao_social']}",
            detalhe="A prefeitura não aceitou. Nenhum documento fiscal foi "
                    "gerado — corrija e emita novamente.",
            referencia=None))

    return achados


def varre():
    """Roda a deteccao, abre o que e novo e fecha o que deixou de valer.
    Devolve (novos, resolvidos)."""
    achados = _detecta()
    ativos = {(a["empresa_id"] or 0, a["tipo"], a.get("referencia") or "")
              for a in achados}

    novos = 0
    for a in achados:
        r = q("""INSERT INTO alertas (contabilidade_id, empresa_id, tipo, nivel,
                   titulo, detalhe, referencia)
                 VALUES (%(contabilidade_id)s,%(empresa_id)s,%(tipo)s,%(nivel)s,
                         %(titulo)s,%(detalhe)s,%(referencia)s)
                 ON CONFLICT (COALESCE(empresa_id,0), tipo, COALESCE(referencia,''))
                   WHERE resolvido_em IS NULL
                 DO UPDATE SET titulo=EXCLUDED.titulo, detalhe=EXCLUDED.detalhe
                 RETURNING (xmax = 0) AS inserido, id""", a, one=True)
        if r and r["inserido"]:
            novos += 1

    # o que sumiu da deteccao foi resolvido - certificado renovado, sync
    # voltou, ciencia ligada. Fechar sozinho evita a lista virar lixo.
    resolvidos = 0
    for x in q("""SELECT id, empresa_id, tipo, referencia FROM alertas
                  WHERE resolvido_em IS NULL"""):
        chave = (x["empresa_id"] or 0, x["tipo"], x["referencia"] or "")
        if chave not in ativos:
            q("UPDATE alertas SET resolvido_em = now() WHERE id = %s", (x["id"],))
            resolvidos += 1

    return novos, resolvidos


def pendentes_para_email():
    """Agrupa por contabilidade o que ainda nao foi comunicado.

    Um e-mail por contabilidade, nunca um por alerta: 80 empresas com o
    mesmo problema gerariam 80 mensagens e a pessoa criaria um filtro para
    nunca mais ler nenhuma.
    """
    linhas = q("""SELECT a.contabilidade_id, a.id, a.nivel, a.titulo, a.detalhe,
                    c.razao_social AS contabilidade
                  FROM alertas a
                  JOIN contabilidades c ON c.id = a.contabilidade_id
                  WHERE a.resolvido_em IS NULL AND a.avisado_em IS NULL
                  ORDER BY a.contabilidade_id,
                    CASE a.nivel WHEN 'erro' THEN 0 WHEN 'aviso' THEN 1 ELSE 2 END,
                    a.id""")
    grupos = {}
    for l in linhas:
        grupos.setdefault(l["contabilidade_id"], []).append(l)
    return grupos


def marca_avisado(ids):
    if ids:
        q("UPDATE alertas SET avisado_em = now() WHERE id = ANY(%s)", (ids,))


def resumo(contabilidade_id=None):
    """Contagem para os KPIs da tela."""
    filtro = "AND contabilidade_id = %s" if contabilidade_id else ""
    p = (contabilidade_id,) if contabilidade_id else ()
    return q(f"""SELECT
                   count(*) FILTER (WHERE nivel='erro'  AND resolvido_em IS NULL) AS criticos,
                   count(*) FILTER (WHERE nivel='aviso' AND resolvido_em IS NULL) AS avisos,
                   count(*) FILTER (WHERE resolvido_em IS NULL AND lido_em IS NULL) AS nao_lidos,
                   count(*) FILTER (WHERE resolvido_em > now() - interval '24 hours') AS resolvidos_24h
                 FROM alertas WHERE 1=1 {filtro}""", p, one=True)
