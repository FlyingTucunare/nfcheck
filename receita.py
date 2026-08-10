"""Consulta cadastral de CNPJ. BrasilAPI primeiro, ReceitaWS como reserva."""
import re, time, random, unicodedata, requests
from datetime import datetime

TIMEOUT = 15
UA = {"User-Agent": "NFCheck/1.0 (+https://nfcheck.com.br)"}
_ultima_chamada = {"t": 0.0}

def _throttle(minimo=1.2):
    """Espaca chamadas para nao bater no rate limit das APIs publicas."""
    delta = time.monotonic() - _ultima_chamada["t"]
    if delta < minimo:
        time.sleep(minimo - delta)
    _ultima_chamada["t"] = time.monotonic()

def _norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).upper().strip()

def resolve_ibge(conn_q, nome, uf):
    """Completa o codigo IBGE pela tabela local quando a API nao trouxe."""
    if not nome or not uf:
        return None
    r = conn_q("SELECT codigo_ibge FROM municipios WHERE uf=%s AND nome_norm=%s",
               (uf.upper(), _norm(nome)), one=True)
    return r["codigo_ibge"] if r else None

def limpa(cnpj):
    return re.sub(r"\D", "", cnpj or "")

def _data(v):
    if not v: return None
    v = str(v)[:10]
    for f in ("%Y-%m-%d", "%d/%m/%Y"):
        try: return datetime.strptime(v, f).date()
        except ValueError: pass
    return None

def _num(v):
    if v in (None, ""): return None
    try: return float(str(v).replace(".", "").replace(",", ".")) if isinstance(v, str) else float(v)
    except ValueError: return None

def _brasilapi(cnpj):
    r = requests.get(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}", timeout=TIMEOUT, headers=UA)
    if r.status_code == 404: raise ValueError("CNPJ nao encontrado na Receita Federal")
    r.raise_for_status()
    d = r.json()
    return {
      "fonte": "brasilapi", "bruto": d,
      "razao_social": d.get("razao_social"),
      "nome_fantasia": d.get("nome_fantasia") or None,
      "matriz_filial": d.get("descricao_identificador_matriz_filial"),
      "situacao_cadastral": d.get("descricao_situacao_cadastral"),
      "situacao_data": _data(d.get("data_situacao_cadastral")),
      "situacao_motivo": d.get("descricao_motivo_situacao_cadastral"),
      "situacao_especial": d.get("situacao_especial") or None,
      "abertura": _data(d.get("data_inicio_atividade")),
      "natureza_juridica": d.get("natureza_juridica"),
      "natureza_juridica_cod": str(d.get("codigo_natureza_juridica") or "") or None,
      "porte": d.get("porte"),
      "capital_social": _num(d.get("capital_social")),
      "cnae_principal": str(d.get("cnae_fiscal") or "") or None,
      "cnae_principal_desc": d.get("cnae_fiscal_descricao"),
      "logradouro": " ".join(x for x in [d.get("descricao_tipo_de_logradouro"),
                                          d.get("logradouro")] if x) or None,
      "numero": d.get("numero"), "complemento": d.get("complemento") or None,
      "bairro": d.get("bairro"), "cep": limpa(d.get("cep"))[:8] or None,
      "municipio_nome": d.get("municipio"),
      "municipio_ibge": str(d.get("codigo_municipio_ibge") or "") or None,
      "uf": d.get("uf"),
      "telefone1": (d.get("ddd_telefone_1") or "").strip() or None,
      "telefone2": (d.get("ddd_telefone_2") or "").strip() or None,
      "email": (d.get("email") or "").strip().lower() or None,
      "simples_optante": (d.get("opcao_pelo_simples")
                          if isinstance(d.get("opcao_pelo_simples"), bool) else None),
      "simples_desde": _data(d.get("data_opcao_pelo_simples")),
      "simples_ate": _data(d.get("data_exclusao_do_simples")),
      "mei_optante": (d.get("opcao_pelo_mei")
                      if isinstance(d.get("opcao_pelo_mei"), bool) else None),
      "mei_desde": _data(d.get("data_opcao_pelo_mei")),
      "cnaes": [{"codigo": str(c.get("codigo")), "descricao": c.get("descricao"),
                 "principal": False} for c in (d.get("cnaes_secundarios") or [])
                 if str(c.get("codigo") or "0") != "0"],
      "socios": [{"nome": s.get("nome_socio"), "documento": s.get("cnpj_cpf_do_socio"),
                  "qualificacao": s.get("qualificacao_socio"),
                  "faixa_etaria": s.get("faixa_etaria"),
                  "entrada": _data(s.get("data_entrada_sociedade")),
                  "pais": s.get("pais"),
                  "representante_nome": s.get("nome_representante_legal"),
                  "representante_doc": s.get("cpf_representante_legal"),
                  "representante_qualif": s.get("qualificacao_representante_legal")}
                 for s in (d.get("qsa") or [])],
    }

def _receitaws(cnpj):
    r = requests.get(f"https://receitaws.com.br/v1/cnpj/{cnpj}", timeout=TIMEOUT, headers=UA)
    r.raise_for_status()
    d = r.json()
    if d.get("status") == "ERROR":
        raise ValueError(d.get("message") or "CNPJ nao encontrado")
    ap = d.get("atividade_principal") or [{}]
    return {
      "fonte": "receitaws", "bruto": d,
      "razao_social": d.get("nome"), "nome_fantasia": d.get("fantasia") or None,
      "matriz_filial": d.get("tipo"), "situacao_cadastral": d.get("situacao"),
      "situacao_data": _data(d.get("data_situacao")), "situacao_motivo": d.get("motivo_situacao"),
      "situacao_especial": d.get("situacao_especial") or None,
      "abertura": _data(d.get("abertura")),
      "natureza_juridica": d.get("natureza_juridica"), "natureza_juridica_cod": None,
      "porte": d.get("porte"), "capital_social": _num(d.get("capital_social")),
      "cnae_principal": limpa(ap[0].get("code")) or None,
      "cnae_principal_desc": ap[0].get("text"),
      "logradouro": d.get("logradouro"), "numero": d.get("numero"),
      "complemento": d.get("complemento") or None, "bairro": d.get("bairro"),
      "cep": limpa(d.get("cep"))[:8] or None, "municipio_nome": d.get("municipio"),
      "municipio_ibge": None, "uf": d.get("uf"),
      "telefone1": (d.get("telefone") or "").strip() or None, "telefone2": None,
      "email": (d.get("email") or "").strip().lower() or None,
      "simples_optante": (d.get("simples") or {}).get("optante"),
      "simples_desde": _data((d.get("simples") or {}).get("data_opcao")),
      "simples_ate": _data((d.get("simples") or {}).get("data_exclusao")),
      "mei_optante": (d.get("simei") or {}).get("optante"),
      "mei_desde": _data((d.get("simei") or {}).get("data_opcao")),
      "cnaes": [{"codigo": limpa(c.get("code")), "descricao": c.get("text"),
                 "principal": False} for c in (d.get("atividades_secundarias") or [])
                 if limpa(c.get("code"))],
      "socios": [{"nome": s.get("nome"), "documento": None,
                  "qualificacao": s.get("qual"), "faixa_etaria": None, "entrada": None,
                  "pais": s.get("pais_origem"),
                  "representante_nome": s.get("nome_rep_legal"),
                  "representante_doc": None,
                  "representante_qualif": s.get("qual_rep_legal")}
                 for s in (d.get("qsa") or [])],
    }

def consulta(cnpj, conn_q=None):
    """BrasilAPI com retry em 429; ReceitaWS so como ultimo recurso.
    conn_q: funcao de query, usada para completar o IBGE localmente."""
    c = limpa(cnpj)
    if len(c) != 14:
        raise ValueError("CNPJ deve ter 14 digitos")

    d = None
    erros = []
    for tentativa in range(4):
        _throttle()
        try:
            d = _brasilapi(c)
            break
        except ValueError:
            raise
        except requests.HTTPError as e:
            cod = e.response.status_code if e.response is not None else 0
            erros.append(f"brasilapi {cod}")
            if cod in (429, 502, 503, 504):
                time.sleep((2 ** tentativa) + random.uniform(0, 0.6))
                continue
            break
        except Exception as e:
            erros.append(f"brasilapi {type(e).__name__}")
            time.sleep(1 + tentativa)

    if d is None:
        try:
            _throttle(2.0)
            d = _receitaws(c)
        except ValueError:
            raise
        except Exception as e:
            erros.append(f"receitaws {type(e).__name__}")
            raise RuntimeError(
                "Nao foi possivel consultar o CNPJ agora (" + "; ".join(erros) +
                "). Tente de novo em instantes ou cadastre manualmente.")

    if not d.get("municipio_ibge") and conn_q:
        d["municipio_ibge"] = resolve_ibge(conn_q, d.get("municipio_nome"), d.get("uf"))
        d["ibge_local"] = True

    if d.get("simples_optante") is None and d.get("porte"):
        d["simples_incerto"] = True

    return d
