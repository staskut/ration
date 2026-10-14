import { describe, expect, it } from "vitest";

import { INVALIDATES, keys, type ChangedResource } from "../src/lib/queries";

describe("query keys", () => {
  it("nest plan-scoped queries under the plan", () => {
    // Invalidating ["plan", id] must reach validation and the shopping list,
    // which is what lets a WebSocket message invalidate precisely.
    expect(keys.validation("p")).toEqual(["plan", "p", "validation"]);
    expect(keys.shoppingList("p")).toEqual(["plan", "p", "shopping-list"]);
    expect(keys.plan("p")).toEqual(["plan", "p"]);
  });

  it("separate different plans", () => {
    expect(keys.plan("a")).not.toEqual(keys.plan("b"));
  });

  it("treat an absent search as a stable key rather than undefined", () => {
    expect(keys.ingredients()).toEqual(["ingredients", ""]);
    expect(keys.ingredients("банан")).toEqual(["ingredients", "банан"]);
  });
});

describe("websocket invalidation map", () => {
  it("covers every resource the server can name as changed", () => {
    // The server's enum, from openapi.yaml's WebSocketMessage.
    const serverSends: ChangedResource[] = [
      "entries",
      "validation",
      "shopping_list",
      "feedback",
      "days",
    ];
    expect(Object.keys(INVALIDATES).sort()).toEqual([...serverSends].sort());
  });

  it("maps a shopping change to the shopping list and nothing else", () => {
    expect(INVALIDATES.shopping_list("p")).toEqual([["plan", "p", "shopping-list"]]);
  });

  it("maps feedback to both the plan and today", () => {
    // The planner sees feedback on the plan; the follower sees it on Today.
    expect(INVALIDATES.feedback("p")).toEqual([["plan", "p"], ["today"]]);
  });

  it("maps an entry change to the whole plan subtree", () => {
    // ["plan", id] is a prefix of validation and shopping-list, so one
    // invalidation reaches all three.
    expect(INVALIDATES.entries("p")).toEqual([["plan", "p"]]);
  });
});
