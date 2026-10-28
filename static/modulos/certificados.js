/* Modulo: panorama de certificados do escritorio.
   Uma linha por empresa - inclusive as SEM certificado, que sao o caso mais
   urgente: sem ele nao ha busca de documentos nem emissao de nota. */

let DADOS = [], GRID = null, FILTRO = null, ARQUIVO = null;

const err = m => { const e = $('#erro'); e.textContent = m || '';
  e.classList.toggle('on', !!m); };

/* faixas que definem cor e urgencia */
function faixa(e){
  if (!e.certificado_id) return 'sem';
  if (e.dias == null) return 'ok';
  if (e.dias < 0) return 'vencido';
  if (e.dias <= 30) return 'vencendo';
  return 'ok';
}

const CHIP = {
  sem:      ['chip-erro',   'Sem certificado'],
  vencido:  ['chip-erro',   'Vencido'],
  vencendo: ['chip-aviso',  'Vence em breve'],
  ok:       ['chip-ok',     'Válido'],
};

function pintaKpis(){
  const conta = f => DADOS.filter(e => faixa(e) === f).length;
  const cartao = (id, rot, val, risco) =>
    '<button class="kpi' + (FILTRO === id ? ' on' : '') +
      (risco ? ' risco' : '') + '" data-kpi="' + id + '">' +
      '<div class="kn">' + val + '</div><div class="kr">' + rot + '</div></button>';

  $('#kpis').innerHTML =
    cartao('todos', 'Empresas', DADOS.length) +
    cartao('ok', 'Válidos', conta('ok')) +
    cartao('vencendo', 'Vencem em 30 dias', conta('vencendo'), conta('vencendo') > 0) +
    cartao('vencido', 'Vencidos', conta('vencido'), conta('vencido') > 0) +
    cartao('sem', 'Sem certificado', conta('sem'), conta('sem') > 0);

  $$('[data-kpi]').forEach(b => b.onclick = () => {
    const k = b.dataset.kpi;
    FILTRO = (FILTRO === k || k === 'todos') ? null : k;
    GRID.filtra(FILTRO ? (e => faixa(e) === FILTRO) : null);
    pintaKpis();
  });
}

const COLUNAS = [
  {k:'razao_social', t:'Empresa', w:270,
   cel: e => '<b>' + Fmt.escapa(e.razao_social) + '</b>' +
     '<div class="t3 num">' + Fmt.cnpj(e.cnpj) + '</div>'},
  {k:'titular_cn', t:'Titular do certificado', w:230,
   cel: e => e.titular_cn
     ? Fmt.escapa(String(e.titular_cn).split(':')[0])
     : '<span class="t3">—</span>'},
  {k:'valido_ate', t:'Validade', w:130, num:true,
   cel: e => e.valido_ate ? Fmt.data(e.valido_ate) : '—'},
  {k:'dias', t:'Situação', w:170,
   cel: e => {
     const f = faixa(e), [cls, txt] = CHIP[f];
     const extra = (f === 'vencendo') ? ' (' + e.dias + ' dias)'
       : (f === 'vencido') ? ' há ' + Math.abs(e.dias) + ' dias' : '';
     return '<span class="chip ' + cls + '">' + txt + extra + '</span>';
   }},
  {k:'dfe_ligado', t:'Busca de DF-e', w:130,
   cel: e => e.dfe_ligado
     ? (e.certificado_id
        ? '<span class="chip chip-ok">Ligada</span>'
        : '<span class="chip chip-erro">Ligada sem certificado</span>')
     : '<span class="t3">Desligada</span>'},
  {k:'acoes', t:'Ações', w:80, cel: e =>
    '<button class="btn btn-3 btn-icone btn-sm" data-parar data-acoes="' +
      e.empresa_id + '" aria-label="Ações">' + Icone.pontos + '</button>'},
];

function menuCert(botao, e){
  const itens = [];
  if (Sessao.pode('cert_escrever'))
    itens.push({txt: e.certificado_id ? 'Substituir certificado'
                                      : 'Enviar certificado',
                icone:'subir', fn:() => modalEnvio(e)});
  if (e.historico > 0)
    itens.push({txt:'Histórico', icone:'relogio', fn:() => verHistorico(e)});
  itens.push({sep:true});
  itens.push({txt:'Abrir empresa', icone:'seta',
    fn:() => { Sessao.empresaId = e.empresa_id; location.href = '/empresa'; }});
  Menu.abre(botao, itens);
}

/* ---------------- envio ---------------- */
function modalEnvio(e){
  ARQUIVO = null;
  Modal.cria({
    id:'m-cert',
    titulo:(e.certificado_id ? 'Substituir' : 'Enviar') + ' certificado',
    corpo:
      '<p class="t3" style="margin-bottom:var(--e-4);line-height:1.6">' +
        Fmt.escapa(e.razao_social) + '</p>' +
      (e.certificado_id
        ? '<div class="aviso aviso-atencao on" style="margin-bottom:var(--e-4)">' +
          'O certificado atual será substituído. Ele continua no histórico, ' +
          'mas deixa de ser usado.</div>' : '') +
      '<div class="solta" id="c-solta">' + Icone.subir +
        '<b id="c-nome">Escolha o arquivo .pfx ou .p12</b>' +
        '<span class="t3">O arquivo não sai do servidor.</span>' +
      '</div>' +
      '<input type="file" id="c-arq" accept=".pfx,.p12" style="display:none">' +
      '<div class="campo-grupo" style="margin-top:var(--e-4)">' +
        '<label class="rotulo">Senha do certificado</label>' +
        '<input class="campo" type="password" id="c-senha" ' +
          'autocomplete="off"></div>' +
      '<div id="c-previa"></div>' +
      '<div class="aviso aviso-erro" id="c-erro"></div>',
    acoes:[
      {txt:'Cancelar', cls:'btn-2'},
      {txt:'Enviar', cls:'btn-1', id:'b-cert', fn:() => enviar(e)},
    ],
  });

  $('#c-solta').onclick = () => $('#c-arq').click();
  $('#c-arq').onchange = ev => {
    ARQUIVO = ev.target.files[0] || null;
    $('#c-nome').textContent = ARQUIVO ? ARQUIVO.name
                                       : 'Escolha o arquivo .pfx ou .p12';
    if (ARQUIVO) espiar();
  };
  Modal.abre('m-cert');
}

/* le a parte publica do .pfx (sem senha) so para conferir de quem e */
async function espiar(){
  const fe = $('#c-erro'); fe.classList.remove('on');
  try {
    const fd = new FormData();
    fd.append('arquivo', ARQUIVO);
    const d = await api.post('/api/certificados/espiar', fd);
    $('#c-previa').innerHTML = '<div class="aviso aviso-ok on" ' +
      'style="margin-top:var(--e-3)">' +
      Fmt.escapa(String(d.titular_cn || '').split(':')[0]) +
      (d.valido_ate ? ' · válido até ' + Fmt.data(d.valido_ate) : '') + '</div>';
    $('#c-senha').focus();
  } catch(e){ $('#c-previa').innerHTML = ''; }
}

async function enviar(e){
  const fe = $('#c-erro');
  const mostra = m => { fe.textContent = m; fe.classList.add('on'); };
  fe.classList.remove('on');
  if (!ARQUIVO) return mostra('Escolha o arquivo do certificado.');
  const senha = $('#c-senha').value;
  if (!senha) return mostra('Informe a senha do certificado.');

  const b = $('#b-cert'); b.disabled = true; b.textContent = 'Enviando…';
  try {
    const fd = new FormData();
    fd.append('empresa_id', e.empresa_id);
    fd.append('senha', senha);
    fd.append('arquivo', ARQUIVO);
    await api.post('/api/certificados', fd);
    Modal.fecha('m-cert');
    toast('Certificado enviado.');
    await carrega();
  } catch(er){ mostra(er.message); }
  finally { b.disabled = false; b.textContent = 'Enviar'; }
}

async function verHistorico(e){
  let lista = [];
  try { lista = await api.get('/api/certificados/historico/' + e.empresa_id); }
  catch(er){ return toast(er.message); }
  Modal.cria({
    id:'m-hist', titulo:'Histórico de certificados',
    corpo:'<p class="t3" style="margin-bottom:var(--e-4)">' +
      Fmt.escapa(e.razao_social) + '</p>' +
      '<div class="hist">' + lista.map(c =>
        '<div><span>' + Fmt.data(c.valido_de) + ' a ' + Fmt.data(c.valido_ate) +
        (c.ativo ? ' <span class="chip chip-ok">Em uso</span>' : '') + '</span>' +
        '<span class="t3">' + Fmt.escapa(c.enviado_por || '—') + '</span></div>'
      ).join('') + '</div>',
    acoes:[{txt:'Fechar', cls:'btn-2'}],
  });
  Modal.abre('m-hist');
}

async function carrega(){
  DADOS = await api.get('/api/certificados/panorama');
  GRID.dados(DADOS);
  if (FILTRO) GRID.filtra(e => faixa(e) === FILTRO);
  pintaKpis();
}

(async () => {
  await Shell.monta({});
  GRID = new Grid({
    alvo:'#area', chave:'certificados', colunas:COLUNAS, ordemInicial:'dias',
    busca: e => [e.razao_social, e.cnpj, e.titular_cn, e.municipio_nome],
    vazio: {titulo:'Nenhuma empresa', texto:'Cadastre empresas para acompanhar os certificados.'},
  });
  GRID.barra('#barra', {placeholder:'Buscar por empresa, CNPJ ou titular...'});
  $('#area').addEventListener('click', ev => {
    const a = ev.target.closest('[data-acoes]');
    if (a){
      ev.stopPropagation();
      const e = DADOS.find(x => String(x.empresa_id) === a.dataset.acoes);
      if (e) menuCert(a, e);
    }
  });
  try { await carrega(); } catch(e){ err(e.message); }
})();
