"""GENERATED from api/schema/*.graphql by `poetry run python -m api.codegen.generate` — do not edit.

Edit the SDL, rerun the generator, commit both. Structure only (types, nullability, defaults,
camelCase aliases); validation and behaviour are added by subclasses in api/gql/inputs.py.
Enum members mirror the SDL names; where the server maps an enum to other runtime values
(see `bind` in api/gql/resolvers.py) the hand model in inputs.py declares the field itself.
"""
# ruff: noqa: F401
import datetime as dt
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import Field

from ..relay import GlobalId, _GraphQLModel



class AssetKind(str, Enum):
    PROPERTY = "PROPERTY"


class CategorySource(str, Enum):
    BUILTIN = "BUILTIN"
    RISEUP = "RISEUP"
    USER = "USER"


class Direction(str, Enum):
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"


class ExpenseKind(str, Enum):
    FIXED = "FIXED"
    VARIABLE = "VARIABLE"


class GoalInterval(str, Enum):
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class GroupOrder(str, Enum):
    NAME_ASC = "NAME_ASC"
    COUNT_DESC = "COUNT_DESC"
    TOTAL_DESC = "TOTAL_DESC"
    TOTAL_ASC = "TOTAL_ASC"


class HorizonKey(str, Enum):
    CURRENT = "CURRENT"
    NEAR = "NEAR"
    FUTURE = "FUTURE"


class KindSource(str, Enum):
    MANUAL = "MANUAL"
    RULE = "RULE"
    MERCHANT = "MERCHANT"
    RECURRING = "RECURRING"
    ONE_OFF = "ONE_OFF"
    RISEUP = "RISEUP"
    CATEGORY = "CATEGORY"


class NotificationCategory(str, Enum):
    PROBLEM = "PROBLEM"
    WARNING = "WARNING"
    REMINDER = "REMINDER"
    SUGGESTION = "SUGGESTION"
    INFO = "INFO"


class NotificationSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class OffsetKind(str, Enum):
    REFUND = "REFUND"
    RULE = "RULE"
    MANUAL = "MANUAL"


class SyncRetryPoint(str, Enum):
    SCRAPE = "SCRAPE"
    DIGEST = "DIGEST"


class TenantRole(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class TenantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TransactionOrder(str, Enum):
    DATE_DESC = "DATE_DESC"
    DATE_ASC = "DATE_ASC"
    AMOUNT_DESC = "AMOUNT_DESC"
    AMOUNT_ASC = "AMOUNT_ASC"


class ValuationSource(str, Enum):
    MANUAL = "MANUAL"
    ESTIMATE = "ESTIMATE"


class AssetCreateInput(_GraphQLModel):
    kind: AssetKind
    label: str
    value: Decimal
    valued_at: dt.date | None = None


class AssetUpdateInput(_GraphQLModel):
    """Any of the asset's fields; none can be cleared."""
    label: str | None = None
    value: Decimal | None = None
    valued_at: dt.date | None = None


class BulkNotificationInput(_GraphQLModel):
    client_mutation_id: str | None = None
    category: list[NotificationCategory] | None = None


class CategoryMergeInput(_GraphQLModel):
    """Result of a delete; `entityId` is the deleted node's global id."""
    into_id: GlobalId


class ClearTransactionOverrideInput(_GraphQLModel):
    client_mutation_id: str | None = None
    id: GlobalId


class DateRange(_GraphQLModel):
    from_: dt.date | None = Field(default=None, alias="from")
    to: dt.date | None = None


class DeleteTagInput(_GraphQLModel):
    client_mutation_id: str | None = None
    id: GlobalId


class GoalCreateInput(_GraphQLModel):
    description: str
    amount: Decimal
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    interval: GoalInterval | None = None
    repetitions: int | None = None
    rise: Decimal | None = None
    horizon: HorizonKey | None = None


class GoalUpdateInput(_GraphQLModel):
    """Any of the goal's fields; a null clears it (description and amount cannot be cleared)."""
    description: str | None = None
    amount: Decimal | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    interval: GoalInterval | None = None
    repetitions: int | None = None
    rise: Decimal | None = None
    horizon: HorizonKey | None = None


class HoldingAssignInput(_GraphQLModel):
    """`holdingId` plus at least one of horizon / goalId; null clears that field."""
    holding_id: str
    horizon: HorizonKey | None = None
    goal_id: GlobalId | None = None


class LinkOffsetInput(_GraphQLModel):
    client_mutation_id: str | None = None
    payback_id: GlobalId
    expense_id: GlobalId
    amount: Decimal | None = None


class NotificationFilter(_GraphQLModel):
    category: list[NotificationCategory] | None = None
    unread: bool | None = None
    include_archived: bool = False
    include_resolved: bool = False
    include_snoozed: bool = False


class NotificationIdInput(_GraphQLModel):
    client_mutation_id: str | None = None
    id: GlobalId


class PlanTargetsUpdateInput(_GraphQLModel):
    """At least one field; a negative amount is an error, null or 0 unsets."""
    emergency_fund: Decimal | None = None
    inheritance: Decimal | None = None
    retirement: Decimal | None = None


class ResetOffsetsInput(_GraphQLModel):
    client_mutation_id: str | None = None
    payback_id: GlobalId


class SetTransactionTagsInput(_GraphQLModel):
    client_mutation_id: str | None = None
    id: GlobalId
    tags: list[str]


class SnoozeAllNotificationsInput(_GraphQLModel):
    client_mutation_id: str | None = None
    snoozed_until_at: dt.datetime
    category: list[NotificationCategory] | None = None


class SyncSourceSecretSetInput(_GraphQLModel):
    source: str
    name: str
    value: str


class TenantAccessSyncInput(_GraphQLModel):
    """Make one person's access to the tenant's published files match their membership."""
    email: str


class TenantCreateInput(_GraphQLModel):
    slug: str
    name: str
    owner_email: str


class TenantMemberRemoveInput(_GraphQLModel):
    email: str


class TenantMemberSetInput(_GraphQLModel):
    """Add the user (created on first use, by email) or change their role."""
    email: str
    role: TenantRole


class TenantSetStatusInput(_GraphQLModel):
    status: TenantStatus


class TransactionFilter(_GraphQLModel):
    direction: Direction | None = None
    date_range: DateRange | None = None
    category_ids: list[GlobalId] | None = None
    tag_ids: list[GlobalId] | None = None
    merchant_id: GlobalId | None = None
    horizon_ids: list[GlobalId] | None = None
    goal_ids: list[GlobalId] | None = None
    search: str | None = None
    include_excluded: bool = False
    include_transfers: bool = False


class UnlinkOffsetInput(_GraphQLModel):
    client_mutation_id: str | None = None
    payback_id: GlobalId
    expense_id: GlobalId


class UpdateNotificationInput(_GraphQLModel):
    client_mutation_id: str | None = None
    id: GlobalId
    read: bool | None = None
    snoozed_until_at: dt.datetime | None = None


class UpdateTagInput(_GraphQLModel):
    client_mutation_id: str | None = None
    id: GlobalId
    name: str | None = None
    color: str | None = None


class UpdateTransactionInput(_GraphQLModel):
    client_mutation_id: str | None = None
    id: GlobalId
    category: str | None = None
    note: str | None = None
    excluded: bool | None = None
    horizon: HorizonKey | None = None
    goal_id: GlobalId | None = None


class CategoryGoalsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class CategoryHorizonsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class CategoryMerchantsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    search: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class CategoryTagsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class CategoryTransactionsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    filter: TransactionFilter | None = None
    order_by: TransactionOrder = TransactionOrder.DATE_DESC


class GoalCategoriesArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class GoalMerchantsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class GoalTagsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class GoalTransactionsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    filter: TransactionFilter | None = None
    order_by: TransactionOrder = TransactionOrder.DATE_DESC


class HorizonCategoriesArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class HorizonGoalsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class HorizonMerchantsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class HorizonTagsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class HorizonTransactionsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    filter: TransactionFilter | None = None
    order_by: TransactionOrder = TransactionOrder.DATE_DESC


class MerchantCategoriesArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class MerchantGoalsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class MerchantHorizonsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class MerchantTagsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class MerchantTransactionsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    filter: TransactionFilter | None = None
    order_by: TransactionOrder = TransactionOrder.DATE_DESC


class MutationArchiveAllNotificationsArgs(_GraphQLModel):
    input: BulkNotificationInput


class MutationArchiveNotificationArgs(_GraphQLModel):
    input: NotificationIdInput


class MutationAssetCreateArgs(_GraphQLModel):
    input: AssetCreateInput


class MutationAssetUpdateArgs(_GraphQLModel):
    id: GlobalId
    input: AssetUpdateInput


class MutationCategoryMergeArgs(_GraphQLModel):
    id: GlobalId
    input: CategoryMergeInput


class MutationCategoryUnmergeArgs(_GraphQLModel):
    id: GlobalId


class MutationClearTransactionOverrideArgs(_GraphQLModel):
    input: ClearTransactionOverrideInput


class MutationDeleteTagArgs(_GraphQLModel):
    input: DeleteTagInput


class MutationGoalCreateArgs(_GraphQLModel):
    input: GoalCreateInput


class MutationGoalDeleteArgs(_GraphQLModel):
    id: GlobalId


class MutationGoalUpdateArgs(_GraphQLModel):
    id: GlobalId
    input: GoalUpdateInput


class MutationHoldingAssignArgs(_GraphQLModel):
    input: HoldingAssignInput


class MutationLinkOffsetArgs(_GraphQLModel):
    input: LinkOffsetInput


class MutationMarkAllNotificationsReadArgs(_GraphQLModel):
    input: BulkNotificationInput


class MutationPlanTargetsUpdateArgs(_GraphQLModel):
    input: PlanTargetsUpdateInput


class MutationResetOffsetsArgs(_GraphQLModel):
    input: ResetOffsetsInput


class MutationSetTransactionTagsArgs(_GraphQLModel):
    input: SetTransactionTagsInput


class MutationSnoozeAllNotificationsArgs(_GraphQLModel):
    input: SnoozeAllNotificationsInput


class MutationSyncSourceRetryArgs(_GraphQLModel):
    id: GlobalId


class MutationSyncSourceRunArgs(_GraphQLModel):
    id: GlobalId


class MutationSyncSourceSecretSetArgs(_GraphQLModel):
    input: SyncSourceSecretSetInput


class MutationTenantAccessSyncArgs(_GraphQLModel):
    id: GlobalId
    input: TenantAccessSyncInput


class MutationTenantCreateArgs(_GraphQLModel):
    input: TenantCreateInput


class MutationTenantMemberRemoveArgs(_GraphQLModel):
    id: GlobalId
    input: TenantMemberRemoveInput


class MutationTenantMemberSetArgs(_GraphQLModel):
    id: GlobalId
    input: TenantMemberSetInput


class MutationTenantSetStatusArgs(_GraphQLModel):
    id: GlobalId
    input: TenantSetStatusInput


class MutationUnarchiveNotificationArgs(_GraphQLModel):
    input: NotificationIdInput


class MutationUnlinkOffsetArgs(_GraphQLModel):
    input: UnlinkOffsetInput


class MutationUpdateNotificationArgs(_GraphQLModel):
    input: UpdateNotificationInput


class MutationUpdateTagArgs(_GraphQLModel):
    input: UpdateTagInput


class MutationUpdateTransactionArgs(_GraphQLModel):
    input: UpdateTransactionInput


class QueryAssetsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None


class QueryCategoriesArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    search: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class QueryExpensesArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    filter: TransactionFilter | None = None
    order_by: TransactionOrder = TransactionOrder.DATE_DESC


class QueryGoalsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    search: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.NAME_ASC


class QueryHorizonsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    search: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.NAME_ASC


class QueryIncomesArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    filter: TransactionFilter | None = None
    order_by: TransactionOrder = TransactionOrder.DATE_DESC


class QueryMerchantsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    search: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class QueryNodeArgs(_GraphQLModel):
    id: GlobalId


class QueryNotificationsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    filter: NotificationFilter | None = None


class QueryNotificationsUnreadCountArgs(_GraphQLModel):
    category: list[NotificationCategory] | None = None


class QuerySyncSourceSecretsArgs(_GraphQLModel):
    source: str


class QuerySyncSourcesArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None


class QueryTagsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    search: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class QueryTransactionByKeyArgs(_GraphQLModel):
    date: dt.date
    abs_amount: Decimal


class QueryTransactionsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    filter: TransactionFilter | None = None
    order_by: TransactionOrder = TransactionOrder.DATE_DESC


class TagCategoriesArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class TagGoalsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class TagHorizonsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class TagMerchantsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    search: str | None = None
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC


class TagTransactionsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
    last: int | None = None
    before: str | None = None
    filter: TransactionFilter | None = None
    order_by: TransactionOrder = TransactionOrder.DATE_DESC


class TransactionAuditLogArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None


class TransactionOffsetCandidatesArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None


class TransactionTagsArgs(_GraphQLModel):
    first: int | None = None
    after: str | None = None
