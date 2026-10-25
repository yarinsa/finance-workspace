import { Page } from "@/components/common";
import FixedExpenses from "@/components/FixedExpenses";

/** Every fixed monthly bill, by how realistically it can be cut (moved out of the month hub). */
export default function Fixed() {
  return (
    <Page title="הוצאות קבועות">
      <FixedExpenses />
    </Page>
  );
}
