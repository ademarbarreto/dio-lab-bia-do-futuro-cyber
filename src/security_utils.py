"""
Funções puras da camada de segurança do Agente ADE.

Extraídas de app_secure.py para permitir testes automatizados (pytest) sem
precisar inicializar o Streamlit, carregar a base de conhecimento ou chamar a
API da OpenAI. Nenhuma função aqui depende de st.session_state, arquivos em
disco ou rede.
"""

import re
import html
import hashlib
import unicodedata

MAX_PERGUNTA_CHARS = 500  # limite de tamanho do input do usuário

PRICE_INPUT_1K = 0.005   # USD por 1k tokens de entrada
PRICE_OUTPUT_1K = 0.015  # USD por 1k tokens de saída

# ==============================================================
# LLM01 - Padrões de tentativa de prompt injection
# ==============================================================
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

# ==============================================================
# LLM02 - Termos proibidos na resposta (normalizados, sem acento)
# ==============================================================
TERMOS_PROIBIDOS = [
    "recomendo", "recomendaria", "invista", "invistam", "aplique", "aplicar em",
    "compre", "comprar", "venda", "vender", "melhor investimento", "alta rentabilidade",
    "sugiro fortemente", "vale a pena colocar", "garanto retorno",
    "e uma otima oportunidade de investir",
]


def hash_pergunta(texto: str) -> str:
    """Gera um hash da pergunta para log de auditoria sem persistir o conteúdo
    literal (mitigação de exposição de dados pessoais em log - LGPD)."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def calcular_custo(tokens_in: int, tokens_out: int) -> float:
    """Calcula o custo estimado (USD) de uma requisição à API a partir do uso
    de tokens de entrada e saída."""
    custo_in = (tokens_in / 1000) * PRICE_INPUT_1K
    custo_out = (tokens_out / 1000) * PRICE_OUTPUT_1K
    return round(custo_in + custo_out, 6)


def contem_tentativa_injection(texto: str) -> bool:
    """Detecta heuristicamente tentativas de prompt injection no texto do
    cliente, com base em PADROES_INJECTION."""
    texto_norm = texto.lower()
    return any(re.search(p, texto_norm) for p in PADROES_INJECTION)


def normalizar(texto: str) -> str:
    """Remove acentuação e normaliza para facilitar checagem de termos
    proibidos (ex.: 'invísta' e 'invista' devem ser tratados igual)."""
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def sanitizar_pergunta(texto: str, max_chars: int = MAX_PERGUNTA_CHARS) -> str:
    """Remove caracteres de controle e limita o tamanho do input do cliente."""
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", texto)  # caracteres de controle
    return texto.strip()[:max_chars]


def resposta_viola_compliance(resposta: str, termos_proibidos=TERMOS_PROIBIDOS) -> bool:
    """Verifica se uma resposta do modelo viola as regras de compliance
    (LLM02 - Insecure Output Handling), normalizando acentos antes de
    comparar contra a lista de termos proibidos."""
    resposta_normalizada = normalizar(resposta)
    return any(normalizar(t) in resposta_normalizada for t in termos_proibidos)


def formatar_real(valor):
    """Formata um valor numérico para o padrão de moeda brasileira (Real)."""
    try:
        valor = float(valor)
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return valor


def escapar(texto: str) -> str:
    """Escapa HTML antes de injetar texto em blocos com unsafe_allow_html,
    para evitar XSS via pergunta do cliente ou resposta do modelo (o layout
    usa divs estilizados em vez de st.chat_message, então o escape manual é
    obrigatório aqui)."""
    return html.escape(texto).replace("\n", "<br>")
