import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import Alpine from "../../../mcpgateway/admin_ui/alpine-setup.js";

function template(name) {
  return readFileSync(`mcpgateway/templates/observability_${name}.html`, "utf8")
    .replaceAll("{{ root_path }}", "/gateway")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "");
}

function metricsResponse(url) {
  if (url.endsWith("/queries")) return [];
  if (url.includes("/performance?")) {
    const duration = {
      count: 2, avg_duration_ms: 15, min_duration_ms: 10,
      p50: 15, p90: 19, p95: 20, p99: 20, max_duration_ms: 20,
    };
    if (url.includes("/tools/")) return { tools: [{ tool_name: "record_call_summary", ...duration }] };
    if (url.includes("/prompts/")) return { prompts: [{ prompt_id: "call_prompt", ...duration }] };
    if (url.includes("/resources/")) return { resources: [{ resource_uri: "calls://summary", ...duration }] };
  }
  if (url.includes("/top-slow?")) {
    return { endpoints: [{ endpoint: "/mcp", count: 2, avg_duration_ms: 15, max_duration_ms: 20 }] };
  }
  return { tools: [], prompts: [], resources: [], chains: [], endpoints: [] };
}

describe("Observability with the production Alpine CSP runtime", () => {
  let errors;

  beforeEach(() => {
    vi.useFakeTimers();
    errors = [];
    Alpine.setErrorHandler((error) => errors.push(error.message));
    vi.stubGlobal("Alpine", Alpine);
    vi.stubGlobal("ROOT_PATH", "/gateway");
    vi.stubGlobal("Admin", { chartRegistry: { destroyByPrefix: vi.fn() } });
    vi.stubGlobal("htmx", {
      ajax: vi.fn(async (_method, url, options) => {
        document.querySelector(options.target).innerHTML = url.includes("/traces?")
          ? '<tr><td>Recorded tool call</td></tr>'
          : '<div>1 trace</div>';
      }),
    });
    vi.stubGlobal("fetch", vi.fn(async (url) => ({
      ok: true,
      json: async () => metricsResponse(url),
      text: async () => template(url.split("/").at(-2)),
    })));
    vi.stubGlobal("__obsExecAndStrip", (html) => html);
    document.body.innerHTML = '<div id="observability-panel"></div>';
    Alpine.stopObservingMutations();
  });

  afterEach(() => {
    document.dispatchEvent(new CustomEvent("observability:leave"));
    Alpine.destroyTree(document.body);
    document.body.innerHTML = "";
    Alpine.stopObservingMutations();
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  test("initializes traces and hides inactive dashboard placeholders", async () => {
    const panel = document.getElementById("observability-panel");
    panel.innerHTML = template("partial");
    Alpine.initTree(panel);
    await vi.advanceTimersByTimeAsync(0);

    expect(errors).toEqual([]);
    expect(document.getElementById("traces-list").textContent).toContain("Recorded tool call");
    for (const name of ["metrics", "tools", "prompts", "resources"]) {
      expect(document.getElementById(`${name}-container`).style.display).toBe("none");
    }
    expect(htmx.ajax).toHaveBeenCalledWith("GET",
      "/gateway/admin/observability/traces?time_range=24h&status_filter=all&limit=50",
      expect.objectContaining({ target: "#traces-list" }));
  });

  test.each([
    ["metrics", "Advanced Metrics", "topSlowTable", "/mcp"],
    ["tools", "MCP Tools", "toolPerformanceTable", "record_call_summary"],
    ["prompts", "Prompts", "promptPerformanceTable", "call_prompt"],
    ["resources", "Resources", "resourcePerformanceTable", "calls://summary"],
  ])(
    "loads the %s view through the dashboard navigation",
    async (name, label, table, value) => {
      const panel = document.getElementById("observability-panel");
      panel.innerHTML = template("partial");
      Alpine.initTree(panel);
      [...panel.querySelectorAll("button")].find((button) => button.textContent.includes(label)).click();
      await vi.advanceTimersByTimeAsync(0);

      expect(errors).toEqual([]);
      const view = document.querySelector(`.${name}-dashboard`);
      expect(view).not.toBeNull();
      expect(Alpine.$data(view).loading).toBe(false);
      expect(Alpine.$data(view).error).toBeNull();
      expect(document.querySelector(`#${table} tbody`).textContent).toContain(value);
      await vi.waitFor(() => {
        expect(document.getElementById(`${name}-container`).style.display).not.toBe("none");
      });
      expect(fetch.mock.calls.some(([url]) =>
        url.startsWith(`/gateway/admin/observability/${name}/`) && !url.endsWith("/partial"),
      )).toBe(true);
    },
  );
});
