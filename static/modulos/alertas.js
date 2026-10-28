/* Modulo: alertas.
   Lista o que precisa de atencao. Cada alerta traz um caminho para resolver -
   avisar sem dizer o que fazer so gera ansiedade. */

let DADOS = [], RESUMO = {}, SITUACAO = 'abertos';

const err = m => { const e = $('#erro'); e.textContent = m || '';
  e.classList.toggle('on', !!m); };

/* para onde ir para resolver cada tipo */
const CAMINHO = {
  cert_vencido:     ['Ver certificados', '/escritorio/certificados'],
  cert_vencendo:    ['Ver certificados', '/escritorio/certificados'],
  sem_certificado:  ['Ver certificados', '/escritorio/certificados'],
  sync_parada:      ['Ver empresas', '/painel'],
  consumo_indevido: ['Ver empresas', '/painel'],
  sem_xml:          ['Ver empresas', '/painel'],
  nfse_rejeitada:   ['Ver notas', '/e/notas'],
};

const quando = d => {
  if (!d) return '';
  const min = Math.floor((Date.now() - new Date(d)) / 60000);
  if (min < 1) return 'agora';
  if (min < 60) return 'há ' + min + ' min';
  if (min < 1440) return 'há ' + Math.floor(min / 60) + 'h';
  return 'há ' + Math.floor(min / 1440) + ' dia(s)';
};

function pintaKpis(){
  const r = RESUMO || {};
  const cartao = (id, rot, val, risco) =>
    '<button class="kpi' + (SITUACAO === id ? ' on' : '') +
      (risco ? ' risco' : '') + '" data-kpi="' + id + '">' +
      '<div class="kn">' + (val || 0) + '</div>' +
      '<div class="kr">' + rot + '</div></button>';

  $('#kpis').innerHTML =
    cartao('abertos', 'Em aberto', (r.criticos || 0) + (r.avisos || 0)) +
    cartao('criticos', 'Críticos', r.criticos, r.criticos > 0) +
    cartao('avisos', 'Avisos', r.avisos, r.avisos > 0) +
    cartao('resolvidos', 'Resolvidos (24h)', r.resolvidos_24h);

  $$('[data-kpi]').forEach(b => b.onclick = () => {
    SITUACAO = b.dataset.kpi;
    carrega();
  });
}

function pinta(){
  let l = DADOS;
  if (SITUACAO === 'criticos') l = l.filter(a => a.nivel === 'erro' && !a.resolvido_em);
  if (SITUACAO === 'avisos')   l = l.filter(a => a.nivel !== 'erro' && !a.resolvido_em);

  if (!l.length){
    $('#lista').innerHTML = '<div class="painel"><div class="vazio-ok">' +
      '<div class="ic">' + Icone.visto + '</div>' +
      '<h3 style="margin:0 0 6px">Nada pendente</h3>' +
      '<p class="t3">Nenhum ponto de atenção nas empresas.</p></div></div>';
    return;
  }

  $('#lista').innerHTML = '<div class="lista">' + l.map(a => {
    const resolvido = !!a.resolvido_em;
    const cam = CAMINHO[a.tipo];
    return '<div class="item ' + (resolvido ? 'feito' : a.nivel) + '">' +
      '<div class="txt">' +
        '<h3>' + Fmt.escapa(a.titulo) + '</h3>' +
        (a.detalhe ? '<p>' + Fmt.escapa(a.detalhe) + '</p>' : '') +
        '<div class="meta">' +
          '<span>' + quando(a.criado_em) + '</span>' +
          (a.empresa ? '<span>' + Fmt.escapa(a.empresa) + '</span>' : '') +
          (resolvido
            ? '<span style="color:var(--ok)">Resolvido ' +
              quando(a.resolvido_em) + '</span>'
            : (a.lido_em ? '<span>Lido por ' +
                Fmt.escapa(a.lido_por_nome || '') + '</span>' : '')) +
        '</div>' +
      '</div>' +
      (resolvido ? '' :
      '<div class="acoes">' +
        (cam ? '<a class="btn btn-2 btn-sm" href="' + cam[1] + '">' +
               cam[0] + '</a>' : '') +
        (a.lido_em ? '' : '<button class="btn btn-3 btn-sm" data-lido="' +
          a.id + '">Marcar como lido</button>') +
      '</div>') +
    '</div>';
  }).join('') + '</div>';

  $$('[data-lido]').forEach(b => b.onclick = async () => {
    try {
      await api.post('/api/alertas/' + b.dataset.lido + '/lido', {});
      await carrega();
    } catch(e){ toast(e.message); }
  });
}

async function carrega(){
  const s = (SITUACAO === 'resolvidos') ? 'resolvidos' : 'abertos';
  const d = await api.get('/api/alertas?situacao=' + s);
  DADOS = d.alertas || [];
  RESUMO = d.resumo || {};
  pintaKpis();
  pinta();
}

(async () => {
  await Shell.monta({});
  $('#verificar').innerHTML = Icone.sync + 'Verificar agora';
  $('#verificar').onclick = async () => {
    const b = $('#verificar');
    b.disabled = true; b.innerHTML = Icone.sync + 'Verificando…';
    try {
      const r = await api.post('/api/alertas/verificar', {});
      toast(r.novos || r.resolvidos
        ? r.novos + ' novo(s), ' + r.resolvidos + ' resolvido(s).'
        : 'Nada mudou.');
      await carrega();
    } catch(e){ toast(e.message); }
    finally { b.disabled = false; b.innerHTML = Icone.sync + 'Verificar agora'; }
  };
  try { await carrega(); } catch(e){ err(e.message); }
})();
