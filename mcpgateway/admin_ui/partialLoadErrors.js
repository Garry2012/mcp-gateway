const boundBodies = new WeakSet();
const sectionSelector = ".tab-panel, #server-edit-modal";

/** Show recoverable errors for read-only admin partial requests. */
export function setupPartialLoadErrors() {
  if (boundBodies.has(document.body)) return;
  boundBodies.add(document.body);
  const notices = new WeakMap();

  function clear(target) {
    notices.get(target)?.remove();
    notices.delete(target);
  }

  function show(event) {
    const { target, elt, requestConfig } = event.detail || {};
    if (
      !target?.closest(sectionSelector) ||
      requestConfig?.verb?.toLowerCase() !== "get"
    )
      return;
    const path = requestConfig.path;
    if (!path || new URL(path, location.href).origin !== location.origin)
      return;
    clear(target);

    const notice = document.createElement("div");
    notice.setAttribute("role", "alert");
    notice.className =
      "p-3 my-2 rounded border border-red-300 text-red-700 dark:text-red-300";
    const message = document.createElement("span");
    message.textContent = "This section could not load. ";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "underline font-medium";
    retry.textContent = "Retry";
    retry.addEventListener("click", async () => {
      if (!target.isConnected || retry.disabled) return;
      retry.disabled = true;
      try {
        await window.htmx.ajax("GET", path, {
          target,
          source: elt?.isConnected ? elt : target,
          values: requestConfig.parameters,
        });
      } catch {
        // HTMX dispatches the error event; keep retry available on rejection.
      } finally {
        retry.disabled = false;
      }
    });
    notice.append(message, retry);
    if (/^Loading\b/.test(target.textContent.trim())) target.replaceChildren();
    const anchor = target.matches("tbody, thead, tr")
      ? target.closest("table")
      : target;
    if (target.matches(sectionSelector)) target.prepend(notice);
    else anchor.before(notice);
    notices.set(target, notice);
  }

  for (const name of ["htmx:responseError", "htmx:sendError", "htmx:timeout"]) {
    document.body.addEventListener(name, show);
  }
  document.body.addEventListener("htmx:beforeRequest", (event) =>
    clear(event.detail.target)
  );
  document.body.addEventListener("htmx:afterSwap", (event) =>
    clear(event.detail.target)
  );
  document.body.addEventListener("htmx:configRequest", (event) => {
    if (
      event.detail.verb === "get" &&
      event.detail.elt?.closest(sectionSelector) &&
      !event.detail.timeout
    ) {
      event.detail.timeout = 60000;
    }
  });
}
