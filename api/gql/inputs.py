"""GraphQL arguments as Pydantic models: each resolver validates its args through one.

These mirror the input types and argument lists in api/schema; the SDL stays the
source of truth (a later step can generate this file from it).
"""
import datetime as dt
from typing import Literal
from decimal import Decimal
from enum import Enum

from pydantic import Field, field_validator, model_validator

from api.inputs import GoalEdit, Patch, TagEdit, TagSet

from .relay import ConnectionArgs, _GraphQLModel, node_id_of


class Direction(str, Enum):
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"


class TransactionOrder(str, Enum):
    DATE_DESC = "DATE_DESC"
    DATE_ASC = "DATE_ASC"
    AMOUNT_DESC = "AMOUNT_DESC"
    AMOUNT_ASC = "AMOUNT_ASC"


class GroupOrder(str, Enum):
    NAME_ASC = "NAME_ASC"
    COUNT_DESC = "COUNT_DESC"
    TOTAL_DESC = "TOTAL_DESC"
    TOTAL_ASC = "TOTAL_ASC"


class NotificationCategory(str, Enum):
    PROBLEM = "PROBLEM"
    WARNING = "WARNING"
    REMINDER = "REMINDER"
    SUGGESTION = "SUGGESTION"
    INFO = "INFO"


class DateRange(_GraphQLModel):
    from_: dt.date | None = Field(default=None, alias="from")
    to: dt.date | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.from_ and self.to and self.from_ > self.to:
            raise ValueError("dateRange.from is after dateRange.to")
        return self

    def contains(self, d):
        return (self.from_ is None or d >= self.from_) and (self.to is None or d <= self.to)


class TransactionFilter(_GraphQLModel):
    direction: Direction | None = None
    date_range: DateRange | None = None
    category_ids: list[node_id_of("Category")] | None = None
    tag_ids: list[node_id_of("Tag")] | None = None
    merchant_id: node_id_of("Merchant") | None = None
    horizon_ids: list[node_id_of("Horizon")] | None = None
    goal_ids: list[node_id_of("Goal")] | None = None
    search: str | None = Field(default=None, max_length=100)
    include_excluded: bool = False
    include_transfers: bool = False

    @field_validator("search")
    @classmethod
    def blank_is_none(cls, v):
        return (v.strip().casefold() or None) if v is not None else None

    def matches(self, t):
        if not self.include_excluded and t.excluded:
            return False
        if not self.include_transfers and t.is_transfer:
            return False
        if self.direction and t.direction != self.direction.value:
            return False
        if self.date_range and not self.date_range.contains(t.date):
            return False
        if self.category_ids is not None and (not t.category or str(t.category.id) not in
                                              {r.key for r in self.category_ids}):
            return False
        if self.tag_ids is not None and not {str(tag.id) for tag, _ in t.tag_links} & {r.key for r in self.tag_ids}:
            return False
        if self.merchant_id and t.merchant.name != self.merchant_id.key:
            return False
        if self.horizon_ids is not None and not (t.horizon and str(t.horizon.id) in {r.key for r in self.horizon_ids}):
            return False
        if self.goal_ids is not None and not (t.goal and str(t.goal.id) in {r.key for r in self.goal_ids}):
            return False
        if self.search and self.search not in t.description.casefold():
            return False
        return True


class TransactionArgs(ConnectionArgs):
    filter: TransactionFilter = TransactionFilter()
    order_by: TransactionOrder = TransactionOrder.DATE_DESC


class NotificationFilter(_GraphQLModel):
    category: list[NotificationCategory] | None = None
    unread: bool | None = None
    include_archived: bool = False
    include_resolved: bool = False
    include_snoozed: bool = False


class NotificationArgs(ConnectionArgs):
    filter: NotificationFilter = NotificationFilter()


class UnreadCountArgs(_GraphQLModel):
    category: list[NotificationCategory] | None = None


class GroupArgs(ConnectionArgs):
    """Arguments of a merchants/categories/tags connection."""
    search: str | None = Field(default=None, max_length=100)
    date_range: DateRange | None = None
    order_by: GroupOrder = GroupOrder.TOTAL_DESC

    @field_validator("search")
    @classmethod
    def blank_is_none(cls, v):
        return (v.strip().casefold() or None) if v is not None else None


# --- mutation inputs: the REST bodies plus a node id and Relay's clientMutationId ----------
# Validated with nulls kept: a field sent as null clears it, a field left out is untouched
# (`model_fields_set` tells them apart).

class MutationInput(_GraphQLModel):
    client_mutation_id: str | None = Field(default=None, max_length=100)


class UpdateTransactionInput(MutationInput, Patch):
    id: node_id_of("Transaction")
    goal_id: node_id_of("Goal") | None = None   # a Goal's global id here, an int in the REST body

    def changes(self):
        out = {f: getattr(self, f) for f in self.model_fields_set & set(Patch.model_fields)}
        if out.get("goal_id") is not None:
            out["goal_id"] = int(out["goal_id"].key)
        return out


class ClearTransactionOverrideInput(MutationInput):
    id: node_id_of("Transaction")


class SetTransactionTagsInput(MutationInput, TagSet):
    id: node_id_of("Transaction")


class LinkOffsetInput(MutationInput):
    payback_id: node_id_of("Transaction")
    expense_id: node_id_of("Transaction")
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class UnlinkOffsetInput(MutationInput):
    payback_id: node_id_of("Transaction")
    expense_id: node_id_of("Transaction")


class ResetOffsetsInput(MutationInput):
    payback_id: node_id_of("Transaction")


class UpdateTagInput(MutationInput, TagEdit):
    id: node_id_of("Tag")


class DeleteTagInput(MutationInput):
    id: node_id_of("Tag")


class GoalCreateInput(MutationInput, GoalEdit):
    description: str = Field(min_length=1, max_length=80)
    amount: float = Field(ge=0, le=100_000_000)

    def fields(self):
        """Everything sent besides description and amount, for goal_store.create_goal."""
        return {f: getattr(self, f) for f in self.model_fields_set & set(GoalEdit.model_fields)
                if f not in ("description", "amount")}


class GoalUpdateInput(MutationInput, GoalEdit):
    id: node_id_of("Goal")

    @model_validator(mode="after")
    def required_stay_set(self):
        if any(f in self.model_fields_set and getattr(self, f) is None for f in ("description", "amount")):
            raise ValueError("description and amount cannot be cleared")
        return self

    def changes(self):
        return {f: getattr(self, f) for f in self.model_fields_set & set(GoalEdit.model_fields)}


class GoalDeleteInput(MutationInput):
    id: node_id_of("Goal")


class CategoryMergeInput(MutationInput):
    id: node_id_of("Category")
    into_id: node_id_of("Category")


class CategoryUnmergeInput(MutationInput):
    id: node_id_of("Category")


class PlanTargetsUpdateInput(MutationInput):
    """Any of the three targets; null or 0 unsets, negative is rejected, an omitted one is untouched."""
    emergency_fund: Decimal | None = Field(default=None, ge=0, le=1_000_000_000, max_digits=12, decimal_places=2)
    inheritance: Decimal | None = Field(default=None, ge=0, le=1_000_000_000, max_digits=12, decimal_places=2)
    retirement: Decimal | None = Field(default=None, ge=0, le=1_000_000_000, max_digits=12, decimal_places=2)

    def changes(self):
        """goal_store.set_targets keyword arguments for the targets that were sent."""
        return {f"{f}_target": getattr(self, f) for f in ("emergency_fund", "inheritance", "retirement")
                if f in self.model_fields_set}


class AssetKind(str, Enum):
    PROPERTY = "property"


class AssetCreateInput(MutationInput):
    kind: AssetKind
    label: str = Field(min_length=1, max_length=80)
    value: Decimal = Field(ge=0, le=1_000_000_000, max_digits=12, decimal_places=2)
    valued_at: dt.date | None = None


class AssetUpdateInput(MutationInput):
    id: node_id_of("Asset")
    label: str | None = Field(default=None, min_length=1, max_length=80)
    value: Decimal | None = Field(default=None, ge=0, le=1_000_000_000, max_digits=12, decimal_places=2)
    valued_at: dt.date | None = None

    @model_validator(mode="after")
    def nothing_cleared(self):
        if any(f in self.model_fields_set and getattr(self, f) is None for f in ("label", "value", "valued_at")):
            raise ValueError("an asset's label, value and valuedAt cannot be cleared")
        return self

    def changes(self):
        """asset_store.update_asset keyword arguments for the fields that were sent."""
        return {f: getattr(self, f) for f in ("label", "value", "valued_at") if f in self.model_fields_set}


class UpdateNotificationInput(MutationInput):
    id: node_id_of("Notification")
    read: bool | None = None
    snoozed_until_at: dt.datetime | None = None   # null clears the snooze

    def changes(self, now):
        """The inbox columns to set: `read` stamps or clears `read_at`; a sent `snoozedUntilAt` replaces the snooze."""
        out = {}
        if self.read is not None:
            out["read_at"] = now if self.read else None
        if "snoozed_until_at" in self.model_fields_set:
            out["snoozed_until_at"] = self.snoozed_until_at
        return out


class NotificationIdInput(MutationInput):
    id: node_id_of("Notification")


class BulkNotificationInput(MutationInput):
    category: list[NotificationCategory] | None = None

    def categories(self):
        return [c.value for c in self.category] if self.category is not None else None


class SnoozeAllNotificationsInput(BulkNotificationInput):
    snoozed_until_at: dt.datetime


class SyncSourceRetryInput(MutationInput):
    id: node_id_of("SyncSource")


class TenantCreateInput(MutationInput):
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=40)
    name: str = Field(min_length=1, max_length=80)
    owner_email: str = Field(max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class TenantMemberSetInput(MutationInput):
    id: node_id_of("Tenant")
    email: str = Field(max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: Literal["owner", "admin", "member"]


class TenantMemberRemoveInput(MutationInput):
    id: node_id_of("Tenant")
    email: str = Field(max_length=200)


class TenantSetStatusInput(MutationInput):
    id: node_id_of("Tenant")
    status: Literal["active", "suspended"]
