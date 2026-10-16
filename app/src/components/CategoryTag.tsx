/** A small pill with a transaction's category (from the `categories` table). Renders nothing when uncategorised. */
export default function CategoryTag({ name }: { name?: string | null }) {
  if (!name) return null;
  return (
    <span className="inline-block max-w-[140px] truncate rounded-full border border-line bg-muted px-1.5 py-px align-middle text-[10px] font-medium leading-4 text-muted-foreground">
      {name}
    </span>
  );
}
