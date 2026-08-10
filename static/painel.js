const $ = s => document.querySelector(s);
const TOKEN = sessionStorage.getItem('nfc_token');
const USUARIO = JSON.parse(sessionStorage.getItem('nfc_usuario') || 'null');
if (!TOKEN) location.href = '/';

const api = async (url, opt = {}) => {
  const r = await fetch(url, {...opt,
    headers: {...(opt.headers||{}), 'Authorization': 'Bearer ' + TOKEN}});
  if (r.status === 401) { sessionStorage.clear(); location.href = '/'; return; }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || 'Erro inesperado');
  return d;
};

const cnpjFmt = c => (c||'').replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5');
const dataFmt = d => d ? new Date(d).toLocaleDateString('pt-BR') : '—';
const moedaFmt = v => v == null ? '—' :
  Number(v).toLocaleString('pt-BR', {style:'currency', currency:'BRL'});

let DADOS = [], filtro = null, ordem = {col:'razao_social', dir:1};

const CERT = {
  ok:      {cls:'c-ok',     txt:'Válido'},
  vencendo:{cls:'c-venc',   txt:'Vencendo'},
  vencido: {cls:'c-erro',   txt:'Vencido'},
  sem:     {cls:'c-neutro', txt:'Sem certificado'},
};

function kpis() {
  const t = DADOS.length;
  const venc = DADOS.filter(e => e.cert_status === 'vencendo' || e.cert_status === 'vencido').length;
  const sem  = DADOS.filter(e => e.cert_status === 'sem').length;
  const par  = DADOS.filter(e => !e.ultima_sync ||
    (Date.now() - new Date(e.ultima_sync)) > 864e5).length;
  const itens = [
    {id:null,        n:t,    r:'Empresas ativas'},
    {id:'cert',      n:venc, r:'Certificado vencendo', alerta:venc>0},
    {id:'sem',       n:sem,  r:'Sem certificado',      alerta:sem>0},
    {id:'sync',      n:par,  r:'Sem sincronizar 24h',  alerta:par>0},
  ];
  $('#kpis').innerHTML = itens.map(k => {
    const cls = ['kpi'];
    if (k.alerta) cls.push('risco');
    if (filtro === k.id) cls.push('on');
    const f = k.id === null ? '' : k.id;
    return '<div class="' + cls.join(' ') + '" data-f="' + f + '">' +
           '<div class="n">' + k.n + '</div>' +
           '<div class="r">' + k.r + '</div></div>';
  }).join('');
  document.querySelectorAll('.kpi').forEach(el =>
    el.onclick = () => { const f = el.dataset.f || null;
      filtro = (filtro === f) ? null : f; render(); });
}

const COLS = [
  {k:'razao_social',      t:'Empresa',       w:230},
  {k:'cnpj',              t:'CNPJ',          w:180},
  {k:'municipio_nome',    t:'Município',     w:150},
  {k:'regime_tributario', t:'Regime',        w:130},
  {k:'porte',             t:'Porte',         w:165},
  {k:'cert_status',       t:'Certificado',   w:135},
  {k:'cert_ate',          t:'Validade',      w:100},
  {k:'ultima_sync',       t:'Última sinc.',  w:115},
];

const LARG_KEY = 'nfc_larguras_v2';
let LARG = JSON.parse(localStorage.getItem(LARG_KEY) || '{}');
const larg = c => LARG[c.k] || c.w;
const salvaLarg = () => localStorage.setItem(LARG_KEY, JSON.stringify(LARG));

function ligaPuxadores() {
  const area = document.getElementById('area');
  if (!area) return;
  area.addEventListener('mousedown', ev => {
    const pux = ev.target.closest('.puxador');
    if (!pux) return;
    ev.preventDefault(); ev.stopPropagation();
    const th = pux.closest('th'), col = th.dataset.c;
    const x0 = ev.pageX, w0 = th.getBoundingClientRect().width;
    const cg = area.querySelector('col[data-c="' + col + '"]');
    pux.classList.add('ativo');
    document.body.classList.add('redim');

    const mover = e => {
      const w = Math.max(70, Math.round(w0 + (e.pageX - x0)));
      LARG[col] = w;
      th.style.width = w + 'px';
      if (cg) cg.style.width = w + 'px';
      ajustaLargura();
    };
    const soltar = () => {
      pux.classList.remove('ativo');
      document.body.classList.remove('redim');
      window.removeEventListener('mousemove', mover);
      window.removeEventListener('mouseup', soltar);
      salvaLarg();
    };
    window.addEventListener('mousemove', mover);
    window.addEventListener('mouseup', soltar);
  });

  area.addEventListener('click', ev => {
    if (ev.target.closest('.puxador')) { ev.stopPropagation(); }
  }, true);

  area.addEventListener('dblclick', ev => {
    const pux = ev.target.closest('.puxador');
    if (!pux) return;
    ev.stopPropagation();
    delete LARG[pux.closest('th').dataset.c];
    salvaLarg(); render();
  });
}

function ajustaLargura() {
  const t = document.querySelector('#area table');
  if (!t) return;
  const soma = COLS.reduce((s, c) => s + larg(c), 0);
  const disp = t.parentElement.clientWidth;
  t.style.width = (soma < disp ? disp : soma) + 'px';
}

function visiveis() {
  const b = ($('#busca').value || '').toLowerCase().trim();
  let l = DADOS.filter(e =>
    !b || (e.razao_social||'').toLowerCase().includes(b) ||
          (e.cnpj||'').includes(b.replace(/\D/g,'')) ||
          (e.municipio_nome||'').toLowerCase().includes(b));
  if (filtro === 'cert') l = l.filter(e => ['vencendo','vencido'].includes(e.cert_status));
  if (filtro === 'sem')  l = l.filter(e => e.cert_status === 'sem');
  if (filtro === 'sync') l = l.filter(e => !e.ultima_sync ||
    (Date.now() - new Date(e.ultima_sync)) > 864e5);
  const c = ordem.col;
  return l.sort((a,b2) => {
    const x = a[c] ?? '', y = b2[c] ?? '';
    return (x > y ? 1 : x < y ? -1 : 0) * ordem.dir;
  });
}

function render() {
  kpis();
  const l = visiveis();
  $('#cnt').textContent = `${l.length} de ${DADOS.length}`;
  if (!l.length) {
    $('#area').innerHTML = `<div class="vazio">${DADOS.length
      ? 'Nenhuma empresa corresponde ao filtro.'
      : 'Nenhuma empresa cadastrada ainda. Comece cadastrando a primeira.'}</div>`;
    return;
  }
  const cg = COLS.map(c =>
    `<col data-c="${c.k}" style="width:${larg(c)}px">`).join('');
  const th = COLS.map(c => {
    const on = ordem.col===c.k ? (ordem.dir===1?'asc':'desc') : '';
    const s = ordem.col===c.k ? (ordem.dir===1?'▲':'▼') : '▲';
    return `<th class="${on}" data-c="${c.k}" style="width:${larg(c)}px" title="${c.t}">` +
           `${c.t}<span class="seta">${s}</span><span class="puxador"></span></th>`;
  }).join('');
  const tr = l.map(e => {
    const cs = CERT[e.cert_status] || CERT.sem;
    return `<tr data-id="${e.id}">
      <td title="${e.razao_social}"><div class="rz">${e.razao_social}</div>
          ${e.nome_fantasia ? `<div class="sub">${e.nome_fantasia}</div>` : ''}</td>
      <td>${cnpjFmt(e.cnpj)}</td>
      <td>${e.municipio_nome||'—'}${e.uf?'/'+e.uf:''}</td>
      <td>${e.regime_tributario||'—'}</td>
      <td>${e.porte||'—'}</td>
      <td><span class="chip ${cs.cls} chip-cert" data-cert="${e.id}"
            style="cursor:pointer" title="Gerenciar certificado">${cs.txt}</span></td>
      <td>${dataFmt(e.cert_ate)}</td>
      <td>${e.ultima_sync ? dataFmt(e.ultima_sync) : '—'}</td>
    </tr>`;
  }).join('');
  $('#area').innerHTML =
    `<div class="rolagem"><table><colgroup>${cg}</colgroup>` +
    `<thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
  ajustaLargura();
  document.querySelectorAll('th[data-c]').forEach(el => el.onclick = () => {
    const c = el.dataset.c;
    ordem = {col:c, dir: ordem.col===c ? -ordem.dir : 1};
    render();
  });
  document.querySelectorAll('.chip-cert').forEach(el => el.onclick = ev => {
    ev.stopPropagation();
    abrirCert(DADOS.find(x => x.id == el.dataset.cert));
  });
  document.querySelectorAll('tbody tr').forEach(el => el.onclick = () => {
    sessionStorage.setItem('nfc_empresa', el.dataset.id);
    location.href = '/empresa';
  });
}

let PREVIA = null;
const mErro = m => { const e=$('#m-erro'); e.textContent=m; e.style.display=m?'block':'none'; };

async function consultar() {
  mErro(''); $('#previa').style.display='none'; $('#m-aviso').style.display='none';
  $('#m-salvar').disabled = true;
  const c = $('#m-cnpj').value.replace(/\D/g,'');
  if (c.length !== 14) { mErro('Informe um CNPJ com 14 dígitos.'); return; }
  const b = $('#m-buscar'); b.disabled=true; b.textContent='Consultando...';
  try {
    const d = await api('/api/empresas/consultar-cnpj/' + c);
    PREVIA = d;
    $('#previa-dl').innerHTML = [
      ['Razão social', d.razao_social],
      ['Nome fantasia', d.nome_fantasia],
      ['Situação', d.situacao_cadastral],
      ['Abertura', dataFmt(d.abertura)],
      ['Porte', d.porte],
      ['Capital social', moedaFmt(d.capital_social)],
      ['Município', (d.municipio_nome||'') + (d.uf?'/'+d.uf:'') +
        (d.municipio_ibge?` (IBGE ${d.municipio_ibge})`:'')],
      ['Atividade', d.cnae_principal_desc],
      ['Simples', d.simples_optante===true?'Optante':d.simples_optante===false?'Não optante':'—'],
      ['Sócios', (d.socios||[]).map(s=>s.nome).join(', ') || '—'],
    ].filter(([,v]) => v).map(([k,v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
    $('#previa').style.display='block';
    if (d.ja_cadastrada) {
      $('#m-aviso').textContent =
        `Este CNPJ já está cadastrado em ${d.ja_cadastrada_em}. Solicite a transferência.`;
      $('#m-aviso').style.display='block';
    } else {
      $('#m-salvar').disabled = false;
    }
  } catch(e) { mErro(e.message); }
  finally { b.disabled=false; b.textContent='Consultar'; }
}

async function salvar() {
  const b = $('#m-salvar'); b.disabled=true; b.textContent='Cadastrando...';
  try {
    await api('/api/empresas', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({cnpj: $('#m-cnpj').value.replace(/\D/g,'')})});
    fecharModal(); await carregar();
  } catch(e) { mErro(e.message); }
  finally { b.disabled=false; b.textContent='Cadastrar'; }
}

const abrirModal = () => { $('#modal').classList.add('on'); $('#m-cnpj').focus(); };
function fecharModal() {
  $('#modal').classList.remove('on'); $('#m-cnpj').value=''; PREVIA=null;
  $('#previa').style.display='none'; $('#m-aviso').style.display='none';
  mErro(''); $('#m-salvar').disabled=true;
}

async function carregar() {
  try { DADOS = await api('/api/empresas'); render(); }
  catch(e) { $('#area').innerHTML = `<div class="vazio">${e.message}</div>`; }
}

$('#quem').textContent = USUARIO ? USUARIO.nome : '';
$('#sair').onclick = e => { e.preventDefault(); sessionStorage.clear(); location.href='/'; };
$('#btn-nova').onclick = abrirModal;
$('#fechar').onclick = fecharModal;
$('#m-cancelar').onclick = fecharModal;
$('#m-buscar').onclick = consultar;
$('#m-salvar').onclick = salvar;
$('#busca').oninput = render;
ligaPuxadores();
window.addEventListener('resize', ajustaLargura);
$('#m-cnpj').addEventListener('keydown', e => { if (e.key==='Enter') consultar(); });
$('#m-cnpj').addEventListener('input', e => {
  let v = e.target.value.replace(/\D/g,'').slice(0,14);
  v = v.replace(/^(\d{2})(\d)/,'$1.$2').replace(/^(\d{2})\.(\d{3})(\d)/,'$1.$2.$3')
       .replace(/\.(\d{3})(\d)/,'.$1/$2').replace(/(\d{4})(\d)/,'$1-$2');
  e.target.value = v;
});
document.addEventListener('keydown', e => { if (e.key==='Escape') fecharModal(); });

carregar();

/* ---------- certificados ---------- */
let CERT_EMP = null;
const cErro = m => { const e=$('#c-erro'); e.textContent=m; e.style.display=m?'block':'none'; };

async function abrirCert(empresa) {
  CERT_EMP = empresa;
  $('#c-empresa').textContent = empresa.razao_social + ' · ' + cnpjFmt(empresa.cnpj);
  $('#c-arquivo').value=''; $('#c-senha').value='';
  $('#c-previa').style.display='none'; $('#c-aviso').style.display='none';
  cErro(''); $('#c-salvar').disabled=true;
  $('#modal-cert').classList.add('on');
  try {
    const h = await api('/api/certificados/empresa/' + empresa.id);
    $('#c-hist').innerHTML = h.length ? `
      <div class="rotulo">Histórico</div>
      <table style="font-size:12.5px"><tbody>${h.map(c=>`
        <tr><td>${c.titular_cn||'—'}</td>
            <td>${dataFmt(c.valido_ate)}</td>
            <td><span class="chip ${c.ativo?'c-ok':'c-neutro'}">${c.ativo?'Ativo':'Substituído'}</span></td>
        </tr>`).join('')}</tbody></table>` : '';
  } catch(e) { $('#c-hist').innerHTML=''; }
}

async function analisarCert() {
  cErro(''); $('#c-previa').style.display='none'; $('#c-aviso').style.display='none';
  $('#c-salvar').disabled=true;
  const f = $('#c-arquivo').files[0], s = $('#c-senha').value;
  if (!f) { cErro('Selecione o arquivo do certificado.'); return; }
  if (!s) { cErro('Informe a senha do certificado.'); return; }
  const b = $('#c-analisar'); b.disabled=true; b.textContent='Verificando...';
  const fd = new FormData();
  fd.append('empresa_id', CERT_EMP.id); fd.append('senha', s); fd.append('arquivo', f);
  try {
    const d = await api('/api/certificados/analisar', {method:'POST', body:fd});
    $('#c-previa-dl').innerHTML = [
      ['Titular', d.titular_cn],
      ['CNPJ', cnpjFmt(d.cnpj_titular)],
      ['Válido de', dataFmt(d.valido_de)],
      ['Válido até', dataFmt(d.valido_ate)],
      ['Situação', d.vencido ? 'VENCIDO' : `Faltam ${d.dias_restantes} dias`],
    ].filter(([,v])=>v).map(([k,v])=>`<dt>${k}</dt><dd>${v}</dd>`).join('');
    $('#c-previa').style.display='block';
    if (d.aviso) { $('#c-aviso').textContent=d.aviso; $('#c-aviso').style.display='block'; }
    if (d.vencido) cErro('Certificado vencido. Envie um certificado válido.');
    else { $('#c-salvar').disabled=false; cErro(''); }
  } catch(e) { cErro(e.message); }
  finally { b.disabled=false; b.textContent='Conferir senha'; }
}

async function salvarCert() {
  const b = $('#c-salvar'); b.disabled=true; b.textContent='Enviando...';
  const fd = new FormData();
  fd.append('empresa_id', CERT_EMP.id);
  fd.append('senha', $('#c-senha').value);
  fd.append('arquivo', $('#c-arquivo').files[0]);
  try {
    await api('/api/certificados', {method:'POST', body:fd});
    $('#modal-cert').classList.remove('on');
    await carregar();
  } catch(e) { cErro(e.message); }
  finally { b.disabled=false; b.textContent='Enviar certificado'; }
}

async function espiarCert() {
  cErro(''); $('#c-previa').style.display='none'; $('#c-aviso').style.display='none';
  $('#c-salvar').disabled=true;
  const f = $('#c-arquivo').files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append('empresa_id', CERT_EMP.id); fd.append('arquivo', f);
  try {
    const d = await api('/api/certificados/espiar', {method:'POST', body:fd});
    $('#c-previa-dl').innerHTML = [
      ['Titular', d.titular_cn],
      ['CNPJ', cnpjFmt(d.cnpj_titular)],
      ['Emissor', d.emissor],
      ['Válido de', dataFmt(d.valido_de)],
      ['Válido até', dataFmt(d.valido_ate)],
      ['Situação', d.vencido ? 'VENCIDO'
        : d.dias_restantes < 30 ? `Vence em ${d.dias_restantes} dias`
        : `Faltam ${d.dias_restantes} dias`],
    ].filter(([,v])=>v).map(([k,v])=>`<dt>${k}</dt><dd>${v}</dd>`).join('');
    $('#c-previa').style.display='block';
    if (d.aviso) { $('#c-aviso').textContent=d.aviso; $('#c-aviso').style.display='block'; }
    if (d.vencido) cErro('Certificado vencido. Envie um certificado válido.');
    else $('#c-senha').focus();
  } catch(e) { cErro(e.message); }
}

$('#c-arquivo').onchange = espiarCert;
$('#c-analisar').onclick = analisarCert;
$('#c-salvar').onclick = salvarCert;
$('#c-fechar').onclick = $('#c-cancelar').onclick =
  () => $('#modal-cert').classList.remove('on');
