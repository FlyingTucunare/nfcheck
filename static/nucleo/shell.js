/* NFCheck — shell. Cabecalho, tema, menu do escritorio e registro de modulos.
   MODULO NOVO: declare aqui em MODULOS e crie static/modulos/<id>.js. So isso. */

const MODULOS = [
  {id:'dfe',        rota:'/e/dfe',        nome:'Documentos',   icone:'arquivo',
   perm:'ver',    desc:'NF-e, CT-e e NFS-e recebidas'},
  {id:'emissao',    rota:'/e/emissao',    nome:'Emitir NFS-e', icone:'subir',
   perm:'emitir', desc:'Emissor Nacional'},
  {id:'importacao', rota:'/e/importacao', nome:'Importar',     icone:'subir',
   perm:'importar', desc:'XML e PDF em lote'},
  {id:'exportacao', rota:'/e/exportacao', nome:'Exportar',     icone:'baixar',
   perm:'baixar', desc:'ZIP, planilhas e relatórios'},
  {id:'relatorios', rota:'/e/relatorios', nome:'Relatórios',   icone:'grafico',
   perm:'relatorio', desc:'Fiscais, controle e gerenciais'},
  {id:'certificado',rota:'/e/certificado',nome:'Certificado',  icone:'escudo',
   perm:'ver',    desc:'Arquivo, validade e histórico'},
  {id:'cadastro',   rota:'/e/cadastro',   nome:'Cadastro',     icone:'predio',
   perm:'ver',    desc:'Dados da empresa na Receita'},
];

const ESCRITORIO = [
  {id:'usuarios',   rota:'/escritorio/usuarios',   nome:'Usuários e acessos',
   icone:'usuarios', perm:'usuario_escrever'},
  {id:'certificados',rota:'/escritorio/certificados',nome:'Certificados',
   icone:'escudo',   perm:'ver'},
  {id:'alertas',    rota:'/escritorio/alertas',    nome:'Alertas',
   icone:'alerta',   perm:'ver'},
  {id:'auditoria',  rota:'/escritorio/auditoria',  nome:'Auditoria',
   icone:'relogio',  perm:'ver'},
  {id:'conta',      rota:'/escritorio/conta',      nome:'Dados da contabilidade',
   icone:'predio',   perm:'usuario_escrever'},
];

const Marca = (cor = 'claro') => {
  const b = cor === 'claro'
    ? ['#7FB2E0','#7FB2E0','#B9D8F0','#EFA33A','#EFA33A','#F6C77E']
    : ['#061E38','#0B3A66','#1663A8','#B34718','#DE6127','#EFA33A'];
  const y = [22,34,48,34,16,0];
  return '<svg viewBox="0 0 300 76" width="132" height="34" aria-label="NFCheck">' +
    y.map((v,i) => '<rect x="' + (2 + i*16) + '" y="' + v + '" width="9" height="30" ' +
      'rx="4.5" fill="' + b[i] + '"/>').join('') +
    '<text x="108" y="52" font-family="Inter,Arial,sans-serif" font-size="38" ' +
      'font-weight="700" fill="' + (cor === 'claro' ? '#fff' : '#061E38') + '" ' +
      'letter-spacing="-1">NF</text>' +
    '<text x="160" y="52" font-family="Inter,Arial,sans-serif" font-size="38" ' +
      'font-weight="400" fill="#EFA33A" letter-spacing="-1">Check</text></svg>';
};

const Shell = {
  _menuEscritorio(){
    const itens = ESCRITORIO.filter(m => Sessao.pode(m.perm));
    if (!itens.length) return '';
    return '<div style="position:relative">' +
      '<button class="btn btn-3 shell-btn" id="shell-menu">' +
        Icone.engrenagem + '<span class="so-largo">Escritório</span></button>' +
      '<div class="shell-drop" id="shell-drop">' +
        itens.map(m => '<a href="' + m.rota + '">' + Icone[m.icone] +
          Fmt.escapa(m.nome) + '</a>').join('') +
      '</div></div>';
  },

  async monta(opcoes = {}){
    Sessao.exige();
    try {
      const eu = await api.get('/api/eu');
      Sessao.permissoes = eu.permissoes || [];
    } catch { return; }

    const u = Sessao.usuario || {};
    const topo = document.createElement('header');
    topo.className = 'shell-topo';
    topo.innerHTML =
      '<div class="shell-in">' +
        '<a href="/painel" class="shell-marca">' + Marca('claro') + '</a>' +
        '<div id="shell-contexto" class="shell-ctx"></div>' +
        '<div class="colunas empurra" style="gap:var(--e-2)">' +
          '<button class="btn btn-3 btn-icone shell-btn" id="shell-tema" ' +
            'aria-label="Alternar tema"></button>' +
          Shell._menuEscritorio() +
          '<div class="shell-eu">' +
            '<span class="so-largo">' + Fmt.escapa(u.nome || '') + '</span>' +
            '<button class="btn btn-3 btn-icone shell-btn" id="shell-sair" ' +
              'aria-label="Sair">' + Icone.sair + '</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.prepend(topo);

    const pinta = () => $('#shell-tema').innerHTML =
      Tema.atual() === 'claro' ? Icone.lua : Icone.sol;
    pinta();
    $('#shell-tema').onclick = () => { Tema.alterna(); pinta(); };
    $('#shell-sair').onclick = () => Sessao.sai();

    const menu = $('#shell-menu');
    if (menu) {
      menu.onclick = e => { e.stopPropagation(); $('#shell-drop').classList.toggle('on'); };
      document.addEventListener('click', () => $('#shell-drop')?.classList.remove('on'));
    }
    if (opcoes.empresa) await Shell.contexto(opcoes.empresa);
  },

  async contexto(empresaId){
    const e = await api.get('/api/empresas/' + empresaId);
    $('#shell-contexto').innerHTML =
      '<a href="/painel" class="shell-volta" title="Voltar aos clientes">' +
        Icone.volta + '</a>' +
      '<div class="shell-sigla">' + Fmt.sigla(e.razao_social) + '</div>' +
      '<div style="min-width:0">' +
        '<div class="shell-emp">' + Fmt.escapa(e.nome_fantasia || e.razao_social) + '</div>' +
        '<div class="shell-cnpj num">' + Fmt.cnpj(e.cnpj) + '</div>' +
      '</div>';
    return e;
  },

  menuModulos(alvo, empresaId){
    const el = typeof alvo === 'string' ? $(alvo) : alvo;
    el.innerHTML = '<nav class="mods">' + MODULOS.filter(m => Sessao.pode(m.perm))
      .map(m => '<a href="' + m.rota + '" class="mod">' +
        '<span class="mod-ic">' + Icone[m.icone] + '</span>' +
        '<span><b>' + m.nome + '</b><i>' + m.desc + '</i></span>' +
        '<span class="mod-seta">' + Icone.seta + '</span></a>').join('') + '</nav>';
  },
};
