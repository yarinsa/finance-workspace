import type { Horizon, Row } from "@/lib/api";
import type { TransactionEditSheetQuery$data } from "@/__generated__/TransactionEditSheetQuery.graphql";

/** The live GraphQL transaction (the `TransactionEditSheet_transaction` fragment, unmasked). */
export type Txn = NonNullable<TransactionEditSheetQuery$data["transactionByKey"]>;

export const lower = (k: string | null | undefined) => (k ? (k.toLowerCase() as Horizon) : null);

/** The GraphQL transaction in the REST `Row` shape the shared overlay keeps until the rebuild publishes. */
export function toRow(t: Txn): Row {
  return {
    date: t.date,
    abs_amount: t.absAmount,
    amount: Number(t.amount),
    description: t.description,
    category: t.category?.name ?? "",
    scraped_category: t.raw.category?.name ?? "",
    note: t.note ?? null,
    excluded: t.excluded,
    overridden: t.overridden,
    origin: t.origin ?? "",
    sources: [...t.sources],
    horizon: lower(t.horizon?.key),
    scraped_horizon: lower(t.raw.horizon?.key),
    tags: t.tags.edges.map((e) => e.node.name),
    goal: t.goal?.description ?? null,
  };
}
