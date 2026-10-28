"""Worker de sincronização de documentos fiscais.

REGRAS DA SEFAZ (NT 2014.002, item 3.11.4) - a razão de cada decisão aqui:

  distNSU
    cStat 138 e ultNSU < maxNSU  -> PODE consultar de novo na hora (drenando)
    cStat 138 e ultNSU == maxNSU -> esvaziou: aguardar 1 hora
    cStat 137 (nada localizado)  -> aguardar 1 hora
    consultar antes disso        -> cStat 656 e CNPJ bloqueado por 1 hora

  consChNFe / consNSU
    no máximo 20 consultas por hora, por CNPJ. Estourar = 656 + bloqueio.

O QUE ISSO SIGNIFICA NA PRÁTICA:
  Empresa com movimento fica em ciclo rápido - cada lote de 50 documentos
  libera a consulta seguinte imediatamente. Empresa parada tem latência de
  até 1 hora para a PRIMEIRA detecção, e isso não tem como contornar
  legalmente.

  O ganho real está no XML completo: o destinatário recebe só o resumo até
  manifestar. Depois da ciência o Ambiente Nacional gera um NSU novo com o
  documento completo - esperar esse NSU pelo distNSU custa até 1 hora.
  Com consChNFe o XML vem em segundos. É aí que ganhamos do fluxo antigo.

DOIS SISTEMAS NO MESMO CNPJ: a SEFAZ não permite. Se outro software já
consome o DistDFe do mesmo CNPJ, os dois disputam o cursor e ambos perdem
documentos. Por isso o switch da tela avisa antes de religar.
"""
import os
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

from db import q
import sefaz

# --- cadência ---
PAUSA_ENTRE_LOTES = 2        # s, enquanto está drenando (cStat 138)
ESPERA_VAZIO_MIN = 60        # min, regra da SEFAZ após 137 ou caught_up
ESPERA_BLOQUEIO_MIN = 65     # min, após 656 (com folga sobre a 1h)
ESPERA_ERRO_MIN = 15         # min, após falha de rede/certificado
CICLO_OCIOSO = 20            # s entre varreduras quando não há trabalho
PARALELAS = 4                # empresas ao mesmo tempo (limite é por CNPJ)
MIN_ALERTAS = 10             # min entre varreduras de alertas
MIN_EMAIL_ALERTAS = 360      # min entre e-mails para a mesma contabilidade

# --- orçamento de consChNFe (limite 20/h por CNPJ; guardamos margem) ---
TETO_CHAVE_HORA = 15

# --- recuperacao automatica de pausas por 656 ---
LIMITE_TENTATIVAS_656 = 3    # tentativas de religar sozinho antes de exigir humano
MIN_RECUPERACAO_656 = 10     # min entre varreduras de recuperacao

BRT = timezone(timedelta(hours=-3))
_parar = threading.Event()

# O uvicorn sobe varios processos; sem isto, cada um consultaria a SEFAZ e
# as consultas duplicadas do mesmo CNPJ dariam cStat 656. A trava consultiva
# do Postgres garante um unico worker ativo, seja quantos processos forem.
TRAVA_ID = 918273645
_conn_trava = None


def _pega_trava():
    """Segura uma advisory lock enquanto a conexao viver. Devolve True se
    este processo e o dono do worker."""
    global _conn_trava
    from db import get_conn
    try:
        _conn_trava = get_conn()
        _conn_trava.autocommit = True
        cur = _conn_trava.cursor()
        cur.execute("SELECT pg_try_advisory_lock(%s)", (TRAVA_ID,))
        if cur.fetchone()[0]:
            return True
        _conn_trava.close()
        _conn_trava = None
        return False
    except Exception as e:
        _log(f"nao consegui a trava: {type(e).__name__}: {e}")
        return False


def _solta_trava():
    global _conn_trava
    if _conn_trava:
        try:
            _conn_trava.close()
        except Exception:
            pass
        _conn_trava = None


def _log(msg):
    print(f"[worker {datetime.now(BRT):%H:%M:%S}] {msg}", flush=True)


# ------------------------------------------------------------ orçamento
def _consultas_chave_na_hora(empresa_id):
    r = q("""SELECT count(*) AS n FROM sync_log
             WHERE empresa_id=%s AND origem='conschnfe'
               AND criado_em > now() - interval '1 hour'""",
          (empresa_id,), one=True)
    return (r or {}).get("n", 0)


def pode_consultar_chave(empresa_id):
    return _consultas_chave_na_hora(empresa_id) < TETO_CHAVE_HORA


# ------------------------------------------------------------ fila
def proximas(limite=PARALELAS):
    """Empresas prontas para sincronizar agora.

    Respeita a janela de horário configurada (view config_efetiva) e o
    proxima_sync de cada cursor - que é onde a cadência da SEFAZ vive.
    """
    linhas = q("""
        SELECT c.empresa_id, c.origem, c.ultimo_nsu, c.max_nsu, c.caught_up,
               e.razao_social, e.cnpj,
               '1'                             AS ambiente,
               COALESCE(cf.ciencia_auto, false) AS ciencia_auto,
               cf.janela_ativa, cf.janela_inicio, cf.janela_fim
        FROM cursores_dfe c
        JOIN empresas e ON e.id = c.empresa_id
        LEFT JOIN config_efetiva cf ON cf.empresa_id = c.empresa_id
        WHERE NOT c.pausado
          AND c.origem IN ('sefaz_nfe','sefaz_cte')
          AND e.arquivada_em IS NULL
          AND COALESCE(c.proxima_sync, now()) <= now()
          AND EXISTS (SELECT 1 FROM certificados ct
                       WHERE ct.empresa_id = e.id AND ct.ativo
                         AND (ct.valido_ate IS NULL OR ct.valido_ate > now()))
          AND (
            COALESCE(cf.janela_ativa, false) = false
            OR (
              CASE WHEN cf.janela_inicio <= cf.janela_fim
                   THEN (now() AT TIME ZONE 'America/Sao_Paulo')::time
                        BETWEEN cf.janela_inicio AND cf.janela_fim
                   ELSE (now() AT TIME ZONE 'America/Sao_Paulo')::time
                        >= cf.janela_inicio
                     OR (now() AT TIME ZONE 'America/Sao_Paulo')::time
                        <= cf.janela_fim
              END
            )
          )
        ORDER BY COALESCE(c.proxima_sync, now())""")

    # uma origem por CNPJ em cada rodada: o bloqueio da SEFAZ e por CNPJ
    vistos, fila = set(), []
    for x in linhas:
        if x["empresa_id"] in vistos:
            continue
        vistos.add(x["empresa_id"])
        fila.append(x)
        if len(fila) >= limite:
            break
    return fila


def _agenda_cnpj(empresa_id, minutos):
    """Adia TODAS as origens do CNPJ: o limite da SEFAZ e por CNPJ."""
    q("""UPDATE cursores_dfe
         SET proxima_sync = greatest(COALESCE(proxima_sync, now()),
                                     now() + (%s || ' minutes')::interval)
         WHERE empresa_id=%s""", (minutos, empresa_id))


def _agenda(empresa_id, origem, minutos=None, segundos=None):
    if segundos is not None:
        q("""UPDATE cursores_dfe
             SET proxima_sync = now() + (%s || ' seconds')::interval
             WHERE empresa_id=%s AND origem=%s""", (segundos, empresa_id, origem))
    else:
        q("""UPDATE cursores_dfe
             SET proxima_sync = now() + (%s || ' minutes')::interval
             WHERE empresa_id=%s AND origem=%s""", (minutos, empresa_id, origem))


# ------------------------------------------------------------ ciência
def _resumos_pendentes(empresa_id, limite):
    """Documentos que chegaram só como resumo e ainda não foram manifestados.
    São eles que travam o XML completo."""
    return q("""SELECT id, chave FROM documentos
                WHERE empresa_id=%s AND resumo AND chave IS NOT NULL
                  AND manifestacao IS NULL AND tipo LIKE 'nfe%%'
                ORDER BY recebido_em DESC LIMIT %s""", (empresa_id, limite))


def dar_ciencia_e_buscar(empresa_id, ambiente):
    """Manifesta ciência dos resumos e busca o XML completo na hora.

    Sem isto, o documento completo só chegaria no próximo lote do distNSU -
    ou seja, até uma hora depois. Este é o ganho central do worker.
    """
    import manifestacao

    orcamento = TETO_CHAVE_HORA - _consultas_chave_na_hora(empresa_id)
    if orcamento <= 0:
        return 0, 0

    pendentes = _resumos_pendentes(empresa_id, orcamento)
    if not pendentes:
        return 0, 0

    manifestados = completos = 0
    for d in pendentes:
        if _parar.is_set():
            break
        try:
            r = manifestacao.enviar(empresa_id, d["chave"], "210210",
                                    usuario_id=None, automatica=True,
                                    ambiente=ambiente)
        except Exception as e:
            _log(f"  ciencia falhou ({d['chave'][:12]}...): {type(e).__name__}")
            continue
        if not r.get("ok"):
            continue
        manifestados += 1

        # o Ambiente Nacional leva alguns segundos para liberar o completo
        time.sleep(3)
        try:
            if buscar_por_chave(empresa_id, d["chave"], ambiente):
                completos += 1
        except Exception as e:
            _log(f"  consChNFe falhou: {type(e).__name__}")
        time.sleep(1)

    return manifestados, completos


def buscar_por_chave(empresa_id, chave, ambiente="1"):
    """consChNFe: traz o XML completo de uma NF-e específica.

    Limite de 20 por hora por CNPJ - o orçamento é controlado por quem chama.
    """
    if not hasattr(sefaz, "consultar_chave"):
        return False
    r = sefaz.consultar_chave(empresa_id, chave, ambiente)
    return bool(r and r.get("novos"))


# ------------------------------------------------------------ ciclo
def ciclo(item):
    """Um ciclo de uma origem de uma empresa. Devolve True se drenou algo."""
    eid, origem = item["empresa_id"], item["origem"]
    nome = (item["razao_social"] or "")[:28]

    try:
        r = sefaz.sincronizar(eid, origem, item["ambiente"])
    except Exception as e:
        _log(f"{nome} [{origem}] ERRO {type(e).__name__}: {e}")
        q("""UPDATE cursores_dfe SET status='erro', erro_msg=%s
             WHERE empresa_id=%s AND origem=%s""",
          (f"{type(e).__name__}: {e}"[:300], eid, origem))
        _agenda(eid, origem, minutos=ESPERA_ERRO_MIN)
        return False

    # bloqueio por consumo indevido: para este CNPJ, segue com os outros
    # 656 e bloqueio real da SEFAZ: pune o CNPJ inteiro por 1h.
    # Qualquer outro 'halt' e falha nossa ou do servidor deles - nao faz
    # sentido castigar as outras origens do mesmo CNPJ por causa disso.
    if r.get("cstat") == "656":
        _log(f"{nome} [{origem}] consumo indevido (656) - CNPJ pausado "
             f"{ESPERA_BLOQUEIO_MIN}min")
        _agenda_cnpj(eid, ESPERA_BLOQUEIO_MIN)
        return False

    if r.get("halt"):
        _log(f"{nome} [{origem}] falhou: {(r.get('mensagem') or '')[:90]}")
        _agenda(eid, origem, minutos=ESPERA_ERRO_MIN)
        return False

    if r.get("aguardar"):
        _agenda(eid, origem, minutos=ESPERA_VAZIO_MIN)
        return False

    novos = r.get("novos", 0)
    cstat = r.get("cstat")

    # ciclo legitimo (nem 656 nem halt): zera o contador de recuperacao
    q("""UPDATE cursores_dfe SET tentativas_656=0
         WHERE empresa_id=%s AND origem=%s""", (eid, origem))

    # 138 com fila restante: a SEFAZ permite continuar agora
    if cstat == "138" and not r.get("caught_up"):
        if novos:
            _log(f"{nome} [{origem}] {novos} novo(s), NSU {r.get('ultimo_nsu')} - drenando")
        _agenda(eid, origem, segundos=PAUSA_ENTRE_LOTES)
        return True

    # esvaziou (137 ou ultNSU == maxNSU): regra de 1 hora
    if novos:
        _log(f"{nome} [{origem}] {novos} novo(s), fila zerada")
    else:
        _log(f"{nome} [{origem}] nada novo (cStat {cstat}) - aguarda 1h")
    # a espera de 1h vale para ESTA origem. Adiar o CNPJ inteiro congelaria
    # a outra origem no meio da drenagem - o que aconteceu na primeira versao:
    # o CT-e esvaziou e parou o NF-e com 1.700 documentos pela frente.
    # O que e por CNPJ e o BLOQUEIO apos 656, tratado acima.
    _agenda(eid, origem, minutos=ESPERA_VAZIO_MIN)
    return bool(novos)


def pos_ciclo(item):
    """Depois de trazer documentos, resolve os resumos: ciência + XML completo."""
    if not item.get("ciencia_auto") or item["origem"] != "sefaz_nfe":
        return
    eid = item["empresa_id"]
    if not pode_consultar_chave(eid):
        return
    m, c = dar_ciencia_e_buscar(eid, item["ambiente"])
    if m:
        _log(f"{(item['razao_social'] or '')[:28]} ciencia em {m}, "
             f"XML completo de {c}")


def rodada():
    """Uma varredura da fila. Devolve quantas empresas tiveram novidade."""
    fila = proximas()
    if not fila:
        return 0

    ativos = 0
    for item in fila:
        if _parar.is_set():
            break
        try:
            houve = ciclo(item)
            if houve:
                ativos += 1
                pos_ciclo(item)
        except Exception:
            _log("falha inesperada no ciclo:\n" + traceback.format_exc()[-600:])
    return ativos


_ultima_varredura = None
_ultimo_email = None


def varre_alertas():
    """Detecta problemas e avisa. Falha aqui nunca pode parar a coleta."""
    global _ultima_varredura, _ultimo_email
    agora = datetime.now(timezone.utc)

    if _ultima_varredura and (agora - _ultima_varredura).total_seconds() < MIN_ALERTAS * 60:
        return
    _ultima_varredura = agora

    try:
        import alertas
        novos, resolvidos = alertas.varre()
        if novos or resolvidos:
            _log(f"alertas: {novos} novo(s), {resolvidos} resolvido(s)")
    except Exception as e:
        _log(f"varredura de alertas falhou: {type(e).__name__}: {e}")
        return

    # e-mail espacado: um resumo por contabilidade, no maximo a cada 6h
    if _ultimo_email and (agora - _ultimo_email).total_seconds() < MIN_EMAIL_ALERTAS * 60:
        return
    try:
        import alertas as al
        import emails
        grupos = al.pendentes_para_email()
        if not grupos:
            return
        _ultimo_email = agora
        for cont_id, itens in grupos.items():
            destinos = q("""SELECT email FROM usuarios
                            WHERE contabilidade_id=%s AND perfil='contabilidade_admin'
                              AND ativo""", (cont_id,))
            if not destinos:
                continue
            nome = itens[0].get("contabilidade") or "sua contabilidade"
            for d in destinos:
                ok, _ = emails.alertas_do_dia(d["email"], nome, itens)
                if ok:
                    al.marca_avisado([i["id"] for i in itens])
                    _log(f"alertas enviados para {d['email']} ({len(itens)})")
    except Exception as e:
        _log(f"envio de alertas falhou: {type(e).__name__}: {e}")


_ultima_recuperacao_656 = None


def recupera_656():
    """Tenta religar sozinho cursores pausados so por 656 puro, apos a
    janela de bloqueio da SEFAZ ja ter passado. Se o mesmo cursor voltar
    a tomar 656 varias vezes seguidas, para de tentar sozinho - pode ser
    outro sistema consultando o mesmo CNPJ, e isso exige um humano olhar.
    """
    global _ultima_recuperacao_656
    agora = datetime.now(timezone.utc)
    if (_ultima_recuperacao_656 and
            (agora - _ultima_recuperacao_656).total_seconds() < MIN_RECUPERACAO_656 * 60):
        return
    _ultima_recuperacao_656 = agora

    candidatos = q("""
        SELECT empresa_id, origem, COALESCE(tentativas_656,0) AS tentativas_656
        FROM cursores_dfe
        WHERE pausado
          AND pausado_motivo = 'Consumo indevido (656). Aguarde 1 hora.'
          AND ultima_sync <= now() - (%s || ' minutes')::interval
    """, (ESPERA_BLOQUEIO_MIN,))

    for c in candidatos:
        eid, origem, tent = c["empresa_id"], c["origem"], c["tentativas_656"]
        if tent >= LIMITE_TENTATIVAS_656:
            continue
        q("""UPDATE cursores_dfe
             SET pausado=false, pausado_motivo=NULL, proxima_sync=now(),
                 tentativas_656=%s
             WHERE empresa_id=%s AND origem=%s""", (tent + 1, eid, origem))
        _log(f"empresa {eid} [{origem}] janela do 656 passou - religando "
             f"sozinho (tentativa {tent + 1}/{LIMITE_TENTATIVAS_656})")

    q("""UPDATE cursores_dfe
         SET pausado_motivo = 'Consumo indevido (656) recorrente - verificar '
                              'se outro sistema consulta o mesmo CNPJ'
         WHERE pausado
           AND pausado_motivo = 'Consumo indevido (656). Aguarde 1 hora.'
           AND COALESCE(tentativas_656,0) >= %s""", (LIMITE_TENTATIVAS_656,))


def laco():
    if not _pega_trava():
        _log("outro processo ja e o worker - este fica de fora")
        return
    """Laço principal. Nunca morre calado: qualquer exceção é registrada e
    o laço continua - foi o silêncio que escondeu o problema do Órbita por
    semanas."""
    _log("worker iniciado")
    while not _parar.is_set():
        try:
            houve = rodada()
            varre_alertas()
            recupera_656()
            # com fila cheia, volta logo; sem nada para fazer, espaça
            _parar.wait(1 if houve else CICLO_OCIOSO)
        except Exception:
            _log("erro no laco:\n" + traceback.format_exc()[-600:])
            _parar.wait(30)
    _solta_trava()
    _log("worker encerrado")


_thread = None


def iniciar():
    """Sobe o worker em thread de fundo. Chamado no startup do FastAPI."""
    global _thread
    if os.environ.get("WORKER_DFE", "1") not in ("1", "true", "sim"):
        _log("desligado por WORKER_DFE")
        return None
    if _thread and _thread.is_alive():
        return _thread
    _parar.clear()
    _thread = threading.Thread(target=laco, name="worker-dfe", daemon=True)
    _thread.start()
    return _thread


def parar():
    _parar.set()


def situacao():
    """Diagnóstico do worker, para a tela de monitoração."""
    vivo = bool(_thread and _thread.is_alive() and _conn_trava)
    fila = q("""SELECT count(*) AS n FROM cursores_dfe c
                JOIN empresas e ON e.id=c.empresa_id
                WHERE NOT c.pausado AND e.arquivada_em IS NULL""", one=True)
    prontas = q("""SELECT count(*) AS n FROM cursores_dfe
                   WHERE NOT pausado AND COALESCE(proxima_sync, now()) <= now()""",
                one=True)
    ultima = q("""SELECT max(criado_em) AS q FROM sync_log""", one=True)
    return {"ativo": vivo, "cursores_ligados": (fila or {}).get("n", 0),
            "prontos_agora": (prontas or {}).get("n", 0),
            "ultima_sincronizacao": (ultima or {}).get("q")}
