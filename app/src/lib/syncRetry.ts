import { toGlobalId } from "@/lib/notifications";
import { graphql } from "react-relay";
import { graphqlRequest } from "@/lib/relay";
import type { syncRetryMutation } from "@/__generated__/syncRetryMutation.graphql";

type RetryFrom = NonNullable<NonNullable<syncRetryMutation["response"]["syncSourceRetry"]>["syncSource"]>["retryFrom"];
export type SyncRetryPoint = Exclude<NonNullable<RetryFrom>, "%future added value">;

const RETRY_MUTATION = graphql`
  mutation syncRetryMutation($id: ID!) {
    syncSourceRetry(id: $id) { success syncSource { id status retryFrom } }
  }
`;

/**
 * Retry a failed or rejected source from where it stopped: the Mac scrapes it again, or goes
 * straight to digest + publish when only those failed. Throws ApiError with the reason otherwise.
 */
export async function retrySync(
  source: string,
): Promise<SyncRetryPoint | null> {
  const data = await graphqlRequest<syncRetryMutation>(RETRY_MUTATION, { id: toGlobalId(source, "SyncSource") });
  return (data.syncSourceRetry?.syncSource?.retryFrom as SyncRetryPoint | null | undefined) ?? null;
}
