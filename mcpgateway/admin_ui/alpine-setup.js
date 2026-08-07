import Alpine from '@alpinejs/csp';
import { buildTableUrl, syncCheckboxFromUrl } from './utils.js';
import { appRoot } from './components/app-root.js';
import { mainLayout } from './components/main-layout.js';
import { overflowMenu } from './components/overflow-menu.js';
import { teamSelector } from './components/team-selector.js';
import { maintenancePanel } from './components/maintenance-panel.js';
import { observabilityDashboard } from './components/observability-dashboard.js';
import { observabilityMetrics } from './components/observability-metrics.js';
import { observabilityTools } from './components/observability-tools.js';
import { observabilityPrompts } from './components/observability-prompts.js';
import { observabilityResources } from './components/observability-resources.js';

Alpine.data('appRoot', appRoot);
Alpine.data('mainLayout', mainLayout);
Alpine.data('overflowMenu', overflowMenu);
Alpine.data('teamSelector', teamSelector);
Alpine.data('maintenancePanel', maintenancePanel);
Alpine.data('observabilityDashboard', observabilityDashboard);
Alpine.data('observabilityMetrics', observabilityMetrics);
Alpine.data('observabilityTools', observabilityTools);
Alpine.data('observabilityPrompts', observabilityPrompts);
Alpine.data('observabilityResources', observabilityResources);

Alpine.magic('syncCheckbox', function () {
  return syncCheckboxFromUrl;
});

Alpine.magic('tableHxGet', function (el) {
  return function (tableName, baseUrl, checkboxId, defaultChecked, extraParams) {
    const checkbox = document.getElementById(checkboxId);
    const checked = checkbox !== null ? checkbox.checked : defaultChecked;
    const params = { include_inactive: String(checked) };
    if (extraParams) Object.assign(params, extraParams);
    el.setAttribute('hx-get', buildTableUrl(tableName, baseUrl, params));
  };
});

export default Alpine;
