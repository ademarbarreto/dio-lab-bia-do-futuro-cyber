import streamlit as st
from dotenv import load_dotenv
import os
import json
import pandas as pd
from openai import OpenAI
from pathlib import Path
import time

# =========================
# CONFIGURAÇÃO DE CUSTO LLM
# =========================

PRICE_INPUT_1K = 0.005   # USD por 1k tokens de entrada
PRICE_OUTPUT_1K = 0.015  # USD por 1k tokens de saída

LIMITE_AVISO = 0.05      # USD
LIMITE_CRITICO = 0.10    # USD

# ==============================================================
# Resolução de paths
# ==============================================================
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ENV_PATH = BASE_DIR / ".env"
BANNER_PATH = BASE_DIR / "images" / "banner-ade.svg"

# ==============================================================
# Carregar variáveis de ambiente (.env)
# ==============================================================
load_dotenv(dotenv_path=ENV_PATH)

api_key = os.getenv("OPENAI_API_KEY")
model_name = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

# ==============================================================
# Configuração inicial do Streamlit
# ==============================================================
st.set_page_config(
    page_title="ADE - Gestor Pessoal Financeiro",
    layout="centered"
)

if "custo_total" not in st.session_state:
    st.session_state.custo_total = 0.0


banner_exibido = False
if BANNER_PATH.exists():
    try:
        st.image(str(BANNER_PATH), use_container_width=True)
        banner_exibido = True
    except Exception:
        banner_exibido = False

if not banner_exibido:
    st.title("💰 ADE - Gestor Pessoal Financeiro")

st.caption("Gestor Pessoal Financeiro, sem recomendações de investimento.")

if not api_key:
    st.error("❌ OPENAI_API_KEY não encontrada no arquivo .env")
    st.stop()

client = OpenAI(api_key=api_key)

# ==============================================================
# Carregar dados da Base de Conhecimento
# ==============================================================
@st.cache_data
def carregar_dados():
    """
    Load financial data from JSON and CSV files.
    
    Reads investor profile and financial products from JSON files,
    and loads attendance history and transaction data from CSV files.
    
    Returns
    -------
    tuple
        A tuple containing:
        - perfil (dict): Investor profile data from 'perfil_investidor.json'
        - produtos (dict): Financial products data from 'produtos_financeiros.json'
        - historico (pd.DataFrame): Attendance history data from 'historico_atendimento.csv'
        - transacoes (pd.DataFrame): Transaction data from 'transacoes.csv'
    
    Raises
    ------
    FileNotFoundError
        If any of the required data files are not found in DATA_DIR.
    json.JSONDecodeError
        If JSON files are malformed.
    """
    with open(DATA_DIR / "perfil_investidor.json", encoding="utf-8") as f:
        perfil = json.load(f)

    with open(DATA_DIR / "produtos_financeiros.json", encoding="utf-8") as f:
        produtos = json.load(f)

    historico = pd.read_csv(DATA_DIR / "historico_atendimento.csv")
    transacoes = pd.read_csv(DATA_DIR / "transacoes.csv")

    return perfil, produtos, historico, transacoes


perfil, produtos, historico, transacoes = carregar_dados()

def formatar_real(valor):
    """
    Formata um valor numérico para o padrão de moeda brasileira (Real).
    
    Converte o valor para float e o formata com separador de milhares (ponto)
    e separador decimal (vírgula), de acordo com o padrão brasileiro.
    
    Args:
        valor: Um valor numérico (int, float ou string) a ser formatado.
    
    Returns:
        str: Uma string formatada no padrão de moeda brasileira (R$ X.XXX,XX).
             Se a conversão para float falhar, retorna o valor original.
    
    Raises:
        None: Trata exceções internamente e retorna o valor original em caso de erro.
    
    Examples:
        >>> formatar_real(1234.56)
        'R$ 1.234,56'
        >>> formatar_real("5000")
        'R$ 5.000,00'
        >>> formatar_real("invalido")
        'invalido'
    """
    try:
        valor = float(valor)
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return valor

def calcular_custo(tokens_in: int, tokens_out: int) -> float:
    """
    Calculate the cost of API usage based on input and output tokens.

    Args:
        tokens_in (int): Number of input tokens consumed.
        tokens_out (int): Number of output tokens generated.

    Returns:
        float: Total cost rounded to 6 decimal places, calculated as the sum of
               input token cost and output token cost based on their respective
               per-1K-token pricing rates.
    """
    custo_in = (tokens_in / 1000) * PRICE_INPUT_1K
    custo_out = (tokens_out / 1000) * PRICE_OUTPUT_1K
    return round(custo_in + custo_out, 6)


# ==============================================================
# Pré-processamento
# ==============================================================
resumo_transacoes = (
    transacoes
    .groupby("categoria")["valor"]
    .sum()
    .reset_index()
)

historico_recente = historico.tail(3)

# ==============================================================
# Contexto
# ==============================================================
contexto = f"""
CLIENTE:
Nome: {perfil['nome']}
Idade: {perfil['idade']}
Profissão: {perfil['profissao']}
Perfil de investidor: {perfil['perfil_investidor']}

OBJETIVO FINANCEIRO:
{perfil['objetivo_principal']}

PATRIMÔNIO:
Total: R$ {perfil['patrimonio_total']}
Reserva de emergência: R$ {perfil['reserva_emergencia_atual']}

RESUMO DE GASTOS MENSAIS POR CATEGORIA:
{resumo_transacoes.to_string(index=False)}

HISTÓRICO DE ATENDIMENTOS (últimos 3):
{historico_recente.to_string(index=False)}

PRODUTOS FINANCEIROS DISPONÍVEIS:
{json.dumps(produtos, indent=2, ensure_ascii=False)}
"""

# ==============================================================
# Prompt de sistema
# ==============================================================
system_prompt = """
Você é o ADE - Assistente Digital de Investimentos.

OBJETIVO:
Ensinar conceitos de finanças pessoais de forma simples, usando apenas os dados fornecidos.

REGRAS OBRIGATÓRIAS:
- NUNCA recomende investimentos específicos.
- NÃO utilize verbos imperativos de investimento.
- Explique apenas conceitos gerais e educativos.
- Responda EXCLUSIVAMENTE com base no CONTEXTO fornecido.
- NÃO faça suposições nem complete informações ausentes.
- Se a informação não estiver no contexto, diga claramente que não sabe.
- Linguagem simples, clara e acessível.
- Máximo de 3 parágrafos.
- Sempre pergunte se o cliente entendeu e se deseja mais explicações.
- Em caso de ambiguidade, peça esclarecimentos.
- Mantenha ética e conformidade regulatória.
"""

# ==============================================================
# Interface do usuário
# ==============================================================
st.subheader("📌 Pergunta do cliente")

pergunta = st.text_area(
    "Digite sua pergunta sobre suas finanças pessoais:",
    placeholder="Ex: Como posso organizar melhor meus gastos mensais?"
)

botao = st.button("💬 Perguntar ao ADE")

# ==============================================================
# Execução
# ==============================================================
if botao and pergunta:
    with st.spinner("Analisando sua pergunta..."):
        inicio = time.time()
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"""
CONTEXTO:
{contexto}

PERGUNTA DO CLIENTE:
{pergunta}
"""
                }
            ],
            temperature=0.2,
            max_tokens=300
        )

        latencia = time.time() - inicio
        resposta = response.choices[0].message.content

        # Métricas de tokens
        usage = response.usage

        tokens_entrada = usage.prompt_tokens if usage else 0
        tokens_saida = usage.completion_tokens if usage else 0
        tokens_total = usage.total_tokens if usage else 0
        custo_request = calcular_custo(tokens_entrada, tokens_saida)
        st.session_state.custo_total += custo_request

        # Validação simples de compliance
        termos_proibidos = [
            "recomendo",
            "invista",
            "aplique",
            "compre",
            "melhor investimento",
            "alta rentabilidade"
        ]

        if any(t in resposta.lower() for t in termos_proibidos):
            st.error("⚠️ A resposta violou as regras de conformidade.")
        else:
            st.success("Resposta do ADE:")
            st.write(resposta)
            # st.markdown("---")
            # st.caption(
            # f"💰 **Custo da requisição:** ${custo_request:.4f} | "
            # f"📊 **Custo total da sessão:** ${st.session_state.custo_total:.4f}")

            if st.session_state.custo_total >= LIMITE_CRITICO:
                st.warning("🚨 Limite crítico de custo atingido! Uso bloqueado.")
            elif st.session_state.custo_total >= LIMITE_AVISO:
                st.warning("⚠️ Atenção: custo da sessão se aproximando do limite.")

            
            st.write("-----------------------------------------------------------") 
            st.write("Métricas de uso")
            st.write(f"tokens_entrada: {tokens_entrada}\n")
            st.write(f"tokens_saida: {tokens_saida}\n")
            st.write(f"tokens_total: {tokens_total}\n")
            st.write(f"latência: {latencia:.2f} segundos\n")
            st.write(f"custo_requisição: ${custo_request:.4f}\n")
            st.write(f"Custo total da sessão: ${st.session_state.custo_total:.4f}\n")
            st.write("-----------------------------------------------------------") 

elif botao:
    st.warning("Digite uma pergunta antes de enviar.")