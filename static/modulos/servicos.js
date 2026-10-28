/* Modulo: cadastro de servicos para emissao de NFS-e.
   O usuario escolhe a ATIVIDADE oficial do municipio (lista publicada pela
   prefeitura, ja filtrada pelos CNAEs da empresa) e o sistema preenche
   codigo de tributacao, item da LC 116 e aliquota. */

const EMP = Sessao.empresaId;
let SERVICOS = [], ATIVIDADES = {compativeis: [], outras: []}, EDITANDO = null;

const err = m => { const e = $('#erro'); e.textContent = m || '';
  e.classList.toggle('on', !!m); };

const estrela = on => '<svg width="16" height="16" viewBox="0 0 24 24" ' +
  'fill="' + (on ? 'currentColor' : 'none') + '" stroke="currentColor" ' +
  'stroke-width="2" stroke-linejoin="round"><path d="M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.9' +
  'L12 17.8 5.8 21.1 7 14.2l-5-4.9 6.9-1z"/></svg>';

const pct = v => v == null ? '—'
  : Number(v).toFixed(2).replace('.', ',') + '%';

/* so emite se tiver a classificacao completa */
const completo = s => !!(s.item_lista_servico && s.codigo_tributacao &&
  s.cind_op && s.cclass_trib);

function pinta(){
  if (!SERVICOS.length){
    $('#lista').innerHTML = '<div class="painel"><div class="vazio">' +
      '<p>Nenhum serviço cadastrado ainda.</p>' +
      '<p class="t3">Cadastre o primeiro para poder emitir NFS-e.</p></div></div>';
    return;
  }
  $('#lista').innerHTML = '<div class="cartoes">' + SERVICOS.map(s => {
    const falta = !completo(s);
    return '<div class="cartao' + (falta ? ' incompleto' : '') + '">' +
      '<div class="topo">' +
        '<div style="min-width:0">' +
          '<h3>' + Fmt.escapa(s.apelido) + '</h3>' +
          (falta ? '<span class="chip chip-aviso" style="margin-top:6px">' +
             'Classificação incompleta</span>' : '') +
        '</div>' +
        '<button class="estrela' + (s.favorito ? ' on' : '') + '" data-fav="' + s.id +
          '" title="' + (s.favorito ? 'Remover dos favoritos' : 'Marcar como favorito') +
          '">' + estrela(s.favorito) + '</button>' +
      '</div>' +
      '<div class="desc">' + Fmt.escapa(s.descricao || '') + '</div>' +
      '<div class="meta">' +
        '<div><div class="r">Item LC 116</div>' +
          '<div class="v">' + Fmt.escapa(s.item_lista_servico || '—') + '</div></div>' +
        '<div><div class="r">Cód. tributação</div>' +
          '<div class="v">' + Fmt.escapa(s.codigo_tributacao || '—') + '</div></div>' +
        '<div><div class="r">Alíquota</div>' +
          '<div class="v">' + pct(s.aliquota_iss) + '</div></div>' +
        '<div><div class="r">Valor sugerido</div>' +
          '<div class="v">' + (s.valor_padrao != null
            ? Fmt.moeda(s.valor_padrao) : '—') + '</div></div>' +
      '</div>' +
      '<div class="acoes">' +
        '<button class="btn btn-3 btn-sm" data-rm="' + s.id + '">Excluir</button>' +
        '<button class="btn btn-2 btn-sm" data-ed="' + s.id + '">Editar</button>' +
      '</div>' +
    '</div>';
  }).join('') + '</div>';

  $$('[data-ed]').forEach(b => b.onclick = () =>
    abreForm(SERVICOS.find(s => s.id == b.dataset.ed)));
  $$('[data-rm]').forEach(b => b.onclick = () => confirmaExclusao(b.dataset.rm));
  $$('[data-fav]').forEach(b => b.onclick = () => alternaFavorito(b.dataset.fav));
}

async function alternaFavorito(id){
  const s = SERVICOS.find(x => x.id == id);
  try {
    await api.put('/api/nfse/servicos/' + id, {...s, empresa_id: EMP,
      favorito: !s.favorito});
    await carrega();
  } catch(e){ toast.erro(e.message); }
}

function confirmaExclusao(id){
  const s = SERVICOS.find(x => x.id == id);
  Modal.cria({
    id:'m-rm', titulo:'Excluir serviço',
    corpo:'<p>Remover <b>' + Fmt.escapa(s.apelido) + '</b> da lista de serviços?</p>' +
      '<p class="t3" style="margin-top:var(--e-3)">As notas já emitidas com esse ' +
      'serviço não são afetadas.</p>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Excluir', cls:'btn-perigo', fn: async () => {
        try {
          await api.del('/api/nfse/servicos/' + id + '?empresa_id=' + EMP);
          Modal.fecha('m-rm'); toast.ok('Serviço excluído.'); await carrega();
        } catch(e){ toast.erro(e.message); }
      }},
    ],
  });
  Modal.abre('m-rm');
}

/* ---------------- formulario ---------------- */
function opcoesAtividade(selecionado){
  const linha = a => '<option value="' + a.codigo + '"' +
    (a.codigo === selecionado ? ' selected' : '') + '>' +
    a.codigo + ' — ' + Fmt.escapa((a.descricao || '').slice(0, 78)) +
    ' (' + pct(a.aliquota) + ')</option>';

  let h = '<option value="">Selecione a atividade…</option>';
  if (ATIVIDADES.compativeis.length){
    h += '<optgroup label="Atividades do CNPJ desta empresa">' +
      ATIVIDADES.compativeis.map(linha).join('') + '</optgroup>';
  }
  if (ATIVIDADES.outras.length){
    h += '<optgroup label="Outras atividades do município (' +
      ATIVIDADES.outras.length + ')">' +
      ATIVIDADES.outras.slice(0, 400).map(linha).join('') + '</optgroup>';
  }
  return h;
}

function abreForm(s){
  EDITANDO = s || null;
  const v = s || {};

  Modal.cria({
    id:'m-srv',
    titulo: s ? 'Editar serviço' : 'Novo serviço',
    corpo:
      '<div class="campo-grupo">' +
        '<label class="rotulo">Apelido do serviço</label>' +
        '<input class="campo" id="f-apelido" maxlength="60" ' +
          'placeholder="Ex.: Licenciamento mensal" value="' +
          Fmt.escapa(v.apelido || '') + '">' +
        '<div class="dica">Nome curto, só para você identificar na hora de emitir.</div>' +
      '</div>' +
      '<div class="campo-grupo">' +
        '<label class="rotulo">Atividade (lista oficial da prefeitura)</label>' +
        '<select class="campo" id="f-atividade">' + opcoesAtividade(v.codigo_tributacao) +
        '</select>' +
        '<div class="dica">A lista vem da prefeitura. As primeiras são as ' +
          'atividades do CNPJ desta empresa — o item da LC 116 e a alíquota são ' +
          'preenchidos automaticamente.</div>' +
        '<div id="box-ativ"></div>' +
      '</div>' +
      '<div class="campo-grupo">' +
        '<label class="rotulo">Descrição que sai na nota</label>' +
        '<textarea class="campo" id="f-descricao" maxlength="2000">' +
          Fmt.escapa(v.descricao || '') + '</textarea>' +
      '</div>' +
      '<div class="grade3">' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Valor sugerido (R$)</label>' +
          '<input class="campo" id="f-valor" type="number" step="0.01" min="0" value="' +
            (v.valor_padrao != null ? Number(v.valor_padrao).toFixed(2) : '') + '">' +
          '<div class="dica">Opcional. Pode ser alterado em cada nota.</div>' +
        '</div>' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">ISS retido pelo tomador</label>' +
          '<select class="campo" id="f-retido">' +
            '<option value="0"' + (!v.iss_retido ? ' selected' : '') + '>Não</option>' +
            '<option value="1"' + (v.iss_retido ? ' selected' : '') + '>Sim</option>' +
          '</select>' +
        '</div>' +
        '<div class="campo-grupo">' +
          '<label class="rotulo">Alíquota ISS</label>' +
          '<input class="campo" id="f-aliq" readonly ' +
            'style="background:var(--sup-2);color:var(--txt-2)" value="' +
            (v.aliquota_iss != null ? pct(v.aliquota_iss) : '—') + '">' +
          '<div class="dica">Definida pela prefeitura.</div>' +
        '</div>' +
      '</div>' +
      '<input type="hidden" id="f-item"    value="' + Fmt.escapa(v.item_lista_servico || '') + '">' +
      '<input type="hidden" id="f-codtrib" value="' + Fmt.escapa(v.codigo_tributacao || '') + '">' +
      '<input type="hidden" id="f-aliqnum" value="' + (v.aliquota_iss != null ? v.aliquota_iss : '') + '">' +
      '<input type="hidden" id="f-nbs"     value="' + Fmt.escapa(v.codigo_nbs || '') + '">' +
      '<input type="hidden" id="f-cindop"  value="' + Fmt.escapa(v.cind_op || '') + '">' +
      '<input type="hidden" id="f-cclass"  value="' + Fmt.escapa(v.cclass_trib || '') + '">' +
      '<div class="aviso aviso-erro" id="f-erro"></div>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Salvar', cls:'btn-1', id:'b-salvar', fn: salvar},
    ],
  });

  $('#f-atividade').onchange = () => escolheuAtividade($('#f-atividade').value);
  if (v.codigo_tributacao) escolheuAtividade(v.codigo_tributacao, true);
  Modal.abre('m-srv');
  setTimeout(() => $('#f-apelido').focus(), 60);
}

/* preenche item LC116 + aliquota da lista oficial e busca a classificacao IBS/CBS */
async function escolheuAtividade(codigo, manterDescricao){
  const box = $('#box-ativ');
  const todas = ATIVIDADES.compativeis.concat(ATIVIDADES.outras);
  const a = todas.find(x => x.codigo === codigo);
  if (!a){
    box.innerHTML = '';
    ['f-item','f-codtrib','f-aliqnum','f-nbs','f-cindop','f-cclass']
      .forEach(i => $('#' + i).value = '');
    $('#f-aliq').value = '—';
    return;
  }

  $('#f-codtrib').value = a.codigo;
  $('#f-item').value    = a.item_lista_servico || '';
  $('#f-aliqnum').value = a.aliquota != null ? a.aliquota : '';
  $('#f-aliq').value    = pct(a.aliquota);
  if (!manterDescricao && !$('#f-descricao').value.trim())
    $('#f-descricao').value = a.descricao || '';

  box.innerHTML = '<div class="sugestao"><div class="tit">' + Icone.escudo +
    'Preenchido pela lista da prefeitura</div><div class="par">' +
    '<div><span class="t3">Item LC 116</span><b>' +
      Fmt.escapa(a.item_lista_servico || '—') + '</b></div>' +
    '<div><span class="t3">Alíquota ISS</span><b>' + pct(a.aliquota) + '</b></div>' +
    '<div><span class="t3">Código de tributação</span><b>' +
      Fmt.escapa(a.codigo) + '</b></div>' +
    '</div><div class="dica" style="margin-top:8px">Carregando classificação ' +
    'IBS/CBS…</div></div>';

  if (!a.item_lista_servico) return;
  try {
    const d = await api.get('/api/nfse/sugestao?item=' +
      encodeURIComponent(a.item_lista_servico));
    const c = (d.classificacao || [])[0];
    const nbs = (d.nbs || [])[0];
    if (nbs)  $('#f-nbs').value    = nbs.codigo_nbs;
    if (c){ $('#f-cindop').value = c.cind_op || '';
            $('#f-cclass').value = c.cclass_trib || ''; }

    box.querySelector('.dica').outerHTML = c
      ? '<div class="par" style="margin-top:8px;padding-top:8px;' +
        'border-top:1px solid var(--linha)">' +
        '<div><span class="t3">NBS</span><b>' +
          Fmt.escapa(nbs ? nbs.codigo_nbs : '—') + '</b></div>' +
        '<div><span class="t3">Cód. operação</span><b>' +
          Fmt.escapa(c.cind_op || '—') + '</b></div>' +
        '<div><span class="t3">Class. tributária</span><b>' +
          Fmt.escapa(c.cclass_trib || '—') + '</b></div>' +
        '</div>'
      : '<div class="dica" style="margin-top:8px">Sem classificação IBS/CBS ' +
        'mapeada para este item.</div>';
  } catch(e){
    const d = box.querySelector('.dica');
    if (d) d.textContent = 'Não foi possível carregar a classificação IBS/CBS.';
  }
}

async function salvar(){
  const fe = $('#f-erro');
  const mostra = m => { fe.textContent = m; fe.classList.add('on'); };
  fe.classList.remove('on');

  const apelido = $('#f-apelido').value.trim();
  const descricao = $('#f-descricao').value.trim();
  if (!apelido)   return mostra('Informe o apelido do serviço.');
  if (!$('#f-atividade').value) return mostra('Selecione a atividade.');
  if (!descricao) return mostra('Informe a descrição que sai na nota.');

  const aliq = $('#f-aliqnum').value;
  const valor = $('#f-valor').value;
  const corpo = {
    empresa_id: EMP, apelido, descricao,
    item_lista_servico: $('#f-item').value || null,
    codigo_tributacao:  $('#f-codtrib').value || null,
    codigo_nbs:         $('#f-nbs').value || null,
    cind_op:            $('#f-cindop').value || null,
    cclass_trib:        $('#f-cclass').value || null,
    aliquota_iss: aliq === '' ? null : Number(aliq) / 100,
    valor_padrao: valor === '' ? null : Number(valor),
    iss_retido: $('#f-retido').value === '1',
    favorito: EDITANDO ? !!EDITANDO.favorito : false,
  };

  const b = $('#b-salvar'); b.disabled = true;
  try {
    if (EDITANDO) await api.put('/api/nfse/servicos/' + EDITANDO.id, corpo);
    else await api.post('/api/nfse/servicos', corpo);
    Modal.fecha('m-srv');
    toast.ok(EDITANDO ? 'Serviço atualizado.' : 'Serviço cadastrado.');
    await carrega();
  } catch(e){ mostra(e.message); }
  finally { b.disabled = false; }
}

async function carrega(){
  SERVICOS = await api.get('/api/nfse/servicos?empresa_id=' + EMP);
  pinta();
}

(async () => {
  await Shell.monta(EMP ? {empresa: EMP} : {});
  $('#novo').innerHTML = Icone.mais + 'Novo serviço';
  $('#novo').onclick = () => abreForm(null);
  try {
    ATIVIDADES = await api.get('/api/nfse/atividades?empresa_id=' + EMP);
    if (ATIVIDADES.aviso) err(ATIVIDADES.aviso);
    await carrega();
  } catch(e){ err(e.message); }
})();
