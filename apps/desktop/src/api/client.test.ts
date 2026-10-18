import { describe, expect, it, vi } from "vitest";

import { ApiError, createApiClient, unwrap } from "@/api/client";

function result<T>(status: number, data?: T, error?: unknown) {
  return Promise.resolve({ data, error, response: new Response(null, { status }) });
}

describe("unwrap", () => {
  it("returns data for a successful response", async () => {
    await expect(unwrap(result(200, { id: 1 }))).resolves.toEqual({ id: 1 });
  });

  it("uses the engine's detail message", async () => {
    const error = await unwrap(
      result(409, undefined, { detail: "This file was already imported." }),
    ).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, message: "This file was already imported." });
  });

  it("joins FastAPI validation messages", async () => {
    const body = { detail: [{ msg: "Field required" }, { msg: "Value is not a valid integer" }] };

    await expect(unwrap(result(422, undefined, body))).rejects.toThrow(
      "Field required Value is not a valid integer",
    );
  });

  it("falls back to a generic message for unknown bodies", async () => {
    await expect(unwrap(result(500, undefined, { unexpected: true }))).rejects.toThrow(
      "The engine couldn't complete the request (HTTP 500).",
    );
  });

  it("treats a missing body on success as an error", async () => {
    await expect(unwrap(result(200))).rejects.toBeInstanceOf(ApiError);
  });
});

describe("createApiClient", () => {
  it("calls loopback with the bearer token", async () => {
    const fetchMock = vi.fn<(request: Request) => Promise<Response>>(() =>
      Promise.resolve(Response.json([])),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = createApiClient({ port: 51234, token: "secret" });

    await unwrap(client.GET("/accounts"));

    const request = fetchMock.mock.calls[0]?.[0];
    expect(request?.url).toBe("http://127.0.0.1:51234/accounts");
    expect(request?.headers.get("Authorization")).toBe("Bearer secret");
  });
});
