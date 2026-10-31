import { graphql } from "react-relay";
import { graphqlRequest } from "@/lib/relay";
import type { sourceSecretsLoadQuery } from "@/__generated__/sourceSecretsLoadQuery.graphql";
import type { sourceSecretsSetMutation } from "@/__generated__/sourceSecretsSetMutation.graphql";

/** A source's connection fields and which of them the household's vault holds. Never a value. */
export type SourceSecrets = sourceSecretsLoadQuery["response"]["syncSourceSecrets"];
export type SecretField = SourceSecrets["fields"][number];

const LOAD = graphql`
  query sourceSecretsLoadQuery($source: String!) {
    syncSourceSecrets(source: $source) { source canEdit fields { name title masked isSet updatedAt } }
  }
`;
const SET = graphql`
  mutation sourceSecretsSetMutation($input: SyncSourceSecretSetInput!) {
    syncSourceSecretSet(input: $input) {
      success
      secrets { source canEdit fields { name title masked isSet updatedAt } }
    }
  }
`;

export const loadSourceSecrets = async (source: string): Promise<SourceSecrets> =>
  (await graphqlRequest<sourceSecretsLoadQuery>(LOAD, { source })).syncSourceSecrets;

/**
 * Store one connection secret in the household's vault. The API writes it straight through and
 * keeps nothing; the answer is the refreshed state (set / missing), never the value.
 */
export async function setSourceSecret(source: string, name: string, value: string): Promise<SourceSecrets> {
  const data = await graphqlRequest<sourceSecretsSetMutation>(SET, { input: { source, name, value } });
  const secrets = data.syncSourceSecretSet?.secrets;
  if (!secrets) throw new Error("השמירה נכשלה");
  return secrets;
}

/** The line under a field: what the vault holds, in calm words. `now` is injectable for tests. */
export function secretStatus(f: Pick<SecretField, "isSet" | "updatedAt">, now = Date.now()): string {
  if (!f.isSet) return "חסר";
  const at = f.updatedAt ? new Date(f.updatedAt).getTime() : NaN;
  if (Number.isNaN(at)) return "מוגדר";
  const days = Math.floor((now - at) / 86_400_000);
  if (days <= 0) return "מוגדר · עודכן היום";
  if (days === 1) return "מוגדר · עודכן אתמול";
  return `מוגדר · עודכן לפני ${days} ימים`;
}
