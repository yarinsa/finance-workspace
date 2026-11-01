import { useState } from "react";
import { graphql, useMutation } from "react-relay";
import { HorizonChips } from "@/components/shared/HorizonChips";
import type { Horizon } from "@/lib/api";
import { getDataVersion, type PersonalGoal } from "@/lib/data";
import { overlayAssign, recordHoldingChange } from "@/lib/holdingsOverlay";
import { failureMessage } from "@/lib/mutationError";
import { toGlobalId } from "@/lib/notifications";
import type { HoldingRow } from "@/lib/savingsView";
import { useLedgerApi } from "@/lib/useLedgerApi";
import type { HoldingPlacementMutation } from "@/__generated__/HoldingPlacementMutation.graphql";

const ASSIGN = graphql`
  mutation HoldingPlacementMutation($input: HoldingAssignInput!) {
    holdingAssign(input: $input) {
      success
      assignment { holdingId horizon goalId }
    }
  }
`;

/**
 * Horizon chips and a goal picker for one holding. Shown only while the ledger API is online;
 * tapping the active horizon clears it (back to the derived horizon or לא משויך). The change
 * shows at once through the holdings overlay and the digest catches up after the next rebuild.
 */
export default function HoldingPlacement({ h, goals }: { h: HoldingRow; goals: readonly PersonalGoal[] }) {
  const { online, markOffline, markDirty } = useLedgerApi();
  const [commit, inFlight] = useMutation<HoldingPlacementMutation>(ASSIGN);
  const [failed, setFailed] = useState<string | null>(null);
  if (online !== true) return null;

  const manualHorizon = h.horizonSource === "manual" ? h.horizon : null;

  const send = (patch: { horizon?: Horizon | null; goalId?: number | null }) => {
    setFailed(null);
    // Shown at once; rolled back to the previous value if the request fails.
    const before = { horizon: manualHorizon, goalId: h.goalId };
    recordHoldingChange((o) => overlayAssign(o, h.id, patch, getDataVersion()));
    const input: { holdingId: string; horizon?: "CURRENT" | "NEAR" | "FUTURE" | null; goalId?: string | null } = { holdingId: h.id };
    if (patch.horizon !== undefined) input.horizon = patch.horizon ? (patch.horizon.toUpperCase() as "CURRENT" | "NEAR" | "FUTURE") : null;
    if (patch.goalId !== undefined) input.goalId = patch.goalId != null ? toGlobalId(patch.goalId, "Goal") : null;
    commit({
      variables: { input },
      onCompleted: (r) => {
        if (r.holdingAssign.success) markDirty();
        else {
          recordHoldingChange((o) => overlayAssign(o, h.id, before, getDataVersion()));
          setFailed("השמירה נכשלה");
        }
      },
      onError: (e) => {
        recordHoldingChange((o) => overlayAssign(o, h.id, before, getDataVersion()));
        setFailed(failureMessage(e, markOffline, "השמירה נכשלה"));
      },
    });
  };

  const assignable = goals.filter((g) => g.goal_id != null);
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <HorizonChips
        value={manualHorizon}
        editable={!inFlight}
        busy={inFlight}
        onPick={(next) => send({ horizon: next === manualHorizon ? null : next })}
      />
      {assignable.length > 0 && (
        <select
          aria-label="יעד"
          value={h.goalId ?? ""}
          disabled={inFlight}
          onChange={(e) => send({ goalId: e.target.value ? Number(e.target.value) : null })}
          className="rounded-full border border-line bg-panel px-2 py-0.5 text-xs text-foreground"
        >
          <option value="">ללא יעד</option>
          {assignable.map((g) => (
            <option key={g.goal_id} value={g.goal_id as number}>
              {g.description}
            </option>
          ))}
        </select>
      )}
      {failed && <span role="alert" className="text-xs text-destructive">{failed}</span>}
    </div>
  );
}
