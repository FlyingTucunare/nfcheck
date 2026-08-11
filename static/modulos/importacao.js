/* Modulo: importacao em lote */

const EMP_CTX = Sessao.empresaId;
const err = m => { const e = $('#erro'); e.textContent = m || '';
  e.classList.toggle('on', !!m); };
const tam = b => b < 1024 ? b + ' B'
  : b < 1048576 ? (b/1024).toFixed(0) + ' KB'
  : (b/1048576).toFixed(1) + ' MB';

function pintaZona(){
  $('#zona-txt').innerHTML = Icone.subir +
    '<b>Arraste os arquivos ou clique para escolher</b>' +
    '<span class="t3">ZIP com XML, XML avulsos ou PDF · até 200 MB</span>';
}

function pintaResultado(r){
  const seg = (r.duracao_ms / 1000).toFixed(1);
  const fora = Object.entries(r.fora_do_escopo || {});
  $('#resultado').innerHTML =
    '<div class="placar">' +
      '<div class="ok"><div class="pv">' + Fmt.numero(r.gravados) + '</div>' +
        '<div class="pr">Gravados</div></div>' +
      '<div><div class="pv">' + Fmt.numero(r.duplicados) + '</div>' +
        '<div class="pr">Já existiam</div></div>' +
      '<div class="al"><div class="pv">' + Fmt.numero(r.ignorados) + '</div>' +
        '<div class="pr">Ignorados</div></div>' +
      '<div><div class="pv">' + Fmt.numero(r.anexos) + '</div>' +
        '<div class="pr">PDF anexados</div></div>' +
      '<div class="' + (r.erros ? 'er' : '') + '"><div class="pv">' +
        Fmt.numero(r.erros) + '</div><div class="pr">Erros</div></div>' +
      '<div><div class="pv">' + seg + 's</div>' +
        '<div class="pr">Duração</div></div>' +
    '</div>' +
    (fora.length ?
    '<div class="painel" style="padding:var(--e-5);margin-bottom:var(--e-4)">' +
      '<h3 style="font-size:var(--t-base);margin-bottom:var(--e-3)">' +
        'Documentos de CNPJ não cadastrados</h3>' +
      '<p class="t3" style="margin:0 0 var(--e-3)">Cadastre estas empresas e ' +
        'importe de novo para aproveitá-los.</p>' +
      '<div class="colunas" style="flex-wrap:wrap;gap:6px">' +
        fora.sort((a,b) => b[1]-a[1]).slice(0,40).map(([c,n]) =>
          '<span class="chip chip-neutro">' + Fmt.cnpj(c) + ' · ' + n + '</span>')
          .join('') + '</div></div>' : '') +
    (r.falhas && r.falhas.length ?
    '<div class="painel" style="padding:var(--e-5)">' +
      '<h3 style="font-size:var(--t-base);margin-bottom:var(--e-3)">Falhas</h3>' +
      '<div class="rolagem"><table class="dados"><tbody>' +
      r.falhas.map(f => '<tr><td title="' + Fmt.escapa(f.arquivo) + '">' +
        Fmt.escapa(f.arquivo) + '</td><td style="width:280px" class="t3">' +
        Fmt.escapa(f.erro) + '</td></tr>').join('') +
      '</tbody></table></div></div>' : '');
}

async function enviar(arquivos){
  err(''); $('#resultado').innerHTML = '';
  if (!arquivos || !arquivos.length) return;
  const f = arquivos[0];
  if (arquivos.length > 1)
    err('Envie um arquivo por vez. Para vários XML, compacte tudo num ZIP.');
  if (arquivos.length > 1) return;

  $('#progresso').classList.remove('esconde');
  $('#ptxt').textContent = 'Enviando ' + f.name + ' · ' + tam(f.size);

  const fd = new FormData();
  fd.append('arquivo', f);

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/importacao');
  xhr.setRequestHeader('Authorization', 'Bearer ' + Sessao.token);
  xhr.upload.onprogress = e => {
    if (!e.lengthComputable) return;
    const p = Math.round(e.loaded / e.total * 100);
    $('#pbarra').style.width = p + '%';
    if (p === 100) $('#ptxt').textContent = 'Processando os documentos...';
  };
  xhr.onload = async () => {
    $('#progresso').classList.add('esconde');
    $('#pbarra').style.width = '0';
    let d = {};
    try { d = JSON.parse(xhr.responseText); } catch {}
    if (xhr.status === 401) { Sessao.sai(); return; }
    if (xhr.status >= 400) { err(d.detail || 'Erro ' + xhr.status); return; }
    pintaResultado(d);
    toast.ok(d.gravados + ' documento(s) importado(s).');
    await carregarHist();
  };
  xhr.onerror = () => {
    $('#progresso').classList.add('esconde');
    err('Falha no envio. Verifique a conexão e tente novamente.');
  };
  xhr.send(fd);
}

async function carregarHist(){
  const l = await api.get('/api/importacao/historico');
  if (!l.length) { $('#hist').innerHTML =
    '<div class="painel"><div class="vazio"><p>Nenhuma importação ainda.</p>' +
    '</div></div>'; return; }
  $('#hist').innerHTML = '<div class="painel"><div class="rolagem">' +
    '<table class="dados"><thead><tr>' +
    '<th>Arquivo</th><th style="width:90px">Tamanho</th>' +
    '<th style="width:90px">Gravados</th><th style="width:95px">Duplicados</th>' +
    '<th style="width:95px">Ignorados</th><th style="width:75px">Erros</th>' +
    '<th style="width:145px">Quando</th><th style="width:140px">Por</th>' +
    '</tr></thead><tbody>' +
    l.map(i => '<tr>' +
      '<td title="' + Fmt.escapa(i.arquivo_nome || '') + '">' +
        Fmt.escapa(i.arquivo_nome || '—') + '</td>' +
      '<td class="num">' + tam(i.arquivo_tamanho || 0) + '</td>' +
      '<td class="num" style="color:var(--ok)">' + Fmt.numero(i.gravados) + '</td>' +
      '<td class="num">' + Fmt.numero(i.duplicados) + '</td>' +
      '<td class="num">' + Fmt.numero(i.ignorados) + '</td>' +
      '<td class="num"' + (i.erros ? ' style="color:var(--erro)"' : '') + '>' +
        Fmt.numero(i.erros) + '</td>' +
      '<td>' + Fmt.dataHora(i.criado_em) + '</td>' +
      '<td>' + Fmt.escapa(i.usuario || '—') + '</td></tr>').join('') +
    '</tbody></table></div></div>';
}

(async () => {
  await Shell.monta(EMP_CTX ? {empresa: EMP_CTX} : {});
  pintaZona();
  const z = $('#zona'), inp = $('#arq');
  z.onclick = () => inp.click();
  inp.onchange = e => enviar(e.target.files);
  ['dragenter','dragover'].forEach(ev => z.addEventListener(ev, e => {
    e.preventDefault(); z.classList.add('sobre'); }));
  ['dragleave','drop'].forEach(ev => z.addEventListener(ev, e => {
    e.preventDefault(); z.classList.remove('sobre'); }));
  z.addEventListener('drop', e => enviar(e.dataTransfer.files));
  try { await carregarHist(); } catch(e) { toast.erro(e.message); }
})();
