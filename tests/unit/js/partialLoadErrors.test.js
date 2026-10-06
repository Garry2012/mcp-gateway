import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { setupPartialLoadErrors } from "../../../mcpgateway/admin_ui/partialLoadErrors.js";

describe("partial load failures", () => {
  let target;
  beforeEach(() => {
    document.body = document.createElement("body");
    document.body.innerHTML =
      '<div class="tab-panel" id="overview-panel" hx-get="/admin/overview/partial"><span>Loading overview...</span></div>';
    target = document.getElementById("overview-panel");
    window.htmx = { ajax: vi.fn().mockResolvedValue(undefined) };
    setupPartialLoadErrors();
  });
  function emit(type, verb = "get", status = 503) {
    target.dispatchEvent(
      new CustomEvent(type, {
        bubbles: true,
        detail: {
          target,
          elt: target,
          xhr: { status },
          requestConfig: {
            verb,
            path: "/admin/overview/partial",
            parameters: {},
          },
        },
      })
    );
  }
  test.each(["htmx:responseError", "htmx:sendError", "htmx:timeout"])(
    "%s replaces loading with a retry",
    async (type) => {
      emit(type);
      expect(document.body.textContent).not.toContain("Loading overview");
      expect(document.querySelector('[role="alert"]')).not.toBeNull();
      document.querySelector("button").click();
      expect(window.htmx.ajax).toHaveBeenCalledWith(
        "GET",
        "/admin/overview/partial",
        expect.objectContaining({ target, source: target })
      );
    }
  );
  test("does not retry mutations", () => {
    emit("htmx:responseError", "post");
    expect(document.querySelector("button")).toBeNull();
  });
  test("preserves loaded content and removes the error after success", () => {
    target.innerHTML = '<div id="existing-content">Existing server list</div>';
    emit("htmx:responseError", "get", 403);
    expect(target.querySelector("#existing-content").textContent).toBe(
      "Existing server list"
    );
    expect(document.querySelector('[role="alert"]')).not.toBeNull();
    emit("htmx:afterSwap");
    expect(document.querySelector('[role="alert"]')).toBeNull();
  });
  test("repeated failures show one error", () => {
    emit("htmx:responseError");
    emit("htmx:responseError");
    expect(document.querySelectorAll('[role="alert"]')).toHaveLength(1);
  });
  test("does not replay cross-origin paths", () => {
    target.dispatchEvent(
      new CustomEvent("htmx:responseError", {
        bubbles: true,
        detail: {
          target,
          elt: target,
          requestConfig: {
            verb: "get",
            path: "https://untrusted.example/admin/overview/partial",
          },
        },
      })
    );
    expect(document.querySelector("button")).toBeNull();
  });
});

test("outerHTML retry removes the old notice when its request completes", async () => {
  document.body = document.createElement("body");
  document.body.innerHTML =
    '<div class="tab-panel"><div id="servers-table" hx-get="/admin/servers/partial" hx-swap="outerHTML"></div></div>';
  const target = document.getElementById("servers-table");
  setupPartialLoadErrors();
  const detail = {
    target,
    elt: target,
    requestConfig: {
      verb: "get",
      path: "/admin/servers/partial",
      parameters: {},
    },
  };
  target.dispatchEvent(
    new CustomEvent("htmx:responseError", { bubbles: true, detail })
  );
  window.htmx = {
    ajax: vi.fn().mockImplementation(async () => {
      target.dispatchEvent(
        new CustomEvent("htmx:beforeRequest", { bubbles: true, detail })
      );
      target.outerHTML = '<div id="servers-table">jayashree-hospital</div>';
      document.getElementById("servers-table").dispatchEvent(
        new CustomEvent("htmx:afterSwap", {
          bubbles: true,
          detail: { target: document.getElementById("servers-table") },
        })
      );
    }),
  };
  document.querySelector("button").click();
  await Promise.resolve();
  expect(document.querySelector('[role="alert"]')).toBeNull();
  expect(document.body.textContent).toContain("jayashree-hospital");
});

test("a panel error stays inside its panel", () => {
  document.body = document.createElement("body");
  document.body.innerHTML =
    '<div class="tab-panel" id="overview-panel">Loading overview...</div>';
  setupPartialLoadErrors();
  const target = document.getElementById("overview-panel");
  target.dispatchEvent(
    new CustomEvent("htmx:responseError", {
      bubbles: true,
      detail: {
        target,
        elt: target,
        requestConfig: { verb: "get", path: "/admin/overview/partial" },
      },
    })
  );
  expect(target.querySelector('[role="alert"]')).not.toBeNull();
});

test("modal selectors receive timeout and retry handling", () => {
  document.body = document.createElement("body");
  document.body.innerHTML =
    '<div id="server-edit-modal"><div id="edit-server-tools">Loading tools...</div></div>';
  setupPartialLoadErrors();
  const target = document.getElementById("edit-server-tools");
  const config = { elt: target, verb: "get" };
  target.dispatchEvent(
    new CustomEvent("htmx:configRequest", { bubbles: true, detail: config })
  );
  expect(config.timeout).toBe(60000);
  target.dispatchEvent(
    new CustomEvent("htmx:responseError", {
      bubbles: true,
      detail: {
        target,
        elt: target,
        requestConfig: { verb: "get", path: "/admin/tools/partial" },
      },
    })
  );
  expect(
    document.querySelector('#server-edit-modal [role="alert"]')
  ).not.toBeNull();
});

test("every initial-load queue resolves to its owning section", () => {
  const template = document.createElement("template");
  template.innerHTML = readFileSync("mcpgateway/templates/admin.html", "utf8");
  const loaders = template.content.querySelectorAll('[hx-sync^="closest "]');
  expect(loaders.length).toBeGreaterThan(0);
  for (const loader of loaders) {
    const selector = loader
      .getAttribute("hx-sync")
      .split(":")[0]
      .slice("closest ".length);
    expect(
      loader.closest(selector),
      loader.id || loader.getAttribute("hx-get")
    ).not.toBeNull();
  }
});
