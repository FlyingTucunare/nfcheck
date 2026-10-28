/* Modulo: cadastro de tomadores (clientes que recebem as NFS-e).
   O cadastro comeca pelo CNPJ: o sistema busca na Receita e preenche tudo. */

const EMP = Sessao.empresaId;
let TOMADORES = [], NOTAS = {}, EDITANDO = null, GRID = null, FILTRO = null;

const err = m => { const e = $('#erro'); e.textContent = m || '';
  e.classList.toggle('on', !!m); };

const soDigito = v => (v || '').replace(/\D/g, '');

function docFmt(v){
  const n = soDigito(v);
  if (n.length === 14)
    return n.slice(0,2)+'.'+n.slice(2,5)+'.'+n.slice(5,8)+'/'+n.slice(8,12)+'-'+n.slice(12);
  if (n.length === 11)
    return n.slice(0,3)+'.'+n.slice(3,6)+'.'+n.slice(6,9)+'-'+n.slice(9);
  return v || '';
}
const cepFmt = v => {
  const n = soDigito(v);
  return n.length === 8 ? n.slice(0,5)+'-'+n.slice(5) : (v || '');
};

/* endereco completo = o que a prefeitura exige para nao rejeitar */
const enderecoOk = t => !!(t.logradouro && t.bairro &&
  soDigito(t.cep).length === 8 && soDigito(t.municipio_ibge).length === 7 && t.uf);

/* ---------------- KPIs ---------------- */
function pintaKpis(){
  const total = TOMADORES.length;
  const semEmail = TOMADORES.filter(t => !t.email).length;
  const semEnd = TOMADORES.filter(t => !enderecoOk(t)).length;
  const comNota = TOMADORES.filter(t => (NOTAS[t.id] || 0) > 0).length;

  const cartao = (id, rot, val, risco) =>
    '<button class="kpi' + (FILTRO === id ? ' on' : '') +
      (risco ? ' risco' : '') + '" data-kpi="' + id + '">' +
      '<div class="kn">' + val + '</div>' +
      '<div class="kr">' + rot + '</div></button>';

  $('#kpis').innerHTML =
    cartao('todos', 'Tomadores', total) +
    cartao('comnota', 'Já receberam nota', comNota) +
    cartao('sememail', 'Sem e-mail', semEmail, semEmail > 0) +
    cartao('semend', 'Endereço incompleto', semEnd, semEnd > 0);

  $$('[data-kpi]').forEach(b => b.onclick = () => {
    FILTRO = (FILTRO === b.dataset.kpi || b.dataset.kpi === 'todos')
      ? null : b.dataset.kpi;
    aplicaFiltro();
    pintaKpis();
  });
}

function aplicaFiltro(){
  const f = {
    sememail: t => !t.email,
    semend:   t => !enderecoOk(t),
    comnota:  t => (NOTAS[t.id] || 0) > 0,
  }[FILTRO];
  GRID.filtra(f || null);
}

/* ---------------- grid ---------------- */
const COLUNAS = [
  {k:'razao_social', t:'Razão social', w:280,
   cel: t => '<b>' + Fmt.escapa(t.razao_social || '') + '</b>' +
     (t.nome_fantasia ? '<div class="t3">' + Fmt.escapa(t.nome_fantasia) + '</div>' : '')},
  {k:'documento', t:'CNPJ / CPF', w:150, num:true, cel: t => docFmt(t.documento)},
  {k:'municipio_nome', t:'Município', w:170,
   cel: t => (t.municipio_nome ? Fmt.escapa(t.municipio_nome) : '—') +
     (t.uf ? ' <span class="t3">' + Fmt.escapa(t.uf) + '</span>' : '') +
     (enderecoOk(t) ? '' :
       '<div><span class="chip chip-aviso">Endereço incompleto</span></div>')},
  {k:'email', t:'E-mail', w:210,
   cel: t => t.email ? Fmt.escapa(t.email)
     : '<span class="chip chip-aviso">Sem e-mail</span>'},
  {k:'notas', t:'Notas', w:80, num:true,
   cel: t => (NOTAS[t.id] || 0) || '—'},
  {k:'acoes', t:'', w:52, cel: t =>
    '<button class="btn btn-3 btn-icone btn-sm" data-parar data-acoes="' + t.id +
      '" aria-label="Ações">' + Icone.pontos + '</button>'},
];

/* ---------------- exclusao (soft delete) ---------------- */
function confirmaExclusao(id){
  const t = TOMADORES.find(x => x.id == id);
  const n = NOTAS[t.id] || 0;
  Modal.cria({
    id:'m-rm', titulo:'Desativar tomador',
    corpo:'<p>Desativar <b>' + Fmt.escapa(t.razao_social) + '</b>?</p>' +
      '<p class="t3" style="margin-top:var(--e-3)">Ele deixa de aparecer na ' +
      'emissão, mas continua no histórico.' +
      (n ? ' Este tomador tem <b>' + n + '</b> nota(s) emitida(s), que não são ' +
        'afetadas.' : '') + '</p>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Desativar', cls:'btn-perigo', fn: async () => {
        try {
          await api.del('/api/nfse/tomadores/' + id + '?empresa_id=' + EMP);
          Modal.fecha('m-rm'); toast('Tomador desativado.'); await carrega();
        } catch(e){ toast(e.message); }
      }},
    ],
  });
  Modal.abre('m-rm');
}

/* ---------------- menu de acoes ---------------- */
function menuTomador(botao, t){
  const itens = [];
  if (Sessao.pode('emitir')){
    itens.push({txt:'Editar cadastro', icone:'lapis', fn:() => abreForm(t)});
    if (t.tipo_doc === 'cnpj')
      itens.push({txt:'Atualizar pela Receita', icone:'sync', fn:() => {
        abreForm(t);
        setTimeout(() => { const b = $('#b-receita'); if (b) b.click(); }, 300);
      }});
    itens.push({txt:'Emitir NFS-e', icone:'subir', fn:() => {
      sessionStorage.setItem('nfc_emitir_tomador', t.id);
      location.href = '/e/emissao';
    }});
    itens.push({sep:true});
    itens.push({txt:'Desativar', icone:'lixo', perigo:true,
      fn:() => confirmaExclusao(t.id)});
  } else {
    itens.push({txt:'Ver cadastro', icone:'lapis', fn:() => abreForm(t)});
  }
  Menu.abre(botao, itens);
}

/* ---------------- formulario ---------------- */
function abreForm(t){
  EDITANDO = t || null;
  const v = t || {};
  const novo = !t;

  Modal.cria({
    id:'m-tom',
    titulo: novo ? 'Novo tomador' : 'Editar tomador',
    corpo:
      (novo
        ? '<div class="busca-cnpj">' +
            '<div class="campo-grupo">' +
              '<label class="rotulo">CNPJ do tomador</label>' +
              '<input class="campo" id="f-busca-cnpj" maxlength="18" ' +
                'placeholder="00.000.000/0000-00" inputmode="numeric">' +
              '<div class="dica">Busca na Receita Federal e preenche o cadastro.</div>' +
            '</div>' +
            '<button class="btn btn-1" id="b-buscar">Buscar</button>' +
          '</div>'
        : '<div style="display:flex;justify-content:flex-end;margin-bottom:var(--e-3)">' +
          '<button class="btn btn-2 btn-sm" id="b-receita">Atualizar pela Receita</button>' +
          '</div>') +
      '<div class="grade2">' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Tipo de documento</label>' +
          '<select class="campo" id="f-tipo">' +
            '<option value="cnpj"' + (v.tipo_doc !== 'cpf' ? ' selected' : '') + '>CNPJ</option>' +
            '<option value="cpf"'  + (v.tipo_doc === 'cpf' ? ' selected' : '') + '>CPF</option>' +
          '</select>' +
        '</div>' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Número do documento</label>' +
          '<input class="campo" id="f-doc" maxlength="18" value="' +
            docFmt(v.documento) + '"' + (novo ? '' : ' readonly ' +
            'style="background:var(--sup-2);color:var(--txt-2)"') + '>' +
          (novo ? '' : '<div class="dica">O documento não pode ser alterado.</div>') +
        '</div>' +
      '</div>' +
      '<div class="campo-grupo">' +
        '<label class="rotulo">Razão social / Nome</label>' +
        '<input class="campo" id="f-razao" maxlength="150" value="' +
          Fmt.escapa(v.razao_social || '') + '">' +
      '</div>' +
      '<div class="grade2">' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Nome fantasia</label>' +
          '<input class="campo" id="f-fantasia" maxlength="60" value="' +
            Fmt.escapa(v.nome_fantasia || '') + '">' +
        '</div>' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Inscrição municipal</label>' +
          '<input class="campo" id="f-im" maxlength="15" value="' +
            Fmt.escapa(v.im || '') + '">' +
          '<div class="dica">Só se o tomador for inscrito no município.</div>' +
        '</div>' +
      '</div>' +
      '<div class="grade2">' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">E-mail</label>' +
          '<input class="campo" id="f-email" type="email" maxlength="80" value="' +
            Fmt.escapa(v.email || '') + '">' +
          '<div class="dica">Para onde a nota é enviada.</div>' +
        '</div>' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Telefone</label>' +
          '<input class="campo" id="f-tel" maxlength="20" value="' +
            Fmt.escapa(v.telefone || '') + '">' +
        '</div>' +
      '</div>' +
      '<div class="grade-cep">' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">CEP</label>' +
          '<input class="campo" id="f-cep" maxlength="9" value="' + cepFmt(v.cep) + '">' +
        '</div>' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Logradouro</label>' +
          '<input class="campo" id="f-log" maxlength="255" value="' +
            Fmt.escapa(v.logradouro || '') + '">' +
        '</div>' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Número</label>' +
          '<input class="campo" id="f-num" maxlength="60" value="' +
            Fmt.escapa(v.numero || '') + '">' +
        '</div>' +
      '</div>' +
      '<div class="grade2">' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Complemento</label>' +
          '<input class="campo" id="f-compl" maxlength="60" value="' +
            Fmt.escapa(v.complemento || '') + '">' +
        '</div>' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Bairro</label>' +
          '<input class="campo" id="f-bairro" maxlength="60" value="' +
            Fmt.escapa(v.bairro || '') + '">' +
        '</div>' +
      '</div>' +
      '<div class="grade3">' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Município</label>' +
          '<input class="campo" id="f-mun" maxlength="80" value="' +
            Fmt.escapa(v.municipio_nome || '') + '">' +
        '</div>' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Cód. IBGE</label>' +
          '<input class="campo" id="f-ibge" maxlength="7" value="' +
            Fmt.escapa(v.municipio_ibge || '') + '">' +
        '</div>' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">UF</label>' +
          '<input class="campo" id="f-uf" maxlength="2" value="' +
            Fmt.escapa(v.uf || '') + '">' +
        '</div>' +
      '</div>' +
      '<div class="aviso aviso-erro" id="f-erro"></div>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Salvar', cls:'btn-1', id:'b-salvar', fn: salvar},
    ],
  });

  if (novo){
    const inp = $('#f-busca-cnpj');
    $('#b-buscar').onclick = () => buscaReceita(soDigito(inp.value), '#b-buscar');
    inp.onkeydown = e => {
      if (e.key === 'Enter'){ e.preventDefault();
        buscaReceita(soDigito(inp.value), '#b-buscar'); } };
    setTimeout(() => inp.focus(), 60);
  } else {
    $('#b-receita').onclick = () =>
      buscaReceita(soDigito(v.documento), '#b-receita');
    setTimeout(() => $('#f-email').focus(), 60);
  }
  Modal.abre('m-tom');
}

async function buscaReceita(cnpj, botao){
  const fe = $('#f-erro'); fe.classList.remove('on');
  if (cnpj.length !== 14){
    fe.textContent = 'Informe um CNPJ com 14 dígitos.'; fe.classList.add('on'); return;
  }
  const b = $(botao), txt = b.textContent;
  b.disabled = true; b.textContent = 'Buscando…';
  try {
    const d = await api.get('/api/nfse/tomadores/receita/' + cnpj);
    const põe = (id, val) => { if (val) $(id).value = val; };
    $('#f-tipo').value = 'cnpj';
    põe('#f-doc', docFmt(cnpj));
    põe('#f-razao', d.razao_social);
    põe('#f-fantasia', d.nome_fantasia);
    põe('#f-email', d.email);
    põe('#f-tel', d.telefone);
    põe('#f-cep', cepFmt(d.cep));
    põe('#f-log', d.logradouro);
    põe('#f-num', d.numero);
    põe('#f-compl', d.complemento);
    põe('#f-bairro', d.bairro);
    põe('#f-mun', d.municipio_nome || d.municipio);
    põe('#f-ibge', d.municipio_ibge);
    põe('#f-uf', d.uf);
    toast('Dados carregados da Receita.');
  } catch(e){
    fe.textContent = e.message; fe.classList.add('on');
  } finally { b.disabled = false; b.textContent = txt; }
}

async function salvar(){
  const fe = $('#f-erro');
  const mostra = m => { fe.textContent = m; fe.classList.add('on'); };
  fe.classList.remove('on');

  const tipo = $('#f-tipo').value;
  const doc = soDigito($('#f-doc').value);
  const razao = $('#f-razao').value.trim();
  if (tipo === 'cnpj' && doc.length !== 14) return mostra('CNPJ deve ter 14 dígitos.');
  if (tipo === 'cpf'  && doc.length !== 11) return mostra('CPF deve ter 11 dígitos.');
  if (!razao) return mostra('Informe a razão social ou o nome.');

  const cep = soDigito($('#f-cep').value);
  const ibge = soDigito($('#f-ibge').value);
  const uf = $('#f-uf').value.trim().toUpperCase();
  const log = $('#f-log').value.trim();

  /* endereco parcial e rejeitado pela prefeitura: ou vai completo, ou vazio */
  if (log || cep || ibge){
    if (!log)  return mostra('Informe o logradouro (ou limpe o endereço todo).');
    if (!$('#f-bairro').value.trim()) return mostra('Informe o bairro.');
    if (cep.length !== 8) return mostra('CEP deve ter 8 dígitos.');
    if (ibge.length !== 7) return mostra('Código IBGE do município deve ter 7 dígitos.');
    if (uf.length !== 2)  return mostra('Informe a UF com 2 letras.');
  }

  const corpo = {
    empresa_id: EMP, tipo_doc: tipo, documento: doc, razao_social: razao,
    nome_fantasia: $('#f-fantasia').value.trim() || null,
    im: $('#f-im').value.trim() || null,
    email: $('#f-email').value.trim() || null,
    telefone: $('#f-tel').value.trim() || null,
    logradouro: log || null,
    numero: $('#f-num').value.trim() || null,
    complemento: $('#f-compl').value.trim() || null,
    bairro: $('#f-bairro').value.trim() || null,
    municipio_ibge: ibge || null,
    municipio_nome: $('#f-mun').value.trim() || null,
    uf: uf || null, cep: cep || null,
  };

  const b = $('#b-salvar'); b.disabled = true;
  try {
    if (EDITANDO) await api.put('/api/nfse/tomadores/' + EDITANDO.id, corpo);
    else await api.post('/api/nfse/tomadores', corpo);
    Modal.fecha('m-tom');
    toast(EDITANDO ? 'Tomador atualizado.' : 'Tomador cadastrado.');
    await carrega();
  } catch(e){ mostra(e.message); }
  finally { b.disabled = false; }
}

async function carrega(){
  TOMADORES = await api.get('/api/nfse/tomadores?empresa_id=' + EMP);
  try {
    const d = await api.get('/api/nfse/notas?empresa_id=' + EMP);
    NOTAS = {};
    (d.notas || []).forEach(n => {
      if (n.tomador_id) NOTAS[n.tomador_id] = (NOTAS[n.tomador_id] || 0) + 1;
    });
  } catch(e){ NOTAS = {}; }
  GRID.dados(TOMADORES);
  aplicaFiltro();
  pintaKpis();
}

(async () => {
  await Shell.monta(EMP ? {empresa: EMP} : {});
  $('#novo').innerHTML = Icone.mais + 'Novo tomador';
  $('#novo').onclick = () => abreForm(null);

  GRID = new Grid({
    alvo:'#area', chave:'tomadores', colunas:COLUNAS, ordemInicial:'razao_social',
    busca: t => [t.razao_social, t.nome_fantasia, t.documento, t.municipio_nome, t.email],
    vazio: {titulo:'Nenhum tomador cadastrado',
            texto:'Cadastre o primeiro cliente para poder emitir NFS-e.'},
  });
  GRID.barra('#barra', {placeholder:'Buscar por nome, CNPJ, município ou e-mail...'});

  $('#area').addEventListener('click', ev => {
    const a = ev.target.closest('[data-acoes]');
    if (a){
      ev.stopPropagation();
      const t = TOMADORES.find(x => String(x.id) === a.dataset.acoes);
      if (t) menuTomador(a, t);
    }
  });

  try { await carrega(); } catch(e){ err(e.message); }
})();
