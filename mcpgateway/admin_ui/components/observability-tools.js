/**
 * Tools view for the observability dashboard.
 *
 * Registered through Alpine.data() rather than assigned to window and invoked
 * as x-data="createToolsController()". The admin UI bundles the CSP-safe Alpine
 * build, whose x-data resolves a bare name against the registered component
 * registry - it does not evaluate arbitrary global expressions. The call form
 * therefore failed with "Undefined variable: createToolsController", the
 * component initialised empty, and the view rendered blank without raising.
 */
export function observabilityTools() {

  return {
    timeRange: 24,
    limit: 20,
    charts: {},
    loading: false,
    error: null,
    autoRefreshInterval: null,
    summaryCards: {
      slowest: null,
      mostErrorProne: null,
      mostUsed: null,
      overallHealth: 'good'
    },

    /**
     * Destroy all Chart.js instances to prevent canvas reuse errors
     */
    destroyAllCharts() {
      // Use global registry for centralized cleanup
      Admin.chartRegistry.destroyByPrefix('tools-');
      this.charts = {};
    },

    /**
     * Cleanup resources on component destroy
     */
    cleanup() {
      this.destroyAllCharts();
      this.stopAutoRefresh();
      if (this.leaveHandler) {
        document.removeEventListener('observability:leave', this.leaveHandler);
      }
    },

    async init() {
      // Clean up any existing charts first
      this.destroyAllCharts();

      await this.loadAllMetrics();
      this.startAutoRefresh();

      // Listen for tab leave event to stop auto-refresh and cleanup
      this.leaveHandler = () => {
        console.log('Tools: received observability:leave event, stopping auto-refresh');
        this.cleanup();
      };
      document.addEventListener('observability:leave', this.leaveHandler);

      // Cleanup on page unload as fallback
      window.addEventListener('beforeunload', () => this.cleanup());
    },
    async loadAllMetrics() {
      this.loading = true;
      this.error = null;
      try {
        await Promise.all([
          this.loadToolUsage(),
          this.loadToolPerformance(),
          this.loadToolErrors(),
          this.loadToolChains(),
          this.loadToolSlowness(),
          this.loadToolErrorProne(),
        ]);
      } catch (e) {
        console.error('Failed to load tool metrics:', e);
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },
    async loadToolUsage() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/tools/usage?hours=${this.timeRange}&limit=${this.limit}`
      );
      if (!response.ok) throw new Error('Failed to load tool usage');
      const data = await response.json();
      this.renderToolUsageChart(data);

      // Update most used card
      if (data.tools && data.tools.length > 0) {
        this.summaryCards.mostUsed = {
          name: data.tools[0].tool_name,
          value: data.tools[0].count,
          metric: 'invocations'
        };
      }
    },
    async loadToolPerformance() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/tools/performance?hours=${this.timeRange}&limit=${this.limit}`
      );
      if (!response.ok) throw new Error('Failed to load tool performance');
      const data = await response.json();
      this.renderToolPerformanceTable(data);

      // Update slowest tool card
      if (data.tools && data.tools.length > 0) {
        const slowest = [...data.tools].sort((a, b) => b.p95 - a.p95)[0];
        this.summaryCards.slowest = {
          name: slowest.tool_name,
          value: slowest.p95,
          metric: 'ms (p95)'
        };
      }
    },
    async loadToolErrors() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/tools/errors?hours=${this.timeRange}&limit=${this.limit}`
      );
      if (!response.ok) throw new Error('Failed to load tool errors');
      const data = await response.json();
      this.renderToolErrorsTable(data);

      // Update most error-prone card and overall health
      if (data.tools && data.tools.length > 0) {
        const mostErrorProne = [...data.tools].sort((a, b) => b.error_rate - a.error_rate)[0];
        this.summaryCards.mostErrorProne = {
          name: mostErrorProne.tool_name,
          value: mostErrorProne.error_rate,
          metric: '% errors'
        };

        // Calculate overall health (average error rate)
        const avgErrorRate = data.tools.reduce((sum, t) => sum + t.error_rate, 0) / data.tools.length;
        if (avgErrorRate < 5) {
          this.summaryCards.overallHealth = 'good';
        } else if (avgErrorRate < 20) {
          this.summaryCards.overallHealth = 'warning';
        } else {
          this.summaryCards.overallHealth = 'critical';
        }
      } else {
        this.summaryCards.overallHealth = 'good';
      }
    },
    async loadToolChains() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/tools/chains?hours=${this.timeRange}&limit=${this.limit}`
      );
      if (!response.ok) throw new Error('Failed to load tool chains');
      const data = await response.json();
      this.renderToolChainsTable(data);
    },
    async loadToolSlowness() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/tools/performance?hours=${this.timeRange}&limit=10`
      );
      if (!response.ok) throw new Error('Failed to load tool slowness');
      const data = await response.json();
      this.renderToolSlownessChart(data);
    },
    async loadToolErrorProne() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/tools/errors?hours=${this.timeRange}&limit=10`
      );
      if (!response.ok) throw new Error('Failed to load tool errors');
      const data = await response.json();
      this.renderToolErrorProneChart(data);
    },
    renderToolUsageChart(data) {
      const canvas = document.getElementById('toolUsageChart');
      if (!canvas) return;

      // Check if canvas is visible before rendering
      if (canvas.offsetParent === null) {
        console.warn('toolUsageChart canvas is hidden, deferring render');
        return;
      }

      // Destroy existing chart via global registry
      Admin.chartRegistry.destroy('tools-usage');

      // Handle empty data
      if (!data.tools || data.tools.length === 0) {
        const ctx = canvas.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        return;
      }

      requestAnimationFrame(() => {
        try {
          // Double-check visibility after animation frame
          if (canvas.offsetParent === null) {
            console.warn('toolUsageChart canvas became hidden, aborting render');
            return;
          }

          // Verify canvas is still in DOM and get valid context
          const ctx = canvas.getContext('2d');
          if (!ctx) {
            console.error('Failed to get 2d context for toolUsageChart');
            return;
          }

          const defaults = getChartDefaults();
          const chart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: data.tools.map(t => t.tool_name),
          datasets: [
            {
              label: 'Invocation Count',
              data: data.tools.map(t => t.count),
              backgroundColor: 'rgba(59, 130, 246, 0.6)',
              borderColor: '#3b82f6',
              borderWidth: 1,
            },
          ],
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            title: {
              display: true,
              text: `Tool Usage Frequency (Last ${this.timeRange}h)`,
              color: defaults.titleColor,
            },
            legend: {
              display: false,
            },
            tooltip: {
              callbacks: {
                label: function (context) {
                  const tool = data.tools?.[context?.dataIndex];
                  if (!tool) return 'No data';
                  return [
                    `Invocations: ${tool.count}`,
                    `Percentage: ${tool.percentage}%`
                  ];
                },
              },
            },
          },
          scales: {
            x: {
              beginAtZero: true,
              title: {
                display: true,
                text: 'Number of Invocations',
                color: defaults.titleColor,
              },
              ticks: {
                color: defaults.tickColor,
              },
              grid: {
                color: defaults.gridColor,
              },
            },
            y: {
              ticks: {
                color: defaults.tickColor,
              },
              grid: {
                color: defaults.gridColor,
              },
            },
          },
        },
      });
          // Register with global registry
          Admin.chartRegistry.register('tools-usage', chart);
          this.charts.toolUsage = chart;
        } catch (e) {
          console.error('Failed to create tool usage chart:', e);
        }
      });
    },
    renderToolPerformanceTable(data) {
      const tbody = document.querySelector('#toolPerformanceTable tbody');
      if (!tbody) return;

      tbody.innerHTML = data.tools
        .map(
          (tool, idx) => `
            <tr class="hover:bg-gray-50 dark:hover:bg-gray-700/50">
              <td class="px-4 py-2 text-sm text-gray-700 dark:text-gray-400">${idx + 1}</td>
              <td class="px-4 py-2 text-sm font-mono text-gray-900 dark:text-gray-200">${tool.tool_name}</td>
              <td class="px-4 py-2 text-sm text-gray-600 dark:text-gray-400">${tool.count}</td>
              <td class="px-4 py-2 text-sm text-orange-600 dark:text-orange-400 font-medium">${tool.avg_duration_ms} ms</td>
              <td class="px-4 py-2 text-sm text-green-600 dark:text-green-400">${tool.min_duration_ms} ms</td>
              <td class="px-4 py-2 text-sm text-blue-600 dark:text-blue-400">${tool.p50} ms</td>
              <td class="px-4 py-2 text-sm text-indigo-600 dark:text-indigo-400">${tool.p90} ms</td>
              <td class="px-4 py-2 text-sm text-purple-600 dark:text-purple-400">${tool.p95} ms</td>
              <td class="px-4 py-2 text-sm text-pink-600 dark:text-pink-400">${tool.p99} ms</td>
              <td class="px-4 py-2 text-sm text-red-600 dark:text-red-400">${tool.max_duration_ms} ms</td>
            </tr>
          `
        )
        .join('');
    },
    renderToolErrorsTable(data) {
      const tbody = document.querySelector('#toolErrorsTable tbody');
      if (!tbody) return;

      tbody.innerHTML = data.tools
        .map(
          (tool, idx) => `
            <tr class="hover:bg-gray-50 dark:hover:bg-gray-700/50">
              <td class="px-4 py-2 text-sm text-gray-700 dark:text-gray-400">${idx + 1}</td>
              <td class="px-4 py-2 text-sm font-mono text-gray-900 dark:text-gray-200">${tool.tool_name}</td>
              <td class="px-4 py-2 text-sm text-gray-600 dark:text-gray-400">${tool.total_count}</td>
              <td class="px-4 py-2 text-sm text-red-600 dark:text-red-400 font-medium">${tool.error_count}</td>
              <td class="px-4 py-2 text-sm text-red-700 dark:text-red-300 font-bold">${tool.error_rate}%</td>
            </tr>
          `
        )
        .join('');
    },
    renderToolChainsTable(data) {
      const tbody = document.querySelector('#toolChainsTable tbody');
      if (!tbody) return;

      tbody.innerHTML = data.chains
        .map(
          (chain, idx) => `
            <tr class="hover:bg-gray-50 dark:hover:bg-gray-700/50">
              <td class="px-4 py-2 text-sm text-gray-700 dark:text-gray-400">${idx + 1}</td>
              <td class="px-4 py-2 text-sm font-mono text-gray-900 dark:text-gray-200">${chain.chain}</td>
              <td class="px-4 py-2 text-sm text-blue-600 dark:text-blue-400 font-medium">${chain.count}</td>
            </tr>
          `
        )
        .join('');
    },
    renderToolSlownessChart(data) {
      const canvas = document.getElementById('toolSlownessChart');
      if (!canvas) return;

      // Check if canvas is visible before rendering
      if (canvas.offsetParent === null) {
        console.warn('toolSlownessChart canvas is hidden, deferring render');
        return;
      }

      // Destroy existing chart via global registry
      Admin.chartRegistry.destroy('tools-slowness');

      // Handle empty data
      if (!data.tools || data.tools.length === 0) {
        const ctx = canvas.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        return;
      }

      // Sort by p95 descending and take top 10
      const sortedTools = [...data.tools]
        .sort((a, b) => b.p95 - a.p95)
        .slice(0, 10);

      requestAnimationFrame(() => {
        try {
          // Double-check visibility after animation frame
          if (canvas.offsetParent === null) {
            console.warn('toolSlownessChart canvas became hidden, aborting render');
            return;
          }

          // Verify canvas is still in DOM and get valid context
          const ctx = canvas.getContext('2d');
          if (!ctx) {
            console.error('Failed to get 2d context for toolSlownessChart');
            return;
          }

          const defaults = getChartDefaults();
          const chart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: sortedTools.map(t => t.tool_name),
          datasets: [
            {
              label: 'p95 Latency (ms)',
              data: sortedTools.map(t => t.p95),
              backgroundColor: 'rgba(239, 68, 68, 0.6)',
              borderColor: '#ef4444',
              borderWidth: 1,
            },
            {
              label: 'p50 Latency (ms)',
              data: sortedTools.map(t => t.p50),
              backgroundColor: 'rgba(59, 130, 246, 0.6)',
              borderColor: '#3b82f6',
              borderWidth: 1,
            },
          ],
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            title: {
              display: true,
              text: `Top 10 Slowest Tools (Last ${this.timeRange}h)`,
              color: defaults.titleColor,
            },
            legend: {
              display: true,
              position: 'top',
              labels: {
                color: defaults.color,
              },
            },
            tooltip: {
              callbacks: {
                label: function (context) {
                  const tool = sortedTools?.[context?.dataIndex];
                  if (!tool) return 'No data';
                  return [
                    `${context.dataset.label}: ${context.parsed.x} ms`,
                    `Avg: ${tool.avg_duration_ms} ms`,
                    `Max: ${tool.max_duration_ms} ms`,
                    `Invocations: ${tool.count}`
                  ];
                },
              },
            },
          },
          scales: {
            x: {
              beginAtZero: true,
              title: {
                display: true,
                text: 'Latency (ms)',
                color: defaults.titleColor,
              },
              ticks: {
                color: defaults.tickColor,
              },
              grid: {
                color: defaults.gridColor,
              },
            },
            y: {
              ticks: {
                color: defaults.tickColor,
              },
              grid: {
                color: defaults.gridColor,
              },
            },
          },
        },
      });
          // Register with global registry
          Admin.chartRegistry.register('tools-slowness', chart);
          this.charts.toolSlowness = chart;
        } catch (e) {
          console.error('Failed to create tool slowness chart:', e);
        }
      });
    },
    renderToolErrorProneChart(data) {
      const canvas = document.getElementById('toolErrorProneChart');
      if (!canvas) return;

      // Check if canvas is visible before rendering
      if (canvas.offsetParent === null) {
        console.warn('toolErrorProneChart canvas is hidden, deferring render');
        return;
      }

      // Destroy existing chart via global registry
      Admin.chartRegistry.destroy('tools-errorprone');

      // Handle empty data
      if (!data.tools || data.tools.length === 0) {
        const ctx = canvas.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        return;
      }

      // Sort by error_rate descending and take top 10
      const sortedTools = [...data.tools]
        .filter(t => t.error_rate > 0)
        .sort((a, b) => b.error_rate - a.error_rate)
        .slice(0, 10);

      if (sortedTools.length === 0) {
        const ctx = canvas.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        const parent = canvas.parentElement;
        if (parent) {
          // Use safe DOM manipulation instead of innerHTML with static content
          parent.textContent = '';
          const p = document.createElement('p');
          p.className = 'text-center text-emerald-500 p-8';
          p.textContent = '✓ No errors found - all tools operating normally!';
          parent.appendChild(p);
        }
        return;
      }

      requestAnimationFrame(() => {
        try {
          // Double-check visibility after animation frame
          if (canvas.offsetParent === null) {
            console.warn('toolErrorProneChart canvas became hidden, aborting render');
            return;
          }

          // Verify canvas is still in DOM and get valid context
          const ctx = canvas.getContext('2d');
          if (!ctx) {
            console.error('Failed to get 2d context for toolErrorProneChart');
            return;
          }

          const defaults = getChartDefaults();
          const chart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: sortedTools.map(t => t.tool_name),
          datasets: [
            {
              label: 'Error Rate (%)',
              data: sortedTools.map(t => t.error_rate),
              backgroundColor: 'rgba(239, 68, 68, 0.6)',
              borderColor: '#ef4444',
              borderWidth: 1,
            },
          ],
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            title: {
              display: true,
              text: `Top 10 Error-Prone Tools (Last ${this.timeRange}h)`,
              color: defaults.titleColor,
            },
            legend: {
              display: false,
            },
            tooltip: {
              callbacks: {
                label: function (context) {
                  const tool = sortedTools?.[context?.dataIndex];
                  if (!tool) return 'No data';
                  return [
                    `Error Rate: ${tool.error_rate}%`,
                    `Errors: ${tool.error_count}`,
                    `Total: ${tool.total_count}`,
                    `Success: ${tool.total_count - tool.error_count}`
                  ];
                },
              },
            },
          },
          scales: {
            x: {
              beginAtZero: true,
              max: 100,
              title: {
                display: true,
                text: 'Error Rate (%)',
                color: defaults.titleColor,
              },
              ticks: {
                color: defaults.tickColor,
              },
              grid: {
                color: defaults.gridColor,
              },
            },
            y: {
              ticks: {
                color: defaults.tickColor,
              },
              grid: {
                color: defaults.gridColor,
              },
            },
          },
        },
      });
          // Register with global registry
          Admin.chartRegistry.register('tools-errorprone', chart);
          this.charts.toolErrorProne = chart;
        } catch (e) {
          console.error('Failed to create tool error-prone chart:', e);
        }
      });
    },

    startAutoRefresh() {
      // Clear any existing interval
      if (this.autoRefreshInterval) {
        clearInterval(this.autoRefreshInterval);
      }
      // Refresh every 60 seconds
      this.autoRefreshInterval = setInterval(() => {
        if (!this.loading) {
          this.loadAllMetrics();
        }
      }, 60000);
    },

    stopAutoRefresh() {
      if (this.autoRefreshInterval) {
        clearInterval(this.autoRefreshInterval);
        this.autoRefreshInterval = null;
      }
    },
    async applyFilters() {
      await this.loadAllMetrics();
    },
  };
}
