import { Page } from "@/components/common";
import ActionList from "@/components/home/ActionList";
import { useInboxActions } from "@/lib/inbox";

/** Everything that needs attention — sync alerts and the pipeline's actions — in one list. */
export default function Inbox() {
  return (
    <Page title="אינבוקס">
      <ActionList actions={useInboxActions()} />
    </Page>
  );
}
