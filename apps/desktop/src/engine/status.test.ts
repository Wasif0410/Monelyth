import { describe, expect, it } from "vitest";

import { InvalidEngineStatusError, parseEngineSnapshot } from "@/engine/status";

describe("parseEngineSnapshot", () => {
  it("parses a starting snapshot", () => {
    expect(parseEngineSnapshot({ seq: 0, state: "starting" })).toEqual({
      seq: 0,
      state: "starting",
    });
  });

  it("parses a ready snapshot and drops unknown fields", () => {
    const value = { seq: 1, state: "ready", port: 51234, token: "abc", version: "0.1.0", x: 1 };

    expect(parseEngineSnapshot(value)).toEqual({
      seq: 1,
      state: "ready",
      port: 51234,
      token: "abc",
      version: "0.1.0",
    });
  });

  it("parses a failed snapshot", () => {
    expect(parseEngineSnapshot({ seq: 2, state: "failed", message: "boom" })).toEqual({
      seq: 2,
      state: "failed",
      message: "boom",
    });
  });

  it.each([
    ["null", null],
    ["an array", []],
    ["a missing seq", { state: "starting" }],
    ["a negative seq", { seq: -1, state: "starting" }],
    ["a fractional seq", { seq: 1.5, state: "starting" }],
    ["an unknown state", { seq: 0, state: "sleeping" }],
    ["port 0", { seq: 0, state: "ready", port: 0, token: "t", version: "1" }],
    ["port 65536", { seq: 0, state: "ready", port: 65536, token: "t", version: "1" }],
    ["a string port", { seq: 0, state: "ready", port: "80", token: "t", version: "1" }],
    ["an empty token", { seq: 0, state: "ready", port: 80, token: "", version: "1" }],
    ["a missing version", { seq: 0, state: "ready", port: 80, token: "t" }],
    ["an empty failure message", { seq: 0, state: "failed", message: "" }],
  ])("rejects %s", (_label, value) => {
    expect(() => parseEngineSnapshot(value)).toThrow(InvalidEngineStatusError);
  });
});
