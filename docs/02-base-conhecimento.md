# Base de Conhecimento

## Dados Utilizados

Descreva se usou os arquivos da pasta `data`, por exemplo:

| Arquivo | Formato | Utilização no Agente |
|---------|---------|---------------------|
| `historico_atendimento.csv` | CSV | Contextualizar interações anteriores para dara continuidade no atendimento |
| `perfil_investidor.json` | JSON | Personalizar recomendações a partir das informações sobre o perfil do investidor |
| `produtos_financeiros.json` | JSON | Sugerir produtos adequados ao perfil e conhecer os produtos financeiros disponíveis |
| `transacoes.csv` | CSV | Analisar padrão de gastos do cliente para analisar o perfil de gastos do cliente |


---

## Adaptações nos Dados

> Você modificou ou expandiu os dados mockados? Descreva aqui.

Utilizei os dados mockados sem modificação nas informações.

---

## Estratégia de Integração

### Como os dados são carregados?
> Descreva como seu agente acessa a base de conhecimento.

##### ==============================================================
### Resolução de paths
##### ==============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

Os dados são carregados via código através da função em python carregar_dados() conforme descrita abaixo:

##### ==============================================================
### Carregar dados da Base de Conhecimento
##### ==============================================================
  
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

### Como os dados são usados no prompt?

Os dados foram carregados via código conforme descrito acima  e injetados no prompt. Para sistemas mais robustos é necessário que estes dados sejam carregados dinamicamente para permitir a atualização e acréscimo de novo dados. O código acima permite que estes dados possam carregar dinamicamente, pois podemos executá-lo a cada mudança da nossa base de dados.

### DADOS DO CLIENTE - Arquivo data/perfil_investidor.json
```
{
  "nome": "João Silva",
  "idade": 32,
  "profissao": "Analista de Sistemas",
  "renda_mensal": 5000.00,
  "perfil_investidor": "moderado",
  "objetivo_principal": "Construir reserva de emergência",
  "patrimonio_total": 15000.00,
  "reserva_emergencia_atual": 10000.00,
  "aceita_risco": false,
  "metas": [
    {
      "meta": "Completar reserva de emergência",
      "valor_necessario": 15000.00,
      "prazo": "2026-06"
    },
    {
      "meta": "Entrada do apartamento",
      "valor_necessario": 50000.00,
      "prazo": "2027-12"
    }
  ]
}

```



### HISTÓRICO DO CLIENTE - data/historico_atendimento.csv

```
data,canal,tema,resumo,resolvido
2025-09-15,chat,CDB,Cliente perguntou sobre rentabilidade e prazos,sim
2025-09-22,telefone,Problema no app,Erro ao visualizar extrato foi corrigido,sim
2025-10-01,chat,Tesouro Selic,Cliente pediu explicação sobre o funcionamento do Tesouro Direto,sim
2025-10-12,chat,Metas financeiras,Cliente acompanhou o progresso da reserva de emergência,sim
2025-10-25,email,Atualização cadastral,Cliente atualizou e-mail e telefone,sim
```


### PRODUTOS DISPONÍVEIS PARA O CLIENTE data/produtos_financeiros.json

```
[
  {
    "nome": "Tesouro Selic",
    "categoria": "renda_fixa",
    "risco": "baixo",
    "rentabilidade": "100% da Selic",
    "aporte_minimo": 30.00,
    "indicado_para": "Reserva de emergência e iniciantes"
  },
  {
    "nome": "CDB Liquidez Diária",
    "categoria": "renda_fixa",
    "risco": "baixo",
    "rentabilidade": "102% do CDI",
    "aporte_minimo": 100.00,
    "indicado_para": "Quem busca segurança com rendimento diário"
  },
  {
    "nome": "LCI/LCA",
    "categoria": "renda_fixa",
    "risco": "baixo",
    "rentabilidade": "95% do CDI",
    "aporte_minimo": 1000.00,
    "indicado_para": "Quem pode esperar 90 dias (isento de IR)"
  },
  {
    "nome": "Fundo Multimercado",
    "categoria": "fundo",
    "risco": "medio",
    "rentabilidade": "CDI + 2%",
    "aporte_minimo": 500.00,
    "indicado_para": "Perfil moderado que busca diversificação"
  },
  {
    "nome": "Fundo de Ações",
    "categoria": "fundo",
    "risco": "alto",
    "rentabilidade": "Variável",
    "aporte_minimo": 100.00,
    "indicado_para": "Perfil arrojado com foco no longo prazo"
  }
]
```

### HISTÓRICO DE TRANSAÇÕES data/transacoes.csv

```
data,descricao,categoria,valor,tipo
2025-10-01,Salário,receita,5000.00,entrada
2025-10-02,Aluguel,moradia,1200.00,saida
2025-10-03,Supermercado,alimentacao,450.00,saida
2025-10-05,Netflix,lazer,55.90,saida
2025-10-07,Farmácia,saude,89.00,saida
2025-10-10,Restaurante,alimentacao,120.00,saida
2025-10-12,Uber,transporte,45.00,saida
2025-10-15,Conta de Luz,moradia,180.00,saida
2025-10-20,Academia,saude,99.00,saida
2025-10-25,Combustível,transporte,250.00,saida
```

---

## Exemplo de Contexto Montado

> Mostre um exemplo de como os dados são formatados para o agente.

Os dados abaixo sintetizados são baseados única e exclusivamente da Base de Dados de Conhecimento. O objetivo é otimizar tokens, pois diminuir os custos no nosso modelo de LLM, sem comprometer a essência do problema que queremos resolver.

```

CLIENTE:
- Nome:  "João Silva"
- Idade: "32"
- Profissão: "Analista de Sistemas"
- Perfil de investidor: "moderado"

OBJETIVO FINANCEIRO:
- Objetivo Principal : "Construir reserva de emergência"

PATRIMÔNIO:
Total: R$ 15000.00
Reserva de emergência: R$ 10000.00

RESUMO DE GASTOS MENSAIS POR CATEGORIA:
- Moradia: R$ 1380
- Alimentação: R$ 570
- Transporte: R$ 295
- Saúde: R$ 188
- Lazer: R$ 55.90
- Total de saída: R$ 2.488,90

HISTÓRICO DE ATENDIMENTOS:

- tema
- CDB
- Problema no app
- Tesouro Selic
- Metas financeiras
- Atualização cadastral


PRODUTOS FINANCEIROS DISPONÍVEIS:
- Tesouro Selic
- CDB Liquidez Diária
- LCI/LCA
- Fundo Multimercado
- Fundo de Ações
...
```
