"""
Painel de processamento de auditorias ANP.

Rodar localmente:
    streamlit run app.py

Configuração (via .streamlit/secrets.toml ou variáveis de ambiente):
    ANTHROPIC_API_KEY
    SUPABASE_URL
    SUPABASE_KEY
"""

import hashlib
import json
import os

import pdfplumber
import streamlit as st
from anthropic import Anthropic

import db

st.set_page_config(page_title="Auditorias ANP", layout="wide")

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
def get_secret(name):
    if name in st.secrets:
        return st.secrets[name]
    return os.environ.get(name)

ANTHROPIC_API_KEY = get_secret("ANTHROPIC_API_KEY")
SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")
MODEL = get_secret("ANTHROPIC_MODEL") or "claude-haiku-4-5-20251001"

if not (ANTHROPIC_API_KEY and SUPABASE_URL and SUPABASE_KEY):
    st.error(
        "Faltam credenciais. Configure ANTHROPIC_API_KEY, SUPABASE_URL e SUPABASE_KEY "
        "em .streamlit/secrets.toml (veja secrets.toml.example)."
    )
    st.stop()

client = Anthropic(api_key=ANTHROPIC_API_KEY)
sb = db.get_client(SUPABASE_URL, SUPABASE_KEY)

CONFIDENCE_THRESHOLD = 0.7

PROMPT = """Você processa documentos de auditorias da ANP (regulação de petróleo e gás no Brasil).
Analise o texto abaixo e responda SOMENTE com JSON válido, sem markdown, sem texto fora do JSON.

Formato exato:
{{
  "tipo_documento": "auditoria_oficial|resposta_operadora|parecer_anp|evidencia_anexa|indeterminado",
  "confianca": 0.0,
  "numero_processo_anp": "string ou null",
  "numero_relatorio": "string ou null",
  "auditoria": null,
  "nao_conformidades": [],
  "respostas": []
}}

Preencha "auditoria" (objeto com operadora, cnpj_operadora, unidade_instalacao, tipo_auditoria,
data_auditoria_inicio, data_auditoria_fim, data_emissao_relatorio, auditor_responsavel,
status_auditoria) e "nao_conformidades" (array de {{numero_item, descricao, norma_referencia,
classificacao_gravidade, prazo_correcao}}) SOMENTE se tipo_documento for auditoria_oficial.
O anexo técnico de uma auditoria também conta como auditoria_oficial.

Preencha "respostas" (array de {{numero_item, resultado_final, decisao_anp, resumo}}) SOMENTE se
tipo_documento for resposta_operadora ou parecer_anp. numero_item deve corresponder ao item da
não conformidade original (ex: "5.4"). resumo em até 25 palavras.

TEXTO DO DOCUMENTO (pode estar truncado):
---
{texto}
---
"""


# ---------------------------------------------------------------------------
# Processamento
# ---------------------------------------------------------------------------
def extract_text(file_bytes, max_chars=80000):
    import io
    parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)[:max_chars]


def classify_and_extract(texto):
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": PROMPT.format(texto=texto)}],
    )
    raw = "".join(b.text for b in msg.content if b.type == "text").strip()
    raw = raw.strip("`")
    if raw.lower().startswith("json"):
        raw = raw[4:].strip()
    return json.loads(raw)


def apply_result(result, filename):
    tipo = result["tipo_documento"]

    if tipo == "auditoria_oficial":
        aud = {k: v for k, v in {
            "numero_processo_anp": result.get("numero_processo_anp"),
            "numero_relatorio": result.get("numero_relatorio"),
            **(result.get("auditoria") or {}),
        }.items() if v is not None}
        id_auditoria = db.upsert_auditoria(sb, aud, filename)
        for nc in result.get("nao_conformidades", []):
            db.upsert_nc(sb, id_auditoria, nc, filename)
        return f"auditoria {id_auditoria} atualizada com {len(result.get('nao_conformidades', []))} não conformidades"

    elif tipo in ("resposta_operadora", "parecer_anp"):
        aud = db.find_auditoria(sb, result.get("numero_processo_anp"))
        if not aud:
            raise ValueError("sem auditoria vinculada — processe o documento de auditoria oficial primeiro")
        id_auditoria = aud["id_auditoria"]
        gravadas = 0
        for r in result.get("respostas", []):
            nc = db.find_nc(sb, id_auditoria, r.get("numero_item"))
            if not nc:
                continue
            db.insert_resposta(sb, nc["id_nao_conformidade"], id_auditoria, tipo, r, filename)
            gravadas += 1
        return f"{gravadas} resposta(s) vinculada(s) à auditoria {id_auditoria}"

    else:
        raise ValueError(f"tipo '{tipo}' não é processado automaticamente")


def process_uploaded_file(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    existing = db.already_processed(sb, file_hash)
    if existing:
        return "duplicado", f"já processado antes ({existing['status']})"

    texto = extract_text(file_bytes)
    if not texto.strip():
        db.mark_processed(sb, file_hash, uploaded_file.name, None, 0.0, "erro", "sem texto extraível (pode precisar de OCR)")
        return "erro", "sem texto extraível (pode precisar de OCR)"

    result = classify_and_extract(texto)

    if result["confianca"] < CONFIDENCE_THRESHOLD or result["tipo_documento"] in ("indeterminado", "evidencia_anexa"):
        db.mark_processed(sb, file_hash, uploaded_file.name, result["tipo_documento"], result["confianca"], "revisao_manual")
        return "revisao", f"confiança {result['confianca']:.2f} — tipo {result['tipo_documento']}"

    try:
        detalhe = apply_result(result, uploaded_file.name)
        db.mark_processed(sb, file_hash, uploaded_file.name, result["tipo_documento"], result["confianca"], "concluido")
        return "concluido", detalhe
    except ValueError as e:
        db.mark_processed(sb, file_hash, uploaded_file.name, result["tipo_documento"], result["confianca"], "revisao_manual", str(e))
        return "revisao", str(e)


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------
st.title("Painel de auditorias ANP")
st.caption(f"Classificação e extração via Claude ({MODEL}) · banco Supabase")

uploaded_files = st.file_uploader(
    "Envie PDFs de auditoria, resposta ou parecer",
    type=["pdf"],
    accept_multiple_files=True,
)

if uploaded_files and st.button(f"Processar {len(uploaded_files)} arquivo(s)", type="primary"):
    progress = st.progress(0.0)
    for i, f in enumerate(uploaded_files):
        with st.spinner(f"Processando {f.name}..."):
            try:
                status, detalhe = process_uploaded_file(f)
            except Exception as e:
                status, detalhe = "erro", str(e)
        icon = {"concluido": "✅", "revisao": "⚠️", "erro": "❌", "duplicado": "↩️"}.get(status, "•")
        st.write(f"{icon} **{f.name}** — {detalhe}")
        progress.progress((i + 1) / len(uploaded_files))
    st.success("Processamento concluído.")

st.divider()

tab1, tab2, tab3, tab4 = st.tabs(["tb_auditorias", "tb_nao_conformidades", "tb_respostas", "fila de revisão"])

with tab1:
    st.dataframe(db.fetch_all(sb, "tb_auditorias"), use_container_width=True)

with tab2:
    st.dataframe(db.fetch_all(sb, "tb_nao_conformidades"), use_container_width=True)

with tab3:
    st.dataframe(db.fetch_all(sb, "tb_respostas"), use_container_width=True)

with tab4:
    revisao = [
        a for a in db.fetch_all(sb, "tb_arquivos_processados")
        if a["status"] in ("revisao_manual", "erro")
    ]
    st.dataframe(revisao, use_container_width=True)
    st.caption("Arquivos com baixa confiança, sem vínculo encontrado, ou com erro de leitura.")
