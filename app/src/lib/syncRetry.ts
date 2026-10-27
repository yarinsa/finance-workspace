import { toGlobalId } from "@/lib/notifications";
import { graphqlRequest } from "@/lib/relay";

export type SyncRetryPoint = "SCRAPE" | "DIGEST";

const RETRY_MUTATION = `mutation SyncSourceRetry($id: ID!) {
  syncSourceRetry(id: $id) { success syncSource { id status retryFrom } }
}`;

/**
 * Retry a failed or rejected source from where it stopped: the Mac scrapes it again, or goes
 * straight to digest + publish when only those failed. Throws ApiError with the reason otherwise.
 */
export async function retrySync(
  source: string,
): Promise<SyncRetryPoint | null> {
  const data = await graphqlRequest<{
    syncSourceRetry: {
      syncSource: { retryFrom: SyncRetryPoint | null } | null;
    };
  }>(RETRY_MUTATION, { id: toGlobalId(source, "SyncSource") });
  return data.syncSourceRetry.syncSource?.retryFrom ?? null;
}
