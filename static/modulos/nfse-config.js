/* Modulo: configuracao de emissao de NFS-e (serie, numeracao, regras fiscais).
   So quem tem permissao 'emitir' pode salvar; 'ativo' e sempre manual - o
   sistema nunca liga a emissao sozinho. */

const EMP = Sessao.empresaId;
if (!EMP) location.href = '/painel';

const err = m => { const e = $('#cfg-erro'); e.textContent = m || '';
  e.classList.toggle('on', !!m); };

function preenche(d){
  const cfg = d.config, emp = d.empresa;
  $('#f-ambiente').value = cfg ? cfg.ambiente : '1';
  $('#f-serie').value = cfg ? cfg.serie_dps : '00001';
  $('#f-numero').value = cfg && cfg.proximo_numero != null ? cfg.proximo_numero : 1;
  $('#f-aliquota').value = cfg && cfg.aliquota_iss != null
    ? (Number(cfg.aliquota_iss) * 100).toFixed(2) : '';
  $('#f-regime').value = cfg ? (cfg.regime_especial || '') : '';
  $('#f-obs').value = cfg ? (cfg.observacao_padrao || '') : '';
  $('#f-simples').checked = cfg ? !!cfg.optante_simples : !!(emp && emp.simples_optante);
  $('#f-incentivo').checked = cfg ? !!cfg.incentivo_fiscal : false;
  $('#f-retido').checked = cfg ? !!cfg.iss_retido_padrao : false;
  $('#f-ativo').checked = cfg ? !!cfg.ativo : false;
}

function pintaAlerta(pendencias){
  const p = (pendencias || []).filter(x => !x.includes('configurada'));
  $('#alerta-topo').innerHTML = p.length
    ? '<div class="aviso aviso-alerta on">Ainda existem pendências além da ' +
      'configuração: ' + p.map(Fmt.escapa).join(' · ') + '</div>' : '';
}

async function salvar(){
  err('');
  const corpo = {
    empresa_id: Number(EMP),
    ambiente: $('#f-ambiente').value,
    serie_dps: $('#f-serie').value.trim() || '00001',
    proximo_numero: $('#f-numero').value ? Number($('#f-numero').value) : null,
    regime_especial: $('#f-regime').value.trim() || null,
    optante_simples: $('#f-simples').checked,
    incentivo_fiscal: $('#f-incentivo').checked,
    aliquota_iss: $('#f-aliquota').value ? Number($('#f-aliquota').value) / 100 : null,
    iss_retido_padrao: $('#f-retido').checked,
    observacao_padrao: $('#f-obs').value.trim() || null,
    ativo: $('#f-ativo').checked,
  };
  const b = $('#f-salvar'); b.disabled = true; b.textContent = 'Salvando...';
  try {
    await api.put('/api/nfse/config', corpo);
    toast.ok('Configuração salva.');
    await carregar();
  } catch(e) { err(e.message); }
  finally { b.disabled = false; b.textContent = 'Salvar configuração'; }
}

async function carregar(){
  const d = await api.get('/api/nfse/config?empresa_id=' + EMP);
  preenche(d);
  pintaAlerta(d.pendencias);
}

(async () => {
  await Shell.monta({empresa: EMP});
  if (!Sessao.pode('emitir')){
    $$('#f-ambiente,#f-serie,#f-numero,#f-aliquota,#f-regime,#f-obs,#f-simples,' +
      '#f-incentivo,#f-retido,#f-ativo').forEach(el => el.disabled = true);
    $('#f-salvar').classList.add('esconde');
  }
  $('#f-salvar').onclick = salvar;
  try { await carregar(); } catch(e) { err(e.message); }
})();
