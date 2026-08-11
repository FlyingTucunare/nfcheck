/* NFCheck — nucleo. Sessao, API, formatadores, toast, modal, tema. */

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

/* ---------- tema ---------- */
const Tema = {
  atual(){ return localStorage.getItem('nfc_tema') || 'claro'; },
  aplica(t){
    document.documentElement.setAttribute('data-tema', t);
    localStorage.setItem('nfc_tema', t);
    document.dispatchEvent(new CustomEvent('tema', {detail:t}));
  },
  alterna(){ Tema.aplica(Tema.atual() === 'claro' ? 'escuro' : 'claro'); },
  init(){ document.documentElement.setAttribute('data-tema', Tema.atual()); },
};
Tema.init();

/* ---------- sessao ---------- */
const Sessao = {
  get token(){ return sessionStorage.getItem('nfc_token'); },
  get usuario(){
    try { return JSON.parse(sessionStorage.getItem('nfc_usuario') || 'null'); }
    catch { return null; }
  },
  get empresaId(){ return sessionStorage.getItem('nfc_empresa'); },
  set empresaId(v){ sessionStorage.setItem('nfc_empresa', v); },
  entra(d){
    sessionStorage.setItem('nfc_token', d.token);
    sessionStorage.setItem('nfc_usuario', JSON.stringify(d.usuario));
  },
  sai(){ sessionStorage.clear(); location.href = '/'; },
  exige(){ if (!Sessao.token) location.href = '/'; },
  pode(p){ return (Sessao.permissoes || []).includes(p); },
  permissoes: [],
};

/* ---------- API ---------- */
async function api(url, opt = {}) {
  const cab = {...(opt.headers || {})};
  if (Sessao.token) cab['Authorization'] = 'Bearer ' + Sessao.token;
  if (opt.body && !(opt.body instanceof FormData) && !cab['Content-Type'])
    cab['Content-Type'] = 'application/json';

  let r;
  try { r = await fetch(url, {...opt, headers: cab}); }
  catch { throw new Error('Falha de conexão. Verifique sua rede.'); }

  if (r.status === 401) { Sessao.sai(); throw new Error('Sessão expirada'); }
  if (r.status === 204) return null;

  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `Erro ${r.status}`);
  return d;
}
api.get  = u => api(u);
api.post = (u, b) => api(u, {method:'POST',
  body: b instanceof FormData ? b : JSON.stringify(b)});
api.put  = (u, b) => api(u, {method:'PUT', body: JSON.stringify(b)});
api.del  = u => api(u, {method:'DELETE'});

/* ---------- formatadores ---------- */
const Fmt = {
  cnpj: c => (c || '').replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5'),
  cpf:  c => (c || '').replace(/^(\d{3})(\d{3})(\d{3})(\d{2})$/, '$1.$2.$3-$4'),
  cep:  c => (c || '').replace(/^(\d{5})(\d{3})$/, '$1-$2'),
  data: d => d ? new Date(d).toLocaleDateString('pt-BR', {timeZone:'America/Sao_Paulo'}) : '—',
  dataHora: d => d ? new Date(d).toLocaleString('pt-BR',
    {timeZone:'America/Sao_Paulo', dateStyle:'short', timeStyle:'short'}) : '—',
  moeda: v => v == null ? '—'
    : Number(v).toLocaleString('pt-BR', {style:'currency', currency:'BRL'}),
  numero: v => v == null ? '—' : Number(v).toLocaleString('pt-BR'),
  relativo(d){
    if (!d) return '—';
    const s = (Date.now() - new Date(d)) / 1000;
    if (s < 60) return 'agora';
    if (s < 3600) return `há ${Math.floor(s/60)} min`;
    if (s < 86400) return `há ${Math.floor(s/3600)}h`;
    if (s < 2592000) return `há ${Math.floor(s/86400)}d`;
    return Fmt.data(d);
  },
  sigla(nome){
    const ign = ['DE','DA','DO','DOS','DAS','E','LTDA','ME','EPP','SA','S/A','EIRELI','CIA'];
    return (nome || '').toUpperCase().split(/[\s\/]+/)
      .filter(p => p.length > 1 && !ign.includes(p))
      .slice(0, 2).map(p => p[0]).join('') || '??';
  },
  escapa: t => String(t ?? '').replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
};

/* ---------- mascaras ---------- */
const Mascara = {
  cnpj(el){
    el.addEventListener('input', e => {
      let v = e.target.value.replace(/\D/g, '').slice(0, 14);
      v = v.replace(/^(\d{2})(\d)/, '$1.$2')
           .replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3')
           .replace(/\.(\d{3})(\d)/, '.$1/$2')
           .replace(/(\d{4})(\d)/, '$1-$2');
      e.target.value = v;
    });
  },
};

/* ---------- toast ---------- */
function toast(msg, tipo = '') {
  let caixa = $('.toasts');
  if (!caixa) {
    caixa = document.createElement('div');
    caixa.className = 'toasts';
    document.body.appendChild(caixa);
  }
  const t = document.createElement('div');
  t.className = 'toast ' + tipo;
  t.textContent = msg;
  caixa.appendChild(t);
  setTimeout(() => {
    t.style.transition = 'opacity .2s, transform .2s';
    t.style.opacity = '0'; t.style.transform = 'translateX(16px)';
    setTimeout(() => t.remove(), 220);
  }, 4200);
}
toast.ok   = m => toast(m, 'ok');
toast.erro = m => toast(m, 'erro');

/* ---------- modal ---------- */
const Modal = {
  abre(id){ const m = $('#'+id); if (m) m.classList.add('on'); },
  fecha(id){ const m = $('#'+id); if (m) m.classList.remove('on'); },
  fechaTodos(){ $$('.modal.on').forEach(m => m.classList.remove('on')); },
  /** Constroi e injeta um modal. cfg: {id,titulo,corpo,acoes:[{txt,cls,fn}]} */
  cria(cfg){
    $('#'+cfg.id)?.remove();
    const m = document.createElement('div');
    m.className = 'modal'; m.id = cfg.id;
    m.innerHTML =
      '<div class="modal-cx">' +
        '<div class="modal-cab"><h4>' + Fmt.escapa(cfg.titulo) + '</h4>' +
          '<button class="btn btn-3 btn-icone" data-fechar aria-label="Fechar">' + Icone.x + '</button>' +
        '</div>' +
        '<div class="modal-corpo">' + (cfg.corpo || '') + '</div>' +
        (cfg.acoes ? '<div class="modal-pe"></div>' : '') +
      '</div>';
    document.body.appendChild(m);
    (cfg.acoes || []).forEach(a => {
      const b = document.createElement('button');
      b.className = 'btn ' + (a.cls || 'btn-2');
      b.textContent = a.txt;
      if (a.id) b.id = a.id;
      b.onclick = () => a.fn ? a.fn(m) : Modal.fecha(cfg.id);
      $('.modal-pe', m).appendChild(b);
    });
    m.addEventListener('click', e => {
      if (e.target === m || e.target.closest('[data-fechar]')) Modal.fecha(cfg.id);
    });
    return m;
  },
};
document.addEventListener('keydown', e => { if (e.key === 'Escape') Modal.fechaTodos(); });

/* ---------- icones (SVG stroke, nunca emoji) ---------- */
const svg = d => '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" ' +
  'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
  'stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
const Icone = {
  x:        svg('<path d="M18 6L6 18M6 6l12 12"/>'),
  mais:     svg('<path d="M12 5v14M5 12h14"/>'),
  seta:     svg('<path d="M9 18l6-6-6-6"/>'),
  volta:    svg('<path d="M15 18l-6-6 6-6"/>'),
  busca:    svg('<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>'),
  grade:    svg('<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>' +
                '<rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>'),
  lista:    svg('<path d="M3 6h18M3 12h18M3 18h18"/>'),
  sol:      svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4' +
                'M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  lua:      svg('<path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/>'),
  sair:     svg('<path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/>'),
  engrenagem: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06' +
                'a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21' +
                'a2 2 0 11-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06' +
                'a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3' +
                'a2 2 0 110-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06' +
                'a2 2 0 112.83-2.83l.06.06A1.65 1.65 0 009 4.6 1.65 1.65 0 0010 3.09V3' +
                'a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06' +
                'a2 2 0 112.83 2.83l-.06.06A1.65 1.65 0 0019.4 9v0a1.65 1.65 0 001.51 1H21' +
                'a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z"/>'),
  usuarios: svg('<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/>' +
                '<path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>'),
  predio:   svg('<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4' +
                'M8 6h.01M16 6h.01M8 10h.01M16 10h.01M8 14h.01M16 14h.01"/>'),
  arquivo:  svg('<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>' +
                '<path d="M14 2v6h6"/>'),
  baixar:   svg('<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/>'),
  subir:    svg('<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12"/>'),
  escudo:   svg('<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'),
  grafico:  svg('<path d="M3 3v18h18M18 17V9M13 17V5M8 17v-3"/>'),
  sync:     svg('<path d="M21 2v6h-6M3 12a9 9 0 0115-6.7L21 8M3 22v-6h6M21 12a9 9 0 01-15 6.7L3 16"/>'),
  alerta:   svg('<path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/>' +
                '<path d="M12 9v4M12 17h.01"/>'),
  relogio:  svg('<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>'),
  pontos:   svg('<circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/>' +
                '<circle cx="12" cy="19" r="1"/>'),
  lapis:    svg('<path d="M17 3a2.8 2.8 0 114 4L7.5 20.5 2 22l1.5-5.5z"/>'),
  caixa:    svg('<path d="M21 8v13H3V8M1 3h22v5H1zM10 12h4"/>'),
  lixo:     svg('<path d="M3 6h18M8 6V4a1 1 0 011-1h6a1 1 0 011 1v2m3 0v14' +
                'a1 1 0 01-1 1H6a1 1 0 01-1-1V6"/>'),
  voltar:   svg('<path d="M3 7v6h6M3.5 13a9 9 0 102-6"/>'),
  copiar:   svg('<rect x="9" y="9" width="13" height="13" rx="2"/>' +
                '<path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>'),
  visto:    svg('<path d="M20 6L9 17l-5-5"/>'),
  bandeira: svg('<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/>' +
                '<line x1="4" y1="22" x2="4" y2="15"/>'),
  link:     svg('<path d="M10 13a5 5 0 007.5.5l3-3a5 5 0 00-7-7l-1.7 1.7"/>' +
                '<path d="M14 11a5 5 0 00-7.5-.5l-3 3a5 5 0 007 7l1.7-1.7"/>'),
};

/* ---------- menu suspenso ---------- */
const Menu = {
  abre(alvo, itens){
    Menu.fecha();
    const m = document.createElement('div');
    m.className = 'menu-flut';
    m.innerHTML = itens.map((i, n) => i.sep
      ? '<div class="menu-sep"></div>'
      : '<button data-i="' + n + '"' + (i.perigo ? ' class="perigo"' : '') + '>' +
        (i.icone ? Icone[i.icone] : '') + Fmt.escapa(i.txt) + '</button>').join('');
    document.body.appendChild(m);

    const r = alvo.getBoundingClientRect();
    const alt = m.offsetHeight || 200, larg = m.offsetWidth || 225;
    const abaixo = window.innerHeight - r.bottom;
    // abre para cima quando nao ha espaco suficiente abaixo
    m.style.top = (abaixo < alt + 16 && r.top > alt + 16
      ? r.top + window.scrollY - alt - 6
      : r.bottom + window.scrollY + 6) + 'px';
    m.style.left = Math.max(8, Math.min(r.right + window.scrollX - larg,
      window.innerWidth - larg - 8)) + 'px';

    m.addEventListener('click', ev => {
      const b = ev.target.closest('button[data-i]');
      if (!b) return;
      ev.stopPropagation();
      const it = itens[Number(b.dataset.i)];
      Menu.fecha();
      it.fn && it.fn();
    });
    setTimeout(() => document.addEventListener('click', Menu.fecha, {once:true}), 0);
    return m;
  },
  fecha(){ $$('.menu-flut').forEach(m => m.remove()); },
};
window.addEventListener('scroll', () => Menu.fecha(), true);

/* ---------- confirmacao ---------- */
function confirma(titulo, texto, onSim, rotulo = 'Confirmar') {
  const m = Modal.cria({
    id: 'modal-confirma', titulo,
    corpo: '<p style="margin:0;line-height:1.65">' + Fmt.escapa(texto) + '</p>',
    acoes: [
      {txt:'Cancelar', cls:'btn-2'},
      {txt:rotulo, cls:'btn-1', fn: mm => { Modal.fecha('modal-confirma'); onSim(); }},
    ],
  });
  Modal.abre('modal-confirma');
  return m;
}

/* ---------- progresso ---------- */
const Progresso = {
  abre(titulo, sub){
    $('#modal-prog')?.remove();
    const m = document.createElement('div');
    m.className = 'modal on'; m.id = 'modal-prog';
    m.innerHTML =
      '<div class="modal-cx" style="max-width:420px">' +
        '<div class="modal-corpo" style="text-align:center;padding:var(--e-6)">' +
          '<h4 style="margin-bottom:6px" id="pg-tit">' + Fmt.escapa(titulo) + '</h4>' +
          '<p class="t3" id="pg-sub" style="margin:0 0 var(--e-5)">' +
            Fmt.escapa(sub || '') + '</p>' +
          '<div style="height:7px;background:var(--sup-3);border-radius:99px;' +
            'overflow:hidden"><div id="pg-barra" style="height:100%;width:0;' +
            'background:var(--acao);transition:width .3s ease"></div></div>' +
          '<div class="colunas" style="justify-content:space-between;' +
            'margin-top:var(--e-3);font-size:var(--t-sm)">' +
            '<span class="t3" id="pg-txt">Preparando...</span>' +
            '<b class="num" id="pg-pct">0%</b></div>' +
        '</div></div>';
    document.body.appendChild(m);
  },
  atualiza(pct, texto){
    const b = $('#pg-barra'); if (!b) return;
    const p = Math.max(0, Math.min(100, Math.round(pct)));
    b.style.width = p + '%';
    $('#pg-pct').textContent = p + '%';
    if (texto) $('#pg-txt').textContent = texto;
  },
  fecha(){ $('#modal-prog')?.remove(); },
};
