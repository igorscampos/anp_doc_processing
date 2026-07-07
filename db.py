"""Funções de acesso ao Supabase (Postgres) para as 4 tabelas do pipeline."""

import uuid
from supabase import create_client


def get_client(url, key):
    return create_client(url, key)


def gen_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Controle de duplicidade
# ---------------------------------------------------------------------------
def already_processed(sb, file_hash):
    res = sb.table("tb_arquivos_processados").select("*").eq("hash_arquivo", file_hash).execute()
    return res.data[0] if res.data else None


def mark_processed(sb, file_hash, nome_arquivo, tipo_documento, confianca, status, motivo=None):
    sb.table("tb_arquivos_processados").upsert({
        "hash_arquivo": file_hash,
        "nome_arquivo": nome_arquivo,
        "tipo_documento": tipo_documento,
        "confianca": confianca,
        "status": status,
        "motivo": motivo,
    }).execute()


# ---------------------------------------------------------------------------
# tb_auditorias
# ---------------------------------------------------------------------------
def find_auditoria(sb, numero_processo_anp):
    if not numero_processo_anp:
        return None
    res = sb.table("tb_auditorias").select("*").eq("numero_processo_anp", numero_processo_anp).execute()
    return res.data[0] if res.data else None


def upsert_auditoria(sb, dados, arquivo_origem):
    existente = find_auditoria(sb, dados.get("numero_processo_anp"))
    if existente:
        id_auditoria = existente["id_auditoria"]
        payload = {k: v for k, v in dados.items() if v is not None}
        sb.table("tb_auditorias").update(payload).eq("id_auditoria", id_auditoria).execute()
    else:
        id_auditoria = gen_id("AUD")
        payload = {"id_auditoria": id_auditoria, "arquivo_origem": arquivo_origem, **dados}
        sb.table("tb_auditorias").insert(payload).execute()
    return id_auditoria


# ---------------------------------------------------------------------------
# tb_nao_conformidades
# ---------------------------------------------------------------------------
def find_nc(sb, id_auditoria, numero_item):
    res = (
        sb.table("tb_nao_conformidades")
        .select("*")
        .eq("id_auditoria", id_auditoria)
        .eq("numero_item", numero_item)
        .execute()
    )
    return res.data[0] if res.data else None


def upsert_nc(sb, id_auditoria, nc, arquivo_origem):
    existente = find_nc(sb, id_auditoria, nc.get("numero_item"))
    if existente:
        sb.table("tb_nao_conformidades").update({
            "descricao": nc.get("descricao") or existente["descricao"],
        }).eq("id_nao_conformidade", existente["id_nao_conformidade"]).execute()
        return existente["id_nao_conformidade"]
    id_nc = gen_id("NC")
    sb.table("tb_nao_conformidades").insert({
        "id_nao_conformidade": id_nc,
        "id_auditoria": id_auditoria,
        "numero_item": nc.get("numero_item"),
        "descricao": nc.get("descricao"),
        "status_atual": "pendente de resposta",
        "arquivo_origem": arquivo_origem,
    }).execute()
    return id_nc


# ---------------------------------------------------------------------------
# tb_respostas
# ---------------------------------------------------------------------------
def insert_resposta(sb, id_nc, id_auditoria, tipo_registro, r, arquivo_origem):
    sb.table("tb_respostas").insert({
        "id_resposta": gen_id("RESP"),
        "id_nao_conformidade": id_nc,
        "id_auditoria": id_auditoria,
        "tipo_registro": tipo_registro,
        "resultado_final": r.get("resultado_final"),
        "decisao_anp": r.get("decisao_anp"),
        "texto_resposta": r.get("resumo"),
        "arquivo_origem": arquivo_origem,
    }).execute()
    if r.get("resultado_final"):
        sb.table("tb_nao_conformidades").update(
            {"status_atual": r.get("resultado_final")}
        ).eq("id_nao_conformidade", id_nc).execute()


# ---------------------------------------------------------------------------
# Leitura para exibição na interface
# ---------------------------------------------------------------------------
def fetch_all(sb, table):
    res = sb.table(table).select("*").order("criado_em", desc=True).execute()
    return res.data
