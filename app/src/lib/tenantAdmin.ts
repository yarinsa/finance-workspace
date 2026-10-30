// Tenant management for the platform admin (GraphQL `tenants` and the tenant* mutations;
// docs/tenancy.md). Everything here errors for anyone else, server-side.
import { graphqlRequest } from "@/lib/relay";

export type TenantRole = "OWNER" | "ADMIN" | "MEMBER";
export type TenantStatus = "ACTIVE" | "SUSPENDED";

export interface AdminTenant {
  id: string; // GraphQL global id
  slug: string;
  name: string;
  status: TenantStatus;
  createdAt: string;
  members: { email: string; role: TenantRole }[];
}

const FIELDS = `id slug name status createdAt members { email role }`;

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
  return (await graphqlRequest<{ tenants: AdminTenant[] }>(`{ tenants { ${FIELDS} } }`)).tenants;
}

export async function createTenant(slug: string, name: string, ownerEmail: string): Promise<AdminTenant> {
  const d = await graphqlRequest<{ tenantCreate: { tenant: AdminTenant } }>(
    `mutation($input: TenantCreateInput!) { tenantCreate(input: $input) { tenant { ${FIELDS} } } }`,
    { input: { slug, name, ownerEmail } },
  );
  return d.tenantCreate.tenant;
}

export async function setMember(id: string, email: string, role: TenantRole): Promise<AdminTenant> {
  const d = await graphqlRequest<{ tenantMemberSet: { tenant: AdminTenant } }>(
    `mutation($id: ID!, $input: TenantMemberSetInput!) { tenantMemberSet(id: $id, input: $input) { tenant { ${FIELDS} } } }`,
    { id, input: { email, role } },
  );
  return d.tenantMemberSet.tenant;
}

export async function removeMember(id: string, email: string): Promise<AdminTenant> {
  const d = await graphqlRequest<{ tenantMemberRemove: { tenant: AdminTenant } }>(
    `mutation($id: ID!, $input: TenantMemberRemoveInput!) { tenantMemberRemove(id: $id, input: $input) { tenant { ${FIELDS} } } }`,
    { id, input: { email } },
  );
  return d.tenantMemberRemove.tenant;
}

export async function setStatus(id: string, status: TenantStatus): Promise<AdminTenant> {
  const d = await graphqlRequest<{ tenantSetStatus: { tenant: AdminTenant } }>(
    `mutation($id: ID!, $input: TenantSetStatusInput!) { tenantSetStatus(id: $id, input: $input) { tenant { ${FIELDS} } } }`,
    { id, input: { status } },
  );
  return d.tenantSetStatus.tenant;
}
