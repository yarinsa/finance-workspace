import type { Row, RowPatch } from "./api";

/**
 * Normalise the edit form into a PATCH body holding only what changed against `base`:
 * an emptied category/note clears that override (`null`); untouched fields are omitted.
 */
export function buildPatch(
  base: Pick<Row, "category" | "note" | "excluded">,
  form: { category: string; note: string; excluded: boolean },
): RowPatch {
  const patch: RowPatch = {};
  const category = form.category.trim();
  if (category !== base.category) patch.category = category === "" ? null : category;
  const note = form.note.trim();
  if (note !== (base.note ?? "")) patch.note = note === "" ? null : note;
  if (form.excluded !== base.excluded) patch.excluded = form.excluded;
  return patch;
}
