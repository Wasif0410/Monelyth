import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom does no layout and lacks a few browser APIs that Radix primitives (Select, Dialog,
// DropdownMenu, Tooltip) call when they open. Every screen uses them, so stub them once here.
// Tests that need real measurements (e.g. a virtualized list) add their own spies on top.
class NoopResizeObserver {
  observe = (): undefined => undefined;
  unobserve = (): undefined => undefined;
  disconnect = (): undefined => undefined;
}
globalThis.ResizeObserver = NoopResizeObserver;
Element.prototype.hasPointerCapture = () => false;
Element.prototype.releasePointerCapture = () => undefined;
Element.prototype.scrollIntoView = () => undefined;

afterEach(() => {
  cleanup();
});
