/* Modulo: notas de servico emitidas.
   Grid com KPIs clicaveis, filtros por competencia e as acoes de cada nota:
   detalhes, DANFSe, XML, consultar protocolo pendente e cancelar. */

const EMP = Sessao.empresaId;
let NOTAS = [], RESUMO = {}, GRID = null, FILTRO = null;

const err = m => { const e = $('#erro'); e.textContent = m || '';
  e.classList.toggle('on', !!m); };

const soDigito = v => (v || '').replace(/\D/g, '');
const dinheiro = v => Fmt.moeda(v || 0);
const pct = v => v == null ? '—' : (Number(v) * 100).toFixed(2).replace('.', ',') + '%';

function docFmt(v){
  const n = soDigito(v);
  if (n.length === 14)
    return n.slice(0,2)+'.'+n.slice(2,5)+'.'+n.slice(5,8)+'/'+n.slice(8,12)+'-'+n.slice(12);
  if (n.length === 11)
    return n.slice(0,3)+'.'+n.slice(3,6)+'.'+n.slice(6,9)+'-'+n.slice(9);
  return v || '—';
}
const mesAno = d => {
  if (!d) return '—';
  const s = String(d).slice(0, 10).split('-');
  return s.length === 3 ? s[1] + '/' + s[0] : String(d);
};

const SITUACOES = {
  autorizada:  {rot:'Autorizada',  cls:'chip-ok'},
  processando: {rot:'Processando', cls:'chip-aviso'},
  rejeitada:   {rot:'Rejeitada',   cls:'chip-erro'},
  cancelada:   {rot:'Cancelada',   cls:'chip-neutro'},
  substituida: {rot:'Substituída', cls:'chip-neutro'},
  rascunho:    {rot:'Rascunho',    cls:'chip-neutro'},
};
const chip = s => {
  const c = SITUACOES[s] || {rot: s || '—', cls:'chip-neutro'};
  return '<span class="chip ' + c.cls + '">' + c.rot + '</span>';
};

/* ---------------- KPIs ---------------- */
function pintaKpis(){
  const conta = s => NOTAS.filter(n => n.situacao === s).length;
  const soma = s => NOTAS.filter(n => n.situacao === s)
    .reduce((t, n) => t + Number(n.valor_servico || 0), 0);

  const cartao = (id, rot, val, risco) =>
    '<button class="kpi' + (FILTRO === id ? ' on' : '') +
      (risco ? ' risco' : '') + '" data-kpi="' + id + '">' +
      '<div class="kn">' + val + '</div>' +
      '<div class="kr">' + rot + '</div></button>';

  $('#kpis').innerHTML =
    cartao('todos', 'Notas', NOTAS.length) +
    cartao('autorizada', 'Autorizadas', conta('autorizada')) +
    cartao('valor', 'Valor autorizado', dinheiro(soma('autorizada'))) +
    cartao('processando', 'Processando', conta('processando'),
           conta('processando') > 0) +
    cartao('rejeitada', 'Rejeitadas', conta('rejeitada'), conta('rejeitada') > 0) +
    cartao('cancelada', 'Canceladas', conta('cancelada'));

  $$('[data-kpi]').forEach(b => b.onclick = () => {
    const k = b.dataset.kpi;
    if (k === 'valor') return;          // cartao informativo, nao filtra
    FILTRO = (FILTRO === k || k === 'todos') ? null : k;
    GRID.filtra(FILTRO ? (n => n.situacao === FILTRO) : null);
    pintaKpis();
  });
}

/* ---------------- grid ---------------- */
const COLUNAS = [
  {k:'numero_nfse', t:'NFS-e', w:90, num:true,
   cel: n => n.numero_nfse
     ? '<b>' + Fmt.escapa(n.numero_nfse) + '</b>'
     : '<span class="t3">—</span>'},
  {k:'numero_rps', t:'RPS', w:80, num:true,
   cel: n => Fmt.escapa(String(n.numero_rps || '—'))},
  {k:'competencia', t:'Competência', w:120, cel: n => mesAno(n.competencia)},
  {k:'tomador_nome', t:'Tomador', w:270,
   cel: n => '<b>' + Fmt.escapa(n.tomador_nome || '—') + '</b>' +
     '<div class="t3">' + docFmt(n.tomador_doc) + '</div>'},
  {k:'descricao', t:'Serviço', w:220,
   cel: n => Fmt.escapa(n.servico_apelido || n.descricao || '—')},
  {k:'valor_servico', t:'Valor', w:120, num:true,
   cel: n => dinheiro(n.valor_servico)},
  {k:'situacao', t:'Situação', w:130, cel: n => chip(n.situacao)},
  {k:'acoes', t:'Ações', w:80, cel: n =>
    '<button class="btn btn-3 btn-icone btn-sm" data-parar data-acoes="' + n.id +
      '" aria-label="Ações">' + Icone.pontos + '</button>'},
];

function menuNota(botao, n){
  const itens = [{txt:'Ver detalhes', icone:'arquivo', fn:() => detalhes(n)}];
  if (n.situacao === 'autorizada' || n.situacao === 'cancelada'){
    itens.push({txt:'Abrir DANFSe', icone:'arquivo', fn:() => abrirDanfse(n.id)});
    itens.push({txt:'Baixar XML', icone:'baixar', fn:() => baixarXml(n.id)});
  }
  if (n.situacao === 'rejeitada' && Sessao.pode('emitir'))
    itens.push({txt:'Corrigir e reemitir', icone:'sync', fn:() => reemitir(n)});
  if (n.situacao === 'processando')
    itens.push({txt:'Consultar na prefeitura', icone:'sync', fn:() => consultar(n)});
  if (n.situacao === 'autorizada' && Sessao.pode('emitir')){
    itens.push({sep:true});
    itens.push({txt:'Cancelar NFS-e', icone:'x', perigo:true, fn:() => cancelar(n)});
  }
  Menu.abre(botao, itens);
}

/* ---------------- acoes ---------------- */
/* link direto nao carrega o token (ele vive no sessionStorage, nao em cookie),
   entao o download vai por fetch com Authorization e vira blob. */
async function abrirDanfse(id){
  toast('Gerando o DANFSe...');
  try {
    const r = await fetch('/api/nfse/notas/' + id + '/danfse',
      {headers:{'Authorization':'Bearer ' + Sessao.token}});
    if (!r.ok){ const d = await r.json().catch(() => ({}));
      toast(d.detail || 'Nao foi possivel gerar o DANFSe'); return; }
    const url = URL.createObjectURL(await r.blob());
    window.open(url, '_blank');
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch { toast('Falha ao gerar o DANFSe.'); }
}

async function baixarXml(id){
  try {
    const r = await fetch('/api/nfse/notas/' + id + '/xml',
      {headers:{'Authorization':'Bearer ' + Sessao.token}});
    if (!r.ok){ const d = await r.json().catch(() => ({}));
      toast(d.detail || 'XML indisponivel'); return; }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await r.blob());
    a.download = (r.headers.get('content-disposition') || '')
      .split('filename=')[1] || 'NFSe_' + id + '.xml';
    a.click(); URL.revokeObjectURL(a.href);
  } catch { toast('Falha no download do XML.'); }
}

/* leva os dados da nota rejeitada para a tela de emissao */
function reemitir(n){
  sessionStorage.setItem('nfc_reemitir', JSON.stringify({
    tomador_id: n.tomador_id, servico_id: n.servico_id,
    valor_servico: n.valor_servico, competencia: n.competencia,
    descricao: n.descricao, iss_retido: n.iss_retido,
    valor_deducoes: n.valor_deducoes, valor_desconto: n.valor_desconto,
    valor_pis: n.valor_pis, valor_cofins: n.valor_cofins,
    valor_inss: n.valor_inss, valor_ir: n.valor_ir, valor_csll: n.valor_csll,
    motivo: n.motivo, numero_rps: n.numero_rps,
  }));
  location.href = '/e/emissao';
}

async function consultar(n){
  toast('Consultando a prefeitura…');
  try {
    const d = await api.post('/api/nfse/notas/' + n.id + '/consultar', {});
    if (d.situacao === 'autorizada')
      toast('Autorizada! NFS-e n. ' + d.numero_nfse);
    else if (d.situacao === 'rejeitada')
      toast('Rejeitada: ' + (d.erro || '').slice(0, 90));
    else toast(d.aviso || 'Ainda em processamento.');
    await carrega();
  } catch(e){ toast(e.message); }
}

function detalhes(n){
  const li = (r, v) => '<div class="rl"><span>' + r + '</span><b>' + v + '</b></div>';
  Modal.cria({
    id:'m-det', titulo:'NFS-e ' + (n.numero_nfse ? 'n. ' + n.numero_nfse
      : '(RPS ' + n.numero_rps + ')'),
    corpo:'<div class="det">' +
      '<div style="margin-bottom:var(--e-4)">' + chip(n.situacao) + '</div>' +
      (n.motivo ? '<div class="aviso aviso-erro on">' + Fmt.escapa(n.motivo) +
        '</div>' : '') +
      '<h4>Tomador</h4>' +
      li('Razão social', Fmt.escapa(n.tomador_nome || '—')) +
      li('CNPJ / CPF', docFmt(n.tomador_doc)) +
      '<h4>Serviço</h4>' +
      li('Descrição', '<span style="font-family:var(--fonte);text-align:right;' +
        'display:inline-block;max-width:280px">' +
        Fmt.escapa(n.descricao || '—') + '</span>') +
      li('Cód. tributação', Fmt.escapa(n.codigo_tributacao || '—')) +
      li('Competência', mesAno(n.competencia)) +
      '<h4>Valores</h4>' +
      li('Valor do serviço', dinheiro(n.valor_servico)) +
      (Number(n.valor_deducoes) ? li('Deduções', dinheiro(n.valor_deducoes)) : '') +
      (Number(n.valor_desconto) ? li('Desconto', dinheiro(n.valor_desconto)) : '') +
      li('Alíquota ISS', pct(n.aliquota_iss)) +
      li('ISS retido', n.iss_retido ? 'Sim' : 'Não') +
      li('Valor líquido', dinheiro(n.valor_liquido)) +
      '<h4>Controle</h4>' +
      li('Série / RPS', Fmt.escapa((n.serie_rps || '—') + ' / ' + (n.numero_rps || '—'))) +
      (n.protocolo_lote ? li('Protocolo', Fmt.escapa(n.protocolo_lote)) : '') +
      (n.emissao ? li('Emitida em', Fmt.dataHora ? Fmt.dataHora(n.emissao)
        : String(n.emissao).slice(0,16).replace('T',' ')) : '') +
      (n.cancelada_em ? li('Cancelada em', String(n.cancelada_em).slice(0,16)
        .replace('T',' ')) : '') +
      (n.cancelamento_motivo ? li('Motivo do cancelamento',
        Fmt.escapa(n.cancelamento_motivo)) : '') +
      '</div>',
    acoes:[{txt:'Fechar', cls:'btn-2'}],
  });
  Modal.abre('m-det');
}

function cancelar(n){
  Modal.cria({
    id:'m-canc', titulo:'Cancelar NFS-e n. ' + n.numero_nfse,
    corpo:
      '<div class="aviso aviso-atencao on" style="margin-bottom:var(--e-4)">' +
        'O cancelamento é definitivo e depende do prazo e das regras do ' +
        'município. Confira antes de confirmar.</div>' +
      '<div class="rl"><span>Tomador</span><b style="font-family:var(--fonte)">' +
        Fmt.escapa(n.tomador_nome || '—') + '</b></div>' +
      '<div class="rl"><span>Valor</span><b>' + dinheiro(n.valor_servico) + '</b></div>' +
      '<div class="campo-grupo" style="margin-top:var(--e-4)">' +
        '<label class="rotulo">Motivo do cancelamento</label>' +
        '<select class="campo" id="c-codigo">' +
          '<option value="1">Erro na emissão</option>' +
          '<option value="2">Serviço não prestado</option>' +
          '<option value="4">Duplicidade da nota</option>' +
        '</select>' +
      '</div>' +
      '<div class="campo-grupo">' +
        '<label class="rotulo">Observação (opcional)</label>' +
        '<input class="campo" id="c-motivo" maxlength="150">' +
      '</div>' +
      '<div class="aviso aviso-erro" id="c-erro"></div>',
    acoes:[
      {txt:'Voltar', cls:'btn-2'},
      {txt:'Confirmar cancelamento', cls:'btn-perigo', id:'b-canc', fn: async () => {
        const fe = $('#c-erro'); fe.classList.remove('on');
        const b = $('#b-canc'); b.disabled = true; b.textContent = 'Cancelando…';
        try {
          const d = await api.post('/api/nfse/notas/' + n.id + '/cancelar', {
            codigo: $('#c-codigo').value,
            motivo: $('#c-motivo').value.trim() || null,
          });
          if (d.ok){
            Modal.fecha('m-canc'); toast('NFS-e cancelada.'); await carrega();
          } else {
            fe.textContent = d.erro || 'Não foi possível cancelar.';
            fe.classList.add('on');
            b.disabled = false; b.textContent = 'Confirmar cancelamento';
          }
        } catch(e){
          fe.textContent = e.message; fe.classList.add('on');
          b.disabled = false; b.textContent = 'Confirmar cancelamento';
        }
      }},
    ],
  });
  Modal.abre('m-canc');
}

/* ---------------- carga ---------------- */
const MESES = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho',
  'Agosto','Setembro','Outubro','Novembro','Dezembro'];

function montaFiltrosData(){
  const ano = new Date().getFullYear();
  const anos = [];
  for (let a = 2024; a <= ano + 1; a++) anos.push(a);
  const opMes = '<option value="">Mês</option>' + MESES.map((m, i) =>
    '<option value="' + String(i + 1).padStart(2, '0') + '">' + m + '</option>').join('');
  const opAno = '<option value="">Ano</option>' +
    anos.map(a => '<option value="' + a + '">' + a + '</option>').join('');
  ['de','ate'].forEach(q => {
    $('#mes-' + q).innerHTML = opMes;
    $('#ano-' + q).innerHTML = opAno;
  });
}

/* o par mes+ano so vira filtro quando os dois estao preenchidos */
function competencia(q, ultimoDia){
  const m = $('#mes-' + q).value, a = $('#ano-' + q).value;
  if (!m || !a) return null;
  return ultimoDia
    ? new Date(Number(a), Number(m), 0).toISOString().slice(0, 10)
    : a + '-' + m + '-01';
}

async function carrega(){
  const p = new URLSearchParams({empresa_id: EMP});
  const i = competencia('de', false), f = competencia('ate', true);
  if (i) p.set('inicio', i);
  if (f) p.set('fim', f);
  const d = await api.get('/api/nfse/notas?' + p.toString());
  NOTAS = d.notas || [];
  RESUMO = d.resumo || {};
  GRID.dados(NOTAS);
  if (FILTRO) GRID.filtra(n => n.situacao === FILTRO);
  pintaKpis();
}

(async () => {
  await Shell.monta(EMP ? {empresa: EMP} : {});
  $('#nova').innerHTML = Icone.mais + 'Emitir NFS-e';
  $('#nova').onclick = () => location.href = '/e/emissao';

  GRID = new Grid({
    alvo:'#area', chave:'notas', colunas:COLUNAS, ordemInicial:'numero_rps',
    busca: n => [n.numero_nfse, n.numero_rps, n.tomador_nome, n.tomador_doc,
                 n.descricao, n.servico_apelido],
    vazio: {titulo:'Nenhuma nota emitida',
            texto:'As NFS-e emitidas por esta empresa aparecem aqui.'},
  });
  GRID.barra('#barra', {placeholder:'Buscar por número, tomador ou serviço...'});

  $('#area').addEventListener('click', ev => {
    const a = ev.target.closest('[data-acoes]');
    if (a){
      ev.stopPropagation();
      const n = NOTAS.find(x => String(x.id) === a.dataset.acoes);
      if (n) menuNota(a, n);
    }
  });

  montaFiltrosData();
  ['mes-de','ano-de','mes-ate','ano-ate'].forEach(i => {
    const el = $('#' + i); if (el) el.onchange = carrega;
  });
  $('#b-limpar').onclick = () => {
    ['mes-de','ano-de','mes-ate','ano-ate'].forEach(i => $('#' + i).value = '');
    FILTRO = null; carrega();
  };

  try { await carrega(); } catch(e){ err(e.message); }
})();
