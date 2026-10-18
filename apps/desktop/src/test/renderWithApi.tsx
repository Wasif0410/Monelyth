/**
 * Render a component inside the same providers the app uses, against a stubbed engine.
 *
 * `routes` maps "METHOD /path" to a JSON body (or a function returning a Response), e.g.
 * `{ "GET /accounts": [] }`. Any request not listed fails the test, so tests state exactly
 * what the screen talks to.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { vi } from "vitest";

import { createApiClient } from "@/api/client";
import { ApiContext } from "@/api/context";
import { TooltipProvider } from "@/components/ui/tooltip";

export type StubRoutes = Record<string, unknown>;

export function stubEngine(routes: StubRoutes) {
  const fetchMock = vi.fn((request: Request) => {
    const url = new URL(request.url);
    const key = `${request.method} ${url.pathname}`;
    if (!(key in routes)) {
      throw new Error(`Unexpected engine request: ${key}`);
    }
    const handler = routes[key];
    if (typeof handler === "function") {
      return Promise.resolve((handler as (request: Request) => Response)(request));
    }
    return Promise.resolve(Response.json(handler));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

interface RenderOptions {
  routes?: StubRoutes;
  /** Extra routes for navigation targets, e.g. `{ path: "/welcome", element: <p>Welcome</p> }`. */
  extraRoutes?: RouteObject[];
  path?: string;
}

export function renderWithApi(ui: ReactElement, options: RenderOptions = {}) {
  const fetchMock = stubEngine(options.routes ?? {});
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const path = options.path ?? "/";
  const router = createMemoryRouter([{ path, element: ui }, ...(options.extraRoutes ?? [])], {
    initialEntries: [path],
  });
  const result = render(
    <ApiContext.Provider value={createApiClient({ port: 51234, token: "test-token" })}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <RouterProvider router={router} />
        </TooltipProvider>
      </QueryClientProvider>
    </ApiContext.Provider>,
  );
  return { ...result, fetchMock, queryClient, router };
}
