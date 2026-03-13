from enum import StrEnum


class AccountType(StrEnum):
    CASH = "CASH"
    BANK = "BANK"
    WALLET = "WALLET"


class CategoryKind(StrEnum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class TransactionDirection(StrEnum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class ImportFileStatus(StrEnum):
    IMPORTED = "IMPORTED"
    REVIEWING = "REVIEWING"
    APPLIED = "APPLIED"


class ExternalTransactionReviewStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


class RecurringCadence(StrEnum):
    MONTHLY = "MONTHLY"


class DebtKind(StrEnum):
    TAX = "TAX"
    LOAN = "LOAN"
    CREDIT = "CREDIT"
    OTHER = "OTHER"


class NotificationType(StrEnum):
    BILL_DUE = "BILL_DUE"
    CARD_DUE = "CARD_DUE"
    DEBT_PAYMENT = "DEBT_PAYMENT"
    SYSTEM = "SYSTEM"


class NotificationChannel(StrEnum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"


class BusinessAccountType(StrEnum):
    CASH = "CASH"
    BANK = "BANK"
    DIGITAL_WALLET = "DIGITAL_WALLET"
    RECEIVABLE = "RECEIVABLE"


class BusinessCategoryKind(StrEnum):
    RECURRING_REVENUE = "RECURRING_REVENUE"
    NON_RECURRING_REVENUE = "NON_RECURRING_REVENUE"
    DEDUCTION = "DEDUCTION"
    REFUND = "REFUND"
    DISCOUNT = "DISCOUNT"
    DIRECT_COST = "DIRECT_COST"
    OPERATING_EXPENSE = "OPERATING_EXPENSE"
    ADMIN_EXPENSE = "ADMIN_EXPENSE"
    FINANCIAL_EXPENSE = "FINANCIAL_EXPENSE"
    INVESTMENT = "INVESTMENT"
    TAX = "TAX"


class AuditAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    ACTIVATE = "ACTIVATE"
    DEACTIVATE = "DEACTIVATE"
    SWITCH = "SWITCH"


class MemberStatus(StrEnum):
    LEAD = "LEAD"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"
    CANCELED = "CANCELED"


class BillingCadence(StrEnum):
    MONTHLY = "MONTHLY"


class SubscriptionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"
    CANCELED = "CANCELED"


class ReceivableStatus(StrEnum):
    PLANNED = "PLANNED"
    ISSUED = "ISSUED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    CANCELED = "CANCELED"
    RENEGOTIATED = "RENEGOTIATED"
    REFUNDED = "REFUNDED"


class ReceivableKind(StrEnum):
    ACTIVATION = "ACTIVATION"
    RECURRING = "RECURRING"
    REPLACEMENT = "REPLACEMENT"
    ADJUSTMENT = "ADJUSTMENT"


class ReceiptMethod(StrEnum):
    PIX = "PIX"
    BOLETO = "BOLETO"
    CARD = "CARD"
    CASH = "CASH"
    TRANSFER = "TRANSFER"
    OTHER = "OTHER"


class IntegrationProvider(StrEnum):
    THEMEMBERS_CHECKOUT = "THEMEMBERS_CHECKOUT"


class WebhookEventStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    IGNORED = "IGNORED"
    FAILED = "FAILED"


class BusinessCashActivityType(StrEnum):
    OPERATING = "OPERATING"
    INVESTING = "INVESTING"
    FINANCING = "FINANCING"


class FundingInstallmentStatus(StrEnum):
    OPEN = "OPEN"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
