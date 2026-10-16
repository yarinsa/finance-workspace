import type { Horizon, Row, RowPatch } from "./api";

/**
 * Normalise the edit form into a PATCH body holding only what changed against `base`:
 * an emptied category/note clears that override (`null`); untouched fields are omitted.
 * `horizon: "clear"` drops a horizon override so the rules decide again.
 */
export function buildPatch(
  base: Pick<Row, "category" | "note" | "excluded" | "horizon" | "scraped_horizon">,
  form: { category: string; note: string; excluded: boolean; horizon?: Horizon | "clear" },
): RowPatch {
  const patch: RowPatch = {};
  const category = form.category.trim();
  if (category !== base.category) patch.category = category === "" ? null : category;
  const note = form.note.trim();
  if (note !== (base.note ?? "")) patch.note = note === "" ? null : note;
  if (form.excluded !== base.excluded) patch.excluded = form.excluded;
  if (form.horizon === "clear") {
    if ((base.horizon ?? null) !== (base.scraped_horizon ?? null)) patch.horizon = null;
  } else if (form.horizon !== undefined && form.horizon !== base.horizon) patch.horizon = form.horizon;
  return patch;
}
