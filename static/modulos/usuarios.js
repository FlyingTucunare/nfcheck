/* Modulo: usuarios e acessos.
   O e-mail e unico DENTRO da contabilidade - a mesma pessoa pode ser cliente
   de duas contabilidades diferentes, cada uma com seu proprio cadastro. */

let DADOS = {usuarios: [], perfis_criaveis: [], eu: null};
let EMPRESAS = [], GRID = null, FILTRO = null, EDITANDO = null;

const err = m => { const e = $('#erro'); e.textContent = m || '';
  e.classList.toggle('on', !!m); };

const soDigito = v => (v || '').replace(/\D/g, '');

const ROTULO = {
  superadmin: 'Administrador do sistema',
  contabilidade_admin: 'Admin da contabilidade',
  contabilidade_operador: 'Operador',
  cliente_final: 'Cliente',
};

function telFmt(v){
  const n = soDigito(v);
  if (n.length === 11) return '(' + n.slice(0,2) + ') ' + n.slice(2,7) + '-' + n.slice(7);
  if (n.length === 10) return '(' + n.slice(0,2) + ') ' + n.slice(2,6) + '-' + n.slice(6);
  return v || '—';
}
const quando = d => {
  if (!d) return 'nunca';
  const dias = Math.floor((Date.now() - new Date(d)) / 86400000);
  if (dias === 0) return 'hoje';
  if (dias === 1) return 'ontem';
  if (dias < 30) return 'há ' + dias + ' dias';
  return new Date(d).toLocaleDateString('pt-BR');
};

/* ---------------- KPIs ---------------- */
function pintaKpis(){
  const us = DADOS.usuarios;
  const ativos = us.filter(x => x.ativo).length;
  const sem2fa = us.filter(x => x.ativo && !x.totp_ativo).length;
  const nunca = us.filter(x => x.ativo && !x.ultimo_login).length;

  const cartao = (id, rot, val, risco) =>
    '<button class="kpi' + (FILTRO === id ? ' on' : '') +
      (risco ? ' risco' : '') + '" data-kpi="' + id + '">' +
      '<div class="kn">' + val + '</div><div class="kr">' + rot + '</div></button>';

  $('#kpis').innerHTML =
    cartao('todos', 'Usuários', us.length) +
    cartao('ativos', 'Ativos', ativos) +
    cartao('sem2fa', 'Sem 2FA', sem2fa, sem2fa > 0) +
    cartao('nunca', 'Nunca acessaram', nunca, nunca > 0);

  $$('[data-kpi]').forEach(b => b.onclick = () => {
    const k = b.dataset.kpi;
    FILTRO = (FILTRO === k || k === 'todos') ? null : k;
    const f = {
      ativos: x => x.ativo,
      sem2fa: x => x.ativo && !x.totp_ativo,
      nunca:  x => x.ativo && !x.ultimo_login,
    }[FILTRO];
    GRID.filtra(f || null);
    pintaKpis();
  });
}

/* ---------------- grid ---------------- */
const COLUNAS = [
  {k:'nome', t:'Nome', w:230,
   cel: x => '<b>' + Fmt.escapa(x.nome || '') + '</b>' +
     (x.ativo ? '' : ' <span class="chip chip-neutro">Inativo</span>')},
  {k:'email', t:'E-mail', w:230, cel: x => Fmt.escapa(x.email || '')},
  {k:'telefone', t:'Telefone', w:140, num:true, cel: x => telFmt(x.telefone)},
  {k:'perfil', t:'Perfil', w:180,
   cel: x => Fmt.escapa(ROTULO[x.perfil] || x.perfil) +
     (x.perfil === 'cliente_final'
       ? '<div class="t3">' + (x.empresas_vinculadas || 0) + ' empresa(s)</div>' : '')},
  {k:'totp_ativo', t:'2FA', w:90,
   cel: x => x.totp_ativo
     ? '<span class="chip chip-ok">Ativo</span>'
     : '<span class="chip chip-aviso">Não</span>'},
  {k:'ultimo_login', t:'Último acesso', w:140,
   cel: x => x.senha_provisoria
     ? '<span class="chip chip-aviso">Senha provisória</span>'
     : quando(x.ultimo_login)},
  {k:'acoes', t:'Ações', w:80, cel: x =>
    '<button class="btn btn-3 btn-icone btn-sm" data-parar data-acoes="' + x.id +
      '" aria-label="Ações">' + Icone.pontos + '</button>'},
];

function menuUsuario(botao, x){
  const eu = x.id === DADOS.eu;
  const itens = [{txt:'Editar cadastro', icone:'lapis', fn:() => abreForm(x)}];
  itens.push({txt:'Resetar senha', icone:'sync', fn:() => resetar(x)});
  if (x.totp_ativo)
    itens.push({txt:'Desativar 2FA', icone:'escudo', fn:() => desativar2fa(x)});
  if (!eu){
    itens.push({sep:true});
    itens.push(x.ativo
      ? {txt:'Desativar acesso', icone:'x', perigo:true, fn:() => situacao(x)}
      : {txt:'Reativar acesso', icone:'visto', fn:() => situacao(x)});
  }
  Menu.abre(botao, itens);
}

/* ---------------- acoes ---------------- */
function situacao(x){
  const desativando = x.ativo;
  Modal.cria({
    id:'m-sit', titulo: (desativando ? 'Desativar' : 'Reativar') + ' acesso',
    corpo:'<p>' + (desativando ? 'Desativar' : 'Reativar') + ' o acesso de <b>' +
      Fmt.escapa(x.nome) + '</b>?</p>' +
      (desativando
        ? '<p class="t3" style="margin-top:var(--e-3)">Ele perde o acesso ' +
          'imediatamente. O histórico e a auditoria são preservados.</p>' : ''),
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt: desativando ? 'Desativar' : 'Reativar',
       cls: desativando ? 'btn-perigo' : 'btn-1', fn: async () => {
        try {
          await api.post('/api/usuarios/' + x.id + '/situacao', {});
          Modal.fecha('m-sit'); toast('Acesso atualizado.'); await carrega();
        } catch(e){ toast(e.message); }
      }},
    ],
  });
  Modal.abre('m-sit');
}

function resetar(x){
  Modal.cria({
    id:'m-res', titulo:'Resetar senha',
    corpo:'<p>Gerar uma nova senha provisória para <b>' +
      Fmt.escapa(x.nome) + '</b>?</p>' +
      '<p class="t3" style="margin-top:var(--e-3)">A senha atual deixa de ' +
      'valer na hora. A nova é enviada por e-mail e precisa ser trocada no ' +
      'primeiro acesso.</p>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Resetar senha', cls:'btn-1', id:'b-res', fn: async () => {
        const b = $('#b-res'); b.disabled = true; b.textContent = 'Gerando…';
        try {
          const d = await api.post('/api/usuarios/' + x.id + '/resetar-senha', {});
          Modal.fecha('m-res');
          mostraSenha(x.nome, x.email, d.senha, d.email_enviado, d.email_detalhe);
          await carrega();
        } catch(e){ toast(e.message); b.disabled = false;
          b.textContent = 'Resetar senha'; }
      }},
    ],
  });
  Modal.abre('m-res');
}

function mostraSenha(nome, email, senha, enviado, detalhe){
  Modal.cria({
    id:'m-senha', titulo:'Senha provisória gerada',
    corpo:
      (enviado
        ? '<div class="aviso aviso-ok on">Enviada por e-mail para <b>' +
          Fmt.escapa(email) + '</b>.</div>'
        : '<div class="aviso aviso-erro on">Não foi possível enviar o e-mail' +
          (detalhe ? ': ' + Fmt.escapa(detalhe) : '') +
          '. Passe a senha ao usuário por outro meio.</div>') +
      '<div class="senha-nova">' +
        '<div class="t3">Senha de ' + Fmt.escapa(nome) + '</div>' +
        '<div class="v">' + Fmt.escapa(senha) + '</div></div>' +
      '<p class="t3">Ela vale até o primeiro acesso, quando o sistema pede ' +
      'para criar uma senha própria.</p>',
    acoes:[
      {txt:'Copiar senha', cls:'btn-2', fn: () => {
        navigator.clipboard.writeText(senha); toast('Senha copiada.');
      }},
      {txt:'Fechar', cls:'btn-1'},
    ],
  });
  Modal.abre('m-senha');
}

function desativar2fa(x){
  Modal.cria({
    id:'m-2fa', titulo:'Desativar verificação em duas etapas',
    corpo:'<div class="aviso aviso-atencao on">Use isto quando <b>' +
      Fmt.escapa(x.nome) + '</b> perdeu o celular e não tem mais códigos de ' +
      'recuperação.</div>' +
      '<p class="t3" style="margin-top:var(--e-3)">A conta volta a depender ' +
      'só da senha. Peça para ele reativar assim que possível.</p>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Desativar 2FA', cls:'btn-perigo', fn: async () => {
        try {
          await api.post('/api/usuarios/' + x.id + '/desativar-2fa', {});
          Modal.fecha('m-2fa'); toast('2FA desativado.'); await carrega();
        } catch(e){ toast(e.message); }
      }},
    ],
  });
  Modal.abre('m-2fa');
}

/* ---------------- formulario ---------------- */
async function abreForm(x){
  EDITANDO = x || null;
  const v = x || {};
  const partes = (v.nome || '').trim().split(' ');
  const nome = partes[0] || '';
  const sobrenome = partes.slice(1).join(' ');

  let vinculadas = [];
  if (x && x.perfil === 'cliente_final'){
    try { vinculadas = await api.get('/api/usuarios/' + x.id + '/empresas'); }
    catch(e){}
  }

  const opPerfil = DADOS.perfis_criaveis.map(p =>
    '<option value="' + p.id + '"' + (v.perfil === p.id ? ' selected' : '') +
    '>' + Fmt.escapa(p.rotulo) + '</option>').join('');

  Modal.cria({
    id:'m-usr', titulo: x ? 'Editar usuário' : 'Novo usuário',
    corpo:
      '<div class="grade2">' +
        '<div class="campo-grupo"><label class="rotulo">Nome</label>' +
          '<input class="campo" id="f-nome" maxlength="40" value="' +
            Fmt.escapa(nome) + '"></div>' +
        '<div class="campo-grupo"><label class="rotulo">Sobrenome</label>' +
          '<input class="campo" id="f-sobre" maxlength="60" value="' +
            Fmt.escapa(sobrenome) + '"></div>' +
      '</div>' +
      '<div class="campo-grupo"><label class="rotulo">E-mail</label>' +
        '<input class="campo" type="email" id="f-email" maxlength="80" value="' +
          Fmt.escapa(v.email || '') + '"' + (x ? ' readonly ' +
          'style="background:var(--sup-2);color:var(--txt-2)"' : '') + '>' +
        (x ? '<div class="dica">O e-mail não pode ser alterado.</div>'
           : '<div class="dica">Será o login. As credenciais vão para este ' +
             'endereço.</div>') +
      '</div>' +
      '<div class="grade2">' +
        '<div class="campo-grupo"><label class="rotulo">Telefone</label>' +
          '<input class="campo" id="f-tel" maxlength="16" placeholder="(11) 90000-0000" ' +
            'value="' + telFmt(v.telefone) + '"></div>' +
        '<div class="campo-grupo"><label class="rotulo">CPF (opcional)</label>' +
          '<input class="campo" id="f-cpf" maxlength="14" placeholder="000.000.000-00" ' +
            'value="' + Fmt.escapa(v.cpf || '') + '"></div>' +
      '</div>' +
      '<div class="campo-grupo"><label class="rotulo">Perfil de acesso</label>' +
        '<select class="campo" id="f-perfil">' + opPerfil + '</select>' +
        '<div class="dica" id="dica-perfil"></div>' +
      '</div>' +
      '<div class="campo-grupo" id="box-empresas" style="display:none">' +
        '<label class="rotulo">Empresas que este cliente pode acessar</label>' +
        '<div class="lista-emp" id="lista-emp">' +
          EMPRESAS.map(e => '<label><input type="checkbox" value="' + e.id + '"' +
            (vinculadas.includes(e.id) ? ' checked' : '') + '>' +
            '<span>' + Fmt.escapa(e.razao_social) +
            '<span class="cnpj">' + Fmt.escapa(e.cnpj || '') + '</span></span></label>'
          ).join('') +
        '</div>' +
        '<div class="dica">O mesmo acesso serve para todas as empresas ' +
          'marcadas — útil quando o cliente é dono de mais de uma.</div>' +
      '</div>' +
      '<div class="aviso aviso-erro" id="f-erro"></div>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt: x ? 'Salvar' : 'Criar e enviar acesso', cls:'btn-1', id:'b-salvar',
       fn: salvar},
    ],
  });

  const ajusta = () => {
    const p = $('#f-perfil').value;
    $('#box-empresas').style.display = p === 'cliente_final' ? 'block' : 'none';
    $('#dica-perfil').textContent = {
      contabilidade_admin: 'Gerencia empresas, certificados e usuários da contabilidade.',
      contabilidade_operador: 'Trabalha nos módulos fiscais de todas as empresas.',
      cliente_final: 'Acessa apenas as empresas marcadas abaixo, sem editar cadastros.',
      superadmin: 'Acesso total ao sistema, em todas as contabilidades.',
    }[p] || '';
  };
  $('#f-perfil').onchange = ajusta;
  ajusta();
  Modal.abre('m-usr');
  setTimeout(() => $('#f-nome').focus(), 60);
}

async function salvar(){
  const fe = $('#f-erro');
  const mostra = m => { fe.textContent = m; fe.classList.add('on'); };
  fe.classList.remove('on');

  const nome = $('#f-nome').value.trim();
  const sobre = $('#f-sobre').value.trim();
  const email = $('#f-email').value.trim();
  const tel = soDigito($('#f-tel').value);
  const cpf = soDigito($('#f-cpf').value);
  const perfil = $('#f-perfil').value;

  if (!nome) return mostra('Informe o nome.');
  if (!sobre) return mostra('Informe o sobrenome.');
  if (!EDITANDO && !/^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$/.test(email))
    return mostra('Informe um e-mail válido.');
  if (tel.length < 10) return mostra('Informe o telefone com DDD.');
  if (cpf && cpf.length !== 11) return mostra('CPF deve ter 11 dígitos.');

  const empresas = perfil === 'cliente_final'
    ? $$('#lista-emp input:checked').map(i => Number(i.value)) : [];
  if (perfil === 'cliente_final' && !empresas.length)
    return mostra('Selecione ao menos uma empresa para o cliente acessar.');

  const b = $('#b-salvar'); b.disabled = true; b.textContent = 'Salvando…';
  try {
    if (EDITANDO){
      await api.put('/api/usuarios/' + EDITANDO.id, {
        nome, sobrenome: sobre, telefone: tel, cpf: cpf || null,
        perfil, empresas: perfil === 'cliente_final' ? empresas : null,
      });
      Modal.fecha('m-usr'); toast('Usuário atualizado.');
    } else {
      const d = await api.post('/api/usuarios', {
        nome, sobrenome: sobre, email, telefone: tel, cpf: cpf || null,
        perfil, empresas,
      });
      Modal.fecha('m-usr');
      mostraSenha(nome + ' ' + sobre, email, d.senha, d.email_enviado,
                  d.email_detalhe);
    }
    await carrega();
  } catch(e){ mostra(e.message); }
  finally { b.disabled = false;
    b.textContent = EDITANDO ? 'Salvar' : 'Criar e enviar acesso'; }
}

/* ---------------- carga ---------------- */
async function carrega(){
  DADOS = await api.get('/api/usuarios');
  GRID.dados(DADOS.usuarios);
  pintaKpis();
}

(async () => {
  await Shell.monta({});
  $('#novo').innerHTML = Icone.mais + 'Novo usuário';
  $('#novo').onclick = () => abreForm(null);

  GRID = new Grid({
    alvo:'#area', chave:'usuarios', colunas:COLUNAS, ordemInicial:'nome',
    busca: x => [x.nome, x.email, x.telefone, ROTULO[x.perfil]],
    vazio: {titulo:'Nenhum usuário cadastrado',
            texto:'Crie o primeiro acesso da sua equipe.'},
  });
  GRID.barra('#barra', {placeholder:'Buscar por nome, e-mail ou perfil...'});

  $('#area').addEventListener('click', ev => {
    const a = ev.target.closest('[data-acoes]');
    if (a){
      ev.stopPropagation();
      const x = DADOS.usuarios.find(y => String(y.id) === a.dataset.acoes);
      if (x) menuUsuario(a, x);
    }
  });

  try {
    EMPRESAS = await api.get('/api/usuarios/empresas-disponiveis');
    await carrega();
  } catch(e){ err(e.message); }
})();
