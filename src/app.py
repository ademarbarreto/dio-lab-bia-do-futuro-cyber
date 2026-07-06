"""
app.py — Copiloto de Vendas FYS
Streamlit + OpenAI GPT-4o-mini
Bootcamp Heineken × DIO | Autor: Ademar Silva Barreto Junior

Migrado para chat nativo (st.chat_message/st.chat_input + streaming) e com
camada de segurança: anti prompt injection, rate limiting/limite de custo,
tratamento de erro sem stack trace e log de auditoria.
"""

import os
import re
import time
import json
import random
import logging
import hashlib
import unicodedata
from pathlib import Path

import streamlit as st
from openai import OpenAI, APIError, APITimeoutError, AuthenticationError, RateLimitError
from prompts.agente import build_system_prompt, get_abertura

# ─────────────────────────────────────────
# CONFIGURAÇÃO DE SEGURANÇA
# ─────────────────────────────────────────
MAX_MENSAGEM_CHARS = 800            # limite de tamanho do input do usuário
MAX_MENSAGENS_POR_SESSAO = 30       # rate limiting simples por sessão
REQUEST_TIMEOUT_SECONDS = 30        # timeout da chamada à API

# Preços aproximados do gpt-4o-mini (USD por 1k tokens) — CONFIRME os valores
# atuais em https://openai.com/api/pricing/ antes de usar em produção.
PRECO_ENTRADA_1K = 0.00015
PRECO_SAIDA_1K = 0.0006
LIMITE_CUSTO_AVISO = 0.15    # USD
LIMITE_CUSTO_CRITICO = 0.30  # USD

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=LOG_DIR / "auditoria.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("fys_seguranca")

# Padrões heurísticos de tentativa de prompt injection (LLM01)
PADROES_INJECTION = [
    r"ignor[ae]\s+(as|todas)?\s*(regras|instru[cç][ãa]o)",
    r"esque[çc]a\s+(as|suas)?\s*(regras|instru[cç][õo]es)",
    r"voc[êe]\s+(agora|a partir de agora)\s+[ée]",
    r"a partir de agora,?\s+voc[êe]\s+[ée]",
    r"system\s*prompt",
    r"\bactue\s+como\b",
    r"\bfinja\s+que\b",
    r"disregard\s+(previous|all)",
    r"ignore\s+(previous|all)\s+instructions",
]


def hash_mensagem(texto: str) -> str:
    """Hash da mensagem para log de auditoria sem persistir o texto literal."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def contem_tentativa_injection(texto: str) -> bool:
    texto_norm = texto.lower()
    return any(re.search(p, texto_norm) for p in PADROES_INJECTION)


def sanitizar_mensagem(texto: str) -> str:
    """Remove caracteres de controle e limita o tamanho do input."""
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", texto)
    return texto.strip()[:MAX_MENSAGEM_CHARS]


def calcular_custo(tokens_in: int, tokens_out: int) -> float:
    custo_in = (tokens_in / 1000) * PRECO_ENTRADA_1K
    custo_out = (tokens_out / 1000) * PRECO_SAIDA_1K
    return round(custo_in + custo_out, 6)


# ─────────────────────────────────────────
# DADOS DE REFERENCIA (inline para o painel)
# ─────────────────────────────────────────
SABORES = {
    "Guaraná da Amazônia": {
        "cor": "#1B5E35", "cor_bg": "#E8F5E9", "emoji": "🟢",
        "pitch": "Guaraná de verdade — encorpado, sem gosto aguado.",
        "gancho": "Você gosta de guaraná? Esse e diferente — experimenta.",
    },
    "Limão Siciliano": {
        "cor": "#4A7C1F", "cor_bg": "#F1F8E9", "emoji": "🌿",
        "pitch": "Azedinho natural, refresca de verdade. Sem artificial.",
        "gancho": "Tá com calor? O limão siciliano bem geladinho cai perfeito.",
    },
    "Laranja-Pera": {
        "cor": "#C05A00", "cor_bg": "#FFF3E0", "emoji": "🟠",
        "pitch": "Combinação unica no mercado — frutado e leve.",
        "gancho": "Esse de laranja com pera e o queridinho — quer arriscar?",
    },
    "Tônica": {
        "cor": "#2C2C2A", "cor_bg": "#F5F5F5", "emoji": "⚫",
        "pitch": "Amargo característico com toque de limao. Otima pura ou mixer.",
        "gancho": "Voce curte tônica? Essa e muito mais refinada.",
    },
}

OBJECOES_DONO = [
    ("Meu cliente não conhece o produto",
     "É exatamente aí que esta a oportunidade. Produto novo tem margem maior e cliente que descobre vira fiel."),
    ("Não tenho espaço na geladeira",
     "Precisa de so uma prateleira — 4 sabores, um de cada. Me dá 5 minutos pra reorganizar?"),
    ("É mais caro que os outros",
     "A margem é maior que nos refris tradicionais. O cliente que experimenta tem ticket médio mais alto."),
    ("Ja tenho muitos refrigerantes",
     "FYS não concorre com Coca-Cola — e um segmento diferente. Voce amplia o publico, não repete o mix."),
    ("Minha clientela e popular",
     "Uma latinha no balcão pra degustação converte mais do que qualquer argumento. Topa testar hoje?"),
    ("Não conheço a marca",
     "FYS é do Grupo Heineken — a mesma empresa das melhores bebidas do Brasil ha decadas."),
]

OBJECOES_CONSUMIDOR = [
    ("Nunca ouvi falar. E bom mesmo?",
     "É do Grupo Heineken. Experimenta um, se não gostar eu te troco."),
    ("É mais caro que o normal...",
     "É 1-2 reais a mais, mas o sabor e muito melhor e tem bem menos acucar. Vale cada centavo."),
    ("Tem menos acuçar? Então é diet?",
     "Não, não é diet. Açucar real, só bem menos — sem gosto de adocante. Mais natural e gostoso."),
    ("Prefiro o de sempre, obrigado.",
     "Claro! Mas o FYS tem metade do açucar do seu refri de sempre. Qualquer hora, e só falar."),
    ("Não conheço esses sabores...",
     "O Guaraná da Amazônia é o mais fácil de entrar — familiar, mas muito melhor. Tenta esse primeiro."),
    ("Não to afim de experimentar hoje.",
     "Sem problema! Deixo geladinho aqui se mudar de idéia. 😉"),
]

DICAS_PDV = [
    "🎯 Posicione o FYS na **altura dos olhos** — ao lado dos refris mais pedidos, nunca no canto.",
    "🧪 Uma **latinha aberta no balcão** para degustação converte mais do que qualquer argumento.",
    "📦 Comece com **1 caixa de cada sabor** — 4 SKUs visiveis ja geram curiosidade.",
    "🔁 O **Guaraná da Amazônia** e o mais facil de entrar para consumidores de guaraná tradicional.",
    "💰 FYS tem **margem maior** que os refris lideres — argumento poderoso para o dono.",
    "🤝 O atendente que **apresenta o FYS primeiro** (antes do de sempre) dobra a conversao.",
    "📸 Registre a geladeira **antes e depois** — compare o giro em 15 dias com o dono.",
    "🌡️ FYS vende mais **bem gelado e bem apresentado** — temperatura e exposicao sao 50% da venda.",
]

MODOS = [
    "💬 Chat Livre com o Copiloto",
    "🏪 Argumentos para o Dono da Padaria",
    "🧑 Script para o Atendente",
    "🛡️ Respostas a Objeções",
    "📍 Dicas de PDV Inteligente",
    "🎭 Simulação de Visita de Vendas",
]

MODO_DESC = {
    "💬 Chat Livre com o Copiloto":         "Pergunta livre — Fyz identifica o contexto.",
    "🏪 Argumentos para o Dono da Padaria": "Argumentos B2B: margem, giro, diferencial.",
    "🧑 Script para o Atendente":           "Scripts B2C prontos para o balcão.",
    "🛡️ Respostas a Objeções":              "Banco completo por perfil (dono / consumidor).",
    "📍 Dicas de PDV Inteligente":          "Posicionamento, exposição e conversão no PDV.",
    "🎭 Simulação de Visita de Vendas":     "Roleplay: pratique a visita com Seu Zé.",
}

QUICK = {
    "💬 Chat Livre com o Copiloto": [
        "Como convencer o dono a colocar FYS na geladeira?",
        "Quais os diferenciais do FYS?",
        "Como responder a objecao de preço?",
    ],
    "🏪 Argumentos para o Dono da Padaria": [
        "Apresente o FYS em 30 segundos",
        "Argumento de margem e giro para o dono",
        "O dono não tem espaço na geladeira",
    ],
    "🧑 Script para o Atendente": [
        "Cliente pede Coca-Cola — o que falar?",
        "Script para vender Guaraná da Amazônia",
        "Script para vender Tonica FYS",
    ],
    "🛡️ Respostas a Objeções": [
        "Tabela completa — Dono da Padaria",
        "Tabela completa — Consumidor Final",
        "O cliente acha que FYS é diet",
    ],
    "📍 Dicas de PDV Inteligente": [
        "Como organizar a geladeira para vender mais",
        "Estrategia de degustação no balcão",
        "Cross-sell FYS com salgado da padaria",
    ],
    "🎭 Simulação de Visita de Vendas": [
        "Bom dia! Vim apresentar um produto novo do Grupo Heineken.",
        "Quero mostrar o FYS — ate 50% menos acucar.",
        "Posso deixar uma caixa para você testar essa semana?",
    ],
}

PLACEHOLDERS = {
    "💬 Chat Livre com o Copiloto":         "Pergunte qualquer coisa sobre vendas FYS...",
    "🏪 Argumentos para o Dono da Padaria": "Ex: O dono diz que o produto e caro demais...",
    "🧑 Script para o Atendente":           "Ex: Script para cliente que nunca ouviu falar do FYS...",
    "🛡️ Respostas a Objeções":              "Ex: Gere tabela de objecoes para o consumidor final...",
    "📍 Dicas de PDV Inteligente":          "Ex: Como posicionar FYS numa geladeira pequena?",
    "🎭 Simulação de Visita de Vendas":     "Fale como agente de vendas visitando a padaria...",
}

# ─────────────────────────────────────────
# CONFIG DA PAGINA
# ─────────────────────────────────────────
st.set_page_config(
    page_title="Copiloto FYS — Vendas IA",
    page_icon="🥤",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1B5E35 0%, #0D3320 100%);
}
[data-testid="stSidebar"] * { color: #E8F5E9 !important; }
[data-testid="stSidebar"] hr { border-color: #2E7D46 !important; }
.sidebar-brand {
    background: rgba(255,255,255,0.09);
    border-radius: 12px; padding: 14px;
    margin-bottom: 14px; text-align: center;
    border: 1px solid rgba(255,255,255,0.13);
}
.sidebar-brand h2 { color: #F5C842 !important; font-size: 20px !important; margin: 0 !important; }
.sidebar-brand p  { color: #A8D5B5 !important; font-size: 11px !important; margin: 3px 0 0 !important; }
.main-hdr {
    background: linear-gradient(135deg, #1B5E35 0%, #2E7D46 60%, #4CAF70 100%);
    border-radius: 14px; padding: 18px 22px; margin-bottom: 18px;
}
.main-hdr h1 { font-size: 22px; margin: 0 0 3px; font-weight: 800; color: #fff; }
.main-hdr p  { font-size: 12px; color: #A8D5B5; margin: 0; }
.modo-bar {
    background: #F4F7F2; border-radius: 8px;
    padding: 9px 13px; font-size: 12px; color: #555;
    margin-bottom: 12px; border: 1px solid #D4E8D4;
}
.ref-sabor {
    border-radius: 0 10px 10px 0; padding: 11px 13px;
    margin-bottom: 7px; font-size: 12px; line-height: 1.6;
}
.ref-obj {
    background: #FFF8E1; border-left: 4px solid #F5C842;
    border-radius: 0 10px 10px 0; padding: 11px 13px; margin-bottom: 7px;
}
.obj-q { font-size: 11px; color: #7B5800; font-weight: 600; margin-bottom: 3px; }
.obj-a { font-size: 12px; color: #333; line-height: 1.6; }
.dica { background: #E8F5E9; border-radius: 10px; padding: 11px 14px;
        margin-bottom: 7px; border: 1px solid #C8E6C9;
        font-size: 12px; color: #1B5E35; line-height: 1.6; }
.qlabel { font-size: 10px; color: #777; margin-bottom: 5px;
          font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────
# ESTADO
# ─────────────────────────────────────────
def init():
    defs = {
        "messages": [], "modo": MODOS[0],
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "dica_dia": random.choice(DICAS_PDV),
        "custo_total": 0.0,
        "num_mensagens": 0,
        "bloqueado": False,
    }
    for k, v in defs.items():
        if k not in st.session_state:
            st.session_state[k] = v


init()


def avatar_para(role: str, modo: str) -> str:
    if role == "user":
        return "👤"
    return "🎭" if "Simul" in modo else "🥤"


# ─────────────────────────────────────────
# OPENAI (com streaming real + tratamento de erro)
# ─────────────────────────────────────────
def gerador_resposta(user_msg: str, modo: str, usage_holder: dict):
    """Gerador que consome a API em streaming. Preenche usage_holder com os
    tokens de entrada/saída assim que o último chunk (com uso) chegar."""
    system = build_system_prompt(modo)
    history = [{"role": "system", "content": system}]
    for m in st.session_state.messages[-12:]:
        history.append({"role": m["role"], "content": m["content"]})
    history.append({"role": "user", "content": user_msg})

    client = OpenAI(api_key=st.session_state.api_key, timeout=REQUEST_TIMEOUT_SECONDS)
    stream = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=history,
        temperature=float(os.getenv("AGENT_TEMPERATURE", "0.7")),
        max_tokens=int(os.getenv("AGENT_MAX_TOKENS", "800")),
        stream=True,
        stream_options={"include_usage": True},
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
        if getattr(chunk, "usage", None):
            usage_holder["tokens_in"] = chunk.usage.prompt_tokens
            usage_holder["tokens_out"] = chunk.usage.completion_tokens


def processar_mensagem(texto_bruto: str, modo: str):
    """Valida, envia ao modelo em streaming e atualiza o histórico —
    com as mesmas proteções de segurança do Agente ADE."""
    if not st.session_state.api_key:
        st.warning("⚠️ Configure sua **OpenAI API Key** na barra lateral para ativar o Copiloto.")
        return

    if st.session_state.bloqueado:
        st.error("🚨 Limite de uso da sessão atingido. Recarregue a página para reiniciar.")
        return

    if st.session_state.num_mensagens >= MAX_MENSAGENS_POR_SESSAO:
        st.session_state.bloqueado = True
        logger.warning("Sessão bloqueada por excesso de mensagens.")
        st.error("🚨 Limite de mensagens por sessão atingido.")
        return

    if st.session_state.custo_total >= LIMITE_CUSTO_CRITICO:
        st.session_state.bloqueado = True
        logger.warning("Sessão bloqueada por limite crítico de custo.")
        st.error("🚨 Limite crítico de custo atingido. Uso bloqueado.")
        return

    texto = sanitizar_mensagem(texto_bruto)
    if not texto:
        return

    st.session_state.messages.append({"role": "user", "content": texto})
    with st.chat_message("user", avatar=avatar_para("user", modo)):
        st.write(texto)

    if contem_tentativa_injection(texto):
        logger.warning(f"Possível prompt injection. hash={hash_mensagem(texto)} modo={modo}")
        aviso = "⚠️ Não consigo processar essa mensagem. Reformule dentro do contexto de vendas FYS."
        with st.chat_message("assistant", avatar=avatar_para("assistant", modo)):
            st.warning(aviso)
        st.session_state.messages.append({"role": "assistant", "content": aviso})
        return

    st.session_state.num_mensagens += 1

    with st.chat_message("assistant", avatar=avatar_para("assistant", modo)):
        usage_holder = {"tokens_in": 0, "tokens_out": 0}
        inicio = time.time()
        try:
            texto_completo = st.write_stream(gerador_resposta(texto, modo, usage_holder))
        except AuthenticationError:
            logger.error("API Key inválida.")
            st.error("❌ **API Key inválida.** Verifique a chave na barra lateral.")
            return
        except RateLimitError:
            logger.error("Limite de uso/quota atingido na API.")
            st.error("❌ **Limite de uso atingido.** Verifique sua conta OpenAI.")
            return
        except APITimeoutError:
            logger.error("Timeout na chamada à API do modelo.")
            st.error("⏱️ O serviço demorou demais para responder. Tente novamente.")
            return
        except APIError:
            logger.error("Erro na API do modelo.")
            st.error("❌ Não foi possível obter resposta no momento. Tente novamente mais tarde.")
            return
        except Exception:
            logger.exception("Erro inesperado ao processar a mensagem.")
            st.error("❌ Ocorreu um erro inesperado. Tente novamente.")
            return

        latencia = time.time() - inicio
        custo_request = calcular_custo(usage_holder["tokens_in"], usage_holder["tokens_out"])
        st.session_state.custo_total += custo_request

        logger.info(
            f"mensagem_hash={hash_mensagem(texto)} modo={modo} "
            f"tokens_in={usage_holder['tokens_in']} tokens_out={usage_holder['tokens_out']} "
            f"custo={custo_request:.6f} latencia={latencia:.2f}s"
        )

        st.session_state.messages.append({"role": "assistant", "content": texto_completo})

        if st.session_state.custo_total >= LIMITE_CUSTO_CRITICO:
            st.session_state.bloqueado = True
            st.warning("🚨 Limite crítico de custo atingido! Uso bloqueado.")
        elif st.session_state.custo_total >= LIMITE_CUSTO_AVISO:
            st.warning("⚠️ Atenção: custo da sessão se aproximando do limite.")


# ─────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
        <h2>🥤 FYS Copiloto</h2>
        <p>Agente de Vendas com IA</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("**🔑 OpenAI API Key**")
    api_key = st.text_input("key", type="password", placeholder="sk-...",
                             value=st.session_state.api_key, label_visibility="collapsed")
    if api_key:
        st.session_state.api_key = api_key
        st.success("✅ API Key configurada")
    else:
        st.warning("Cole sua API Key para ativar.")

    st.divider()

    st.markdown("**🎯 Modo de Atuação**")
    modo = st.radio("modo", options=MODOS,
                    index=MODOS.index(st.session_state.modo),
                    label_visibility="collapsed")
    if modo != st.session_state.modo:
        st.session_state.modo = modo
        st.session_state.messages = []
        st.rerun()

    st.divider()
    st.markdown("**🥤 Linha FYS**")
    for nome, info in SABORES.items():
        st.markdown(
            f"<span style='color:{info['cor']};font-size:12px;'>"
            f"{info['emoji']} <b>{nome}</b></span>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("**📊 Uso da sessão**")
    progresso = min(st.session_state.custo_total / LIMITE_CUSTO_CRITICO, 1.0) if LIMITE_CUSTO_CRITICO else 0
    st.progress(progresso, text=f"${st.session_state.custo_total:.4f} de ${LIMITE_CUSTO_CRITICO:.2f}")
    st.caption(f"{st.session_state.num_mensagens}/{MAX_MENSAGENS_POR_SESSAO} mensagens nesta sessão")

    if st.button("🗑️ Limpar conversa", use_container_width=True):
        # Reinicia só o histórico visível — os contadores de custo e
        # mensagens são mantidos por design (evita burlar os limites).
        st.session_state.messages = []
        st.rerun()

    st.markdown(
        "<p style='font-size:10px;color:#6aaa80;text-align:center;margin-top:10px'>"
        "Bootcamp Heineken x DIO<br>Autor: Ademar Silva Barreto Jr.</p>",
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
modo = st.session_state.modo

st.markdown("""
<div class="main-hdr">
    <h1>🥤 Copiloto de Vendas FYS</h1>
    <p>Assistente de IA para fortalecer as vendas em padarias e PDVs · Powered by OpenAI GPT-4o-mini</p>
</div>
""", unsafe_allow_html=True)

col_chat, col_ref = st.columns([3, 2], gap="medium")

# ══ CHAT ══
with col_chat:
    st.markdown(
        f"<div class='modo-bar'>🎯 <b>{modo}</b> &nbsp;·&nbsp; {MODO_DESC[modo]}</div>",
        unsafe_allow_html=True,
    )

    if st.session_state.bloqueado:
        st.error("🚨 Limite de uso da sessão atingido. Recarregue a página para reiniciar.")

    chat_box = st.container(height=400, border=True)
    with chat_box:
        if not st.session_state.messages:
            abertura = get_abertura(modo)
            with st.chat_message("assistant", avatar=avatar_para("assistant", modo)):
                st.write(abertura)
        else:
            for m in st.session_state.messages:
                with st.chat_message(m["role"], avatar=avatar_para(m["role"], modo)):
                    st.write(m["content"])

    # Ações rápidas — só aparecem enquanto a conversa está vazia
    if not st.session_state.messages:
        st.markdown("<div class='qlabel'>⚡ Ações rápidas</div>", unsafe_allow_html=True)
        actions = QUICK.get(modo, [])
        qa_cols = st.columns(len(actions)) if actions else []
        for i, act in enumerate(actions):
            with qa_cols[i]:
                if st.button(act, key=f"qa_{i}", use_container_width=True):
                    processar_mensagem(act, modo)
                    st.rerun()

    entrada = st.chat_input(
        PLACEHOLDERS.get(modo, "Digite sua mensagem..."),
        max_chars=MAX_MENSAGEM_CHARS,
        disabled=st.session_state.bloqueado,
    )
    if entrada:
        processar_mensagem(entrada, modo)
        st.rerun()

# ══ PAINEL DE REFERENCIA ══
with col_ref:
    st.markdown("### 💡 Dica do Dia")
    st.markdown(f"<div class='dica'>{st.session_state.dica_dia}</div>", unsafe_allow_html=True)
    if st.button("🔄 Nova dica", key="nd"):
        st.session_state.dica_dia = random.choice(DICAS_PDV)
        st.rerun()

    st.divider()

    MODOS_SABORES = [
        "💬 Chat Livre com o Copiloto",
        "🧑 Script para o Atendente",
        "🏪 Argumentos para o Dono da Padaria",
    ]

    if modo in MODOS_SABORES:
        st.markdown("### 🥤 Linha de Produtos")
        for nome, info in SABORES.items():
            cor   = info["cor"]
            cor_b = info["cor_bg"]
            html  = (
                f"<div class='ref-sabor' style='background:{cor_b};border-left:4px solid {cor};'>"
                f"<div style='font-weight:700;font-size:12px;color:{cor};margin-bottom:4px;'>"
                f"{info['emoji']} {nome}</div>"
                f"<div style='font-size:11px;color:#444;'>{info['pitch']}</div>"
                f"<div style='font-size:11px;font-style:italic;color:{cor};margin-top:5px;"
                f"border-left:2px solid #8BC34A;padding-left:7px;'>\"{info['gancho']}\"</div>"
                f"</div>"
            )
            st.markdown(html, unsafe_allow_html=True)

    elif modo == "🛡️ Respostas a Objeções":
        st.markdown("### 🛡️ Banco de Objeções")
        tab1, tab2 = st.tabs(["🏪 Dono", "🧑 Consumidor"])
        with tab1:
            for q, a in OBJECOES_DONO:
                st.markdown(
                    f"<div class='ref-obj'><div class='obj-q'>❝ {q} ❞</div>"
                    f"<div class='obj-a'>→ {a}</div></div>",
                    unsafe_allow_html=True,
                )
        with tab2:
            for q, a in OBJECOES_CONSUMIDOR:
                st.markdown(
                    f"<div class='ref-obj'><div class='obj-q'>❝ {q} ❞</div>"
                    f"<div class='obj-a'>→ {a}</div></div>",
                    unsafe_allow_html=True,
                )

    elif modo == "📍 Dicas de PDV Inteligente":
        st.markdown("### 📍 Todas as Dicas")
        for d in DICAS_PDV:
            st.markdown(f"<div class='dica'>{d}</div>", unsafe_allow_html=True)

    elif "Simul" in modo:
        st.markdown("### 🎭 Guia da Simulacao")
        st.markdown("""
<div class='dica'>
<b>Como funciona:</b><br>
Voce e o <b>agente de vendas FYS</b>.<br>
Fyz vira <b>Seu Zé</b>, dono de padaria com objecoes reais.<br><br>
<b>Objetivo:</b><br>
✅ Colocar FYS na geladeira<br>
✅ Expor na altura dos olhos<br>
✅ Pedir 1 caixa de cada sabor<br><br>
Apos 4-5 turnos: <b>feedback estruturado</b> da Fyz.
</div>""", unsafe_allow_html=True)

        st.markdown("**🎯 Checklist do Agente**")
        checks = [
            "Criou rapport com o dono",
            "Mencionou o Grupo Heineken",
            "Destacou o diferencial (menos acucar)",
            "Respondeu objecao de preco",
            "Propôs degustação ou acao concreta",
            "Fechou com proximo passo claro",
        ]
        for i, c in enumerate(checks):
            st.checkbox(c, key=f"chk_{i}")

    st.divider()
    st.markdown(
        "<p style='font-size:10px;color:#888;text-align:center;'>"
        "🥤 FYS · Grupo Heineken Brasil<br>"
        "Desafio Criativo · Bootcamp Heineken x DIO</p>",
        unsafe_allow_html=True,
    )
