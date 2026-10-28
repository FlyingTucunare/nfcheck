"""Envio de e-mail transacional pelo Resend.

O dominio nfcheck.com.br ainda nao esta verificado no Resend (depende de
upgrade do plano), entao o envio sai por orbita.log.br com o NOME de
exibicao "NFCheck" - na caixa de entrada o destinatario ve NFCheck, e o
dominio tecnico so aparece se ele inspecionar o cabecalho.
Quando o dominio for verificado, basta trocar REMETENTE.
"""
import os

import requests

API = "https://api.resend.com/emails"
REMETENTE = os.environ.get("EMAIL_REMETENTE", "NFCheck <notificacoes@orbita.log.br>")
RESPONDER = os.environ.get("EMAIL_RESPONDER", "")
BASE_URL = os.environ.get("APP_URL", "https://app.nfcheck.com.br")

TINTA = "#061E38"
AZUL = "#0B3A66"
LARANJA = "#DE6127"
CINZA = "#5B6B7C"
LINHA = "#D6DEE6"

LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 76" width="150" height="38">
  <rect x="2" y="22" width="9" height="30" rx="4.5" fill="#061E38"/>
  <rect x="18" y="34" width="9" height="30" rx="4.5" fill="#0B3A66"/>
  <rect x="34" y="48" width="9" height="30" rx="4.5" fill="#1663A8"/>
  <rect x="50" y="34" width="9" height="30" rx="4.5" fill="#B34718"/>
  <rect x="66" y="16" width="9" height="30" rx="4.5" fill="#DE6127"/>
  <rect x="82" y="0" width="9" height="30" rx="4.5" fill="#EFA33A"/>
  <text x="108" y="52" font-family="Helvetica,Arial,sans-serif" font-size="38"
        font-weight="700" fill="#061E38" letter-spacing="-1">NF</text>
  <text x="160" y="52" font-family="Helvetica,Arial,sans-serif" font-size="38"
        font-weight="400" fill="#DE6127" letter-spacing="-1">Check</text>
</svg>"""


def _chave():
    k = os.environ.get("RESEND_API_KEY")
    if not k:
        raise RuntimeError("RESEND_API_KEY ausente no .env")
    return k


def moldura(titulo, corpo, rodape_extra=""):
    """Envolve o conteudo no layout da marca. Tabela e estilo inline porque
    cliente de e-mail nao le CSS externo nem flexbox."""
    return f"""<!doctype html><html><body style="margin:0;padding:0;
background:#F2F4F7;font-family:Helvetica,Arial,sans-serif;color:{TINTA}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="background:#F2F4F7;padding:28px 12px">
<tr><td align="center">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
   style="max-width:560px;background:#fff;border:1px solid {LINHA};
   border-radius:10px;overflow:hidden">
    <tr><td style="padding:22px 28px;border-bottom:1px solid {LINHA}">{LOGO}</td></tr>
    <tr><td style="padding:28px">
      <h1 style="margin:0 0 16px;font-size:19px;font-weight:600;
       letter-spacing:-.01em">{titulo}</h1>
      {corpo}
    </td></tr>
    <tr><td style="padding:16px 28px;border-top:1px solid {LINHA};
     background:#FAFBFC">
      <p style="margin:0;font-size:11px;color:{CINZA};line-height:1.6">
        NFCheck &mdash; gestão de documentos fiscais.<br>
        Esta mensagem foi enviada automaticamente. {rodape_extra}
      </p>
    </td></tr>
  </table>
</td></tr></table></body></html>"""


def envia(para, assunto, html, texto=None):
    """Envia e devolve (ok, detalhe). Nunca levanta excecao: falha de e-mail
    nao pode derrubar a operacao que o disparou."""
    try:
        corpo = {"from": REMETENTE, "to": [para] if isinstance(para, str) else para,
                 "subject": assunto, "html": html}
        if texto:
            corpo["text"] = texto
        if RESPONDER:
            corpo["reply_to"] = RESPONDER
        r = requests.post(API, json=corpo, timeout=20,
                          headers={"Authorization": f"Bearer {_chave()}",
                                   "Content-Type": "application/json"})
        if r.status_code >= 300:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        return True, (r.json() or {}).get("id")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# --------------------------------------------------------------- modelos
def boas_vindas(nome, email, senha, perfil_rotulo, contabilidade=None):
    """Credenciais de primeiro acesso.

    A senha vai no corpo porque e provisoria e expira no primeiro uso -
    o sistema obriga a troca antes de liberar qualquer tela.
    """
    primeiro = (nome or "").split()[0] if nome else ""
    corpo = f"""
      <p style="margin:0 0 14px;font-size:14px;line-height:1.65">
        Olá, {primeiro}. Seu acesso ao NFCheck foi criado
        {f'pela <b>{contabilidade}</b>' if contabilidade else ''}.
      </p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#F7F9FB;border:1px solid {LINHA};border-radius:8px;
       margin:18px 0">
        <tr><td style="padding:16px 18px">
          <p style="margin:0 0 10px;font-size:11px;color:{CINZA};
           text-transform:uppercase;letter-spacing:.08em">Seus dados de acesso</p>
          <p style="margin:0 0 6px;font-size:14px">
            <span style="color:{CINZA}">E-mail:</span>
            <b style="font-family:ui-monospace,Menlo,monospace">{email}</b></p>
          <p style="margin:0 0 6px;font-size:14px">
            <span style="color:{CINZA}">Senha provisória:</span>
            <b style="font-family:ui-monospace,Menlo,monospace;font-size:16px">{senha}</b></p>
          <p style="margin:0;font-size:14px">
            <span style="color:{CINZA}">Perfil:</span> {perfil_rotulo}</p>
        </td></tr>
      </table>
      <p style="margin:0 0 20px;font-size:13px;line-height:1.65;color:{CINZA}">
        No primeiro acesso o sistema pede para você criar uma senha própria.
        Depois disso, esta senha provisória deixa de valer.
      </p>
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="background:{LARANJA};border-radius:7px">
          <a href="{BASE_URL}" style="display:inline-block;padding:12px 26px;
           color:#fff;text-decoration:none;font-size:14px;font-weight:600">
            Acessar o NFCheck</a>
        </td></tr></table>
      <p style="margin:20px 0 0;font-size:12px;color:{CINZA};line-height:1.6">
        Ou copie este endereço: <span style="color:{AZUL}">{BASE_URL}</span>
      </p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="margin-top:22px;border-top:1px solid {LINHA}">
        <tr><td style="padding-top:16px">
          <p style="margin:0;font-size:12px;color:{CINZA};line-height:1.65">
            <b>Proteja sua conta:</b> não compartilhe suas credenciais.
            Ative a verificação em duas etapas em Segurança da conta &mdash;
            o sistema guarda certificados digitais.
          </p>
        </td></tr></table>"""

    texto = (f"Ola, {primeiro}.\n\nSeu acesso ao NFCheck foi criado.\n\n"
             f"E-mail: {email}\nSenha provisoria: {senha}\nPerfil: {perfil_rotulo}\n\n"
             f"Acesse {BASE_URL} - no primeiro acesso voce cria sua propria senha.\n\n"
             f"Nao compartilhe suas credenciais.")
    return envia(email, "Seu acesso ao NFCheck", moldura("Bem-vindo ao NFCheck", corpo),
                 texto)


def senha_redefinida(nome, email, senha):
    primeiro = (nome or "").split()[0] if nome else ""
    corpo = f"""
      <p style="margin:0 0 14px;font-size:14px;line-height:1.65">
        Olá, {primeiro}. Sua senha do NFCheck foi redefinida por um
        administrador.
      </p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#F7F9FB;border:1px solid {LINHA};border-radius:8px;
       margin:18px 0">
        <tr><td style="padding:16px 18px">
          <p style="margin:0 0 6px;font-size:14px">
            <span style="color:{CINZA}">E-mail:</span>
            <b style="font-family:ui-monospace,Menlo,monospace">{email}</b></p>
          <p style="margin:0;font-size:14px">
            <span style="color:{CINZA}">Nova senha provisória:</span>
            <b style="font-family:ui-monospace,Menlo,monospace;font-size:16px">{senha}</b></p>
        </td></tr></table>
      <p style="margin:0 0 20px;font-size:13px;line-height:1.65;color:{CINZA}">
        No próximo acesso você define uma senha própria.
        <b>Se não foi você quem pediu, avise o administrador da sua
        contabilidade imediatamente.</b>
      </p>
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="background:{LARANJA};border-radius:7px">
          <a href="{BASE_URL}" style="display:inline-block;padding:12px 26px;
           color:#fff;text-decoration:none;font-size:14px;font-weight:600">
            Entrar no NFCheck</a>
        </td></tr></table>"""
    texto = (f"Ola, {primeiro}.\n\nSua senha do NFCheck foi redefinida.\n\n"
             f"E-mail: {email}\nNova senha provisoria: {senha}\n\n"
             f"Acesse {BASE_URL}. Se nao foi voce quem pediu, avise o "
             f"administrador da sua contabilidade.")
    return envia(email, "Sua senha do NFCheck foi redefinida",
                 moldura("Senha redefinida", corpo), texto)

def empresa_adicionada(nome, email, empresa, contabilidade=None, total=None):
    """Avisa o cliente que ganhou acesso a mais uma empresa.

    O cliente_final pode ser dono de varias empresas: o acesso e da PESSOA,
    e cada empresa nova entra no mesmo login. O aviso existe para ele saber
    que o escopo do acesso dele mudou - transparencia sobre o proprio dado.
    """
    primeiro = (nome or "").split()[0] if nome else ""
    corpo = f"""
      <p style="margin:0 0 14px;font-size:14px;line-height:1.65">
        Olá, {primeiro}. A empresa abaixo foi adicionada ao seu acesso
        no NFCheck{f' pela <b>{contabilidade}</b>' if contabilidade else ''}.
      </p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#F7F9FB;border:1px solid {LINHA};border-radius:8px;
       margin:18px 0">
        <tr><td style="padding:16px 18px">
          <p style="margin:0 0 4px;font-size:11px;color:{CINZA};
           text-transform:uppercase;letter-spacing:.08em">Empresa adicionada</p>
          <p style="margin:0;font-size:15px;font-weight:600">{empresa}</p>
        </td></tr></table>
      <p style="margin:0 0 20px;font-size:13px;line-height:1.65;color:{CINZA}">
        Use o mesmo e-mail e senha de sempre.
        {f'Seu acesso passa a cobrir {total} empresas.' if total and total > 1 else ''}
        Ao entrar, escolha a empresa que quer consultar.
      </p>
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="background:{LARANJA};border-radius:7px">
          <a href="{BASE_URL}" style="display:inline-block;padding:12px 26px;
           color:#fff;text-decoration:none;font-size:14px;font-weight:600">
            Acessar o NFCheck</a>
        </td></tr></table>
      <p style="margin:20px 0 0;font-size:12px;color:{CINZA};line-height:1.6">
        Se você não reconhece esta empresa, avise sua contabilidade.
      </p>"""
    texto = (f"Ola, {primeiro}.\n\nA empresa {empresa} foi adicionada ao seu "
             f"acesso no NFCheck.\n\nUse o mesmo e-mail e senha de sempre em "
             f"{BASE_URL}.\n\nSe voce nao reconhece esta empresa, avise sua "
             f"contabilidade.")
    return envia(email, f"{empresa} foi adicionada ao seu acesso",
                 moldura("Nova empresa no seu acesso", corpo), texto)


def alertas_do_dia(para, contabilidade, itens):
    """Um resumo por contabilidade, nunca um e-mail por alerta.

    Com 80 empresas, um e-mail por problema faria a pessoa criar um filtro e
    nunca mais ler nenhum - o alerta viraria ruido em vez de proteger.
    """
    criticos = [i for i in itens if i["nivel"] == "erro"]
    avisos = [i for i in itens if i["nivel"] != "erro"]

    def bloco(lista, cor, rotulo):
        if not lista:
            return ""
        return (f'<p style="margin:18px 0 8px;font-size:11px;color:{CINZA};'
                f'text-transform:uppercase;letter-spacing:.08em;'
                f'font-weight:600">{rotulo}</p>' +
                "".join(
                    f'<table role="presentation" width="100%" cellpadding="0" '
                    f'cellspacing="0" style="border-left:3px solid {cor};'
                    f'background:#F7F9FB;border-radius:0 6px 6px 0;margin-bottom:8px">'
                    f'<tr><td style="padding:12px 14px">'
                    f'<p style="margin:0;font-size:14px;font-weight:600">{i["titulo"]}</p>'
                    f'<p style="margin:4px 0 0;font-size:12.5px;color:{CINZA};'
                    f'line-height:1.55">{i["detalhe"] or ""}</p>'
                    f'</td></tr></table>' for i in lista))

    corpo = (
        f'<p style="margin:0 0 4px;font-size:14px;line-height:1.65">'
        f'Encontramos {len(itens)} ponto(s) de atenção nas empresas da '
        f'<b>{contabilidade}</b>.</p>'
        + bloco(criticos, "#C0392B", "Precisam de ação")
        + bloco(avisos, LARANJA, "Vale acompanhar")
        + f'<table role="presentation" cellpadding="0" cellspacing="0" '
          f'style="margin-top:22px"><tr><td style="background:{LARANJA};'
          f'border-radius:7px"><a href="{BASE_URL}/escritorio/alertas" '
          f'style="display:inline-block;padding:12px 26px;color:#fff;'
          f'text-decoration:none;font-size:14px;font-weight:600">'
          f'Ver no NFCheck</a></td></tr></table>')

    texto = f"{len(itens)} ponto(s) de atencao em {contabilidade}:\n\n" + \
        "\n".join(f"- [{i['nivel']}] {i['titulo']}" for i in itens) + \
        f"\n\nDetalhes em {BASE_URL}/escritorio/alertas"

    assunto = (f"{len(criticos)} pendência(s) crítica(s) no NFCheck"
               if criticos else f"{len(itens)} ponto(s) de atenção no NFCheck")
    return envia(para, assunto, moldura("Pontos de atenção", corpo), texto)
