# agents.md - FinSight

## Produto
Aplicacao web mobile-first para organizar financas pessoais, projetar saldo futuro e apoiar plano de pagamento de dividas.

## MVP
- auth (login/logout/reset)
- contas/categorias
- transacoes
- recorrencias
- cartao + parcelas por competencia
- forecast 6 meses com semaforo
- dashboard mobile-first

## Stack
- Python 3.12+
- FastAPI
- SQLAlchemy 2.0 + Alembic
- Postgres
- Jinja2 + HTMX + TailwindCSS
- Sessao segura + CSRF

## Arquitetura
- `app/domain`
- `app/application`
- `app/infrastructure`
- `app/web`

