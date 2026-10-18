import createClient, { type Client } from "openapi-fetch";

import type { components, paths } from "@/api/schema";
import { engineUrl } from "@/engine/client";
import type { EngineConnection } from "@/engine/status";

/** A client whose routes, parameters and responses are typed from the engine's OpenAPI schema. */
export type ApiClient = Client<paths>;

/** Response and request bodies, named as the engine names them. */
export type Schemas = components["schemas"];

export function createApiClient(connection: EngineConnection): ApiClient {
  const client = createClient<paths>({ baseUrl: engineUrl(connection, "/").slice(0, -1) });
  client.use({
    onRequest({ request }) {
      request.headers.set("Authorization", `Bearer ${connection.token}`);
      return request;
    },
  });
  return client;
}

/** A failed engine request. `message` is written for the user and safe to show as is. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(messageFromBody(status, body));
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

interface ApiResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/**
 * Await an openapi-fetch call and return its data, or throw `ApiError` for an error status.
 * Use inside TanStack Query functions so failures reach `error` with a readable message.
 */
export async function unwrap<T>(call: Promise<ApiResult<T>>): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) throw new ApiError(response.status, error);
  // A 2xx response without a body is a contract violation for every route we call.
  if (data === undefined) throw new ApiError(response.status, "The engine sent an empty response.");
  return data;
}

/**
 * The engine answers domain errors with `{"detail": "<message>"}` and invalid requests with
 * FastAPI's `{"detail": [{"msg": ...}, ...]}`; turn either into one sentence.
 */
function messageFromBody(status: number, body: unknown): string {
  if (typeof body === "string" && body) return body;
  if (typeof body === "object" && body !== null && "detail" in body) {
    const { detail } = body;
    if (typeof detail === "string" && detail) return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item: unknown) =>
          typeof item === "object" && item !== null && "msg" in item && typeof item.msg === "string"
            ? item.msg
            : undefined,
        )
        .filter((msg): msg is string => msg !== undefined);
      if (messages.length > 0) return messages.join(" ");
    }
  }
  return `The engine couldn't complete the request (HTTP ${String(status)}).`;
}
