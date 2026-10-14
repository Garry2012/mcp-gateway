import { readFileSync } from "node:fs";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test, vi } from "vitest";
import Alpine from "../../../mcpgateway/admin_ui/alpine-setup.js";
import { installInnerHtmlGuard } from "../../../mcpgateway/admin_ui/security.js";
import { observabilityMetrics } from "../../../mcpgateway/admin_ui/components/observability-metrics.js";
import { observabilityTools } from "../../../mcpgateway/admin_ui/components/observability-tools.js";
import { observabilityPrompts } from "../../../mcpgateway/admin_ui/components/observability-prompts.js";
import { observabilityResources } from "../../../mcpgateway/admin_ui/components/observability-resources.js";

const originalInnerHTML = Object.getOwnPropertyDescriptor(Element.prototype, "innerHTML");

beforeAll(() => {
  installInnerHtmlGuard();
  expect(window.__mcpgatewayInnerHtmlGuardInstalled).toBe(true);
});

afterAll(() => {
  Object.defineProperty(Element.prototype, "innerHTML", originalInnerHTML);
  delete window.__mcpgatewayInnerHtmlGuardInstalled;
});

function insertPartial(panel) {
  const parsed = new DOMParser().parseFromString(template("partial"), "text/html");
  panel.replaceChildren(...parsed.body.childNodes);
}

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
        const isTraces = url.includes("/traces?");
        const parsed = new DOMParser().parseFromString(isTraces
          ? '<table><tbody><tr><td>Recorded tool call</td></tr></tbody></table>'
          : '<div>1 trace</div>', "text/html");
        const source = isTraces ? parsed.querySelector("tbody") : parsed.body;
        document.querySelector(options.target).replaceChildren(...source.childNodes);
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
    insertPartial(panel);
    Alpine.initTree(panel);
    await vi.advanceTimersByTimeAsync(0);

    expect(errors).toEqual([]);
    expect(document.getElementById("traces-list").textContent).toContain("Recorded tool call");
    for (const name of ["metrics", "tools", "prompts", "resources"]) {
      expect(document.getElementById(`${name}-container`).style.display).toBe("none");
    }
    expect(window.htmx.ajax).toHaveBeenCalledWith("GET",
      "/gateway/admin/observability/traces?time_range=24h&status_filter=all&limit=50",
      expect.objectContaining({ target: "#traces-list" }));
  });

  test.each([
    ["metrics", "Advanced Metrics", "topSlowTable", "/mcp", 5],
    ["tools", "MCP Tools", "toolPerformanceTable", "record_call_summary", 10],
    ["prompts", "Prompts", "promptPerformanceTable", "call_prompt", 10],
    ["resources", "Resources", "resourcePerformanceTable", "calls://summary", 10],
  ])(
    "loads the %s view through the dashboard navigation",
    async (name, label, table, value, columns) => {
      const panel = document.getElementById("observability-panel");
      insertPartial(panel);
      Alpine.initTree(panel);
      [...panel.querySelectorAll("button")].find((button) => button.textContent.includes(label)).click();
      await vi.advanceTimersByTimeAsync(0);

      expect(errors).toEqual([]);
      const view = document.querySelector(`.${name}-dashboard`);
      expect(view).not.toBeNull();
      expect(Alpine.$data(view).loading).toBe(false);
      expect(Alpine.$data(view).error).toBeNull();
      const rows = document.querySelectorAll(`#${table} tbody tr`);
      expect(rows).toHaveLength(1);
      expect(rows[0].cells).toHaveLength(columns);
      expect(rows[0].cells[1].textContent).toBe(value);
      await vi.waitFor(() => {
        expect(document.getElementById(`${name}-container`).style.display).not.toBe("none");
      });
      expect(fetch.mock.calls.some(([url]) =>
        url.startsWith(`/gateway/admin/observability/${name}/`) && !url.endsWith("/partial"),
      )).toBe(true);
    },
  );
});


const tableCases = [
  ["topSlowTable", observabilityMetrics, "renderTopSlowTable", "endpoints", "endpoint", ["1", "label", "0", "0 ms", "0 ms"]],
  ["topVolumeTable", observabilityMetrics, "renderTopVolumeTable", "endpoints", "endpoint", ["1", "label", "0", "0 ms"]],
  ["topErrorsTable", observabilityMetrics, "renderTopErrorsTable", "endpoints", "endpoint", ["1", "label", "0", "0", "0%"]],
  ["toolPerformanceTable", observabilityTools, "renderToolPerformanceTable", "tools", "tool_name", ["1", "label", "0", "0 ms", "0 ms", "0 ms", "0 ms", "0 ms", "0 ms", "0 ms"]],
  ["toolErrorsTable", observabilityTools, "renderToolErrorsTable", "tools", "tool_name", ["1", "label", "0", "0", "0%"]],
  ["toolChainsTable", observabilityTools, "renderToolChainsTable", "chains", "chain", ["1", "label", "0"]],
  ["promptPerformanceTable", observabilityPrompts, "renderPromptPerformanceTable", "prompts", "prompt_id", ["1", "label", "0", "0 ms", "0 ms", "0 ms", "0 ms", "0 ms", "0 ms", "0 ms"]],
  ["resourcePerformanceTable", observabilityResources, "renderResourcePerformanceTable", "resources", "resource_uri", ["1", "label", "0", "0 ms", "0 ms", "0 ms", "0 ms", "0 ms", "0 ms", "0 ms"]],
];

function tableData(key, labelKey, labels) {
  return { [key]: labels.map((label) => ({
    [labelKey]: label, count: 0, total_count: 0, error_count: 0, error_rate: 0,
    avg_duration_ms: 0, min_duration_ms: 0, max_duration_ms: 0,
    p50: 0, p90: 0, p95: 0, p99: 0,
  })) };
}

describe.each(tableCases)("%s with the production HTML guard", (id, factory, method, key, labelKey, expectedCells) => {
  beforeEach(() => {
    document.body.innerHTML = `<table id="${id}"><tbody></tbody></table>`;
  });

  afterEach(() => {
    document.body.replaceChildren();
  });

  test("preserves cell boundaries and renders hostile labels as literal text", () => {
    const label = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script> & <svg onload="window.__pwned=1"></td><td>x';
    factory()[method](tableData(key, labelKey, [label]));
    const rows = document.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(1);
    const expected = [...expectedCells];
    expected[1] = label;
    expect([...rows[0].cells].map((cell) => cell.textContent)).toEqual(expected);
    expect(rows[0].querySelector("img,script,svg")).toBeNull();
    expect(window.__pwned).toBeUndefined();
    expect(rows[0].cells[1].classList.contains("font-mono")).toBe(true);
  });

  test("preserves distinct numeric values and their units", () => {
    const data = tableData(key, labelKey, ["label"]);
    Object.assign(data[key][0], {
      count: 12, total_count: 30, error_count: 3, error_rate: 10,
      avg_duration_ms: 4.5, min_duration_ms: 1, p50: 4, p90: 7,
      p95: 8, p99: 9, max_duration_ms: 11,
    });
    const expected = {
      topSlowTable: ["1", "label", "12", "4.5 ms", "11 ms"],
      topVolumeTable: ["1", "label", "12", "4.5 ms"],
      topErrorsTable: ["1", "label", "30", "3", "10%"],
      toolErrorsTable: ["1", "label", "30", "3", "10%"],
      toolChainsTable: ["1", "label", "12"],
    }[id] ?? ["1", "label", "12", "4.5 ms", "1 ms", "4 ms", "7 ms", "8 ms", "9 ms", "11 ms"];
    factory()[method](data);
    expect([...document.querySelector("tbody tr").cells].map((cell) => cell.textContent)).toEqual(expected);
  });

  test("renders markup in a count field as text", () => {
    const data = tableData(key, labelKey, ["label"]);
    const payload = '<img src=x onerror="window.__pwned=1">';
    data[key][0].count = payload;
    data[key][0].total_count = payload;
    factory()[method](data);
    expect(document.querySelector("tbody tr").cells[2].textContent).toBe(payload);
    expect(document.querySelector("tbody img")).toBeNull();
    expect(window.__pwned).toBeUndefined();
  });

  test("ignores a missing table", () => {
    document.body.replaceChildren();
    expect(() => factory()[method](tableData(key, labelKey, ["label"]))).not.toThrow();
  });

  test("replaces previous results and removes stale rows on an empty refresh", () => {
    const view = factory();
    view[method](tableData(key, labelKey, ["first", "second"]));
    let rows = document.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect([...rows].map((row) => row.cells[0].textContent)).toEqual(["1", "2"]);
    expect([...rows].map((row) => row.cells[1].textContent)).toEqual(["first", "second"]);
    view[method](tableData(key, labelKey, ["replacement"]));
    rows = document.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(1);
    expect(rows[0].cells[1].textContent).toBe("replacement");
    view[method]({ [key]: [] });
    expect(document.querySelector("tbody").childNodes).toHaveLength(0);
  });
});
