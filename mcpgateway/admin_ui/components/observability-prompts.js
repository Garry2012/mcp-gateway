/**
 * Prompts view for the observability dashboard.
 *
 * Registered through Alpine.data() rather than assigned to window and invoked
 * as x-data="createPromptsController()". The admin UI bundles the CSP-safe Alpine
 * build, whose x-data resolves a bare name against the registered component
 * registry - it does not evaluate arbitrary global expressions. The call form
 * therefore failed with "Undefined variable: createPromptsController", the
 * component initialised empty, and the view rendered blank without raising.
 */
export function observabilityPrompts() {

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
      Admin.chartRegistry.destroyByPrefix('prompts-');
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
        console.log('Prompts: received observability:leave event, stopping auto-refresh');
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
          this.loadPromptUsage(),
          this.loadPromptPerformance(),
          this.loadPromptSlowness(),
          this.loadPromptErrorProne(),
        ]);
      } catch (e) {
        console.error('Failed to load prompt metrics:', e);
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },
    async loadPromptUsage() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/prompts/usage?hours=${this.timeRange}&limit=${this.limit}`
      );
      if (!response.ok) throw new Error('Failed to load prompt usage');
      const data = await response.json();
      this.renderPromptUsageChart(data);

      // Update most used card
      if (data.prompts && data.prompts.length > 0) {
        this.summaryCards.mostUsed = {
          name: data.prompts[0].prompt_id,
          value: data.prompts[0].count,
          metric: 'renders'
        };
      }
    },
    async loadPromptPerformance() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/prompts/performance?hours=${this.timeRange}&limit=${this.limit}`
      );
      if (!response.ok) throw new Error('Failed to load prompt performance');
      const data = await response.json();
      this.renderPromptPerformanceTable(data);

      // Update slowest prompt card
      if (data.prompts && data.prompts.length > 0) {
        const slowest = [...data.prompts].sort((a, b) => b.p95 - a.p95)[0];
        this.summaryCards.slowest = {
          name: slowest.prompt_id,
          value: slowest.p95,
          metric: 'ms (p95)'
        };
      }
    },
    async loadPromptSlowness() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/prompts/performance?hours=${this.timeRange}&limit=10`
      );
      if (!response.ok) throw new Error('Failed to load prompt slowness');
      const data = await response.json();
      this.renderPromptSlownessChart(data);
    },
    async loadPromptErrorProne() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/prompts/errors?hours=${this.timeRange}&limit=10`
      );
      if (!response.ok) throw new Error('Failed to load prompt errors');
      const data = await response.json();
      this.renderPromptErrorProneChart(data);

      // Update most error-prone card and overall health
      if (data.prompts && data.prompts.length > 0) {
        const mostErrorProne = [...data.prompts].sort((a, b) => b.error_rate - a.error_rate)[0];
        this.summaryCards.mostErrorProne = {
          name: mostErrorProne.prompt_id,
          value: mostErrorProne.error_rate,
          metric: '% errors'
        };

        // Calculate overall health
        const avgErrorRate = data.prompts.reduce((sum, p) => sum + p.error_rate, 0) / data.prompts.length;
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
    renderPromptUsageChart(data) {
      const canvas = document.getElementById('promptUsageChart');
      if (!canvas) return;

      // Check if canvas is visible before rendering
      if (canvas.offsetParent === null) {
        console.warn('promptUsageChart canvas is hidden, deferring render');
        return;
      }

      // Destroy existing chart via global registry
      Admin.chartRegistry.destroy('prompts-usage');

      // Handle empty data
      if (!data.prompts || data.prompts.length === 0) {
        const ctx = canvas.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        return;
      }

      requestAnimationFrame(() => {
        try {
          // Double-check visibility after animation frame
          if (canvas.offsetParent === null) {
            console.warn('promptUsageChart canvas became hidden, aborting render');
            return;
          }

          // Verify canvas is still in DOM and get valid context
          const ctx = canvas.getContext('2d');
          if (!ctx) {
            console.error('Failed to get 2d context for promptUsageChart');
            return;
          }

          const defaults = getChartDefaults();
          const chart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: data.prompts.map(p => p.prompt_id),
          datasets: [
            {
              label: 'Render Count',
              data: data.prompts.map(p => p.count),
              backgroundColor: 'rgba(168, 85, 247, 0.6)',
              borderColor: '#a855f7',
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
              text: `Prompt Rendering Frequency (Last ${this.timeRange}h)`,
              color: defaults.titleColor,
            },
            legend: {
              display: false,
            },
            tooltip: {
              callbacks: {
                label: function (context) {
                  const prompt = data.prompts?.[context?.dataIndex];
                  if (!prompt) return 'No data';
                  return [
                    `Renders: ${prompt.count}`,
                    `Percentage: ${prompt.percentage}%`
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
                text: 'Number of Renders',
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
          Admin.chartRegistry.register('prompts-usage', chart);
          this.charts.promptUsage = chart;
        } catch (e) {
          console.error('Failed to create prompt usage chart:', e);
        }
      });
    },
    renderPromptPerformanceTable(data) {
      const tbody = document.querySelector('#promptPerformanceTable tbody');
      if (!tbody) return;

      tbody.innerHTML = data.prompts
        .map(
          (prompt, idx) => `
            <tr class="hover:bg-gray-50 dark:hover:bg-gray-700/50">
              <td class="px-4 py-2 text-sm text-gray-700 dark:text-gray-400">${idx + 1}</td>
              <td class="px-4 py-2 text-sm font-mono text-gray-900 dark:text-gray-200">${prompt.prompt_id}</td>
              <td class="px-4 py-2 text-sm text-gray-600 dark:text-gray-400">${prompt.count}</td>
              <td class="px-4 py-2 text-sm text-orange-600 dark:text-orange-400 font-medium">${prompt.avg_duration_ms} ms</td>
              <td class="px-4 py-2 text-sm text-green-600 dark:text-green-400">${prompt.min_duration_ms} ms</td>
              <td class="px-4 py-2 text-sm text-blue-600 dark:text-blue-400">${prompt.p50} ms</td>
              <td class="px-4 py-2 text-sm text-indigo-600 dark:text-indigo-400">${prompt.p90} ms</td>
              <td class="px-4 py-2 text-sm text-purple-600 dark:text-purple-400">${prompt.p95} ms</td>
              <td class="px-4 py-2 text-sm text-pink-600 dark:text-pink-400">${prompt.p99} ms</td>
              <td class="px-4 py-2 text-sm text-red-600 dark:text-red-400">${prompt.max_duration_ms} ms</td>
            </tr>
          `
        )
        .join('');
    },
    renderPromptSlownessChart(data) {
      const canvas = document.getElementById('promptSlownessChart');
      if (!canvas) return;

      // Check if canvas is visible before rendering
      if (canvas.offsetParent === null) {
        console.warn('promptSlownessChart canvas is hidden, deferring render');
        return;
      }

      // Destroy existing chart via global registry
      Admin.chartRegistry.destroy('prompts-slowness');

      // Handle empty data
      if (!data.prompts || data.prompts.length === 0) {
        const ctx = canvas.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        return;
      }

      // Sort by p95 descending and take top 10
      const sortedPrompts = [...data.prompts]
        .sort((a, b) => b.p95 - a.p95)
        .slice(0, 10);

      requestAnimationFrame(() => {
        try {
          // Double-check visibility after animation frame
          if (canvas.offsetParent === null) {
            console.warn('promptSlownessChart canvas became hidden, aborting render');
            return;
          }

          // Verify canvas is still in DOM and get valid context
          const ctx = canvas.getContext('2d');
          if (!ctx) {
            console.error('Failed to get 2d context for promptSlownessChart');
            return;
          }

          const defaults = getChartDefaults();
          const chart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: sortedPrompts.map(p => p.prompt_id),
          datasets: [
            {
              label: 'p95 Latency (ms)',
              data: sortedPrompts.map(p => p.p95),
              backgroundColor: 'rgba(239, 68, 68, 0.6)',
              borderColor: '#ef4444',
              borderWidth: 1,
            },
            {
              label: 'p50 Latency (ms)',
              data: sortedPrompts.map(p => p.p50),
              backgroundColor: 'rgba(168, 85, 247, 0.6)',
              borderColor: '#a855f7',
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
              text: `Top 10 Slowest Prompts (Last ${this.timeRange}h)`,
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
                  const prompt = sortedPrompts?.[context?.dataIndex];
                  if (!prompt) return 'No data';
                  return [
                    `${context.dataset.label}: ${context.parsed.x} ms`,
                    `Avg: ${prompt.avg_duration_ms} ms`,
                    `Max: ${prompt.max_duration_ms} ms`,
                    `Renders: ${prompt.count}`
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
          Admin.chartRegistry.register('prompts-slowness', chart);
          this.charts.promptSlowness = chart;
        } catch (e) {
          console.error('Failed to create prompt slowness chart:', e);
        }
      });
    },
    renderPromptErrorProneChart(data) {
      const canvas = document.getElementById('promptErrorProneChart');
      if (!canvas) return;

      // Check if canvas is visible before rendering
      if (canvas.offsetParent === null) {
        console.warn('promptErrorProneChart canvas is hidden, deferring render');
        return;
      }

      // Destroy existing chart via global registry
      Admin.chartRegistry.destroy('prompts-errorprone');

      // Handle empty data
      if (!data.prompts || data.prompts.length === 0) {
        const ctx = canvas.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        return;
      }

      // Sort by error_rate descending and take top 10
      const sortedPrompts = [...data.prompts]
        .filter(p => p.error_rate > 0)
        .sort((a, b) => b.error_rate - a.error_rate)
        .slice(0, 10);

      if (sortedPrompts.length === 0) {
        const ctx = canvas.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        const parent = canvas.parentElement;
        if (parent) {
          // Use safe DOM manipulation instead of innerHTML with static content
          parent.textContent = '';
          const p = document.createElement('p');
          p.className = 'text-center text-emerald-500 p-8';
          p.textContent = '✓ No errors found - all prompts rendering successfully!';
          parent.appendChild(p);
        }
        return;
      }

      requestAnimationFrame(() => {
        try {
          // Double-check visibility after animation frame
          if (canvas.offsetParent === null) {
            console.warn('promptErrorProneChart canvas became hidden, aborting render');
            return;
          }

          // Verify canvas is still in DOM and get valid context
          const ctx = canvas.getContext('2d');
          if (!ctx) {
            console.error('Failed to get 2d context for promptErrorProneChart');
            return;
          }

          const defaults = getChartDefaults();
          const chart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: sortedPrompts.map(p => p.prompt_id),
          datasets: [
            {
              label: 'Error Rate (%)',
              data: sortedPrompts.map(p => p.error_rate),
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
              text: `Top 10 Error-Prone Prompts (Last ${this.timeRange}h)`,
              color: defaults.titleColor,
            },
            legend: {
              display: false,
            },
            tooltip: {
              callbacks: {
                label: function (context) {
                  const prompt = sortedPrompts?.[context?.dataIndex];
                  if (!prompt) return 'No data';
                  return [
                    `Error Rate: ${prompt.error_rate}%`,
                    `Errors: ${prompt.error_count}`,
                    `Total: ${prompt.total_count}`,
                    `Success: ${prompt.total_count - prompt.error_count}`
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
          Admin.chartRegistry.register('prompts-errorprone', chart);
          this.charts.promptErrorProne = chart;
        } catch (e) {
          console.error('Failed to create prompt error-prone chart:', e);
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
