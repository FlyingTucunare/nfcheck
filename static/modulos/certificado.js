/* Modulo: certificado digital da empresa */

const EMP = Sessao.empresaId;
if (!EMP) location.href = '/painel';

let ARQUIVO = null, ESPIADO = null;
const cErro = m => { const e = $('#c-erro'); e.textContent = m || '';
  e.classList.toggle('on', !!m); };
const cAviso = m => { const e = $('#c-aviso'); e.textContent = m || '';
  e.classList.toggle('on', !!m); };

function pintaZona(){
  $('#zona-txt').innerHTML = ARQUIVO
    ? Icone.arquivo + '<b>' + Fmt.escapa(ARQUIVO.name) + '</b>' +
      '<span class="t3">Clique para trocar o arquivo</span>'
    : Icone.subir + '<b>Escolha o arquivo .pfx ou .p12</b>' +
      '<span class="t3">Ou arraste até aqui</span>';
}

async function espiar(){
  cErro(''); cAviso(''); $('#previa').innerHTML = ''; ESPIADO = null;
  if (!ARQUIVO) return;
  const fd = new FormData();
  fd.append('empresa_id', EMP); fd.append('arquivo', ARQUIVO);
  try {
    const d = await api.post('/api/certificados/espiar', fd);
    ESPIADO = d;
    $('#previa').innerHTML =
      '<div style="background:var(--sup-2);border:1px solid var(--linha);' +
      'border-radius:var(--r);padding:var(--e-4)"><dl class="dados">' +
      [['Titular', d.titular_cn], ['CNPJ', Fmt.cnpj(d.cnpj_titular)],
       ['Emissor', d.emissor], ['Válido de', Fmt.data(d.valido_de)],
       ['Válido até', Fmt.data(d.valido_ate)],
       ['Situação', d.vencido ? 'VENCIDO' : 'Faltam ' + d.dias_restantes + ' dias']]
      .filter(([, v]) => v).map(([k, v]) =>
        '<dt>' + k + '</dt><dd>' + Fmt.escapa(v) + '</dd>').join('') + '</dl></div>';
    if (d.aviso) cAviso(d.aviso);
    if (d.vencido) cErro('Este certificado está vencido.');
    else $('#c-senha').focus();
  } catch(e) { cErro(e.message); }
}

async function enviar(){
  cErro('');
  if (!ARQUIVO) { cErro('Escolha o arquivo do certificado.'); return; }
  const senha = $('#c-senha').value;
  if (!senha) { cErro('Informe a senha do certificado.'); return; }
  const b = $('#c-enviar'); b.disabled = true; b.textContent = 'Enviando...';
  const fd = new FormData();
  fd.append('empresa_id', EMP); fd.append('senha', senha); fd.append('arquivo', ARQUIVO);
  try {
    await api.post('/api/certificados', fd);
    toast.ok('Certificado enviado.');
    ARQUIVO = null; ESPIADO = null;
    $('#c-arq').value = ''; $('#c-senha').value = '';
    $('#previa').innerHTML = ''; cAviso(''); pintaZona();
    await carregar();
  } catch(e) { cErro(e.message); }
  finally { b.disabled = false; b.textContent = 'Enviar certificado'; }
}

function pintaAtivo(l){
  const c = l.find(x => x.ativo);
  if (!c) {
    $('#ativo').innerHTML = '<div class="vazio" style="padding:var(--e-5)">' +
      '<p>Nenhum certificado ativo. Envie um arquivo A1 ao lado.</p></div>';
    $('#alerta-topo').innerHTML = '';
    return;
  }
  const dias = Math.floor((new Date(c.valido_ate) - Date.now()) / 864e5);
  const est = dias < 0 ? ['chip-erro', 'Vencido']
    : dias <= 30 ? ['chip-aviso', 'Vence em ' + dias + ' dias']
    : ['chip-ok', 'Válido por ' + dias + ' dias'];
  $('#ativo').innerHTML =
    '<div style="margin-bottom:var(--e-4)"><span class="chip ' + est[0] + '">' +
      '<span class="ponto"></span>' + est[1] + '</span></div>' +
    '<dl class="dados">' +
    [['Titular', c.titular_cn], ['CNPJ', Fmt.cnpj(c.cnpj_titular)],
     ['Válido de', Fmt.data(c.valido_de)], ['Válido até', Fmt.data(c.valido_ate)],
     ['Enviado em', Fmt.dataHora(c.enviado_em)], ['Enviado por', c.enviado_por]]
    .filter(([, v]) => v).map(([k, v]) =>
      '<dt>' + k + '</dt><dd>' + Fmt.escapa(v) + '</dd>').join('') + '</dl>';
  $('#alerta-topo').innerHTML = dias > 30 ? '' :
    '<div class="aviso ' + (dias < 0 ? 'aviso-erro' : 'aviso-alerta') + ' on">' +
    (dias < 0 ? 'O certificado está vencido. A sincronização e a emissão não funcionam.'
      : 'O certificado vence em ' + dias + ' dias. Providencie a renovação.') + '</div>';
}

function pintaHist(l){
  if (!l.length) { $('#hist').innerHTML =
    '<p class="t3" style="margin:0">Nenhum certificado enviado ainda.</p>'; return; }
  $('#hist').innerHTML = '<div class="rolagem"><table class="dados"><thead><tr>' +
    '<th>Titular</th><th style="width:150px">CNPJ</th>' +
    '<th style="width:110px">Válido até</th><th style="width:150px">Enviado</th>' +
    '<th style="width:120px">Situação</th></tr></thead><tbody>' +
    l.map(c => '<tr>' +
      '<td title="' + Fmt.escapa(c.titular_cn || '') + '">' +
        Fmt.escapa(c.titular_cn || '—') + '</td>' +
      '<td class="num">' + Fmt.cnpj(c.cnpj_titular) + '</td>' +
      '<td class="num">' + Fmt.data(c.valido_ate) + '</td>' +
      '<td>' + Fmt.dataHora(c.enviado_em) + '</td>' +
      '<td><span class="chip ' + (c.ativo ? 'chip-ok' : 'chip-neutro') + '">' +
        '<span class="ponto"></span>' + (c.ativo ? 'Ativo' : 'Substituído') +
      '</span></td></tr>').join('') + '</tbody></table></div>';
}

async function carregar(){
  const l = await api.get('/api/certificados/empresa/' + EMP);
  pintaAtivo(l); pintaHist(l);
}

(async () => {
  await Shell.monta({empresa: EMP});
  if (!Sessao.pode('cert_escrever')) $('#col-envio').classList.add('esconde');
  pintaZona();
  const z = $('#zona'), inp = $('#c-arq');
  z.onclick = () => inp.click();
  inp.onchange = e => { ARQUIVO = e.target.files[0]; pintaZona(); espiar(); };
  ['dragenter','dragover'].forEach(ev => z.addEventListener(ev, e => {
    e.preventDefault(); z.classList.add('sobre'); }));
  ['dragleave','drop'].forEach(ev => z.addEventListener(ev, e => {
    e.preventDefault(); z.classList.remove('sobre'); }));
  z.addEventListener('drop', e => {
    ARQUIVO = e.dataTransfer.files[0]; pintaZona(); espiar(); });
  $('#c-enviar').onclick = enviar;
  $('#c-senha').onkeydown = e => { if (e.key === 'Enter') enviar(); };
  try { await carregar(); } catch(e) { toast.erro(e.message); }
})();
