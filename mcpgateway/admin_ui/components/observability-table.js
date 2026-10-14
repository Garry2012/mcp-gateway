/**
 * Replace table rows with text-only cells.
 *
 * @param {HTMLTableSectionElement} tbody - Table body to update.
 * @param {Array<object>} items - Records in display order.
 * @param {Array<[string, function]>} columns - Cell classes and value functions.
 */
export function replaceTableRows(tbody, items, columns) {
  const fragment = document.createDocumentFragment();
  items.forEach((item, idx) => {
    const row = document.createElement('tr');
    row.className = 'hover:bg-gray-50 dark:hover:bg-gray-700/50';
    for (const [className, value] of columns) {
      const cell = document.createElement('td');
      cell.className = className;
      cell.textContent = String(value(item, idx));
      row.appendChild(cell);
    }
    fragment.appendChild(row);
  });
  tbody.replaceChildren(fragment);
}
