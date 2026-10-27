import { useEffect, useState } from "react";
import { fetchQuery, graphql, useMutation } from "react-relay";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { SectionLabel } from "@/components/common";
import { failureMessage } from "@/lib/mutationError";
import { environment } from "@/lib/relay";
import { useLedgerApi } from "@/lib/useLedgerApi";
import type { CategoryMergeSheetQuery } from "@/__generated__/CategoryMergeSheetQuery.graphql";
import type { CategoryMergeSheetMergeMutation } from "@/__generated__/CategoryMergeSheetMergeMutation.graphql";
import type { CategoryMergeSheetUnmergeMutation } from "@/__generated__/CategoryMergeSheetUnmergeMutation.graphql";

const QUERY = graphql`
  query CategoryMergeSheetQuery {
    categories(first: 200) {
      edges {
        node {
          id
          name
          mergedInto {
            name
          }
        }
      }
    }
  }
`;

const MERGE = graphql`
  mutation CategoryMergeSheetMergeMutation(
    $id: ID!
    $input: CategoryMergeInput!
  ) {
    categoryMerge(id: $id, input: $input) {
      success
      category {
        id
        mergedInto {
          name
        }
      }
    }
  }
`;

const UNMERGE = graphql`
  mutation CategoryMergeSheetUnmergeMutation($id: ID!) {
    categoryUnmerge(id: $id) {
      success
      category {
        id
        mergedInto {
          name
        }
      }
    }
  }
`;

interface Cat {
  id: string;
  name: string;
  mergedInto: string | null;
}

/**
 * Merge a top-level category into another one (its transactions and plan count there from
 * the next rebuild), or undo a merge into it. `targets` are the other top-level categories.
 */
export default function CategoryMergeSheet({
  category,
  targets,
  onClose,
}: {
  category: string | null;
  targets: string[];
  onClose: () => void;
}) {
  const { online, markOffline, markDirty } = useLedgerApi();
  const [cats, setCats] = useState<Cat[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [commitMerge] = useMutation<CategoryMergeSheetMergeMutation>(MERGE);
  const [commitUnmerge] =
    useMutation<CategoryMergeSheetUnmergeMutation>(UNMERGE);

  useEffect(() => {
    if (!category) return;
    setCats(null);
    setError(null);
    const sub = fetchQuery<CategoryMergeSheetQuery>(
      environment,
      QUERY,
      {},
      { fetchPolicy: "network-only" },
    ).subscribe({
      next: (d) =>
        setCats(
          d.categories.edges.map((e) => ({
            id: e.node.id,
            name: e.node.name,
            mergedInto: e.node.mergedInto?.name ?? null,
          })),
        ),
      error: (e: Error) =>
        setError(failureMessage(e, markOffline, "הטעינה נכשלה")),
    });
    return () => sub.unsubscribe();
  }, [category, markOffline]);

  const byName = new Map((cats ?? []).map((c) => [c.name, c]));
  const self = category ? byName.get(category) : undefined;
  const mergedHere = (cats ?? []).filter((c) => c.mergedInto === category);
  const readOnly = online !== true || busy;

  const done = () => {
    setBusy(false);
    markDirty();
    onClose();
  };
  const fail = (e: Error) => {
    setBusy(false);
    setError(failureMessage(e, markOffline, "השמירה נכשלה"));
  };
  const merge = (into: Cat) => {
    if (!self) return;
    setBusy(true);
    commitMerge({
      variables: { id: self.id, input: { intoId: into.id } },
      onCompleted: done,
      onError: fail,
    });
  };
  const unmerge = (c: Cat) => {
    setBusy(true);
    commitUnmerge({ variables: { id: c.id }, onCompleted: done, onError: fail });
  };

  return (
    <Sheet open={category != null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="bottom"
        className="max-h-[90dvh] overflow-y-auto"
        dir="rtl"
      >
        <SheetHeader>
          <SheetTitle className="font-display text-xl font-medium">
            מיזוג {category}
          </SheetTitle>
          <SheetDescription>
            התנועות והתכנון של {category} ייספרו בקטגוריה שתבחרו. אפשר לבטל בכל
            רגע.
          </SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-6">
          {error && <div className="mb-2 text-sm text-bad">{error}</div>}
          {online !== true && (
            <div className="mb-2 text-sm text-muted-foreground">
              עריכה זמינה כשהמחשב הביתי מחובר.
            </div>
          )}
          {!cats && !error && (
            <div className="text-sm text-muted-foreground">טוען…</div>
          )}
          {cats && mergedHere.length > 0 && (
            <>
              <SectionLabel className="mb-1">מוזגו לכאן</SectionLabel>
              <ul className="mb-4 divide-y divide-line">
                {mergedHere.map((c) => (
                  <li
                    key={c.id}
                    className="flex items-center justify-between py-2"
                  >
                    <span>{c.name}</span>
                    <button
                      type="button"
                      disabled={readOnly}
                      onClick={() => unmerge(c)}
                      className="text-sm font-semibold text-brand disabled:opacity-50"
                    >
                      ביטול מיזוג
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          {cats && self && (
            <>
              <SectionLabel className="mb-1">למזג לתוך</SectionLabel>
              <ul className="divide-y divide-line">
                {targets
                  .map((t) => byName.get(t))
                  .filter((t): t is Cat => t != null && t.mergedInto == null)
                  .map((t) => (
                    <li key={t.id}>
                      <button
                        type="button"
                        disabled={readOnly}
                        onClick={() => merge(t)}
                        className="w-full py-2.5 text-start disabled:opacity-50"
                      >
                        {t.name}
                      </button>
                    </li>
                  ))}
              </ul>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
