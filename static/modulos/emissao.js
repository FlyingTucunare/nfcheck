/* Modulo: emissao de NFS-e.
   Tela unica com painel de conferencia ao vivo. A transmissao e sincrona:
   manda o lote e ja consulta o protocolo, entao o numero da nota aparece
   na hora. Confirmacao obrigatoria antes de transmitir - e producao. */

const EMP = Sessao.empresaId;
let CFG = null, SERVICOS = [], TOMADORES = [], TOMADOR = null, SERVICO = null;
let ENVIANDO = false;

const err = m => { const e = $('#erro'); e.textContent = m || '';
  e.classList.toggle('on', !!m); };

const soDigito = v => (v || '').replace(/\D/g, '');
const num = id => { const v = parseFloat($(id).value); return isNaN(v) ? 0 : v; };
const pct = v => v == null ? '—' : (Number(v) * 100).toFixed(2).replace('.', ',') + '%';

function docFmt(v){
  const n = soDigito(v);
  if (n.length === 14)
    return n.slice(0,2)+'.'+n.slice(2,5)+'.'+n.slice(5,8)+'/'+n.slice(8,12)+'-'+n.slice(12);
  if (n.length === 11)
    return n.slice(0,3)+'.'+n.slice(3,6)+'.'+n.slice(6,9)+'-'+n.slice(9);
  return v || '';
}

/* endereco completo: exigido pela prefeitura, senao a nota e rejeitada */
const enderecoOk = t => !!(t && t.logradouro && t.bairro &&
  soDigito(t.cep).length === 8 && soDigito(t.municipio_ibge).length === 7 && t.uf);

const servicoOk = s => !!(s && s.item_lista_servico && s.codigo_tributacao &&
  s.cind_op && s.cclass_trib);

/* ---------------- tomador ---------------- */
function pintaTomador(){
  const b = $('#bloco-tomador');
  if (TOMADOR){
    b.innerHTML = '<div class="escolhido">' +
      '<div style="min-width:0">' +
        '<div class="nome">' + Fmt.escapa(TOMADOR.razao_social) + '</div>' +
        '<div class="sub">' + docFmt(TOMADOR.documento) +
          (TOMADOR.municipio_nome ? ' · ' + Fmt.escapa(TOMADOR.municipio_nome) +
            '/' + Fmt.escapa(TOMADOR.uf || '') : '') + '</div>' +
      '</div>' +
      '<button class="btn btn-2 btn-sm" id="b-trocar">Trocar</button></div>' +
      (enderecoOk(TOMADOR) ? ''
        : '<div class="aviso aviso-erro on" style="margin-top:var(--e-3)">' +
          'Endereço incompleto. A prefeitura pode rejeitar a nota. ' +
          '<a href="/e/tomadores">Corrigir cadastro</a></div>');
    $('#b-trocar').onclick = () => { TOMADOR = null; pintaTomador(); pintaResumo(); };
  } else {
    b.innerHTML = '<div class="linha-tom">' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Selecione o tomador</label>' +
          '<select class="campo" id="f-tomador">' +
            '<option value="">Selecione…</option>' +
            TOMADORES.map(t => '<option value="' + t.id + '">' +
              Fmt.escapa(t.razao_social) + ' — ' + docFmt(t.documento) +
              '</option>').join('') +
          '</select>' +
        '</div>' +
        '<a class="btn btn-2" href="/e/tomadores">Cadastrar novo</a>' +
      '</div>' +
      (TOMADORES.length ? '' : '<div class="dica">Nenhum tomador cadastrado ainda.</div>');
    const s = $('#f-tomador');
    if (s) s.onchange = () => {
      TOMADOR = TOMADORES.find(t => t.id == s.value) || null;
      pintaTomador(); pintaResumo();
    };
  }
}

/* ---------------- servico ---------------- */
function pintaServicos(){
  const favoritos = SERVICOS.filter(s => s.favorito);
  const demais = SERVICOS.filter(s => !s.favorito);
  const op = s => '<option value="' + s.id + '"' +
    (servicoOk(s) ? '' : ' disabled') + '>' + Fmt.escapa(s.apelido) +
    (servicoOk(s) ? '' : ' (classificação incompleta)') + '</option>';

  $('#f-servico').innerHTML = '<option value="">Selecione o serviço…</option>' +
    (favoritos.length ? '<optgroup label="Favoritos">' +
      favoritos.map(op).join('') + '</optgroup>' : '') +
    (demais.length ? '<optgroup label="Serviços">' +
      demais.map(op).join('') + '</optgroup>' : '');
}

function escolheuServico(){
  SERVICO = SERVICOS.find(s => s.id == $('#f-servico').value) || null;
  const d = $('#dica-servico');
  if (!SERVICO){ d.textContent = ''; pintaResumo(); return; }
  if (!$('#f-descricao').value.trim() || !$('#f-descricao').dataset.tocado)
    $('#f-descricao').value = SERVICO.descricao || '';
  if (SERVICO.valor_padrao != null && !$('#f-valor').value)
    $('#f-valor').value = Number(SERVICO.valor_padrao).toFixed(2);
  $('#f-retido').value = SERVICO.iss_retido ? '1' : '0';
  d.textContent = 'Item ' + (SERVICO.item_lista_servico || '—') +
    ' · código ' + (SERVICO.codigo_tributacao || '—') +
    ' · alíquota ' + pct(SERVICO.aliquota_iss);
  pintaResumo();
}

/* ---------------- resumo ao vivo ---------------- */
function calcula(){
  const bruto = num('#f-valor');
  const ded = num('#f-deducoes'), desc = num('#f-desconto');
  const pis = num('#f-pis'), cofins = num('#f-cofins'), inss = num('#f-inss');
  const ir = num('#f-ir'), csll = num('#f-csll');
  const retido = $('#f-retido').value === '1';
  const aliq = SERVICO && SERVICO.aliquota_iss != null ? Number(SERVICO.aliquota_iss) : 0;
  const base = Math.max(0, bruto - ded - desc);
  const iss = base * aliq;
  const liquido = bruto - desc - pis - cofins - inss - ir - csll - (retido ? iss : 0);
  return {bruto, ded, desc, pis, cofins, inss, ir, csll, retido, aliq, base, iss,
          liquido: Math.max(0, liquido)};
}

function pintaResumo(){
  const c = calcula();
  const pronto = TOMADOR && SERVICO && c.bruto > 0;
  const linha = (r, v, neg) => '<div class="rl' + (neg ? ' neg' : '') + '"><span>' + r +
    '</span><b>' + (neg ? '− ' : '') + 'R$ ' + Fmt.moeda(v).replace('R$', '').trim() +
    '</b></div>';

  $('#resumo').innerHTML =
    '<div class="cab"><div class="r">Nota a emitir</div>' +
      '<div class="v">RPS n. ' + (CFG && CFG.config ? CFG.config.proximo_numero : '—') +
      ' · série ' + (CFG && CFG.config ? CFG.config.serie_dps : '—') + '</div></div>' +
    (pronto
      ? '<div class="corpo">' +
          '<div class="rl"><span>Tomador</span><b style="max-width:200px;' +
            'font-family:var(--fonte)">' + Fmt.escapa(TOMADOR.razao_social) + '</b></div>' +
          '<div class="rl"><span>Item LC 116</span><b>' +
            Fmt.escapa(SERVICO.item_lista_servico || '—') + '</b></div>' +
          '<div class="rl"><span>Cód. tributação</span><b>' +
            Fmt.escapa(SERVICO.codigo_tributacao || '—') + '</b></div>' +
          '<div class="rl"><span>Alíquota ISS</span><b>' + pct(c.aliq) + '</b></div>' +
          '<div style="height:10px"></div>' +
          linha('Valor do serviço', c.bruto) +
          (c.ded ? linha('Deduções', c.ded, true) : '') +
          (c.desc ? linha('Desconto', c.desc, true) : '') +
          '<div class="rl"><span>Base de cálculo</span><b>R$ ' +
            Fmt.moeda(c.base).replace('R$','').trim() + '</b></div>' +
          '<div class="rl"><span>ISS ' + (c.retido ? '(retido)' : '') + '</span><b>R$ ' +
            Fmt.moeda(c.iss).replace('R$','').trim() + '</b></div>' +
          (c.pis ? linha('PIS', c.pis, true) : '') +
          (c.cofins ? linha('COFINS', c.cofins, true) : '') +
          (c.inss ? linha('INSS', c.inss, true) : '') +
          (c.ir ? linha('IR', c.ir, true) : '') +
          (c.csll ? linha('CSLL', c.csll, true) : '') +
        '</div>' +
        '<div class="liquido"><div class="r">Valor líquido</div>' +
          '<div class="n">R$ ' + Fmt.moeda(c.liquido).replace('R$','').trim() +
          '</div></div>'
      : '<div class="corpo"><div class="vazio-resumo">' +
        'Selecione o tomador, o serviço e o valor<br>para conferir a nota aqui.' +
        '</div></div>') +
    '<div class="rodape">' +
      '<button class="btn btn-1" id="b-emitir" style="width:100%"' +
        (pronto ? '' : ' disabled') + '>Revisar e emitir</button>' +
      (CFG && CFG.config && CFG.config.ambiente === '2'
        ? '<div class="dica" style="text-align:center">Ambiente de homologação</div>'
        : '<div class="dica" style="text-align:center">Emissão em produção — ' +
          'a nota é real</div>') +
    '</div>';

  const b = $('#b-emitir');
  if (b && pronto) b.onclick = confirmar;
}

/* ---------------- confirmacao e envio ---------------- */
function confirmar(){
  const c = calcula();
  const comp = $('#f-competencia').value;
  if (!comp) return toast('Informe a competência.');

  const li = (r, v) => '<div class="rl"><span>' + r + '</span><b>' + v + '</b></div>';
  Modal.cria({
    id:'m-conf', titulo:'Confirmar emissão',
    corpo:
      '<div class="aviso aviso-atencao on" style="margin-bottom:var(--e-4)">' +
        'A nota será transmitida à Prefeitura e passa a valer como documento ' +
        'fiscal. O cancelamento depende de prazo e regras do município.</div>' +
      li('Tomador', Fmt.escapa(TOMADOR.razao_social)) +
      li('CNPJ / CPF', docFmt(TOMADOR.documento)) +
      li('Serviço', Fmt.escapa(SERVICO.apelido)) +
      li('Item LC 116', Fmt.escapa(SERVICO.item_lista_servico || '—')) +
      li('Cód. tributação', Fmt.escapa(SERVICO.codigo_tributacao || '—')) +
      li('Competência', comp.split('-').reverse().join('/')) +
      li('Valor do serviço', 'R$ ' + Fmt.moeda(c.bruto).replace('R$','').trim()) +
      li('Alíquota ISS', pct(c.aliq)) +
      li('ISS' + (c.retido ? ' (retido)' : ''),
         'R$ ' + Fmt.moeda(c.iss).replace('R$','').trim()) +
      '<div class="liquido" style="margin-top:var(--e-4);border-radius:var(--r)">' +
        '<div class="r">Valor líquido</div><div class="n">R$ ' +
        Fmt.moeda(c.liquido).replace('R$','').trim() + '</div></div>',
    acoes:[
      {txt:'Voltar', cls:'btn-2'},
      {txt:'Confirmar e emitir', cls:'btn-1', id:'b-conf', fn: emitir},
    ],
  });
  Modal.abre('m-conf');
}

async function emitir(){
  if (ENVIANDO) return;
  ENVIANDO = true;
  const b = $('#b-conf');
  if (b){ b.disabled = true; b.textContent = 'Transmitindo…'; }

  const comp = $('#f-competencia').value + '-01';
  const corpo = {
    empresa_id: EMP, tomador_id: TOMADOR.id, servico_id: SERVICO.id,
    valor_servico: num('#f-valor'), competencia: comp,
    descricao: $('#f-descricao').value.trim() || null,
    valor_deducoes: num('#f-deducoes'), valor_desconto: num('#f-desconto'),
    valor_pis: num('#f-pis'), valor_cofins: num('#f-cofins'),
    valor_inss: num('#f-inss'), valor_ir: num('#f-ir'), valor_csll: num('#f-csll'),
    iss_retido: $('#f-retido').value === '1',
  };

  try {
    const r = await api.post('/api/nfse/emitir', corpo);
    Modal.fecha('m-conf');
    if (r.situacao === 'autorizada') telaSucesso(r);
    else if (r.situacao === 'processando') telaProcessando(r);
    else telaRejeitada(r);
  } catch(e){
    if (b){ b.disabled = false; b.textContent = 'Confirmar e emitir'; }
    toast(e.message);
  } finally {
    ENVIANDO = false;
    await recarregaConfig();
  }
}

/* ---------------- desfechos ---------------- */
function telaSucesso(r){
  Modal.cria({
    id:'m-ok', titulo:'', largura:520,
    corpo: '<div class="sucesso">' +
      '<div class="ic">' + Icone.visto + '</div>' +
      '<h2>NFS-e autorizada</h2>' +
      '<p class="t3">A nota foi registrada na Prefeitura.</p>' +
      '<div class="num">n. ' + Fmt.escapa(r.numero_nfse || '—') + '</div>' +
      (r.codigo_verificacao ? '<div class="cod">Código de verificação: <b>' +
        Fmt.escapa(r.codigo_verificacao) + '</b></div>' : '') +
      '<div class="acoes">' +
        '<a class="btn btn-1" target="_blank" href="/api/nfse/notas/' + r.nfse_id +
          '/danfse">Abrir DANFSe</a>' +
        '<a class="btn btn-2" href="/api/nfse/notas/' + r.nfse_id + '/xml">Baixar XML</a>' +
      '</div></div>',
    acoes:[
      {txt:'Ver todas as notas', cls:'btn-2', fn:() => location.href = '/e/notas'},
      {txt:'Emitir outra', cls:'btn-1', fn:() => location.reload()},
    ],
  });
  Modal.abre('m-ok');
}

function telaProcessando(r){
  Modal.cria({
    id:'m-proc', titulo:'Lote transmitido',
    corpo:'<div class="aviso aviso-atencao on">' + Fmt.escapa(r.aviso ||
      'A Prefeitura recebeu o lote e ainda está processando.') + '</div>' +
      '<div class="rl"><span>Protocolo</span><b>' +
        Fmt.escapa(r.protocolo || '—') + '</b></div>' +
      '<p class="t3" style="margin-top:var(--e-4)">A nota fica em ' +
      '<b>processando</b> até a Prefeitura concluir. Use "Consultar" na tela ' +
      'de notas para atualizar.</p>',
    acoes:[
      {txt:'Ver notas', cls:'btn-2', fn:() => location.href = '/e/notas'},
      {txt:'Consultar agora', cls:'btn-1', fn: async () => {
        try {
          const d = await api.post('/api/nfse/notas/' + r.nfse_id + '/consultar', {});
          Modal.fecha('m-proc');
          if (d.situacao === 'autorizada') telaSucesso(d);
          else if (d.situacao === 'rejeitada') telaRejeitada(d);
          else telaProcessando(d);
        } catch(e){ toast(e.message); }
      }},
    ],
  });
  Modal.abre('m-proc');
}

function telaRejeitada(r){
  const msgs = r.mensagens || [];
  Modal.cria({
    id:'m-rej', titulo:'Nota rejeitada',
    corpo:'<div class="aviso aviso-erro on">A Prefeitura não aceitou a nota. ' +
      'Nenhum documento fiscal foi gerado.</div>' +
      (msgs.length
        ? msgs.map(m => '<div class="secao" style="margin-bottom:var(--e-3)">' +
            '<b>' + Fmt.escapa(m.codigo || '') + '</b> — ' +
            Fmt.escapa(m.mensagem || '') +
            (m.solucao ? '<div class="dica">' + Fmt.escapa(m.solucao) + '</div>' : '') +
            '</div>').join('')
        : '<p>' + Fmt.escapa(r.erro || 'Erro não identificado.') + '</p>') +
      '<p class="t3">Corrija o que for indicado e emita novamente. ' +
      'O número do RPS foi consumido — a próxima nota usa o seguinte.</p>',
    acoes:[{txt:'Entendi', cls:'btn-1'}],
  });
  Modal.abre('m-rej');
}

/* ---------------- reemissao ---------------- */
/* Repoe os dados de uma nota rejeitada. Gera uma nota NOVA, com numero de RPS
   novo - o numero da rejeitada nao e reaproveitado, para nao criar duplicidade
   na sequencia que a fiscalizacao audita. */
function preencheReemissao(d){
  TOMADOR = TOMADORES.find(t => t.id == d.tomador_id) || null;
  pintaTomador();

  if (d.servico_id){
    $('#f-servico').value = d.servico_id;
    escolheuServico();
  }
  if (d.descricao){
    $('#f-descricao').value = d.descricao;
    $('#f-descricao').dataset.tocado = '1';
  }
  if (d.valor_servico != null) $('#f-valor').value = Number(d.valor_servico).toFixed(2);
  if (d.competencia) $('#f-competencia').value = String(d.competencia).slice(0, 7);
  $('#f-retido').value = d.iss_retido ? '1' : '0';

  const ret = {'#f-deducoes':'valor_deducoes', '#f-desconto':'valor_desconto',
    '#f-pis':'valor_pis', '#f-cofins':'valor_cofins', '#f-inss':'valor_inss',
    '#f-ir':'valor_ir', '#f-csll':'valor_csll'};
  let temRetencao = false;
  Object.entries(ret).forEach(([id, campo]) => {
    const v = Number(d[campo] || 0);
    if (v > 0){ $(id).value = v.toFixed(2); temRetencao = true; }
  });
  if (temRetencao){
    $('#box-retencoes').style.display = 'block';
    $('#b-retencoes').innerHTML = Icone.x + 'Retenções e deduções';
  }

  if (d.motivo){
    const e = $('#erro');
    e.innerHTML = '<b>Esta nota foi rejeitada (RPS ' + Fmt.escapa(String(d.numero_rps || '—')) +
      '):</b><br>' + Fmt.escapa(d.motivo) +
      '<br><span class="t3">Corrija o que for necessário. Será gerada uma nota ' +
      'nova, com novo número de RPS.</span>';
    e.classList.add('on');
  }
  pintaResumo();
}

/* ---------------- carga ---------------- */
async function recarregaConfig(){
  try { CFG = await api.get('/api/nfse/config?empresa_id=' + EMP); } catch(e){}
  pintaResumo();
}

function _semAcento(s){ return s.normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }

function _acaoPendencia(p){
  const t = _semAcento(p).toLowerCase();
  if (t.includes('certificado digital')) return {href:'/e/certificado', label:'Certificado'};
  if (t.includes('nfs-e ainda nao configurada'))
    return {href:'/e/nfse-config', label:'Configuração NFS-e'};
  if (t.includes('sem inscricao municipal') || t.includes('sem municipio definido'))
    return {href:'/e/cadastro', label:'Cadastro'};
  if (t.includes('tomador')) return {href:'/e/tomadores', label:'Tomadores'};
  if (t.includes('servico')) return {href:'/e/servicos', label:'Serviços'};
  return null;
}

function bloqueia(pendencias){
  $('#area').style.display = 'none';
  const acoes = new Map();
  pendencias.forEach(p => { const a = _acaoPendencia(p); if (a && !acoes.has(a.href)) acoes.set(a.href, a); });
  $('#bloqueio').innerHTML = '<div class="pendencias">' +
    '<h3>Não é possível emitir ainda</h3><ul>' +
    pendencias.map(p => '<li>' + Fmt.escapa(p) + '</li>').join('') +
    '</ul><div style="margin-top:var(--e-4);display:flex;gap:var(--e-3);flex-wrap:wrap">' +
    Array.from(acoes.values()).map(a =>
      '<a class="btn btn-2" href="' + a.href + '">' + Fmt.escapa(a.label) + '</a>').join('') +
    '</div></div>';
}

(async () => {
  await Shell.monta(EMP ? {empresa: EMP} : {});
  $('#ver-notas').innerHTML = Icone.arquivo + 'Notas emitidas';
  $('#ver-notas').onclick = () => location.href = '/e/notas';
  $('#b-retencoes').innerHTML = Icone.mais + 'Retenções e deduções';
  $('#b-retencoes').onclick = () => {
    const b = $('#box-retencoes');
    const aberto = b.style.display !== 'none';
    b.style.display = aberto ? 'none' : 'block';
    $('#b-retencoes').innerHTML = (aberto ? Icone.mais : Icone.x) +
      'Retenções e deduções';
  };

  const hoje = new Date();
  $('#f-competencia').value = hoje.toISOString().slice(0, 7);

  try {
    CFG = await api.get('/api/nfse/config?empresa_id=' + EMP);
    if (CFG.pendencias && CFG.pendencias.length){ bloqueia(CFG.pendencias); return; }

    [SERVICOS, TOMADORES] = await Promise.all([
      api.get('/api/nfse/servicos?empresa_id=' + EMP),
      api.get('/api/nfse/tomadores?empresa_id=' + EMP),
    ]);

    const pend = [];
    if (!TOMADORES.length) pend.push('Nenhum tomador cadastrado.');
    if (!SERVICOS.filter(servicoOk).length)
      pend.push('Nenhum serviço com classificação fiscal completa.');
    if (pend.length){ bloqueia(pend); return; }

    pintaTomador();
    pintaServicos();

    /* veio da tela de tomadores pelo atalho "Emitir NFS-e" */
    const pre = sessionStorage.getItem('nfc_emitir_tomador');
    if (pre){
      sessionStorage.removeItem('nfc_emitir_tomador');
      TOMADOR = TOMADORES.find(t => t.id == pre) || null;
      pintaTomador();
    }

    /* veio de "Corrigir e reemitir" numa nota rejeitada */
    const rejeitada = sessionStorage.getItem('nfc_reemitir');
    if (rejeitada){
      sessionStorage.removeItem('nfc_reemitir');
      try { preencheReemissao(JSON.parse(rejeitada)); } catch(e){}
    }

    $('#f-servico').onchange = escolheuServico;
    $('#f-descricao').oninput = e => { e.target.dataset.tocado = '1'; };
    ['#f-valor','#f-retido','#f-competencia'].forEach(i => {
      const el = $(i); if (el) el.oninput = el.onchange = pintaResumo;
    });
    $$('.ret').forEach(el => el.oninput = pintaResumo);

    pintaResumo();
  } catch(e){ err(e.message); }
})();
