/* Modulo: seguranca da conta - troca de senha e 2FA (TOTP). */

let SIT = null, PREPARO = null;

const err = m => { const e = $('#erro'); e.textContent = m || '';
  e.classList.toggle('on', !!m); };

/* ---------------- senha ---------------- */
function conferaRegras(){
  const s = $('#s-nova').value;
  const r = {tam: s.length >= 10, letra: /[a-zA-Z]/.test(s), num: /[0-9]/.test(s)};
  Object.entries(r).forEach(([k, ok]) => {
    const li = document.querySelector('[data-r="' + k + '"]');
    if (li) li.classList.toggle('ok', ok);
  });
  return Object.values(r).every(Boolean);
}

async function trocaSenha(){
  err('');
  const atual = $('#s-atual').value, nova = $('#s-nova').value,
        nova2 = $('#s-nova2').value;
  if (!atual) return err('Informe a senha atual.');
  if (!conferaRegras()) return err('A nova senha não atende aos requisitos.');
  if (nova !== nova2) return err('As senhas não conferem.');

  const b = $('#b-senha'); b.disabled = true; b.textContent = 'Salvando...';
  try {
    await api.post('/api/senha/trocar', {senha_atual: atual, senha_nova: nova});
    ['#s-atual','#s-nova','#s-nova2'].forEach(i => $(i).value = '');
    conferaRegras();
    toast('Senha alterada.');
    await carrega();
  } catch(e){ err(e.message); }
  finally { b.disabled = false; b.textContent = 'Alterar senha'; }
}

/* ---------------- 2FA ---------------- */
function pinta2fa(){
  const a = $('#area-2fa');
  if (SIT && SIT.ativo){
    a.innerHTML =
      '<div class="estado ativo">' + Icone.escudo +
        '<div class="txt"><b>Ativa</b>' +
        'Seu acesso pede código além da senha.</div></div>' +
      '<div class="rl" style="display:flex;justify-content:space-between;' +
        'padding:6px 0;font-size:var(--t-sm)">' +
        '<span class="t3">Códigos de recuperação disponíveis</span>' +
        '<b>' + SIT.codigos_restantes + '</b></div>' +
      '<div style="display:flex;gap:var(--e-3);margin-top:var(--e-4)">' +
        '<button class="btn btn-2" id="b-novos">Gerar novos códigos</button>' +
        '<button class="btn btn-3" id="b-desativar">Desativar</button>' +
      '</div>' +
      (SIT.codigos_restantes <= 2
        ? '<div class="aviso aviso-atencao on" style="margin-top:var(--e-4)">' +
          'Restam poucos códigos de recuperação. Gere novos e guarde em local ' +
          'seguro.</div>' : '');
    $('#b-desativar').onclick = desativa;
    $('#b-novos').onclick = () => prepara(true);
    return;
  }

  a.innerHTML =
    '<div class="estado inativo">' + Icone.alerta +
      '<div class="txt"><b>Não ativada</b>' +
      'Sua conta depende só da senha.</div></div>' +
    '<p class="t3" style="line-height:1.7;margin-bottom:var(--e-4)">' +
      'Você vai precisar de um aplicativo autenticador no celular — ' +
      'Google Authenticator, Microsoft Authenticator ou Authy, por exemplo.</p>' +
    '<button class="btn btn-1" id="b-ativar">Ativar verificação em duas etapas</button>';
  $('#b-ativar').onclick = () => prepara(false);
}

async function prepara(renovando){
  err('');
  try {
    PREPARO = await api.post('/api/2fa/preparar', {});
  } catch(e){ return err(e.message); }

  Modal.cria({
    id:'m-2fa',
    titulo: renovando ? 'Gerar novos códigos' : 'Ativar verificação em duas etapas',
    corpo:
      '<p class="t3" style="line-height:1.7;margin-bottom:var(--e-4)">' +
        '1. Abra seu aplicativo autenticador<br>' +
        '2. Escaneie o QR Code abaixo<br>' +
        '3. Digite o código de 6 dígitos que aparecer</p>' +
      (PREPARO.qrcode
        ? '<div class="qr">' + PREPARO.qrcode + '</div>'
        : '<div class="aviso aviso-atencao on">Não foi possível gerar o QR Code. ' +
          'Cadastre a chave manualmente no aplicativo.</div>') +
      '<div class="campo-grupo">' +
        '<label class="rotulo">Chave para cadastro manual</label>' +
        '<div class="segredo">' + Fmt.escapa(PREPARO.segredo) + '</div>' +
      '</div>' +
      '<div class="campo-grupo">' +
        '<label class="rotulo">Código do aplicativo</label>' +
        '<input class="campo cod-input" id="f-cod" inputmode="numeric" ' +
          'maxlength="6" placeholder="000000" autocomplete="one-time-code">' +
      '</div>' +
      '<div class="aviso aviso-erro" id="e-2fa"></div>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Confirmar', cls:'btn-1', id:'b-conf', fn: ativa},
    ],
  });
  Modal.abre('m-2fa');
  setTimeout(() => { const c = $('#f-cod'); if (c){ c.focus();
    c.onkeydown = e => { if (e.key === 'Enter') ativa(); }; } }, 80);
}

async function ativa(){
  const fe = $('#e-2fa'); fe.classList.remove('on');
  const codigo = ($('#f-cod').value || '').trim();
  if (codigo.length !== 6){
    fe.textContent = 'Digite os 6 dígitos.'; fe.classList.add('on'); return;
  }
  const b = $('#b-conf'); b.disabled = true; b.textContent = 'Verificando...';
  try {
    const d = await api.post('/api/2fa/ativar',
      {segredo: PREPARO.segredo, codigo});
    Modal.fecha('m-2fa');
    mostraCodigos(d.codigos_recuperacao);
    await carrega();
  } catch(e){
    fe.textContent = e.message; fe.classList.add('on');
    b.disabled = false; b.textContent = 'Confirmar';
  }
}

function mostraCodigos(codigos){
  Modal.cria({
    id:'m-cod', titulo:'Guarde seus códigos de recuperação',
    corpo:
      '<div class="aviso aviso-atencao on" style="margin-bottom:var(--e-4)">' +
        'Estes códigos aparecem <b>uma única vez</b>. Cada um serve para um ' +
        'acesso, caso você perca o celular. Guarde em local seguro — fora ' +
        'deste sistema.</div>' +
      '<div class="codigos">' +
        codigos.map(c => '<div>' + Fmt.escapa(c) + '</div>').join('') +
      '</div>',
    acoes:[
      {txt:'Copiar', cls:'btn-2', fn: () => {
        navigator.clipboard.writeText(codigos.join('\n'));
        toast('Códigos copiados.');
      }},
      {txt:'Guardei os códigos', cls:'btn-1'},
    ],
  });
  Modal.abre('m-cod');
}

function desativa(){
  Modal.cria({
    id:'m-off', titulo:'Desativar verificação em duas etapas',
    corpo:
      '<div class="aviso aviso-atencao on" style="margin-bottom:var(--e-4)">' +
        'Sua conta volta a depender apenas da senha.</div>' +
      '<div class="campo-grupo">' +
        '<label class="rotulo">Confirme sua senha</label>' +
        '<input class="campo" type="password" id="f-senha-off">' +
      '</div>' +
      '<div class="aviso aviso-erro" id="e-off"></div>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Desativar', cls:'btn-perigo', id:'b-off', fn: async () => {
        const fe = $('#e-off'); fe.classList.remove('on');
        const b = $('#b-off'); b.disabled = true;
        try {
          await api.post('/api/2fa/desativar', {senha: $('#f-senha-off').value});
          Modal.fecha('m-off'); toast('Verificação em duas etapas desativada.');
          await carrega();
        } catch(e){
          fe.textContent = e.message; fe.classList.add('on'); b.disabled = false;
        }
      }},
    ],
  });
  Modal.abre('m-off');
}

/* ---------------- carga ---------------- */
async function carrega(){
  SIT = await api.get('/api/2fa/situacao');
  pinta2fa();
  if (SIT.senha_provisoria){
    $('#desc-senha').innerHTML = '<span style="color:var(--aviso)">' +
      'Sua senha foi definida por outra pessoa. Troque agora por uma que ' +
      'só você conheça.</span>';
  }
}

(async () => {
  await Shell.monta({});
  $('#b-senha').onclick = trocaSenha;
  $('#s-nova').oninput = conferaRegras;
  try { await carrega(); } catch(e){ err(e.message); }
})();
