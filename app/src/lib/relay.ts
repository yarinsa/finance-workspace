// The Relay environment for the ledger API's GraphQL endpoint (`/api/graphql`, schema in
// api/schema/*.graphql). Same transport rules as `request()` in ./api.ts: same-origin
// cookie, the CSRF headers on every POST, and failures mapped onto ApiOffline/ApiError so
// screens handle "the home computer is off" the same way for REST and GraphQL.
import { Environment, Network, RecordSource, Store, type FetchFunction } from "relay-runtime";
import { ApiError, ApiOffline, unauthenticated } from "./api";

const OFFLINE_STATUSES = new Set([502, 503, 504]);

interface GraphQLResponseBody {
  data?: unknown;
  errors?: { message: string; path?: (string | number)[] }[];
}

const fetchGraphQL: FetchFunction = async (operation, variables) => {
  let res: Response;
  try {
    res = await fetch("/api/graphql", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Requested-With": "finance-app", Accept: "application/json" },
      body: JSON.stringify({ query: operation.text, variables, operationName: operation.name }),
    });
  } catch (err) {
    throw new ApiOffline(err instanceof Error ? err.message : "network error");
  }
  if (res.status === 401) throw unauthenticated();
  if (OFFLINE_STATUSES.has(res.status)) throw new ApiOffline(`HTTP ${res.status}`);
  if (!res.headers.get("content-type")?.includes("json")) throw new ApiOffline("non-JSON response");

  let body: GraphQLResponseBody & { error?: string; message?: string };
  try {
    body = await res.json();
  } catch {
    throw new ApiOffline("unreadable response");
  }
  // 400 (invalid document), 403 (origin/CSRF) and friends: nothing to render.
  if (!res.ok) {
    throw new ApiError(res.status, body.error ?? "graphql", body.errors?.[0]?.message ?? body.message ?? "");
  }
  // A field-level error with no data at all is a failed operation (e.g. a mutation refused).
  if (body.errors?.length && body.data == null) throw new ApiError(200, "graphql", body.errors[0].message);
  if (body.errors?.length) {
    // Mutations answer `data: {field: null}` with the reason in `errors`.
    const fields = body.data && typeof body.data === "object" ? Object.values(body.data) : [];
    if (fields.length > 0 && fields.every((v) => v == null)) throw new ApiError(200, "graphql", body.errors[0].message);
  }
  return body as never;
};

export function createEnvironment(): Environment {
  return new Environment({ network: Network.create(fetchGraphQL), store: new Store(new RecordSource()) });
}

/** The app-wide environment (one store, so a mutation's payload updates every screen showing it). */
export const environment = createEnvironment();
