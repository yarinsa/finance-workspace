/**
 * A transaction's tags (from the `tags` table) as small outlined `#name` chips, set apart
 * from the filled category pill. With `onPick`, each chip is a button (e.g. filter by tag);
 * the click does not bubble to the row. Renders nothing when untagged.
 */
export default function TagChips({ tags, onPick }: { tags?: string[] | null; onPick?: (tag: string) => void }) {
  if (!tags?.length) return null;
  const chip =
    "inline-block max-w-[110px] truncate rounded-full border border-brand/40 px-1.5 py-px align-middle text-[10px] font-medium leading-4 text-brand";
  return (
    <>
      {tags.map((t) =>
        onPick ? (
          <span
            key={t}
            role="button"
            tabIndex={0}
            className={`${chip} cursor-pointer hover:bg-brand/10`}
            onClick={(e) => {
              e.stopPropagation();
              onPick(t);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                e.stopPropagation();
                onPick(t);
              }
            }}
          >
            #{t}
          </span>
        ) : (
          <span key={t} className={chip}>
            #{t}
          </span>
        ),
      )}
    </>
  );
}
