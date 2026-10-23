# Integracao TheMembers Checkout

## Objetivo
Receber webhooks do checkout do TheMembers com seguranca, processar em tempo quase real e manter trilha de auditoria para associados, assinaturas, contas a receber e recebimentos.

## Referencias oficiais
- Webhooks do checkout: https://docs.themembers.com.br/pt-BR/checkouts/webhooks
- Payload de `transaction.approved` para assinatura: https://docs.themembers.com.br/pt-BR/checkouts/webhooks/events/purchases/subscription-transactions-approved

## O que foi implementado
- Integracao por `business` em `business_integrations`
- Log tecnico de cada webhook em `webhook_events`
- Endpoint de entrada:
  - `POST /api/integrations/themembers/{webhook_path_token}/checkout-webhook`
- Painel operacional:
  - `GET /app/business-control/integrations`
- Mapeamento do produto externo no cadastro de planos:
  - `membership_plans.external_product_id`
  - `membership_plans.external_reference_id`
- Vinculos externos persistidos:
  - `members.external_customer_id`
  - `subscriptions.external_subscription_id`
  - `receivables.external_invoice_id`
  - `receivables.external_order_id`
  - `receipts.external_transaction_id`
- Baixa automatica no financeiro:
  - `receipt` criado automaticamente
  - `business_cash_entry` de entrada criado automaticamente
  - categoria `PRD` para produtos avulsos e `MRR/ATV/2VIA` para receitas recorrentes

## Modelo de seguranca
- A URL do webhook inclui um `webhook_path_token` aleatorio por business.
- O token de seguranca enviado em `X-Signature` e comparado com `hmac.compare_digest`.
- O segredo nao fica salvo em texto puro; o banco guarda `webhook_secret_hash` e `webhook_secret_hint`.
- Reenvios nao duplicam efeito financeiro porque o evento e tratado por `event_key`.
- Eventos com falha ficam persistidos e podem ser reprocessados pelo painel.

## Eventos suportados
- `release.access`
  - cria/atualiza associado
  - cria/reativa assinatura quando o payload traz `subscription`
  - concilia pagamento inicial quando o payload traz `transaction` e `order`
  - tambem trata compra avulsa quando nao existe `subscription`
- `transaction.approved`
  - concilia pagamento recorrente de plano mensal ou anual
  - cria ou reutiliza titulo por competencia
  - registra recebimento e avanca `next_billing_on`
  - tambem registra venda avulsa de cursos e outros produtos sem criar assinatura
- `order.canceled`
  - marca pedido de cancelamento
  - suspende assinatura quando aplicavel
- `subscription.canceled`
  - mesmo tratamento operacional de pedido de cancelamento
- `revoke.access`
  - cancela acesso
  - cancela assinatura e associado
- `transaction.refunded`
- `transaction.charged_back`
- `transaction.pending_refund`
  - marcam o titulo conciliado como `REFUNDED`

## Ordem dos eventos
O TheMembers pode entregar eventos em ordens diferentes. O fluxo foi preparado para isso:
- `transaction.approved` pode chegar antes de `release.access`
- `release.access` pode chegar com `transaction` e `order` no mesmo payload
- compras avulsas podem chegar sem `subscription`
- eventos repetidos retornam `duplicate` e nao criam lancamentos extras

## Regras comerciais importantes
- plano mensal
  - gera competencia mensal
  - alimenta `MRR`
- plano anual
  - gera cobranca anual
  - `next_billing_on` avanca 12 meses
  - o dashboard usa equivalente mensal para `MRR`
- produto avulso
  - nao cria assinatura
  - gera `receivable` sem `subscription_id`
  - baixa automaticamente no caixa como receita de produto

## Operacao em escala
Para base alta, o fluxo atual evita baixa manual:
- cada `transaction.approved` cria ou reutiliza titulo e recebimento
- a entrada ja cai no fluxo de caixa
- o dashboard mostra crescimento diario dos ultimos 14 dias
- o dashboard destaca receita de hoje, receita dos ultimos 7 dias, novas assinaturas, novos associados e vendas avulsas do mes

Se a volumetria crescer muito alem do processamento sincrono atual, o proximo passo recomendado e adicionar fila assincrona para consumo dos webhooks, mantendo o mesmo contrato de payload e idempotencia.

## Fluxo operacional no FinSight
1. Provisionar a integracao em `Business Control > Integracoes`
2. Copiar a `Webhook URL`
3. Copiar o token de seguranca exibido no provisionamento ou rotacao
4. Configurar no TheMembers os eventos desejados
5. Preencher `product_id` ou `reference_id` nos planos em `Business Control > Planos`
6. Monitorar `Eventos recentes` e reprocessar falhas quando necessario

## Regras de mapeamento de plano
O FinSight tenta localizar o plano nesta ordem:
1. `reference_id`
2. `product_id`
3. nome exato do plano (`title`)

Se nenhum mapeamento funcionar, o evento fica como `FAILED`.

## Respostas do webhook
- `200 OK`
  - `processed`
  - `ignored`
  - `duplicate`
- `202 Accepted`
  - `failed` com evento salvo para reprocessamento
- `401 Unauthorized`
  - token `X-Signature` ausente ou invalido
- `404 Not Found`
  - `webhook_path_token` nao reconhecido
- `422 Unprocessable Entity`
  - payload invalido para a rotina atual

## Estrutura relevante do banco
- `business_integrations`
  - integracao ativa do provider
  - token de URL
  - hash do segredo
  - ultimo recebimento/processamento
- `webhook_events`
  - tipo do evento
  - `event_key`
  - payload e headers sanitizados
  - status `RECEIVED`, `PROCESSED`, `IGNORED`, `FAILED`
  - erro e contador de tentativas

## Testes locais com curl
Substitua:
- `{URL}` pela URL provisionada no painel
- `{TOKEN}` pelo token de seguranca atual

### `release.access`
```bash
curl -X POST "{URL}" \
  -H "Content-Type: application/json" \
  -H "X-Signature: {TOKEN}" \
  -d '{
    "payload": {
      "id": "evt-release-local-1",
      "event": "release.access",
      "data": {
        "customer": {
          "id": "cust-local-1",
          "name": "Associada Local",
          "email": "local@teste.com"
        },
        "main_product": {
          "id": "soomei-start",
          "reference_id": "TM-SOOMEI-START",
          "title": "Soomei Start"
        },
        "subscription": {
          "code": "SUB-LOCAL-1",
          "starts_at": "2026-03-13T10:00:00Z",
          "invoice": {
            "code": "INV-LOCAL-1",
            "expire_at": "2026-03-13T00:00:00Z",
            "amount": 4990
          }
        },
        "transaction": {
          "id": "TRX-LOCAL-1",
          "value": 4990,
          "method": "pix",
          "paid_at": "2026-03-13T10:02:00Z"
        },
        "order": {
          "id": "ORD-LOCAL-1",
          "total": 4990,
          "created_at": "2026-03-13T10:00:00Z"
        }
      }
    }
  }'
```

### `transaction.approved`
```bash
curl -X POST "{URL}" \
  -H "Content-Type: application/json" \
  -H "X-Signature: {TOKEN}" \
  -d '{
    "payload": {
      "id": "evt-transaction-local-2",
      "event": "transaction.approved",
      "data": {
        "customer": {
          "id": "cust-local-1",
          "name": "Associada Local",
          "email": "local@teste.com"
        },
        "main_product": {
          "id": "soomei-start",
          "reference_id": "TM-SOOMEI-START",
          "title": "Soomei Start"
        },
        "subscription": {
          "code": "SUB-LOCAL-1",
          "invoice": {
            "code": "INV-LOCAL-2",
            "expire_at": "2026-04-05T00:00:00Z",
            "amount": 4990
          }
        },
        "transaction": {
          "id": "TRX-LOCAL-2",
          "value": 4990,
          "method": "pix",
          "paid_at": "2026-04-05T08:00:00Z"
        },
        "order": {
          "id": "ORD-LOCAL-2",
          "total": 4990,
          "created_at": "2026-04-05T07:58:00Z"
        }
      }
    }
  }'
```

### `transaction.approved` de produto avulso
```bash
curl -X POST "{URL}" \
  -H "Content-Type: application/json" \
  -H "X-Signature: {TOKEN}" \
  -d '{
    "payload": {
      "id": "evt-course-local-1",
      "event": "transaction.approved",
      "data": {
        "customer": {
          "id": "cust-course-1",
          "name": "Associada Curso",
          "email": "curso@teste.com"
        },
        "main_product": {
          "id": "curso-soomei",
          "reference_id": "TM-CURSO-SOOMEI",
          "title": "Curso Receita Recorrente"
        },
        "transaction": {
          "id": "TRX-COURSE-1",
          "value": 2990,
          "method": "pix",
          "paid_at": "2026-03-13T11:00:00Z"
        },
        "order": {
          "id": "ORD-COURSE-1",
          "total": 2990,
          "created_at": "2026-03-13T10:58:00Z"
        }
      }
    }
  }'
```

### `order.canceled`
```bash
curl -X POST "{URL}" \
  -H "Content-Type: application/json" \
  -H "X-Signature: {TOKEN}" \
  -d '{
    "payload": {
      "id": "evt-cancel-local-1",
      "event": "order.canceled",
      "data": {
        "customer": {
          "id": "cust-local-1",
          "name": "Associada Local",
          "email": "local@teste.com"
        },
        "main_product": {
          "id": "soomei-start",
          "reference_id": "TM-SOOMEI-START",
          "title": "Soomei Start"
        },
        "subscription": {
          "code": "SUB-LOCAL-1"
        }
      }
    }
  }'
```

## Roteiro recomendado de teste de integracao
1. Provisionar a integracao e validar `X-Signature` correto.
2. Enviar `release.access` e confirmar:
   - associado criado
   - assinatura ativa
   - titulo criado e pago
3. Reenviar o mesmo payload e confirmar status `duplicate`.
4. Enviar `transaction.approved` de renovacao e confirmar:
   - novo titulo
   - novo recebimento
   - `next_billing_on` avancado
5. Enviar `transaction.approved` de produto avulso e confirmar:
   - nenhum `subscription` novo
   - `receivable` sem `subscription_id`
   - `receipt` criado
   - entrada refletida no caixa
6. Enviar `order.canceled` e confirmar assinatura `SUSPENDED`.
7. Enviar `revoke.access` e confirmar assinatura e associado `CANCELED`.
8. Enviar payload com plano sem mapeamento e confirmar:
   - evento `FAILED`
   - reprocessamento pelo painel apos corrigir o plano

## Testes automatizados incluidos
- `tests/test_themembers_integration.py`
  - criacao do associado via `release.access`
  - plano anual avancando `next_billing_on` em 12 meses
  - venda avulsa sem assinatura
  - idempotencia
  - cancelamento e revogacao
  - reprocessamento de falha
  - rejeicao de assinatura invalida

## Observacoes
- Em SQLite de desenvolvimento, a aplicacao faz reparo automatico do schema legado para acomodar as colunas novas antes do uso do modulo.
- O reprocessamento opera sobre o evento persistido; ele nao depende de o provider reenviar o payload.
