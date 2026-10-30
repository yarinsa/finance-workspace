import { graphql } from "react-relay";
import { graphqlRequest } from "@/lib/relay";
import type { tenantAdminListQuery } from "@/__generated__/tenantAdminListQuery.graphql";
import type { tenantAdminCreateMutation } from "@/__generated__/tenantAdminCreateMutation.graphql";
import type { tenantAdminMemberSetMutation } from "@/__generated__/tenantAdminMemberSetMutation.graphql";
import type { tenantAdminMemberRemoveMutation } from "@/__generated__/tenantAdminMemberRemoveMutation.graphql";
import type { tenantAdminSetStatusMutation } from "@/__generated__/tenantAdminSetStatusMutation.graphql";

// Every operation selects the same tenant fields, so the compiler-generated result types are
// identical and `AdminTenant` is simply the list query's row.
type RawTenant = tenantAdminListQuery["response"]["tenants"][number];
type Future = "%future added value";
export type TenantRole = Exclude<RawTenant["members"][number]["role"], Future>;
export type TenantStatus = Exclude<RawTenant["status"], Future>;
/** The tenant row, enums narrowed to the SDL values (the compiler adds a "%future added value" arm). */
export type AdminTenant = Omit<RawTenant, "status" | "members"> & {
  status: TenantStatus;
  members: { email: string; role: TenantRole }[];
};
const narrow = (t: RawTenant): AdminTenant => t as unknown as AdminTenant;

const LIST = graphql`
  query tenantAdminListQuery { tenants { id slug name status createdAt members { email role } } }
`;
const CREATE = graphql`
  mutation tenantAdminCreateMutation($input: TenantCreateInput!) {
    tenantCreate(input: $input) { tenant { id slug name status createdAt members { email role } } }
  }
`;
const MEMBER_SET = graphql`
  mutation tenantAdminMemberSetMutation($id: ID!, $input: TenantMemberSetInput!) {
    tenantMemberSet(id: $id, input: $input) { tenant { id slug name status createdAt members { email role } } }
  }
`;
const MEMBER_REMOVE = graphql`
  mutation tenantAdminMemberRemoveMutation($id: ID!, $input: TenantMemberRemoveInput!) {
    tenantMemberRemove(id: $id, input: $input) { tenant { id slug name status createdAt members { email role } } }
  }
`;
const SET_STATUS = graphql`
  mutation tenantAdminSetStatusMutation($id: ID!, $input: TenantSetStatusInput!) {
    tenantSetStatus(id: $id, input: $input) { tenant { id slug name status createdAt members { email role } } }
  }
`;

/** The tenant uuid inside a GraphQL global id ("Tenant:<uuid>", base64url). */
export function tenantUuid(globalId: string): string {
  const b64 = globalId.replaceAll("-", "+").replaceAll("_", "/");
  const bin = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
  return bin.slice(bin.indexOf(":") + 1);
}

/** The command that puts a member in their Cognito group. The edge serves a tenant's published
 * files only to that group, and only the Mac (with AWS credentials) can change it. */
export function groupCommand(t: Pick<AdminTenant, "id">, email: string): string {
  return `infra/tenant-groups.sh add ${tenantUuid(t.id)} ${email}`;
}

export async function listTenants(): Promise<AdminTenant[]> {
  return (await graphqlRequest<tenantAdminListQuery>(LIST, {})).tenants.map(narrow);
}

export async function createTenant(slug: string, name: string, ownerEmail: string): Promise<AdminTenant> {
  const d = await graphqlRequest<tenantAdminCreateMutation>(CREATE, { input: { slug, name, ownerEmail } });
  return narrow(d.tenantCreate!.tenant!);
}

export async function setMember(id: string, email: string, role: TenantRole): Promise<AdminTenant> {
  const d = await graphqlRequest<tenantAdminMemberSetMutation>(MEMBER_SET, { id, input: { email, role } });
  return narrow(d.tenantMemberSet!.tenant!);
}

export async function removeMember(id: string, email: string): Promise<AdminTenant> {
  const d = await graphqlRequest<tenantAdminMemberRemoveMutation>(MEMBER_REMOVE, { id, input: { email } });
  return narrow(d.tenantMemberRemove!.tenant!);
}

export async function setStatus(id: string, status: TenantStatus): Promise<AdminTenant> {
  const d = await graphqlRequest<tenantAdminSetStatusMutation>(SET_STATUS, { id, input: { status } });
  return narrow(d.tenantSetStatus!.tenant!);
}
