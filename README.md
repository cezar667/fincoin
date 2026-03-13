# FinSight

Base inicial do MVP com FastAPI, SQLAlchemy, Alembic, autenticacao por sessao e forecast.
Agora inclui as Fases 1 e 2 do modulo `Business Control`, com isolamento multi-business e operacao de associados/assinaturas.

## Rodar local
1. `pip install -e .[dev]`
2. (Opcional) copie `.env.example` para `.env`
3. Rode as migracoes: `alembic upgrade head`
4. `python scripts/seed_demo.py` (opcional)
5. `uvicorn app.main:app --reload`
6. Abra `http://127.0.0.1:8000/login` e, apos login, use `http://127.0.0.1:8000/app/transactions` para:
   - cadastrar contas, categorias e cartoes
   - lancar receitas/despesas
   - cadastrar parcelamentos
   - importar CSV de cartao: `http://127.0.0.1:8000/app/import`
   - configurar o modulo empresarial em `http://127.0.0.1:8000/app/business-control`

## Sem Postgres local
- Se `DATABASE_URL` apontar para Postgres indisponivel, a aplicacao faz fallback automatico para `sqlite:///./finsight.db`.
- Para forcar SQLite no ambiente atual:
  - PowerShell: `$env:DATABASE_URL="sqlite+pysqlite:///./finsight.db"`

## Alembic em banco dev legado
- Se o banco SQLite local ja tiver sido criado por `Base.metadata.create_all`, o `alembic upgrade head` agora faz bootstrap automatico do `alembic_version` antes de aplicar novas migracoes.
- Isso evita a falha de recriar tabelas-base em `finsight.db` durante o desenvolvimento.

## Importacao CSV de cartao (staging + apply)
- Fluxo: upload CSV -> `external_transactions` (staging) -> revisao -> apply para `transactions`.
- Rotas principais:
  - `GET /app/import`
  - `POST /api/import/csv`
  - `GET /app/import/{import_file_id}/review`
  - `GET /api/import/{import_file_id}/items?status=PENDING`
  - `POST /api/import/{import_file_id}/apply`
  - `POST /api/import/items/{external_tx_id}/set-mapping`
  - `POST /api/import/items/{external_tx_id}/reject`
- Limite de upload no MVP: 5MB por arquivo.

## Testes
- Rodar suite completa: `.venv\Scripts\python.exe -m pytest -q`
- Novos testes da feature:
  - `tests/test_import_utils.py`
  - `tests/test_import_pipeline.py`
  - `tests/test_business_control.py`

## Business Control - Fase 1
- Rotas principais:
  - `GET /app/business-control`
  - `GET /app/business-control/businesses`
  - `GET /app/business-control/accounts`
  - `GET /app/business-control/categories`
  - `GET /app/business-control/cost-centers`
- Escopo atual:
  - multi-business por `business_id`
  - contas empresariais
  - categorias empresariais
  - centros de custo
  - auditoria de acoes criticas
  - seed inicial da Soomei no `scripts/seed_demo.py`

## Business Control - Fase 2
- Rotas principais:
  - `GET /app/business-control/members`
  - `GET /app/business-control/membership-plans`
  - `GET /app/business-control/subscriptions`
  - `GET /app/business-control/receivables`
  - `GET /app/business-control/integrations`
- Escopo atual:
  - associados com status operacional
  - planos de assinatura
  - assinaturas com geracao automatica de cobrancas
  - contas a receber e baixa de recebimentos
  - dashboard visual com jornada do associado e mapa operacional

## Integracao TheMembers
- Rotas principais:
  - `GET /app/business-control/integrations`
  - `POST /api/integrations/themembers/{webhook_path_token}/checkout-webhook`
- Escopo atual:
  - provisionamento do webhook do TheMembers por business
  - token de seguranca com comparacao segura
  - persistencia de eventos recebidos para auditoria e reprocessamento
  - idempotencia por `event_key`
  - sincronizacao de `release.access`, `transaction.approved`, cancelamentos e estornos
  - mapeamento de `product_id` / `reference_id` no cadastro de planos
- Documentacao detalhada:
  - `docs/themembers_checkout_integration.md`
