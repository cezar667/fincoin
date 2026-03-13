from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application.dto.business_control_dto import (
    CreateBusinessDTO,
    UpsertBusinessAccountDTO,
    UpsertBusinessCategoryDTO,
    UpsertCostCenterDTO,
)
from app.infrastructure.db.models.audit_log import AuditLog
from app.infrastructure.db.models.business import Business
from app.infrastructure.db.models.business_account import BusinessAccount
from app.infrastructure.db.models.business_category import BusinessCategory
from app.infrastructure.db.models.cost_center import CostCenter
from app.infrastructure.db.models.enums import (
    AuditAction,
    BusinessAccountType,
    BusinessCategoryKind,
)


SOOMEI_ACCOUNTS = [
    {
        "name": "Conta Operacional",
        "type": BusinessAccountType.BANK,
        "institution_name": "Banco principal",
        "initial_balance_cents": 0,
    },
    {
        "name": "Carteira de Recebimentos",
        "type": BusinessAccountType.RECEIVABLE,
        "institution_name": "Gateway",
        "initial_balance_cents": 0,
    },
    {
        "name": "Caixa de Apoio",
        "type": BusinessAccountType.CASH,
        "institution_name": None,
        "initial_balance_cents": 0,
    },
]

SOOMEI_CATEGORIES = [
    {
        "code": "MRR",
        "name": "Mensalidades de associados",
        "kind": BusinessCategoryKind.RECURRING_REVENUE,
        "description": "Receita recorrente principal da Soomei.",
    },
    {
        "code": "ATV",
        "name": "Taxa de ativacao",
        "kind": BusinessCategoryKind.NON_RECURRING_REVENUE,
        "description": "Receitas cobradas na adesao inicial.",
    },
    {
        "code": "2VIA",
        "name": "Segunda via de cartao",
        "kind": BusinessCategoryKind.NON_RECURRING_REVENUE,
        "description": "Receita eventual de substituicao de cartao.",
    },
    {
        "code": "DESC",
        "name": "Descontos comerciais",
        "kind": BusinessCategoryKind.DISCOUNT,
        "description": "Descontos aplicados nas cobrancas.",
    },
    {
        "code": "EST",
        "name": "Estornos",
        "kind": BusinessCategoryKind.REFUND,
        "description": "Valores devolvidos aos associados.",
    },
    {
        "code": "CARD",
        "name": "Custo do cartao NFC",
        "kind": BusinessCategoryKind.DIRECT_COST,
        "description": "Custo unitario de emissao de cartoes.",
    },
    {
        "code": "GWY",
        "name": "Tarifa de gateway",
        "kind": BusinessCategoryKind.OPERATING_EXPENSE,
        "description": "Tarifas de operacao e meios de pagamento.",
    },
    {
        "code": "ADM",
        "name": "Administrativo geral",
        "kind": BusinessCategoryKind.ADMIN_EXPENSE,
        "description": "Despesas administrativas do business.",
    },
    {
        "code": "FIN",
        "name": "Juros e tarifas financeiras",
        "kind": BusinessCategoryKind.FINANCIAL_EXPENSE,
        "description": "Custos financeiros, tarifas e antecipacoes.",
    },
    {
        "code": "INV",
        "name": "Investimento em crescimento",
        "kind": BusinessCategoryKind.INVESTMENT,
        "description": "Marketing, tecnologia e expansao.",
    },
    {
        "code": "TAX",
        "name": "Tributos",
        "kind": BusinessCategoryKind.TAX,
        "description": "Tributos incidentes sobre a operacao.",
    },
]

SOOMEI_COST_CENTERS = [
    {
        "code": "OPER",
        "name": "Operacao",
        "description": "Emissao, ativacao e suporte operacional.",
    },
    {
        "code": "COM",
        "name": "Comercial",
        "description": "Aquisicao, parcerias e crescimento da base.",
    },
    {
        "code": "TECH",
        "name": "Tecnologia",
        "description": "Produto, plataforma e automacoes.",
    },
    {
        "code": "ADM",
        "name": "Administrativo",
        "description": "Backoffice, financeiro e compliance.",
    },
]


@dataclass(slots=True)
class BusinessDashboardSummary:
    total_businesses: int
    active_businesses: int
    active_accounts: int
    active_categories: int
    active_cost_centers: int
    initial_balance_cents: int
    recent_audits: list[AuditLog]


def money_to_cents(value: str) -> int:
    try:
        parsed = Decimal(value.replace(",", ".").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("Valor monetario invalido.") from exc
    return int((parsed * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class BusinessControlService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_businesses(self, *, owner_user_id: UUID) -> list[Business]:
        stmt = (
            select(Business)
            .where(Business.owner_user_id == owner_user_id)
            .order_by(Business.is_active.desc(), Business.name.asc())
        )
        return list(self.db.scalars(stmt))

    def resolve_active_business(
        self,
        *,
        owner_user_id: UUID,
        requested_business_id: UUID | None,
    ) -> Business | None:
        businesses = self.list_businesses(owner_user_id=owner_user_id)
        if not businesses:
            return None
        if requested_business_id is not None:
            for business in businesses:
                if business.id == requested_business_id and business.is_active:
                    return business
        for business in businesses:
            if business.is_active:
                return business
        return businesses[0]

    def build_dashboard(self, *, owner_user_id: UUID, business_id: UUID) -> BusinessDashboardSummary:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        businesses = self.list_businesses(owner_user_id=owner_user_id)
        active_businesses = sum(1 for item in businesses if item.is_active)
        active_accounts = self.db.scalar(
            select(func.count(BusinessAccount.id)).where(
                BusinessAccount.business_id == business_id,
                BusinessAccount.is_active.is_(True),
            )
        )
        active_categories = self.db.scalar(
            select(func.count(BusinessCategory.id)).where(
                BusinessCategory.business_id == business_id,
                BusinessCategory.is_active.is_(True),
            )
        )
        active_cost_centers = self.db.scalar(
            select(func.count(CostCenter.id)).where(
                CostCenter.business_id == business_id,
                CostCenter.is_active.is_(True),
            )
        )
        initial_balance = self.db.scalar(
            select(func.coalesce(func.sum(BusinessAccount.initial_balance_cents), 0)).where(
                BusinessAccount.business_id == business_id,
                BusinessAccount.is_active.is_(True),
            )
        )
        recent_audits = list(
            self.db.scalars(
                select(AuditLog)
                .where(AuditLog.business_id == business_id)
                .order_by(AuditLog.created_at.desc())
                .limit(8)
            )
        )
        return BusinessDashboardSummary(
            total_businesses=len(businesses),
            active_businesses=active_businesses,
            active_accounts=int(active_accounts or 0),
            active_categories=int(active_categories or 0),
            active_cost_centers=int(active_cost_centers or 0),
            initial_balance_cents=int(initial_balance or 0),
            recent_audits=recent_audits,
        )

    def get_business(self, *, owner_user_id: UUID, business_id: UUID) -> Business:
        row = self.db.scalar(
            select(Business).where(
                Business.id == business_id,
                Business.owner_user_id == owner_user_id,
            )
        )
        if row is None:
            raise ValueError("Business nao encontrado.")
        return row

    def list_accounts(self, *, owner_user_id: UUID, business_id: UUID) -> list[BusinessAccount]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        stmt = (
            select(BusinessAccount)
            .where(BusinessAccount.business_id == business_id)
            .order_by(BusinessAccount.is_active.desc(), BusinessAccount.name.asc())
        )
        return list(self.db.scalars(stmt))

    def list_categories(self, *, owner_user_id: UUID, business_id: UUID) -> list[BusinessCategory]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        stmt = (
            select(BusinessCategory)
            .where(BusinessCategory.business_id == business_id)
            .order_by(BusinessCategory.is_active.desc(), BusinessCategory.kind.asc(), BusinessCategory.name.asc())
        )
        return list(self.db.scalars(stmt))

    def list_cost_centers(self, *, owner_user_id: UUID, business_id: UUID) -> list[CostCenter]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        stmt = (
            select(CostCenter)
            .where(CostCenter.business_id == business_id)
            .order_by(CostCenter.is_active.desc(), CostCenter.name.asc())
        )
        return list(self.db.scalars(stmt))

    def create_business(
        self,
        *,
        actor_user_id: UUID,
        payload: CreateBusinessDTO,
        request_id: str | None = None,
    ) -> Business:
        existing = self.db.scalar(select(Business).where(func.lower(Business.slug) == payload.slug.lower()))
        if existing is not None:
            raise ValueError("Ja existe um business com este slug.")
        row = Business(
            owner_user_id=actor_user_id,
            name=payload.name,
            slug=payload.slug,
            legal_name=payload.legal_name,
            description=payload.description,
            currency_code="BRL",
            is_active=True,
        )
        self.db.add(row)
        self.db.flush()
        self._add_audit(
            business_id=row.id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="Business",
            entity_id=row.id,
            summary=f"Business '{row.name}' criado.",
            details=payload.model_dump(mode="json"),
            request_id=request_id,
        )
        if payload.seed_template == "SOOMEI":
            self._apply_soomei_template(actor_user_id=actor_user_id, business=row, request_id=request_id)
        self.db.commit()
        self.db.refresh(row)
        return row

    def switch_business(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        request_id: str | None = None,
    ) -> Business:
        business = self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        if not business.is_active:
            raise ValueError("Reative o business antes de usa-lo como contexto ativo.")
        self._add_audit(
            business_id=business.id,
            actor_user_id=actor_user_id,
            action=AuditAction.SWITCH,
            entity_type="Business",
            entity_id=business.id,
            summary=f"Business ativo alterado para '{business.name}'.",
            details={"slug": business.slug, "is_active": business.is_active},
            request_id=request_id,
        )
        self.db.commit()
        return business

    def set_business_active(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        is_active: bool,
        request_id: str | None = None,
    ) -> Business:
        business = self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        if business.is_active == is_active:
            return business
        business.is_active = is_active
        self.db.add(business)
        self._add_audit(
            business_id=business.id,
            actor_user_id=actor_user_id,
            action=AuditAction.ACTIVATE if is_active else AuditAction.DEACTIVATE,
            entity_type="Business",
            entity_id=business.id,
            summary=f"Business '{business.name}' {'ativado' if is_active else 'desativado'}.",
            details={"is_active": is_active},
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(business)
        return business

    def create_account(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        payload: UpsertBusinessAccountDTO,
        request_id: str | None = None,
    ) -> BusinessAccount:
        business = self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        self._assert_account_name_available(business_id=business.id, name=payload.name)
        row = BusinessAccount(
            business_id=business.id,
            name=payload.name,
            type=payload.type,
            institution_name=payload.institution_name,
            initial_balance_cents=payload.initial_balance_cents,
            is_active=True,
        )
        self.db.add(row)
        self.db.flush()
        self._add_audit(
            business_id=business.id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="BusinessAccount",
            entity_id=row.id,
            summary=f"Conta empresarial '{row.name}' criada.",
            details=payload.model_dump(mode="json"),
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_account(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        account_id: UUID,
        payload: UpsertBusinessAccountDTO,
        request_id: str | None = None,
    ) -> BusinessAccount:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        row = self._get_account(business_id=business_id, account_id=account_id)
        self._assert_account_name_available(business_id=business_id, name=payload.name, exclude_id=row.id)
        before = self._account_snapshot(row)
        row.name = payload.name
        row.type = payload.type
        row.institution_name = payload.institution_name
        row.initial_balance_cents = payload.initial_balance_cents
        self.db.add(row)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.UPDATE,
            entity_type="BusinessAccount",
            entity_id=row.id,
            summary=f"Conta empresarial '{row.name}' atualizada.",
            details={"before": before, "after": self._account_snapshot(row)},
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def set_account_active(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        account_id: UUID,
        is_active: bool,
        request_id: str | None = None,
    ) -> BusinessAccount:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        row = self._get_account(business_id=business_id, account_id=account_id)
        if row.is_active == is_active:
            return row
        row.is_active = is_active
        self.db.add(row)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.ACTIVATE if is_active else AuditAction.DEACTIVATE,
            entity_type="BusinessAccount",
            entity_id=row.id,
            summary=f"Conta empresarial '{row.name}' {'ativada' if is_active else 'desativada'}.",
            details={"is_active": is_active},
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def create_category(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        payload: UpsertBusinessCategoryDTO,
        request_id: str | None = None,
    ) -> BusinessCategory:
        business = self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        self._assert_category_available(business_id=business.id, name=payload.name, code=payload.code)
        row = BusinessCategory(
            business_id=business.id,
            code=payload.code,
            name=payload.name,
            kind=payload.kind,
            description=payload.description,
            is_active=True,
        )
        self.db.add(row)
        self.db.flush()
        self._add_audit(
            business_id=business.id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="BusinessCategory",
            entity_id=row.id,
            summary=f"Categoria empresarial '{row.name}' criada.",
            details=payload.model_dump(mode="json"),
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_category(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        category_id: UUID,
        payload: UpsertBusinessCategoryDTO,
        request_id: str | None = None,
    ) -> BusinessCategory:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        row = self._get_category(business_id=business_id, category_id=category_id)
        self._assert_category_available(
            business_id=business_id,
            name=payload.name,
            code=payload.code,
            exclude_id=row.id,
        )
        before = self._category_snapshot(row)
        row.code = payload.code
        row.name = payload.name
        row.kind = payload.kind
        row.description = payload.description
        self.db.add(row)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.UPDATE,
            entity_type="BusinessCategory",
            entity_id=row.id,
            summary=f"Categoria empresarial '{row.name}' atualizada.",
            details={"before": before, "after": self._category_snapshot(row)},
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def set_category_active(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        category_id: UUID,
        is_active: bool,
        request_id: str | None = None,
    ) -> BusinessCategory:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        row = self._get_category(business_id=business_id, category_id=category_id)
        if row.is_active == is_active:
            return row
        row.is_active = is_active
        self.db.add(row)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.ACTIVATE if is_active else AuditAction.DEACTIVATE,
            entity_type="BusinessCategory",
            entity_id=row.id,
            summary=f"Categoria empresarial '{row.name}' {'ativada' if is_active else 'desativada'}.",
            details={"is_active": is_active},
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def create_cost_center(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        payload: UpsertCostCenterDTO,
        request_id: str | None = None,
    ) -> CostCenter:
        business = self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        self._assert_cost_center_available(business_id=business.id, name=payload.name, code=payload.code)
        row = CostCenter(
            business_id=business.id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            is_active=True,
        )
        self.db.add(row)
        self.db.flush()
        self._add_audit(
            business_id=business.id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="CostCenter",
            entity_id=row.id,
            summary=f"Centro de custo '{row.name}' criado.",
            details=payload.model_dump(mode="json"),
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_cost_center(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        cost_center_id: UUID,
        payload: UpsertCostCenterDTO,
        request_id: str | None = None,
    ) -> CostCenter:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        row = self._get_cost_center(business_id=business_id, cost_center_id=cost_center_id)
        self._assert_cost_center_available(
            business_id=business_id,
            name=payload.name,
            code=payload.code,
            exclude_id=row.id,
        )
        before = self._cost_center_snapshot(row)
        row.code = payload.code
        row.name = payload.name
        row.description = payload.description
        self.db.add(row)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.UPDATE,
            entity_type="CostCenter",
            entity_id=row.id,
            summary=f"Centro de custo '{row.name}' atualizado.",
            details={"before": before, "after": self._cost_center_snapshot(row)},
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def set_cost_center_active(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        cost_center_id: UUID,
        is_active: bool,
        request_id: str | None = None,
    ) -> CostCenter:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        row = self._get_cost_center(business_id=business_id, cost_center_id=cost_center_id)
        if row.is_active == is_active:
            return row
        row.is_active = is_active
        self.db.add(row)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.ACTIVATE if is_active else AuditAction.DEACTIVATE,
            entity_type="CostCenter",
            entity_id=row.id,
            summary=f"Centro de custo '{row.name}' {'ativado' if is_active else 'desativado'}.",
            details={"is_active": is_active},
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def _apply_soomei_template(
        self,
        *,
        actor_user_id: UUID,
        business: Business,
        request_id: str | None,
    ) -> None:
        for account in SOOMEI_ACCOUNTS:
            self.db.add(BusinessAccount(business_id=business.id, **account, is_active=True))
        for category in SOOMEI_CATEGORIES:
            self.db.add(BusinessCategory(business_id=business.id, **category, is_active=True))
        for cost_center in SOOMEI_COST_CENTERS:
            self.db.add(CostCenter(business_id=business.id, **cost_center, is_active=True))
        self.db.flush()
        self._add_audit(
            business_id=business.id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="BusinessSeed",
            entity_id=business.id,
            summary="Estrutura inicial da Soomei aplicada.",
            details={
                "template": "SOOMEI",
                "accounts": len(SOOMEI_ACCOUNTS),
                "categories": len(SOOMEI_CATEGORIES),
                "cost_centers": len(SOOMEI_COST_CENTERS),
            },
            request_id=request_id,
        )

    def _assert_account_name_available(
        self,
        *,
        business_id: UUID,
        name: str,
        exclude_id: UUID | None = None,
    ) -> None:
        stmt = select(BusinessAccount).where(
            BusinessAccount.business_id == business_id,
            func.lower(BusinessAccount.name) == name.lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(BusinessAccount.id != exclude_id)
        if self.db.scalar(stmt) is not None:
            raise ValueError("Ja existe uma conta empresarial com este nome.")

    def _assert_category_available(
        self,
        *,
        business_id: UUID,
        name: str,
        code: str | None,
        exclude_id: UUID | None = None,
    ) -> None:
        stmt = select(BusinessCategory).where(
            BusinessCategory.business_id == business_id,
            func.lower(BusinessCategory.name) == name.lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(BusinessCategory.id != exclude_id)
        if self.db.scalar(stmt) is not None:
            raise ValueError("Ja existe uma categoria empresarial com este nome.")
        if code is None:
            return
        code_stmt = select(BusinessCategory).where(
            BusinessCategory.business_id == business_id,
            func.lower(BusinessCategory.code) == code.lower(),
        )
        if exclude_id is not None:
            code_stmt = code_stmt.where(BusinessCategory.id != exclude_id)
        if self.db.scalar(code_stmt) is not None:
            raise ValueError("Ja existe uma categoria empresarial com este codigo.")

    def _assert_cost_center_available(
        self,
        *,
        business_id: UUID,
        name: str,
        code: str | None,
        exclude_id: UUID | None = None,
    ) -> None:
        stmt = select(CostCenter).where(
            CostCenter.business_id == business_id,
            func.lower(CostCenter.name) == name.lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(CostCenter.id != exclude_id)
        if self.db.scalar(stmt) is not None:
            raise ValueError("Ja existe um centro de custo com este nome.")
        if code is None:
            return
        code_stmt = select(CostCenter).where(
            CostCenter.business_id == business_id,
            func.lower(CostCenter.code) == code.lower(),
        )
        if exclude_id is not None:
            code_stmt = code_stmt.where(CostCenter.id != exclude_id)
        if self.db.scalar(code_stmt) is not None:
            raise ValueError("Ja existe um centro de custo com este codigo.")

    def _get_account(self, *, business_id: UUID, account_id: UUID) -> BusinessAccount:
        row = self.db.scalar(
            select(BusinessAccount).where(
                BusinessAccount.id == account_id,
                BusinessAccount.business_id == business_id,
            )
        )
        if row is None:
            raise ValueError("Conta empresarial nao encontrada.")
        return row

    def _get_category(self, *, business_id: UUID, category_id: UUID) -> BusinessCategory:
        row = self.db.scalar(
            select(BusinessCategory).where(
                BusinessCategory.id == category_id,
                BusinessCategory.business_id == business_id,
            )
        )
        if row is None:
            raise ValueError("Categoria empresarial nao encontrada.")
        return row

    def _get_cost_center(self, *, business_id: UUID, cost_center_id: UUID) -> CostCenter:
        row = self.db.scalar(
            select(CostCenter).where(
                CostCenter.id == cost_center_id,
                CostCenter.business_id == business_id,
            )
        )
        if row is None:
            raise ValueError("Centro de custo nao encontrado.")
        return row

    def _add_audit(
        self,
        *,
        business_id: UUID,
        actor_user_id: UUID | None,
        action: AuditAction,
        entity_type: str,
        entity_id: UUID,
        summary: str,
        details: dict[str, object],
        request_id: str | None,
    ) -> None:
        self.db.add(
            AuditLog(
                business_id=business_id,
                actor_user_id=actor_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                summary=summary,
                details=details,
                request_id=request_id,
            )
        )

    @staticmethod
    def _account_snapshot(row: BusinessAccount) -> dict[str, object]:
        return {
            "name": row.name,
            "type": row.type.value,
            "institution_name": row.institution_name,
            "initial_balance_cents": row.initial_balance_cents,
            "is_active": row.is_active,
        }

    @staticmethod
    def _category_snapshot(row: BusinessCategory) -> dict[str, object]:
        return {
            "code": row.code,
            "name": row.name,
            "kind": row.kind.value,
            "description": row.description,
            "is_active": row.is_active,
        }

    @staticmethod
    def _cost_center_snapshot(row: CostCenter) -> dict[str, object]:
        return {
            "code": row.code,
            "name": row.name,
            "description": row.description,
            "is_active": row.is_active,
        }
