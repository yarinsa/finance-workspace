/**
 * A tappable, scrollable list of options (categories, tags) under a text field: a
 * datalist replacement that works on mobile Safari and always shows every option.
 * `query` filters by substring unless it exactly matches an option (then all show).
 */
export default function OptionChips({
  options,
  query = "",
  selected,
  disabled,
  onPick,
  label,
}: {
  options: string[];
  query?: string;
  selected?: string | null;
  disabled?: boolean;
  onPick: (option: string) => void;
  label: string;
}) {
  const q = query.trim();
  const shown = q && !options.includes(q) ? options.filter((o) => o.includes(q)) : options;
  if (shown.length === 0) return null;
  return (
    <div role="listbox" aria-label={label} className="mt-1.5 flex max-h-36 flex-wrap gap-1.5 overflow-y-auto">
      {shown.map((o) => (
        <button
          key={o}
          type="button"
          role="option"
          aria-selected={o === selected}
          disabled={disabled}
          onClick={() => onPick(o)}
          className={`rounded-full border px-2.5 py-1 text-xs disabled:opacity-40 ${
            o === selected ? "border-brand bg-brand/15 font-semibold" : "border-line"
          }`}
        >
          {o}
        </button>
      ))}
    </div>
  );
}
