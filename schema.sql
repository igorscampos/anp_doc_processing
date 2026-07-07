-- Rode este script no SQL Editor do seu projeto Supabase (Project > SQL Editor > New query)

create table if not exists tb_auditorias (
    id_auditoria text primary key,
    numero_processo_anp text,
    numero_relatorio text,
    operadora text,
    cnpj_operadora text,
    unidade_instalacao text,
    tipo_auditoria text,
    data_auditoria_inicio text,
    data_auditoria_fim text,
    data_emissao_relatorio text,
    auditor_responsavel text,
    status_auditoria text,
    arquivo_origem text,
    criado_em timestamptz default now(),
    atualizado_em timestamptz default now()
);

create table if not exists tb_nao_conformidades (
    id_nao_conformidade text primary key,
    id_auditoria text references tb_auditorias(id_auditoria),
    numero_item text,
    descricao text,
    norma_referencia text,
    classificacao_gravidade text,
    prazo_correcao text,
    status_atual text,
    arquivo_origem text,
    criado_em timestamptz default now(),
    atualizado_em timestamptz default now()
);

create table if not exists tb_respostas (
    id_resposta text primary key,
    id_nao_conformidade text references tb_nao_conformidades(id_nao_conformidade),
    id_auditoria text references tb_auditorias(id_auditoria),
    tipo_registro text check (tipo_registro in ('resposta_operadora','parecer_anp')),
    data_resposta text,
    texto_resposta text,
    acao_corretiva text,
    evidencias_anexadas text,
    decisao_anp text,
    justificativa_decisao text,
    resultado_final text,
    arquivo_origem text,
    criado_em timestamptz default now()
);

-- controla arquivos já processados (evita gastar tokens de novo com o mesmo PDF)
create table if not exists tb_arquivos_processados (
    hash_arquivo text primary key,
    nome_arquivo text,
    tipo_documento text,
    confianca numeric,
    status text,
    motivo text,
    criado_em timestamptz default now()
);

-- Row Level Security: desativado para simplificar o protótipo.
-- Antes de expor a app publicamente, ative RLS e crie policies adequadas.
alter table tb_auditorias disable row level security;
alter table tb_nao_conformidades disable row level security;
alter table tb_respostas disable row level security;
alter table tb_arquivos_processados disable row level security;
