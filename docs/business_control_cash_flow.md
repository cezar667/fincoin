# Business Control Finance

## Objetivo

Esta fase adiciona ao modulo `Business Control` o controle financeiro da empresa com foco em:

- fluxo de caixa empresarial
- uso do capital captado
- financiamento com parcelas
- visibilidade do caixa atual e das saidas por categoria/centro de custo
- crescimento diario da receita e da base
- baixa automatica das entradas vindas do checkout

## Rotas web

- `GET /app/business-control`
  - dashboard consolidado da empresa
- `GET /app/business-control/cash-flow`
  - extrato, saldos por conta e formulario de lancamentos
- `POST /app/business-control/cash-flow`
  - cria um `BusinessCashEntry`
- `GET /app/business-control/fundings`
  - contratos de credito e agenda de parcelas
- `POST /app/business-control/fundings`
  - cria um `BusinessFunding` e gera a entrada do credito + parcelas
- `POST /app/business-control/fundings/installments/{installment_id}/pay`
  - quita a parcela e gera a saida correspondente no caixa

## Entidades novas

- `BusinessCashEntry`
  - livro-caixa empresarial
  - suporta `direction`, `activity_type`, conta, categoria, centro de custo e vinculo opcional ao financiamento
- `BusinessFunding`
  - contrato de credito captado pela empresa
- `BusinessFundingInstallment`
  - agenda de parcelas com status `OPEN`, `PAID` e `OVERDUE`

## Regras principais

- ao cadastrar um financiamento o sistema:
  - cria o contrato
  - gera uma entrada de caixa do principal captado
  - gera toda a agenda de parcelas
- ao quitar uma parcela o sistema:
  - marca a parcela como paga
  - cria uma saida de caixa na conta de liquidacao do contrato
- ao registrar um recebimento de associado o sistema:
  - mantem o contas a receber
  - cria uma entrada de caixa operacional
- ao receber webhook do TheMembers o sistema:
  - cria ou atualiza associado
  - cria assinatura quando houver `subscription`
  - cria ou reutiliza o titulo
  - registra o recebimento
  - cria a entrada de caixa automaticamente
- produtos avulsos como cursos:
  - nao criam assinatura
  - entram como receita avulsa e alimentam o caixa
- planos anuais:
  - avancam a renovacao em 12 meses
  - entram no `MRR` pelo valor mensal equivalente
- lancamentos manuais podem ser vinculados a um financiamento para mostrar onde o credito foi consumido

## Indicadores expostos no dashboard

- caixa atual
- entradas e saidas do mes
- saldo liquido do mes
- capital captado
- capital preservado
- capital consumido
- divida em aberto
- parcelas com vencimento nos proximos 30 dias
- distribuicao de gastos por categoria e centro de custo
- receita de hoje
- receita dos ultimos 7 dias
- novos associados no dia
- novas assinaturas no dia
- vendas avulsas no mes
- trilha visual de crescimento dos ultimos 14 dias

## Seed demo

O `scripts/seed_demo.py` agora cria:

- a empresa demo `Soomei`
- um credito inicial de `R$ 100.000,00`
- gastos iniciais vinculados ao credito
- associados, planos mensal e anual, assinatura e contas a receber
- categorias de receita recorrente e produto avulso

## Roteiro de teste manual

1. Rodar `alembic upgrade head`
2. Rodar `python scripts/seed_demo.py` usando a `.venv`
3. Acessar `/app/business-control`
4. Conferir no dashboard:
   - `Capital captado`
   - `Credito preservado`
   - `Parcelas em 30 dias`
5. Acessar `/app/business-control/cash-flow`
   - criar uma nova saida vinculada ao credito
   - confirmar que a saida aparece no extrato
6. Acessar `/app/business-control/fundings`
   - quitar uma parcela
   - confirmar que a baixa aparece na agenda e no caixa
7. Acessar `/app/business-control/receivables`
   - registrar um recebimento
   - confirmar a entrada em `/app/business-control/cash-flow`
8. Disparar um webhook `transaction.approved` do TheMembers para curso ou produto avulso
   - confirmar que nao houve baixa manual
   - confirmar nova entrada no caixa
   - confirmar atualizacao dos cards de crescimento diario

## Testes automatizados

- `tests/test_business_control_finance.py`
  - criacao do financiamento e da entrada de caixa
  - baixa da parcela com reflexo no caixa
  - recebimento operacional criando entrada no caixa
  - venda avulsa via webhook refletindo em caixa e no painel de crescimento
