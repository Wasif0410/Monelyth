import { describe, expect, it, vi } from "vitest";

import { EngineRequestError, engineUrl, fetchHealth } from "@/engine/client";

const connection = { port: 51234, token: "secret-token" };

function stubFetch(implementation: (input: string, init?: RequestInit) => Promise<Response>) {
  const fetchMock = vi.fn(implementation);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("engineUrl", () => {
  it("always targets loopback", () => {
    expect(engineUrl(connection, "/health")).toBe("http://127.0.0.1:51234/health");
  });
});

describe("fetchHealth", () => {
  it("sends the bearer token and returns the parsed body", async () => {
    const fetchMock = stubFetch(() =>
      Promise.resolve(Response.json({ status: "ok", version: "0.1.0" })),
    );

    await expect(fetchHealth(connection)).resolves.toEqual({ status: "ok", version: "0.1.0" });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("http://127.0.0.1:51234/health");
    expect(init?.headers).toEqual({ Authorization: "Bearer secret-token" });
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("reports an HTTP error status", async () => {
    stubFetch(() => Promise.resolve(Response.json({ detail: "Unauthorized" }, { status: 401 })));

    const error = await fetchHealth(connection).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(EngineRequestError);
    expect(error).toMatchObject({ status: 401, message: "The engine responded with HTTP 401." });
  });

  it("reports an unreachable engine", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));

    await expect(fetchHealth(connection)).rejects.toThrow(
      new EngineRequestError("The engine could not be reached."),
    );
  });

  it("reports a body that is not JSON", async () => {
    stubFetch(() => Promise.resolve(new Response("not json", { status: 200 })));

    await expect(fetchHealth(connection)).rejects.toThrow("not JSON");
  });

  it("reports an unexpected body shape", async () => {
    stubFetch(() => Promise.resolve(Response.json({ status: "maybe" })));

    await expect(fetchHealth(connection)).rejects.toThrow("unexpected health response");
  });

  it("passes the caller's abort through unchanged", async () => {
    stubFetch((_input, init) => {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    });
    const controller = new AbortController();

    const pending = fetchHealth(connection, controller.signal);
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});
