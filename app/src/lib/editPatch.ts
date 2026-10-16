import type { Horizon, Row } from "./api";

/**
 * Normalise the edit form into a PATCH body holding only what changed against `base`:
 * an emptied category/note clears that override (`null`); untouched fields are omitted.
 * `horizon: "clear"` drops a horizon override so the rules decide again.
 * `G` is the goal id's type: a number for the REST body, the opaque GraphQL id otherwise.
 */
export interface EditPatch<G = number> {
  category?: string | null;
  note?: string | null;
  excluded?: boolean;
  horizon?: Horizon | null;
  goal_id?: G | null;
}

export function buildPatch<G = number>(
  base: Pick<Row, "category" | "note" | "excluded" | "horizon" | "scraped_horizon"> & { goal_id?: G | null },
  form: { category: string; note: string; excluded: boolean; horizon?: Horizon | "clear"; goal_id?: G | null },
): EditPatch<G> {
  const patch: EditPatch<G> = {};
  const category = form.category.trim();
  if (category !== base.category) patch.category = category === "" ? null : category;
  const note = form.note.trim();
  if (note !== (base.note ?? "")) patch.note = note === "" ? null : note;
  if (form.excluded !== base.excluded) patch.excluded = form.excluded;
  if (form.horizon === "clear") {
    if ((base.horizon ?? null) !== (base.scraped_horizon ?? null)) patch.horizon = null;
  } else if (form.horizon !== undefined && form.horizon !== base.horizon) patch.horizon = form.horizon;
  if (form.goal_id !== undefined && form.goal_id !== (base.goal_id ?? null)) patch.goal_id = form.goal_id;
  return patch;
}
