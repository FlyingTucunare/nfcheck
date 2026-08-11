/* Modulo: documentos fiscais recebidos */

const EMP = Sessao.empresaId;
if (!EMP) location.href = '/painel';

let GRID, TOTAIS = {}, SITUACAO = null, ITENS = [];

const chipSit = d => d.resumo
  ? '<span class="chip chip-neutro"><span class="ponto"></span>Resumo</span>'
  : d.manifestacao
  ? '<span class="chip chip-ok"><span class="ponto"></span>Manifestado</span>'
  : '<span class="chip chip-aviso"><span class="ponto"></span>Pendente</span>';

const COLUNAS = [
  {k:'tipo_rotulo', t:'Tipo', w:66},
  {k:'emitente_nome', t:'Emitente', w:200, cel: d =>
    '<div style="font-weight:var(--p-medio);overflow:hidden;text-overflow:ellipsis">' +
      Fmt.escapa(d.emitente_nome || '—') + '</div>'},
  {k:'emitente_cnpj', t:'CNPJ', w:168, cel: d =>
    '<span class="num">' + Fmt.cnpj(d.emitente_cnpj) + '</span>'},
  {k:'numero', t:'Número', w:88, num:true, cel: d =>
    '<span class="num">' + Fmt.escapa(d.numero || '—') + '</span>'},
  {k:'emissao', t:'Emissão', w:158, cel: d =>
    '<span class="num">' + Fmt.dataHora(d.emissao) + '</span>'},
  {k:'valor', t:'Valor', w:126, num:true, cel: d =>
    '<span class="num">' + Fmt.moeda(d.valor) + '</span>'},
  {k:'situacao_calc', t:'Situação', w:118, cel: chipSit},
  {k:'acoes', t:'Ações', w:205, cel: d =>
    (d.tem_xml && !d.resumo ? '<button class="btn btn-3 btn-icone btn-sm" data-parar ' +
      'data-danfe="' + d.id + '" title="Ver DANFE/DACTE">' + Icone.arquivo +
      '</button>' : '') +
    (d.tem_xml ? '<button class="btn btn-3 btn-icone btn-sm" data-parar ' +
      'data-xml="' + d.id + '" title="Baixar XML">' + Icone.baixar + '</button>' : '') +
    (Sessao.pode('manifestar') && !d.manifestacao ?
      '<button class="btn btn-3 btn-icone btn-sm" data-parar data-manif="' + d.id +
      '" title="Manifestar">' + Icone.visto + '</button>' : '') +
    '<button class="btn btn-3 btn-icone btn-sm" data-parar data-chave="' +
      Fmt.escapa(d.chave || '') + '" title="Copiar chave">' + Icone.copiar + '</button>' +
    '<button class="btn btn-3 btn-icone btn-sm" data-parar data-sefaz="' +
      Fmt.escapa(d.chave || '') + '" title="Consultar no portal da SEFAZ">' +
      Icone.link + '</button>'},
];

const FILTROS = [
  {id:null, r:'Documentos', v:() => Fmt.numero(TOTAIS.n || 0)},
  {id:'valor', r:'Valor total', v:() => Fmt.moeda(TOTAIS.soma || 0), estatico:true},
  {id:'pendente', r:'A manifestar', v:() => Fmt.numero(TOTAIS.pendentes || 0),
   risco:() => TOTAIS.pendentes > 0},
  {id:'manifestado', r:'Manifestados', v:() =>
    Fmt.numero((TOTAIS.n || 0) - (TOTAIS.pendentes || 0) - (TOTAIS.resumos || 0))},
  {id:'resumo', r:'Só resumo', v:() => Fmt.numero(TOTAIS.resumos || 0)},
];

function pintaKpis(){
  $('#kpis').innerHTML = FILTROS.map(f => {
    const cls = ['kpi'];
    if (f.risco && f.risco()) cls.push('risco');
    if (SITUACAO === f.id) cls.push('on');
    if (f.estatico) cls.push('esta');
    return '<button class="' + cls.join(' ') + '" data-f="' + (f.id ?? '') + '"' +
      (f.estatico ? ' disabled style="cursor:default"' : '') + '>' +
      '<div class="kn" style="font-size:' + (f.estatico ? '19px' : '26px') + '">' +
      f.v() + '</div><div class="kr">' + f.r + '</div></button>';
  }).join('');
  $$('.kpi:not([disabled])').forEach(el => el.onclick = () => {
    const id = el.dataset.f || null;
    SITUACAO = SITUACAO === id ? null : id;
    carregar();
  });
}

function params(){
  const p = new URLSearchParams({empresa_id: EMP, limite: 2000});
  if ($('#f-de').value)  p.set('de', $('#f-de').value);
  if ($('#f-ate').value) p.set('ate', $('#f-ate').value);
  if ($('#f-tipo').value) p.set('tipo', $('#f-tipo').value);
  if ($('#f-busca').value.trim()) p.set('busca', $('#f-busca').value.trim());
  if (SITUACAO && SITUACAO !== 'valor') p.set('situacao', SITUACAO);
  return p;
}

async function carregar(){
  try {
    const d = await api.get('/api/documentos?' + params());
    ITENS = d.itens; TOTAIS = d.totais;
    GRID.dados(ITENS);
    pintaKpis();
    if (d.truncado) toast('Mostrando os 2000 mais recentes. Refine os filtros.');
  } catch(e) { toast.erro(e.message); }
}

const parte = (titulo, html) => !html ? '' :
  '<div style="margin-bottom:var(--e-5)">' +
    '<div class="rotulo" style="margin-bottom:var(--e-3);padding-bottom:6px;' +
      'border-bottom:1px solid var(--linha)">' + titulo + '</div>' + html + '</div>';

const linhasDl = pares => {
  const l = pares.filter(([, v]) => v !== null && v !== undefined && v !== '' && v !== '—');
  return l.length ? '<dl>' + l.map(([k, v, cls]) =>
    '<dt>' + k + '</dt><dd' + (cls ? ' class="' + cls + '"' : '') + '>' +
    Fmt.escapa(v) + '</dd>').join('') + '</dl>' : '';
};

const pessoa = p => !p ? '' : linhasDl([
  ['Nome', p.nome], ['Fantasia', p.fantasia],
  ['CNPJ', p.cnpj && p.cnpj.length === 14 ? Fmt.cnpj(p.cnpj) : p.cnpj, 'num'],
  ['IE', p.ie], ['Endereço', p.endereco],
  ['Município', (p.municipio || '') + (p.uf ? '/' + p.uf : '')],
  ['CEP', p.cep ? Fmt.cep(p.cep) : null], ['Telefone', p.fone],
]);

const tabelaItens = itens => !itens.length ? '' :
  '<div class="rolagem"><table class="dados"><thead><tr>' +
    '<th style="width:38px">#</th><th>Descrição</th>' +
    '<th style="width:78px">NCM</th><th style="width:58px">CFOP</th>' +
    '<th style="width:78px">Qtd</th><th style="width:48px">Un</th>' +
    '<th style="width:98px">Unitário</th><th style="width:98px">Total</th>' +
  '</tr></thead><tbody>' + itens.map(i => '<tr>' +
    '<td class="num">' + Fmt.escapa(i.n) + '</td>' +
    '<td title="' + Fmt.escapa(i.descricao) + '">' + Fmt.escapa(i.descricao) + '</td>' +
    '<td class="num">' + Fmt.escapa(i.ncm || '—') + '</td>' +
    '<td class="num">' + Fmt.escapa(i.cfop || '—') + '</td>' +
    '<td class="num">' + (i.quantidade != null
      ? i.quantidade.toLocaleString('pt-BR', {maximumFractionDigits:4}) : '—') + '</td>' +
    '<td>' + Fmt.escapa(i.unidade || '—') + '</td>' +
    '<td class="num">' + Fmt.moeda(i.unitario) + '</td>' +
    '<td class="num">' + Fmt.moeda(i.total) + '</td></tr>').join('') +
  '</tbody></table></div>';

const ROT_TOT = {vProd:'Produtos', vFrete:'Frete', vSeg:'Seguro', vDesc:'Desconto',
  vOutro:'Outras despesas', vBC:'Base ICMS', vICMS:'ICMS', vBCST:'Base ICMS ST',
  vST:'ICMS ST', vIPI:'IPI', vPIS:'PIS', vCOFINS:'COFINS', vNF:'Total da nota'};

const tabelaTot = t => {
  const l = Object.entries(ROT_TOT)
    .filter(([k]) => t[k] != null && (t[k] !== 0 || k === 'vNF' || k === 'vProd'));
  return l.length ? '<dl>' + l.map(([k, r]) =>
    '<dt>' + r + '</dt><dd class="num"' +
    (k === 'vNF' ? ' style="font-weight:var(--p-forte);font-size:var(--t-lg)"' : '') +
    '>' + Fmt.moeda(t[k]) + '</dd>').join('') + '</dl>' : '';
};

async function verDetalhe(d){
  Modal.cria({id:'m-doc', titulo:'Carregando...',
    corpo:'<p class="t3">Lendo o documento...</p>'});
  Modal.abre('m-doc');
  try {
    const [x, c] = await Promise.all([
      api.get('/api/documentos/' + d.id),
      api.get('/api/documentos/' + d.id + '/conteudo').catch(() => ({disponivel:false})),
    ]);

    const geral = linhasDl([
      ['Tipo', x.tipo_rotulo], ['Natureza', c.natureza],
      ['Número', x.numero], ['Série', x.serie],
      ['Emissão', Fmt.dataHora(x.emissao)],
      ['Chave', x.chave, 'num'],
      ['Protocolo', c.protocolo, 'num'],
      ['Autorização', c.protocolo_data ? Fmt.dataHora(c.protocolo_data) : null],
      ['Situação SEFAZ', c.status],
      ['Papel da empresa', x.papel],
      ['Origem', x.origem === 'importacao' ? 'Importação em lote' : x.origem],
      ['NSU', x.nsu], ['Recebido em', Fmt.dataHora(x.recebido_em)],
      ['Manifestação', x.manifestacao || 'Pendente'],
    ]);

    const transp = c.transportadora || (c.volumes && c.volumes.length) ? linhasDl([
      ['Transportadora', c.transportadora && c.transportadora.nome],
      ['CNPJ', c.transportadora && c.transportadora.cnpj
        ? Fmt.cnpj(c.transportadora.cnpj) : null, 'num'],
      ['Frete por conta', ({'0':'Emitente','1':'Destinatário','2':'Terceiros',
        '3':'Próprio do emitente','4':'Próprio do destinatário','9':'Sem transporte'})
        [c.modalidade_frete]],
      ['Volumes', (c.volumes || []).map(v =>
        [v.qtd, v.especie].filter(Boolean).join(' ')).join(' · ')],
      ['Peso bruto', (c.volumes || [])[0] && (c.volumes[0].peso_bruto + ' kg')],
    ]) : '';

    const dups = (c.duplicatas || []).length ?
      '<div class="rolagem"><table class="dados"><thead><tr><th>Parcela</th>' +
      '<th style="width:110px">Vencimento</th><th style="width:120px">Valor</th>' +
      '</tr></thead><tbody>' + c.duplicatas.map(p => '<tr>' +
        '<td class="num">' + Fmt.escapa(p.numero) + '</td>' +
        '<td class="num">' + Fmt.data(p.vencimento) + '</td>' +
        '<td class="num">' + Fmt.moeda(p.valor) + '</td></tr>').join('') +
      '</tbody></table></div>' : '';

    const corpo = '<div class="det">' +
      parte('Documento', geral) +
      (c.disponivel ? (
        parte('Emitente', pessoa(c.emitente)) +
        parte('Destinatário', pessoa(c.destinatario)) +
        parte('Itens · ' + (c.itens || []).length, tabelaItens(c.itens || [])) +
        parte('Totais', tabelaTot(c.totais || {})) +
        parte('Transporte', transp) +
        parte('Cobrança', dups) +
        parte('Informações complementares', c.informacoes
          ? '<p style="margin:0;font-size:var(--t-md);line-height:1.6;' +
            'white-space:pre-wrap">' + Fmt.escapa(c.informacoes) + '</p>' : '')
      ) : '<div class="aviso aviso-alerta on">Apenas o resumo está disponível. ' +
           'O XML completo é liberado após a manifestação.</div>') +
    '</div>';

    const podeAux = c.disponivel && !x.resumo;
    Modal.cria({
      id:'m-doc',
      titulo: x.tipo_rotulo + ' ' + (x.numero || '') +
        (x.serie ? ' · série ' + x.serie : ''),
      corpo,
      acoes:[
        ...(podeAux ? [{txt: x.tipo.includes('cte') ? 'DACTE' : 'DANFE', cls:'btn-2',
          fn:() => abrirAuxiliar(x.id)}] : []),
        ...(x.xml_path ? [{txt:'XML', cls:'btn-2', fn:() => baixar(x.id, 'xml')}] : []),
        ...(x.pdf_path ? [{txt:'PDF anexo', cls:'btn-2',
          fn:() => baixar(x.id, 'pdf')}] : []),
        {txt:'Fechar', cls:'btn-1'},
      ],
    });
    Modal.abre('m-doc');
  } catch(e) { Modal.fecha('m-doc'); toast.erro(e.message); }
}

async function abrirAuxiliar(id){
  toast('Gerando o documento auxiliar...');
  try {
    const r = await fetch('/api/documentos/' + id + '/danfe',
      {headers:{'Authorization':'Bearer ' + Sessao.token}});
    if (!r.ok) { const d = await r.json().catch(() => ({}));
      toast.erro(d.detail || 'Não foi possível gerar'); return; }
    const url = URL.createObjectURL(await r.blob());
    window.open(url, '_blank');
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch { toast.erro('Falha ao gerar o documento auxiliar.'); }
}

async function baixar(id, tipo){
  try {
    const r = await fetch('/api/documentos/' + id + '/' + tipo,
      {headers:{'Authorization':'Bearer ' + Sessao.token}});
    if (!r.ok) { const d = await r.json().catch(() => ({}));
      toast.erro(d.detail || 'Arquivo indisponível'); return; }
    const b = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = (r.headers.get('content-disposition') || '')
      .split('filename=')[1] || id + '.' + tipo;
    a.click(); URL.revokeObjectURL(a.href);
  } catch { toast.erro('Falha no download.'); }
}

async function verEmitentes(){
  const p = new URLSearchParams({empresa_id: EMP});
  if ($('#f-de').value)  p.set('de', $('#f-de').value);
  if ($('#f-ate').value) p.set('ate', $('#f-ate').value);
  try {
    const l = await api.get('/api/documentos/resumo/emitentes?' + p);
    Modal.cria({
      id:'m-emit', titulo:'Maiores emitentes',
      corpo: l.length ? '<div class="rolagem"><table class="dados"><thead><tr>' +
        '<th>Emitente</th><th style="width:145px">CNPJ</th>' +
        '<th style="width:70px">Docs</th><th style="width:130px">Total</th>' +
        '</tr></thead><tbody>' + l.map(x => '<tr>' +
          '<td title="' + Fmt.escapa(x.emitente_nome) + '">' +
            Fmt.escapa(x.emitente_nome) + '</td>' +
          '<td class="num">' + Fmt.cnpj(x.emitente_cnpj) + '</td>' +
          '<td class="num">' + Fmt.numero(x.docs) + '</td>' +
          '<td class="num">' + Fmt.moeda(x.total) + '</td></tr>').join('') +
        '</tbody></table></div>' : '<p class="t3">Nenhum documento no período.</p>',
      acoes:[{txt:'Fechar', cls:'btn-1'}],
    });
    Modal.abre('m-emit');
  } catch(e) { toast.erro(e.message); }
}

(async () => {
  await Shell.monta({empresa: EMP});
  $('#btn-emitentes').innerHTML = Icone.grafico + 'Emitentes';
  $('#btn-imp').innerHTML = Icone.subir + 'Importar';
  if (!Sessao.pode('importar')) $('#btn-imp').classList.add('esconde');

  GRID = new Grid({
    alvo:'#area', chave:'dfe', colunas:COLUNAS, ordemInicial:'emissao',
    selecionavel:true, porPagina:'auto', colunaFlexivel:'emitente_nome',
    busca: d => [d.emitente_nome, d.emitente_cnpj, d.numero, d.chave],
    aoClicar: verDetalhe,
    vazio:{titulo:'Nenhum documento', texto:'Importe XML ou aguarde a sincronização.'},
  });
  GRID.ordem = {col:'emissao', dir:-1};
  GRID.barra('#barra-oculta' in window ? '#barra-oculta' : document.createElement('div'));

  $('#area').addEventListener('click', ev => {
    const x = ev.target.closest('[data-xml]');
    if (x) { ev.stopPropagation(); baixar(x.dataset.xml, 'xml'); return; }
    const p = ev.target.closest('[data-pdf]');
    if (p) { ev.stopPropagation(); baixar(p.dataset.pdf, 'pdf'); return; }
    const f = ev.target.closest('[data-danfe]');
    if (f) { ev.stopPropagation(); abrirAuxiliar(f.dataset.danfe); return; }
    const m = ev.target.closest('[data-manif]');
    if (m) { ev.stopPropagation();
      menuManifestar(m, [Number(m.dataset.manif)]); return; }
    const k = ev.target.closest('[data-chave]');
    if (k) { ev.stopPropagation();
      navigator.clipboard.writeText(k.dataset.chave);
      toast.ok('Chave copiada.'); return; }
    const sf = ev.target.closest('[data-sefaz]');
    if (sf) { ev.stopPropagation();
      window.open('https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx' +
        '?tipoConsulta=completa&tipoConteudo=XbSeqxE8pl8=', '_blank');
      navigator.clipboard.writeText(sf.dataset.sefaz);
      toast('Chave copiada. Cole no portal da SEFAZ.'); }
  });

  let t;
  const recarrega = () => { clearTimeout(t); t = setTimeout(carregar, 350); };
  ['f-de','f-ate','f-tipo'].forEach(id => $('#' + id).onchange = carregar);
  $('#f-busca').oninput = recarrega;
  $('#btn-emitentes').onclick = verEmitentes;
  $('#f-limpar').onclick = () => {
    ['f-de','f-ate','f-tipo','f-busca'].forEach(id => $('#' + id).value = '');
    SITUACAO = null; carregar();
  };

  document.addEventListener('grid-selecao', ev => {
    if (ev.detail.grid !== GRID) return;
    const n = ev.detail.ids.length;
    $('#barra-sel').classList.toggle('on', n > 0);
    $('#sel-n').textContent = n;
    $('#sel-plural').textContent = n === 1 ? 'documento' : 'documentos';
  });
  $('#sel-xml').onclick = () => exportarLote('xml');
  $('#sel-pdf').onclick = () => exportarLote('pdf');
  $('#sel-limpar').onclick = () => GRID.limpaSelecao();
  $('#sel-manif').onclick = e => menuManifestar(e.currentTarget, [...GRID.selecao]);

  await carregar();
})();

async function exportarLote(formato){
  const ids = [...GRID.selecao];
  if (!ids.length) return;
  const nome = formato === 'pdf' ? 'documentos auxiliares' : 'arquivos XML';
  Progresso.abre('Exportando ' + nome,
    ids.length + ' documento(s) selecionado(s)');

  // o servidor processa em bloco: a barra acompanha o tempo estimado
  const msPorDoc = formato === 'pdf' ? 55 : 4;
  const estimado = Math.max(1200, ids.length * msPorDoc);
  const t0 = Date.now();
  const timer = setInterval(() => {
    const p = Math.min(93, (Date.now() - t0) / estimado * 100);
    Progresso.atualiza(p, formato === 'pdf'
      ? 'Gerando os PDF no servidor...' : 'Compactando os arquivos...');
  }, 180);

  try {
    const r = await fetch('/api/documentos/lote', {
      method:'POST',
      headers:{'Authorization':'Bearer ' + Sessao.token,
               'Content-Type':'application/json'},
      body: JSON.stringify({ids, formato}),
    });
    clearInterval(timer);
    if (!r.ok) { const d = await r.json().catch(() => ({}));
      Progresso.fecha(); toast.erro(d.detail || 'Erro ' + r.status); return; }
    Progresso.atualiza(97, 'Preparando o download...');
    const inc = r.headers.get('X-Incluidos'), fal = r.headers.get('X-Falhas');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await r.blob());
    a.download = 'nfcheck_' + formato + '_' + inc + 'docs.zip';
    a.click(); URL.revokeObjectURL(a.href);
    Progresso.atualiza(100, 'Concluído');
    setTimeout(Progresso.fecha, 500);
    toast.ok(inc + ' arquivo(s) exportado(s)' +
      (Number(fal) ? ' · ' + fal + ' sem conteúdo disponível' : '') + '.');
  } catch { clearInterval(timer); Progresso.fecha();
    toast.erro('Falha na exportação.'); }
}

/* ---------- manifestacao ---------- */
const EV = {
  '210210': 'Ciência da operação',
  '210200': 'Confirmação da operação',
  '210220': 'Desconhecimento da operação',
  '210240': 'Operação não realizada',
};

function menuManifestar(botao, ids){
  if (!ids.length) return;
  const lote = ids.length > 1;
  const itens = [
    {txt: EV['210210'], icone:'visto', fn:() => confirmaManif(ids, '210210')},
    {txt: EV['210200'], icone:'visto', fn:() => confirmaManif(ids, '210200')},
  ];
  if (!lote) {
    itens.push({sep:true});
    itens.push({txt: EV['210220'], icone:'alerta', perigo:true,
      fn:() => confirmaManif(ids, '210220')});
    itens.push({txt: EV['210240'], icone:'alerta', perigo:true,
      fn:() => confirmaManif(ids, '210240')});
  }
  Menu.abre(botao, itens);
}

function confirmaManif(ids, evento){
  const lote = ids.length > 1;
  const pedeSenha = lote && evento === '210200';
  const pedeJust = evento === '210240';
  Modal.cria({
    id:'m-manif', titulo: EV[evento],
    corpo:
      '<div class="aviso aviso-erro" id="mf-erro"></div>' +
      '<div class="aviso aviso-alerta on" style="margin-bottom:var(--e-4)">' +
        'Este evento é <b>irreversível</b> e será registrado na SEFAZ em nome da ' +
        'empresa. ' + (evento === '210200'
          ? 'A confirmação reconhece que a operação ocorreu.'
          : 'A ciência inicia o prazo de 180 dias para a manifestação definitiva.') +
      '</div>' +
      '<p style="margin:0 0 var(--e-4)"><b class="num">' + ids.length + '</b> ' +
        'documento(s) serão manifestados.</p>' +
      (pedeJust ? '<div class="grupo"><label class="rotulo" for="mf-just">' +
        'Justificativa (mínimo 15 caracteres)</label>' +
        '<textarea class="campo" id="mf-just"></textarea></div>' : '') +
      (pedeSenha ? '<div class="grupo"><label class="rotulo" for="mf-senha">' +
        'Confirme sua senha para prosseguir</label>' +
        '<input class="campo" type="password" id="mf-senha" ' +
        'autocomplete="current-password"></div>' : ''),
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Manifestar', cls: evento === '210200' ? 'btn-perigo' : 'btn-1',
       fn:() => executaManif(ids, evento)},
    ],
  });
  Modal.abre('m-manif');
  if (pedeSenha) setTimeout(() => $('#mf-senha').focus(), 60);
}

async function executaManif(ids, evento){
  const just = $('#mf-just') ? $('#mf-just').value.trim() : null;
  const senha = $('#mf-senha') ? $('#mf-senha').value : null;
  if ($('#mf-just') && just.length < 15) {
    const a = $('#mf-erro'); a.textContent = 'A justificativa precisa de 15 caracteres.';
    a.classList.add('on'); return;
  }
  if ($('#mf-senha') && !senha) {
    const a = $('#mf-erro'); a.textContent = 'Informe sua senha.';
    a.classList.add('on'); return;
  }
  Modal.fecha('m-manif');
  Progresso.abre(EV[evento], ids.length + ' documento(s) · comunicando com a SEFAZ');

  const estimado = Math.max(2000, ids.length * 1600);
  const t0 = Date.now();
  const timer = setInterval(() => {
    const p = Math.min(94, (Date.now() - t0) / estimado * 100);
    const feitos = Math.floor(p / 100 * ids.length);
    Progresso.atualiza(p, 'Enviando evento ' + Math.min(feitos + 1, ids.length) +
      ' de ' + ids.length + '...');
  }, 300);

  try {
    const r = await api.post('/api/documentos/manifestar',
      {ids, evento, justificativa: just || null, senha: senha || null});
    clearInterval(timer);
    Progresso.atualiza(100, 'Concluído');
    setTimeout(Progresso.fecha, 500);
    const falhou = r.resultados.filter(x => !x.ok);
    if (r.ok) toast.ok(r.ok + ' de ' + r.total + ' manifestado(s) com sucesso.');
    if (falhou.length) {
      const lista = falhou.slice(0, 12).map(f =>
        '<tr><td class="num">' + Fmt.escapa(f.numero || f.id) + '</td>' +
        '<td class="t3">' + Fmt.escapa(f.motivo || 'erro') + '</td></tr>').join('');
      Modal.cria({id:'m-falhas', titulo: falhou.length + ' não manifestado(s)',
        corpo:'<table class="dados"><tbody>' + lista + '</tbody></table>' +
          (falhou.length > 12 ? '<p class="t3" style="margin-top:var(--e-3)">' +
            'e mais ' + (falhou.length - 12) + '...</p>' : ''),
        acoes:[{txt:'Fechar', cls:'btn-1'}]});
      Modal.abre('m-falhas');
    }
    GRID.limpaSelecao();
    await carregar();
  } catch(e) {
    clearInterval(timer); Progresso.fecha(); toast.erro(e.message);
  }
}
