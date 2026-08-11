/* NFCheck — grid reutilizavel.
   Ordenacao, largura ajustavel e persistente, busca, filtros e duas visoes.

   const g = new Grid({
     alvo: '#area',
     chave: 'clientes',                    // namespace do localStorage
     colunas: [
       {k:'razao_social', t:'Empresa', w:240, cel:e => ...},
       {k:'valor', t:'Valor', w:110, num:true, fmt:Fmt.moeda},
     ],
     busca: e => [e.razao_social, e.cnpj],  // campos pesquisaveis
     aoClicar: e => { ... },
     cartao: e => '<div>...</div>',         // habilita a visao em cards
     vazio: {titulo:'...', texto:'...'},
   });
   g.dados(lista);
*/

class Grid {
  constructor(cfg) {
    this.cfg     = cfg;
    this.el      = typeof cfg.alvo === 'string' ? $(cfg.alvo) : cfg.alvo;
    this.chave   = cfg.chave || 'grid';
    this.colunas = cfg.colunas;
    this.lista   = [];
    this.termo   = '';
    this.filtro  = null;
    this.ordem   = {col: cfg.ordemInicial || cfg.colunas[0].k, dir: 1};
    this.visao   = cfg.cartao
      ? (localStorage.getItem('nfc_visao_' + this.chave) || 'cartoes')
      : 'tabela';
    this.larguras = this._leLarguras();
    this.selecao = new Set();
    this.selecionavel = !!cfg.selecionavel;
    this.auto = cfg.porPagina === 'auto';
    this.porPagina = this.auto ? 20 : (cfg.porPagina || 0);
    this.pagina = 1;
    if (this.auto) {
      let t;
      window.addEventListener('resize', () => {
        clearTimeout(t);
        t = setTimeout(() => { if (this._calculaCabem()) this.render(); }, 200);
      });
    }
    this._ligaEventos();
  }

  /* ---------- dados ---------- */
  dados(l){ this.lista = l || []; this.pagina = 1; this.render(); return this; }
  busca(t){ this.termo = (t || '').toLowerCase().trim();
    this.pagina = 1; this.render(); }
  filtra(f){ this.filtro = f; this.pagina = 1; this.render(); }
  vaiPara(p){
    const max = Math.max(1, Math.ceil(this.visiveis().length / this.porPagina));
    this.pagina = Math.max(1, Math.min(p, max));
    this.render();
    this.el.scrollIntoView({behavior:'smooth', block:'start'});
  }
  trocaVisao(v){
    this.visao = v;
    localStorage.setItem('nfc_visao_' + this.chave, v);
    this.render();
    document.dispatchEvent(new CustomEvent('grid-visao', {detail:{grid:this, visao:v}}));
  }

  visiveis(){
    let l = this.lista;
    if (this.termo && this.cfg.busca) {
      l = l.filter(x => (this.cfg.busca(x) || [])
        .some(c => String(c ?? '').toLowerCase().includes(this.termo)));
    }
    if (this.filtro) l = l.filter(this.filtro);
    const c = this.colunas.find(x => x.k === this.ordem.col);
    return [...l].sort((a, b) => {
      let x = a[this.ordem.col], y = b[this.ordem.col];
      if (c && c.num) { x = Number(x) || 0; y = Number(y) || 0; }
      else { x = String(x ?? '').toLowerCase(); y = String(y ?? '').toLowerCase(); }
      return (x > y ? 1 : x < y ? -1 : 0) * this.ordem.dir;
    });
  }

  /* ---------- larguras ---------- */
  _leLarguras(){
    try { return JSON.parse(localStorage.getItem('nfc_larg_' + this.chave) || '{}'); }
    catch { return {}; }
  }
  _salvaLarguras(){
    localStorage.setItem('nfc_larg_' + this.chave, JSON.stringify(this.larguras));
  }
  _larg(c){ return this.larguras[c.k] || c.w || 140; }

  /* ---------- render ---------- */
  render(){
    const l = this.visiveis();
    document.dispatchEvent(new CustomEvent('grid-render',
      {detail:{grid:this, total:this.lista.length, exibidos:l.length}}));

    if (!l.length) { this.el.innerHTML = this._vazio(); return; }
    if (this.auto && !this._calculado) {
      this._calculado = true;
      this._calculaCabem();
    }
    const pag = this.porPagina
      ? l.slice((this.pagina - 1) * this.porPagina, this.pagina * this.porPagina)
      : l;
    this.el.innerHTML = (this.visao === 'cartoes' && this.cfg.cartao
      ? this._cartoes(pag) : this._tabela(pag)) + this._paginacao(l.length);
    this._ligaLinhas();
    this._ligaPaginacao();
    if (this.visao === 'tabela') this._ajusta();
  }

  _paginacao(total){
    if (!this.porPagina || total <= this.porPagina) return '';
    const paginas = Math.ceil(total / this.porPagina);
    const p = this.pagina;
    const nums = [];
    const add = n => { if (!nums.includes(n) && n >= 1 && n <= paginas) nums.push(n); };
    add(1); add(2);
    for (let i = p - 1; i <= p + 1; i++) add(i);
    add(paginas - 1); add(paginas);
    nums.sort((a, b) => a - b);

    let botoes = '', ant = 0;
    nums.forEach(n => {
      if (n - ant > 1) botoes += '<span class="t3">…</span>';
      botoes += '<button class="pag-btn' + (n === p ? ' on' : '') +
        '" data-p="' + n + '">' + n + '</button>';
      ant = n;
    });
    const ini = (p - 1) * this.porPagina + 1;
    const fim = Math.min(p * this.porPagina, total);
    return '<div class="paginacao">' +
      '<span class="t3">' + ini + '–' + fim + ' de ' + Fmt.numero(total) + '</span>' +
      '<button class="pag-btn" data-p="' + (p - 1) + '"' +
        (p === 1 ? ' disabled' : '') + '>‹</button>' + botoes +
      '<button class="pag-btn" data-p="' + (p + 1) + '"' +
        (p === paginas ? ' disabled' : '') + '>›</button>' +
    '</div>';
  }

  _ligaPaginacao(){
    $$('.pag-btn[data-p]', this.el).forEach(b => b.onclick = ev => {
      ev.stopPropagation();
      this.vaiPara(Number(b.dataset.p));
    });
  }

  _vazio(){
    const v = this.cfg.vazio || {};
    const semDados = !this.lista.length;
    return '<div class="painel"><div class="vazio">' +
      '<h4>' + Fmt.escapa(semDados ? (v.titulo || 'Nada por aqui ainda')
                                   : 'Nenhum resultado') + '</h4>' +
      '<p>' + Fmt.escapa(semDados ? (v.texto || '')
                                  : 'Ajuste a busca ou os filtros.') + '</p>' +
      (semDados && v.acao ? v.acao : '') + '</div></div>';
  }

  _cartoes(l){
    return '<div class="entra-lista" style="display:grid;' +
      'grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:var(--e-4)">' +
      l.map((e, i) => {
        const html = this.cfg.cartao(e);
        return html.replace('<div class="cartao',
          '<div data-id="' + e.id + '" style="animation-delay:' +
          Math.min(i * 28, 300) + 'ms" class="cartao');
      }).join('') + '</div>';
  }

  limpaSelecao(){ this.selecao.clear(); this.render(); this._avisaSelecao(); }
  _avisaSelecao(){
    document.dispatchEvent(new CustomEvent('grid-selecao',
      {detail:{grid:this, ids:[...this.selecao]}}));
  }

  _tabela(l){
    const sel = this.selecionavel;
    const cols = (sel ? '<col style="width:40px">' : '') + this.colunas.map(c =>
      '<col data-c="' + c.k + '" style="width:' + this._larg(c) + 'px">').join('');
    const marcados = l.length && l.every(x => this.selecao.has(x.id));
    const th = (sel ? '<th style="width:40px;cursor:default">' +
        '<input type="checkbox" data-todos' + (marcados ? ' checked' : '') +
        ' title="Selecionar os desta pagina"></th>' : '') +
      this.colunas.map(c => {
      const on = this.ordem.col === c.k ? (this.ordem.dir === 1 ? 'asc' : 'desc') : '';
      const s  = this.ordem.col === c.k ? (this.ordem.dir === 1 ? '▲' : '▼') : '▲';
      return '<th class="' + on + '" data-c="' + c.k + '" title="' + Fmt.escapa(c.t) + '" ' +
             'style="width:' + this._larg(c) + 'px">' + Fmt.escapa(c.t) +
             '<span class="seta">' + s + '</span><span class="puxador"></span></th>';
    }).join('');
    const tr = l.map(e => '<tr data-id="' + e.id + '"' +
      (this.selecao.has(e.id) ? ' class="sel"' : '') + '>' +
      (sel ? '<td data-parar><input type="checkbox" data-sel="' + e.id + '"' +
        (this.selecao.has(e.id) ? ' checked' : '') + '></td>' : '') +
      this.colunas.map(c => {
      const v = c.cel ? c.cel(e) : (c.fmt ? c.fmt(e[c.k]) : Fmt.escapa(e[c.k] ?? '—'));
      const cls = c.num ? ' class="num"' : '';
      return '<td' + cls + ' title="' + Fmt.escapa(c.cel ? '' : (e[c.k] ?? '')) + '">' +
             v + '</td>';
    }).join('') + '</tr>').join('');

    return '<div class="painel"><div class="rolagem"><table class="dados">' +
      '<colgroup>' + cols + '</colgroup><thead><tr>' + th + '</tr></thead>' +
      '<tbody>' + tr + '</tbody></table></div></div>';
  }

  _calculaCabem(){
    /* quantas linhas cabem sem rolagem: sobra da viewport dividida pela altura */
    const topo = this.el.getBoundingClientRect().top;
    const reservado = 42 + 56 + 24;   // cabecalho da tabela + paginacao + folga
    const linha = parseInt(getComputedStyle(document.body)
      .getPropertyValue('--alt-linha')) || 38;
    const cabem = Math.max(8, Math.floor((window.innerHeight - topo - reservado) / linha));
    if (cabem === this.porPagina) return false;
    this.porPagina = cabem;
    return true;
  }

  _ajusta(){
    const t = $('table.dados', this.el);
    if (!t) return;
    const extra = this.selecionavel ? 40 : 0;
    const soma = this.colunas.reduce((s, c) => s + this._larg(c), 0) + extra;
    const disp = t.parentElement.clientWidth;
    t.style.width = (soma < disp ? disp : soma) + 'px';

    // sobra de espaco vai para a coluna flexivel, nao distribuida em todas
    const flex = this.cfg.colunaFlexivel;
    if (flex && soma < disp && !this.larguras[flex]) {
      const c = this.colunas.find(x => x.k === flex);
      if (c) {
        const nova = (c.w || 140) + (disp - soma);
        const cg = $('col[data-c="' + flex + '"]', this.el);
        const th = $('th[data-c="' + flex + '"]', this.el);
        if (cg) cg.style.width = nova + 'px';
        if (th) th.style.width = nova + 'px';
      }
    }
  }

  _ligaLinhas(){
    if (!this.cfg.aoClicar) return;
    const sel = this.visao === 'cartoes' ? '.cartao[data-id]' : 'tbody tr[data-id]';
    $$(sel, this.el).forEach(el => {
      el.classList.add('cartao-click');
      el.onclick = ev => {
        if (ev.target.closest('[data-parar]')) return;
        const item = this.lista.find(x => String(x.id) === el.dataset.id);
        if (item) this.cfg.aoClicar(item, ev);
      };
    });
  }

  _ligaEventos(){
    this.el.addEventListener('click', ev => {
      const th = ev.target.closest('th[data-c]');
      if (!th || ev.target.closest('.puxador')) return;
      const c = th.dataset.c;
      this.ordem = {col: c, dir: this.ordem.col === c ? -this.ordem.dir : 1};
      this.render();
    });

    this.el.addEventListener('mousedown', ev => {
      const pux = ev.target.closest('.puxador');
      if (!pux) return;
      ev.preventDefault(); ev.stopPropagation();
      const th = pux.closest('th'), col = th.dataset.c;
      const x0 = ev.pageX, w0 = th.getBoundingClientRect().width;
      const cg = $('col[data-c="' + col + '"]', this.el);
      pux.classList.add('ativo');
      document.body.classList.add('redim');

      const mover = e => {
        const w = Math.max(60, Math.round(w0 + (e.pageX - x0)));
        this.larguras[col] = w;
        th.style.width = w + 'px';
        if (cg) cg.style.width = w + 'px';
        this._ajusta();
      };
      const soltar = () => {
        pux.classList.remove('ativo');
        document.body.classList.remove('redim');
        window.removeEventListener('mousemove', mover);
        window.removeEventListener('mouseup', soltar);
        this._salvaLarguras();
      };
      window.addEventListener('mousemove', mover);
      window.addEventListener('mouseup', soltar);
    });

    this.el.addEventListener('dblclick', ev => {
      const pux = ev.target.closest('.puxador');
      if (!pux) return;
      ev.stopPropagation();
      delete this.larguras[pux.closest('th').dataset.c];
      this._salvaLarguras(); this.render();
    });

    this.el.addEventListener('change', ev => {
      const t = ev.target.closest('[data-todos]');
      if (t) {
        const todos = this.visiveis();
        const vis = this.porPagina
          ? todos.slice((this.pagina - 1) * this.porPagina,
                        this.pagina * this.porPagina)
          : todos;
        if (t.checked) vis.forEach(x => this.selecao.add(x.id));
        else vis.forEach(x => this.selecao.delete(x.id));
        this.render(); this._avisaSelecao(); return;
      }
      const c = ev.target.closest('[data-sel]');
      if (c) {
        const id = Number(c.dataset.sel);
        c.checked ? this.selecao.add(id) : this.selecao.delete(id);
        c.closest('tr').classList.toggle('sel', c.checked);
        this._avisaSelecao();
      }
    });

    window.addEventListener('resize', () => this._ajusta());
  }

  /* ---------- barra de controles ---------- */
  barra(alvo, opcoes = {}){
    const el = typeof alvo === 'string' ? $(alvo) : alvo;
    el.innerHTML =
      '<div class="colunas" style="gap:var(--e-2);margin-bottom:var(--e-3)">' +
        '<div style="position:relative;flex:1;max-width:360px">' +
          '<span style="position:absolute;left:11px;top:50%;transform:translateY(-50%);' +
            'color:var(--txt-3);display:flex">' + Icone.busca + '</span>' +
          '<input class="campo" style="padding-left:34px" data-busca ' +
            'placeholder="' + (opcoes.placeholder || 'Buscar...') + '">' +
        '</div>' +
        (opcoes.extra || '') +
        (this.cfg.cartao ?
        '<div class="colunas" style="gap:0;border:1px solid var(--linha);' +
          'border-radius:var(--r);overflow:hidden;background:var(--sup-1)">' +
          '<button class="btn btn-3 btn-sm" data-v="cartoes" style="border-radius:0">' +
            Icone.grade + '</button>' +
          '<button class="btn btn-3 btn-sm" data-v="tabela" style="border-radius:0;' +
            'border-left:1px solid var(--linha)">' + Icone.lista + '</button>' +
        '</div>' : '') +
        '<span class="empurra t3" data-contador></span>' +
      '</div>';

    $('[data-busca]', el).oninput = e => this.busca(e.target.value);
    $$('[data-v]', el).forEach(b => {
      b.onclick = () => { this.trocaVisao(b.dataset.v); this._pintaVisao(el); };
    });
    this._pintaVisao(el);

    document.addEventListener('grid-render', ev => {
      if (ev.detail.grid !== this) return;
      const c = $('[data-contador]', el);
      if (c) c.textContent = ev.detail.exibidos + ' de ' + ev.detail.total;
    });
    return this;
  }

  _pintaVisao(el){
    $$('[data-v]', el).forEach(b => {
      const on = b.dataset.v === this.visao;
      b.style.background = on ? 'var(--marca-tinta)' : 'transparent';
      b.style.color = on ? '#fff' : 'var(--txt-2)';
    });
  }
}
