/* Modulo: trilha de auditoria.
   Registra o que foi feito no sistema - login, senha, 2FA, certificado,
   emissao, cancelamento. Serve para responder "quem mexeu nisso?" sem
   depender de memoria. */

let DADOS = [], GRID = null;

const err = m => { const e = $('#erro'); e.textContent = m || '';
  e.classList.toggle('on', !!m); };

/* rotulos em portugues; acao desconhecida aparece crua, sem esconder nada */
const ROTULO = {
  login: 'Entrou no sistema',
  senha_alterada: 'Alterou a própria senha',
  senha_resetada: 'Resetou a senha de alguém',
  '2fa_ativado': 'Ativou verificação em duas etapas',
  '2fa_desativado': 'Desativou a própria verificação',
  '2fa_desativado_por_admin': 'Desativou o 2FA de outro usuário',
  usuario_criado: 'Criou um usuário',
  usuario_editado: 'Editou um usuário',
  usuario_ativado: 'Reativou um acesso',
  usuario_desativado: 'Desativou um acesso',
  acesso_cliente_criado: 'Deu acesso a um cliente',
  empresa_vinculada_a_cliente: 'Vinculou empresa a um cliente',
  dfe_ligado: 'Ligou a busca de documentos',
  dfe_desligado: 'Desligou a busca de documentos',
  cert_enviado: 'Enviou um certificado',
  config_sincronizacao: 'Alterou a configuração de sincronização',
  empresa_criada: 'Cadastrou uma empresa',
  empresa_arquivada: 'Arquivou uma empresa',
};

/* acoes que merecem destaque: mexem em acesso ou em documento fiscal */
const SENSIVEIS = new Set(['senha_resetada', '2fa_desativado_por_admin',
  'usuario_desativado', 'usuario_criado', 'acesso_cliente_criado',
  'cert_enviado', 'empresa_arquivada', 'dfe_ligado']);

const rotulo = a => ROTULO[a] || a;

function quando(d){
  const dt = new Date(d);
  const hoje = new Date();
  const mesmoDia = dt.toDateString() === hoje.toDateString();
  const hora = dt.toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'});
  return mesmoDia ? 'hoje ' + hora
    : dt.toLocaleDateString('pt-BR', {day:'2-digit', month:'2-digit'}) + ' ' + hora;
}

const COLUNAS = [
  {k:'criado_em', t:'Quando', w:130, num:true, cel: r => quando(r.criado_em)},
  {k:'usuario', t:'Quem', w:200,
   cel: r => r.usuario
     ? '<b>' + Fmt.escapa(r.usuario) + '</b>' +
       '<div class="t3">' + Fmt.escapa(r.usuario_email || '') + '</div>'
     : '<span class="t3">sistema</span>'},
  {k:'acao', t:'O que fez', w:260,
   cel: r => (SENSIVEIS.has(r.acao)
     ? '<b>' + Fmt.escapa(rotulo(r.acao)) + '</b>'
     : Fmt.escapa(rotulo(r.acao)))},
  {k:'empresa', t:'Empresa', w:210,
   cel: r => r.empresa ? Fmt.escapa(r.empresa) : '<span class="t3">—</span>'},
  {k:'ip', t:'Origem', w:130, num:true,
   cel: r => r.ip ? Fmt.escapa(r.ip) : '<span class="t3">—</span>'},
  {k:'detalhe', t:'', w:70, cel: r => r.detalhe
    ? '<button class="btn btn-3 btn-icone btn-sm" data-parar data-det="' + r.id +
      '" aria-label="Ver detalhes">' + Icone.arquivo + '</button>'
    : ''},
];

function detalhes(r){
  Modal.cria({
    id:'m-det', titulo: rotulo(r.acao),
    corpo:
      '<div style="display:flex;justify-content:space-between;padding:5px 0;' +
        'font-size:var(--t-sm)"><span class="t3">Quando</span><b>' +
        new Date(r.criado_em).toLocaleString('pt-BR') + '</b></div>' +
      '<div style="display:flex;justify-content:space-between;padding:5px 0;' +
        'font-size:var(--t-sm)"><span class="t3">Quem</span><b>' +
        Fmt.escapa(r.usuario || 'sistema') + '</b></div>' +
      (r.ip ? '<div style="display:flex;justify-content:space-between;padding:5px 0;' +
        'font-size:var(--t-sm)"><span class="t3">Origem</span><b class="num">' +
        Fmt.escapa(r.ip) + '</b></div>' : '') +
      (r.empresa ? '<div style="display:flex;justify-content:space-between;' +
        'padding:5px 0;font-size:var(--t-sm)"><span class="t3">Empresa</span><b>' +
        Fmt.escapa(r.empresa) + '</b></div>' : '') +
      '<div class="t3" style="margin:var(--e-4) 0 6px">Detalhes</div>' +
      '<div class="det">' +
        Fmt.escapa(JSON.stringify(r.detalhe, null, 2)) + '</div>',
    acoes:[{txt:'Fechar', cls:'btn-2'}],
  });
  Modal.abre('m-det');
}

async function carrega(){
  const p = new URLSearchParams();
  const i = $('#f-inicio').value, f = $('#f-fim').value, a = $('#f-acao').value;
  if (i) p.set('inicio', i);
  if (f) p.set('fim', f);
  if (a) p.set('acao', a);

  const d = await api.get('/api/auditoria' + (p.toString() ? '?' + p : ''));
  DADOS = d.registros || [];
  GRID.dados(DADOS);

  const sel = $('#f-acao');
  if (!sel.dataset.pronto){
    sel.innerHTML = '<option value="">Todas</option>' +
      (d.acoes || []).map(x => '<option value="' + x.acao + '">' +
        Fmt.escapa(rotulo(x.acao)) + ' (' + x.n + ')</option>').join('');
    sel.dataset.pronto = '1';
  }
}

(async () => {
  await Shell.monta({});
  GRID = new Grid({
    alvo:'#area', chave:'auditoria', colunas:COLUNAS, ordemInicial:'criado_em',
    busca: r => [r.usuario, r.usuario_email, rotulo(r.acao), r.empresa, r.ip],
    vazio: {titulo:'Nada registrado',
            texto:'As ações feitas no sistema aparecem aqui.'},
  });
  GRID.barra('#barra', {placeholder:'Buscar por pessoa, ação, empresa ou IP...'});

  $('#area').addEventListener('click', ev => {
    const b = ev.target.closest('[data-det]');
    if (b){
      ev.stopPropagation();
      const r = DADOS.find(x => String(x.id) === b.dataset.det);
      if (r) detalhes(r);
    }
  });

  ['f-inicio','f-fim','f-acao'].forEach(i => $('#' + i).onchange = carrega);
  $('#b-limpar').onclick = () => {
    ['f-inicio','f-fim','f-acao'].forEach(i => $('#' + i).value = '');
    carrega();
  };

  try { await carrega(); } catch(e){ err(e.message); }
})();
