/* Modulo: Clientes — visao do escritorio */

const CERT = {
  ok:       {cls:'chip-ok',     txt:'Válido'},
  vencendo: {cls:'chip-aviso',  txt:'Vencendo'},
  vencido:  {cls:'chip-erro',   txt:'Vencido'},
  sem:      {cls:'chip-neutro', txt:'Sem certificado'},
};
const chip = (cls, txt) =>
  '<span class="chip ' + cls + '"><span class="ponto"></span>' + Fmt.escapa(txt) + '</span>';

const parado = e => !e.ultima_sync || (Date.now() - new Date(e.ultima_sync)) > 864e5;

const FILTROS = [
  {id:null,   r:'Empresas ativas'},
  {id:'cert', r:'Certificado vencendo', risco:true,
   fn:e => ['vencendo','vencido'].includes(e.cert_status)},
  {id:'sem',  r:'Sem certificado', risco:true, fn:e => e.cert_status === 'sem'},
  {id:'sync', r:'Sem sincronizar 24h', risco:true, fn:parado},
  {id:'manif', r:'Aguardando manifestação', risco:true, fn:e => e.pendentes > 0},
];

let GRID, DADOS = [], FILTRO = null;

function pintaKpis(){
  $('#kpis').innerHTML = FILTROS.map(f => {
    const n = f.fn ? DADOS.filter(f.fn).length : DADOS.length;
    const cls = ['kpi'];
    if (f.risco && n > 0) cls.push('risco');
    if (FILTRO === f.id) cls.push('on');
    return '<button class="' + cls.join(' ') + '" data-f="' + (f.id ?? '') + '">' +
      '<div class="kn">' + n + '</div><div class="kr">' + f.r + '</div></button>';
  }).join('');
  $$('.kpi').forEach(el => el.onclick = () => {
    const id = el.dataset.f || null;
    FILTRO = FILTRO === id ? null : id;
    const f = FILTROS.find(x => x.id === FILTRO);
    GRID.filtra(f && f.fn ? f.fn : null);
    pintaKpis();
  });
}

const kpiMini = (rot, val, destaque) =>
  '<div style="flex:1;min-width:0;text-align:center">' +
    '<div class="num" style="font-size:20px;font-weight:var(--p-forte);' +
      'letter-spacing:-.03em;line-height:1.15;white-space:nowrap;overflow:hidden;' +
      'text-overflow:ellipsis' + (destaque ? ';color:var(--aviso)' : '') + '">' +
      val + '</div>' +
    '<div style="font-size:9.5px;color:var(--txt-3);text-transform:uppercase;' +
      'letter-spacing:.06em;margin-top:5px;font-weight:var(--p-forte);' +
      'white-space:nowrap">' + rot + '</div>' +
  '</div>';

const compacto = v => {
  const n = Number(v) || 0;
  if (n >= 1e6) return 'R$ ' + (n/1e6).toFixed(1).replace('.', ',') + 'M';
  if (n >= 1e3) return 'R$ ' + (n/1e3).toFixed(1).replace('.', ',') + 'k';
  return 'R$ ' + n.toFixed(0);
};

const cartao = e => {
  const cs = CERT[e.cert_status] || CERT.sem;
  const chips = [chip(cs.cls, cs.txt)];
  if (e.regime_tributario) chips.push(chip('chip-neutro', e.regime_tributario));
  if (e.situacao_cadastral && e.situacao_cadastral !== 'ATIVA')
    chips.push(chip('chip-erro', e.situacao_cadastral));
  return '<div class="cartao cartao-click" style="display:flex;flex-direction:column;' +
      'gap:0;padding:var(--e-5)">' +
    '<div class="colunas" style="align-items:flex-start;gap:var(--e-3);' +
      'margin-bottom:18px">' +
      '<div style="min-width:0;flex:1">' +
        '<div style="font-weight:var(--p-forte);font-size:var(--t-lg);line-height:1.35;' +
          'display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;' +
          'overflow:hidden">' + Fmt.escapa(e.nome_fantasia || e.razao_social) + '</div>' +
        '<div class="num t3" style="margin-top:4px">' + Fmt.cnpj(e.cnpj) + '</div>' +
      '</div>' +
      '<div class="shell-sigla">' + Fmt.sigla(e.razao_social) + '</div>' +
    '</div>' +
    '<div class="colunas" style="flex-wrap:wrap;gap:6px;margin-bottom:20px">' +
      chips.join('') + '</div>' +

    '<div class="colunas" style="gap:var(--e-2);background:var(--sup-2);' +
      'border:1px solid var(--linha);border-radius:var(--r);' +
      'padding:18px var(--e-2);margin-bottom:14px">' +
      kpiMini('Docs', Fmt.numero(e.docs_mes)) +
      '<span style="width:1px;align-self:stretch;background:var(--linha)"></span>' +
      kpiMini('Valor', compacto(e.valor_mes)) +
      '<span style="width:1px;align-self:stretch;background:var(--linha)"></span>' +
      kpiMini('Manifestar', Fmt.numero(e.pendentes), e.pendentes > 0) +
    '</div>' +

    '<div class="colunas" style="font-size:10.5px;color:var(--txt-3);gap:var(--e-3);' +
      'margin-bottom:18px">' +
      '<span title="Último NSU de NF-e e CT-e">NSU ' +
        '<b class="num" style="color:var(--txt-2)">' + Fmt.numero(e.nsu_nfe || 0) +
        '</b> · <b class="num" style="color:var(--txt-2)">' + Fmt.numero(e.nsu_cte || 0) +
        '</b></span>' +
      '<span class="empurra">' + (e.pausado ? 'Pausado'
        : 'Sinc. ' + Fmt.relativo(e.ultima_sync)) + '</span>' +
    '</div>' +

    '<div class="colunas" style="border-top:1px solid var(--linha);padding-top:16px;' +
      'margin-top:auto;font-size:var(--t-sm);color:var(--txt-2)">' +
      '<span>' + Fmt.escapa(e.municipio_nome || '—') + (e.uf ? '/' + e.uf : '') +
        (e.cert_ate ? ' · vence <b style="color:var(--txt)">' + Fmt.data(e.cert_ate) +
        '</b>' : '') + '</span>' +
      '<span class="empurra colunas" style="gap:var(--e-4)">' +
        (Sessao.pode('empresa_escrever') ?
        '<button class="acao-txt" data-parar data-acoes="' + e.id + '">' +
          Icone.lapis + 'Editar</button>' : '') +
        '<span class="acao-txt">Abrir' + Icone.seta + '</span>' +
      '</span>' +
    '</div></div>';
};

const COLUNAS = [
  {k:'razao_social', t:'Empresa', w:250, cel: e =>
    '<div style="font-weight:var(--p-medio);overflow:hidden;text-overflow:ellipsis">' +
      Fmt.escapa(e.razao_social) + '</div>'},
  {k:'cnpj', t:'CNPJ', w:150, cel: e => '<span class="num">' + Fmt.cnpj(e.cnpj) + '</span>'},
  {k:'municipio_nome', t:'Município', w:150, cel: e =>
    Fmt.escapa(e.municipio_nome || '—') + (e.uf ? '/' + e.uf : '')},
  {k:'regime_tributario', t:'Regime', w:135},
  {k:'porte', t:'Porte', w:165},
  {k:'cert_status', t:'Certificado', w:145, cel: e => {
    const cs = CERT[e.cert_status] || CERT.sem;
    return '<span data-parar data-cert="' + e.id + '" style="cursor:pointer">' +
      chip(cs.cls, cs.txt) + '</span>';
  }},
  {k:'cert_ate', t:'Validade', w:105, cel: e =>
    '<span class="num">' + Fmt.data(e.cert_ate) + '</span>'},
  {k:'docs_mes', t:'Docs mês', w:95, num:true, cel: e =>
    '<span class="num">' + Fmt.numero(e.docs_mes) + '</span>'},
  {k:'valor_mes', t:'Valor mês', w:125, num:true, cel: e =>
    '<span class="num">' + Fmt.moeda(e.valor_mes) + '</span>'},
  {k:'pendentes', t:'A manifestar', w:110, num:true, cel: e =>
    '<span class="num" style="' + (e.pendentes > 0 ? 'color:var(--aviso);' +
      'font-weight:var(--p-forte)' : '') + '">' + Fmt.numero(e.pendentes) + '</span>'},
  {k:'ultima_sync', t:'Última sinc.', w:120, cel: e =>
    '<span class="' + (parado(e) ? 't3' : '') + '">' +
      (e.pausado ? 'Pausado' : Fmt.relativo(e.ultima_sync)) + '</span>'},
  {k:'acoes', t:'', w:52, cel: e =>
    '<button class="btn btn-3 btn-icone btn-sm" data-parar data-acoes="' + e.id +
      '" aria-label="Ações">' + Icone.pontos + '</button>'},
];

/* ---------- nova empresa ---------- */
function modalNova(){
  Modal.cria({
    id:'m-nova', titulo:'Nova empresa',
    corpo:
      '<div class="aviso aviso-erro" id="n-erro"></div>' +
      '<div class="grupo"><label class="rotulo" for="n-cnpj">CNPJ</label>' +
        '<div class="colunas" style="gap:var(--e-2)">' +
          '<input class="campo" id="n-cnpj" placeholder="00.000.000/0000-00" maxlength="18">' +
          '<button class="btn btn-2" id="n-buscar">Consultar</button></div>' +
        '<p class="dica">Os dados vêm da Receita Federal automaticamente.</p></div>' +
      '<div id="n-previa"></div>' +
      '<div class="aviso aviso-alerta" id="n-aviso"></div>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Cadastrar', cls:'btn-1', id:'n-salvar', fn:salvarNova},
    ],
  });
  Modal.abre('m-nova');
  Mascara.cnpj($('#n-cnpj'));
  $('#n-salvar').disabled = true;
  $('#n-buscar').onclick = consultarCnpj;
  $('#n-cnpj').onkeydown = e => { if (e.key === 'Enter') consultarCnpj(); };
  $('#n-cnpj').focus();
}

const nErro = m => {
  const e = $('#n-erro'); if (!e) return;
  e.textContent = m; e.classList.toggle('on', !!m);
};

async function consultarCnpj(){
  nErro(''); $('#n-previa').innerHTML = ''; $('#n-aviso').classList.remove('on');
  $('#n-salvar').disabled = true;
  const c = $('#n-cnpj').value.replace(/\D/g, '');
  if (c.length !== 14) { nErro('Informe um CNPJ com 14 dígitos.'); return; }
  const b = $('#n-buscar'); b.disabled = true; b.textContent = 'Consultando...';
  try {
    const d = await api.get('/api/empresas/consultar-cnpj/' + c);
    const linhas = [
      ['Razão social', d.razao_social],
      ['Nome fantasia', d.nome_fantasia],
      ['Situação', d.situacao_cadastral],
      ['Abertura', Fmt.data(d.abertura)],
      ['Porte', d.porte],
      ['Capital social', Fmt.moeda(d.capital_social)],
      ['Município', (d.municipio_nome || '') + (d.uf ? '/' + d.uf : '') +
        (d.municipio_ibge ? ' · IBGE ' + d.municipio_ibge : '')],
      ['Atividade', d.cnae_principal_desc],
      ['Simples', d.simples_optante === true ? 'Optante'
        : d.simples_optante === false ? 'Não optante' : '—'],
      ['Sócios', (d.socios || []).map(s => s.nome).join(', ')],
    ].filter(([, v]) => v && v !== '—');
    $('#n-previa').innerHTML =
      '<div style="background:var(--sup-2);border:1px solid var(--linha);' +
        'border-radius:var(--r);padding:var(--e-4)"><dl style="margin:0;display:grid;' +
        'grid-template-columns:auto 1fr;gap:7px var(--e-4);font-size:var(--t-md)">' +
      linhas.map(([k, v]) => '<dt class="rotulo" style="margin:0">' + k + '</dt>' +
        '<dd style="margin:0">' + Fmt.escapa(v) + '</dd>').join('') + '</dl></div>';
    if (d.ja_cadastrada) {
      const a = $('#n-aviso');
      a.textContent = 'Este CNPJ já está cadastrado em ' + d.ja_cadastrada_em +
        '. Solicite a transferência.';
      a.classList.add('on');
    } else $('#n-salvar').disabled = false;
  } catch(e) { nErro(e.message); }
  finally { b.disabled = false; b.textContent = 'Consultar'; }
}

async function salvarNova(){
  const b = $('#n-salvar'); b.disabled = true; b.textContent = 'Cadastrando...';
  try {
    const r = await api.post('/api/empresas',
      {cnpj: $('#n-cnpj').value.replace(/\D/g, '')});
    Modal.fecha('m-nova');
    toast.ok(r.razao_social + ' cadastrada.');
    await carregar();
  } catch(e) { nErro(e.message); }
  finally { b.disabled = false; b.textContent = 'Cadastrar'; }
}

/* ---------- inicio ---------- */
async function carregar(){
  DADOS = await api.get('/api/empresas');
  GRID.dados(DADOS);
  pintaKpis();
}

(async () => {
  await Shell.monta();
  $('#nova').innerHTML = Icone.mais + 'Nova empresa';
  $('#nova').onclick = modalNova;
  if (!Sessao.pode('empresa_escrever')) $('#nova').classList.add('esconde');

  GRID = new Grid({
    alvo:'#area', chave:'clientes', colunas:COLUNAS, cartao,
    ordemInicial:'razao_social',
    busca: e => [e.razao_social, e.nome_fantasia, e.cnpj, e.municipio_nome],
    aoClicar: e => { Sessao.empresaId = e.id; location.href = '/empresa'; },
    vazio: {titulo:'Nenhuma empresa cadastrada',
            texto:'Cadastre o primeiro cliente para começar.'},
  });
  GRID.barra('#barra', {placeholder:'Buscar por razão social, CNPJ ou município...'});

  $('#area').addEventListener('click', ev => {
    const a = ev.target.closest('[data-acoes]');
    if (a) {
      ev.stopPropagation();
      const emp = DADOS.find(x => String(x.id) === a.dataset.acoes);
      if (emp) menuEmpresa(a, emp);
      return;
    }
    const c = ev.target.closest('[data-cert]');
    if (c) { ev.stopPropagation(); toast('Módulo de certificado em construção.'); }
  });

  try { await carregar(); }
  catch(e) { toast.erro(e.message); }
})();

/* ---------- acoes da empresa ---------- */
function menuEmpresa(botao, e){
  const itens = [];
  if (Sessao.pode('empresa_escrever')) {
    itens.push({txt:'Editar dados', icone:'lapis', fn:() => modalEditar(e)});
    itens.push({txt:'Atualizar pela Receita', icone:'sync', fn:() => atualizarReceita(e)});
    itens.push({txt:'Sincronização', icone:'relogio', fn:() => modalSync(e)});
    itens.push({sep:true});
  }
  itens.push({txt:'Abrir empresa', icone:'seta',
    fn:() => { Sessao.empresaId = e.id; location.href = '/empresa'; }});
  if (Sessao.pode('empresa_escrever')) {
    itens.push({sep:true});
    itens.push(e.arquivada
      ? {txt:'Restaurar', icone:'voltar', fn:() => restaurar(e)}
      : {txt:'Arquivar', icone:'caixa', perigo:true, fn:() => modalArquivar(e)});
  }
  Menu.abre(botao, itens);
}

function modalEditar(e){
  Modal.cria({
    id:'m-editar', titulo:'Editar ' + (e.nome_fantasia || e.razao_social),
    corpo:
      '<div class="aviso aviso-erro" id="ed-erro"></div>' +
      '<p class="dica" style="margin:0 0 var(--e-4)">Razão social, CNPJ, município e ' +
        'porte vêm da Receita Federal e não são editáveis aqui.</p>' +
      '<div class="grupo"><label class="rotulo" for="ed-fantasia">Nome fantasia</label>' +
        '<input class="campo" id="ed-fantasia" value="' +
          Fmt.escapa(e.nome_fantasia || '') + '"></div>' +
      '<div class="colunas" style="gap:var(--e-3);align-items:flex-start">' +
        '<div class="grupo" style="flex:1"><label class="rotulo" for="ed-ie">' +
          'Inscrição estadual</label><input class="campo" id="ed-ie" value="' +
          Fmt.escapa(e.ie || '') + '"></div>' +
        '<div class="grupo" style="flex:1"><label class="rotulo" for="ed-im">' +
          'Inscrição municipal</label><input class="campo" id="ed-im" value="' +
          Fmt.escapa(e.im || '') + '"></div>' +
      '</div>' +
      '<div class="grupo"><label class="rotulo" for="ed-regime">Regime tributário</label>' +
        '<select class="campo" id="ed-regime">' +
        ['','Simples Nacional','Lucro Presumido','Lucro Real','MEI','Imune ou isenta']
          .map(o => '<option' + (o === (e.regime_tributario || '') ? ' selected' : '') +
            '>' + o + '</option>').join('') + '</select></div>' +
      '<div class="grupo"><label class="rotulo" for="ed-obs">Observações</label>' +
        '<textarea class="campo" id="ed-obs">' +
          Fmt.escapa(e.observacoes || '') + '</textarea></div>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Salvar', cls:'btn-1', id:'ed-salvar', fn:async () => {
        const b = $('#ed-salvar'); b.disabled = true; b.textContent = 'Salvando...';
        try {
          await api.put('/api/empresas/' + e.id, {
            nome_fantasia: $('#ed-fantasia').value.trim(),
            ie: $('#ed-ie').value.trim(), im: $('#ed-im').value.trim(),
            regime_tributario: $('#ed-regime').value,
            observacoes: $('#ed-obs').value.trim(),
          });
          Modal.fecha('m-editar'); toast.ok('Dados atualizados.'); await carregar();
        } catch(err) {
          const a = $('#ed-erro'); a.textContent = err.message; a.classList.add('on');
        } finally { b.disabled = false; b.textContent = 'Salvar'; }
      }},
    ],
  });
  Modal.abre('m-editar');
}

async function atualizarReceita(e){
  toast('Consultando a Receita Federal...');
  try {
    const r = await api.post('/api/empresas/' + e.id + '/atualizar-receita', {});
    toast.ok('Atualizado · ' + r.situacao);
    await carregar();
  } catch(err) { toast.erro(err.message); }
}

function modalSync(e){
  const herda = e.janela_herdada && e.ciencia_herdada;
  Modal.cria({
    id:'m-sync', titulo:'Sincronização · ' + (e.nome_fantasia || e.razao_social),
    corpo:
      '<div class="aviso aviso-erro" id="sy-erro"></div>' +
      '<label class="colunas" style="gap:var(--e-2);margin-bottom:var(--e-5);' +
        'cursor:pointer"><input type="checkbox" id="sy-herda"' +
        (herda ? ' checked' : '') + '>' +
        '<span>Usar o padrão do escritório</span></label>' +
      '<div id="sy-campos">' +
        '<div class="grupo">' +
          '<label class="colunas" style="gap:var(--e-2);cursor:pointer">' +
            '<input type="checkbox" id="sy-janela"' +
            (e.janela_ativa ? ' checked' : '') + '>' +
            '<span>Restringir a janela de consulta à SEFAZ</span></label>' +
          '<p class="dica">Desligado, consulta 24h por dia respeitando o limite da SEFAZ.</p>' +
        '</div>' +
        '<div class="colunas" style="gap:var(--e-3)" id="sy-horas">' +
          '<div class="grupo" style="flex:1"><label class="rotulo">Início</label>' +
            '<input class="campo" type="time" id="sy-ini" value="' +
              (e.janela_inicio || '22:00').slice(0,5) + '"></div>' +
          '<div class="grupo" style="flex:1"><label class="rotulo">Fim</label>' +
            '<input class="campo" type="time" id="sy-fim" value="' +
              (e.janela_fim || '06:00').slice(0,5) + '"></div>' +
        '</div>' +
        '<div class="grupo" style="margin-top:var(--e-4)">' +
          '<label class="colunas" style="gap:var(--e-2);cursor:pointer">' +
            '<input type="checkbox" id="sy-ciencia"' +
            (e.ciencia_auto ? ' checked' : '') + '>' +
            '<span>Dar ciência da operação automaticamente</span></label>' +
        '</div>' +
        '<div class="aviso aviso-alerta on" style="margin-top:var(--e-2)">' +
          'A ciência da operação é irreversível, inicia o prazo de 180 dias para a ' +
          'manifestação definitiva e vale como reconhecimento da operação perante o ' +
          'fisco. Cada ciência automática fica registrada na auditoria.</div>' +
      '</div>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Salvar', cls:'btn-1', id:'sy-salvar', fn:async () => {
        const b = $('#sy-salvar'); b.disabled = true; b.textContent = 'Salvando...';
        try {
          await api.put('/api/empresas/' + e.id + '/sincronizacao', {
            herdar: $('#sy-herda').checked,
            janela_ativa: $('#sy-janela').checked,
            janela_inicio: $('#sy-ini').value,
            janela_fim: $('#sy-fim').value,
            ciencia_auto: $('#sy-ciencia').checked,
          });
          Modal.fecha('m-sync'); toast.ok('Configuração salva.'); await carregar();
        } catch(err) {
          const a = $('#sy-erro'); a.textContent = err.message; a.classList.add('on');
        } finally { b.disabled = false; b.textContent = 'Salvar'; }
      }},
    ],
  });
  Modal.abre('m-sync');
  const pinta = () => {
    const h = $('#sy-herda').checked;
    $('#sy-campos').style.opacity = h ? '.45' : '1';
    $('#sy-campos').style.pointerEvents = h ? 'none' : 'auto';
    $('#sy-horas').style.display = $('#sy-janela').checked ? 'flex' : 'none';
  };
  $('#sy-herda').onchange = pinta;
  $('#sy-janela').onchange = pinta;
  pinta();
}

function modalArquivar(e){
  Modal.cria({
    id:'m-arq', titulo:'Arquivar empresa',
    corpo:
      '<p style="margin:0 0 var(--e-4);line-height:1.65">' +
        '<b>' + Fmt.escapa(e.razao_social) + '</b> sai da lista e para de sincronizar. ' +
        'Nenhum documento, XML ou certificado é apagado — dá para restaurar depois.</p>' +
      '<div class="grupo"><label class="rotulo" for="arq-motivo">Motivo (opcional)</label>' +
        '<input class="campo" id="arq-motivo" placeholder="Encerrou contrato, baixa..."></div>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Arquivar', cls:'btn-perigo', fn:async () => {
        try {
          await api.post('/api/empresas/' + e.id + '/arquivar',
            {motivo: $('#arq-motivo').value.trim() || null});
          Modal.fecha('m-arq'); toast.ok('Empresa arquivada.'); await carregar();
        } catch(err) { toast.erro(err.message); }
      }},
    ],
  });
  Modal.abre('m-arq');
}

async function restaurar(e){
  try {
    await api.post('/api/empresas/' + e.id + '/restaurar', {});
    toast.ok('Empresa restaurada.'); await carregar();
  } catch(err) { toast.erro(err.message); }
}
