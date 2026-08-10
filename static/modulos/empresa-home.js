/* Modulo: home da empresa */

const EMP_ID = Sessao.empresaId;
if (!EMP_ID) location.href = '/painel';

const fi = (rot, val, cls, rota) =>
  '<' + (rota ? 'a href="' + rota + '"' : 'div') + ' class="fi' + (cls ? ' ' + cls : '') +
    (rota ? ' cli' : '') + '">' +
    '<div class="fv">' + val + '</div><div class="fr">' + rot + '</div>' +
  '</' + (rota ? 'a' : 'div') + '>';

const TIPO = {
  nfeProc:'NF-e', NFe:'NF-e', resNFe:'NF-e (resumo)',
  cteProc:'CT-e', CTe:'CT-e', resCTe:'CT-e (resumo)',
  procEventoNFe:'Evento', resEvento:'Evento', procEventoCTe:'Evento',
};

function pintaAlertas(l){
  $('#alertas').innerHTML = (l || []).map(a =>
    '<div class="al-item al-' + a.nivel + '">' +
      (a.nivel === 'erro' ? Icone.alerta : Icone.alerta) +
      '<span>' + Fmt.escapa(a.txt) + '</span></div>').join('');
}

function pintaFaixa(d){
  const c = d.certificado;
  const certVal = !c ? '—' : c.dias < 0 ? 'Vencido' : c.dias + 'd';
  const certCls = !c ? '' : c.dias < 0 ? 'er' : c.dias <= 30 ? 'al' : '';
  const sync = d.cursores.map(x => x.ultima_sync).filter(Boolean).sort().pop();
  $('#faixa').innerHTML = '<div class="faixa">' +
    fi('Docs no mês', Fmt.numero(d.mes.docs), '', '/e/dfe') +
    fi('Valor no mês', Fmt.moeda(d.mes.valor)) +
    fi('A manifestar', Fmt.numero(d.mes.pendentes),
       d.mes.pendentes > 0 ? 'al' : '', '/e/dfe') +
    fi('Certificado', certVal, certCls, '/e/certificado') +
    fi('Total de docs', Fmt.numero(d.total_docs)) +
    fi('Última sinc.', sync ? Fmt.relativo(sync) : '—') +
  '</div>';
}

function pintaDocs(l){
  if (!l.length) {
    $('#docs').innerHTML = '<div class="painel"><div class="vazio">' +
      '<h4>Nenhum documento ainda</h4>' +
      '<p>Os documentos aparecem aqui quando a sincronização rodar ' +
      'ou após uma importação em lote.</p>' +
      (Sessao.pode('importar') ?
        '<a class="btn btn-2" href="/e/importacao">Importar XML</a>' : '') +
      '</div></div>';
    return;
  }
  $('#docs').innerHTML = '<div class="painel"><div class="rolagem">' +
    '<table class="dados"><thead><tr>' +
      '<th style="width:80px">Tipo</th><th>Emitente</th>' +
      '<th style="width:100px">Emissão</th><th style="width:110px">Valor</th>' +
      '<th style="width:105px">Situação</th></tr></thead><tbody>' +
    l.map(x => '<tr>' +
      '<td>' + (TIPO[x.tipo] || x.tipo) + '</td>' +
      '<td title="' + Fmt.escapa(x.emitente_nome || '') + '">' +
        Fmt.escapa(x.emitente_nome || '—') + '</td>' +
      '<td class="num">' + Fmt.data(x.emissao) + '</td>' +
      '<td class="num">' + Fmt.moeda(x.valor) + '</td>' +
      '<td>' + (x.manifestacao
        ? '<span class="chip chip-ok"><span class="ponto"></span>Manifestado</span>'
        : '<span class="chip chip-aviso"><span class="ponto"></span>Pendente</span>') +
      '</td></tr>').join('') +
    '</tbody></table></div></div>';
}

function pintaFicha(d){
  const e = d.empresa;
  const end = [e.logradouro, e.numero, e.complemento, e.bairro]
    .filter(Boolean).join(', ');
  const linhas = [
    ['Razão social', e.razao_social],
    ['CNPJ', Fmt.cnpj(e.cnpj)],
    ['Situação', e.situacao_cadastral],
    ['Abertura', Fmt.data(e.abertura)],
    ['Regime', e.regime_tributario],
    ['Porte', e.porte],
    ['Endereço', end + (e.cep ? ' · ' + Fmt.cep(e.cep) : '')],
    ['Município', (e.municipio_nome || '') + (e.uf ? '/' + e.uf : '')],
    ['Atividade', e.cnae_principal_desc],
    ['IE', e.ie], ['IM', e.im],
    ['Telefone', e.telefone1], ['E-mail', e.email],
    ['Capital', Fmt.moeda(e.capital_social)],
    ['Sócios', (d.socios || []).map(s => s.nome).join(' · ')],
    ['Observações', e.observacoes],
  ].filter(([, v]) => v && v !== '—' && String(v).trim());
  $('#ficha').innerHTML = linhas.map(([k, v]) =>
    '<dt>' + k + '</dt><dd>' + Fmt.escapa(v) + '</dd>').join('');
}

(async () => {
  await Shell.monta({empresa: EMP_ID});
  Shell.menuModulos('#modulos', EMP_ID);
  try {
    const d = await api.get('/api/empresas/' + EMP_ID + '/resumo');
    document.title = 'NFCheck — ' + (d.empresa.nome_fantasia || d.empresa.razao_social);
    pintaAlertas(d.alertas);
    pintaFaixa(d);
    pintaDocs(d.ultimos);
    pintaFicha(d);
  } catch(e) { toast.erro(e.message); }
})();
