/**
 * Metrics view for the observability dashboard.
 *
 * Registered through Alpine.data() rather than assigned to window and invoked
 * as x-data="createMetricsController()". The admin UI bundles the CSP-safe Alpine
 * build, whose x-data resolves a bare name against the registered component
 * registry - it does not evaluate arbitrary global expressions. The call form
 * therefore failed with "Undefined variable: createMetricsController", the
 * component initialised empty, and the view rendered blank without raising.
 */
export function observabilityMetrics() {
// Metrics Dashboard Controller Factory

  return {
    timeRange: 24,
    interval: 60,
    limit: 10,
    charts: {},
    loading: false,
    error: null,
    autoRefreshInterval: null,
    visibilityHandler: null,

    /**
     * Destroy all Chart.js instances to prevent canvas reuse errors
     */
    destroyAllCharts() {
      // Use global registry for centralized cleanup
      Admin.chartRegistry.destroyByPrefix('metrics-');
      this.charts = {};
    },

    /**
     * Initialize the metrics dashboard with proper cleanup
     */
    async init() {
      // Clean up any existing charts first
      this.destroyAllCharts();

      // Load initial data
      await this.loadAllMetrics();

      // Start auto-refresh
      this.startAutoRefresh();

      // Handle visibility changes to pause updates when tab is hidden
      this.visibilityHandler = () => {
        if (document.hidden) {
          this.stopAutoRefresh();
        } else {
          // Check if we're still on the observability tab
          const panel = document.getElementById('observability-panel');
          if (panel && !panel.classList.contains('hidden')) {
            this.startAutoRefresh();
            // Refresh data when tab becomes visible
            if (!this.loading) {
              this.loadAllMetrics();
            }
          }
        }
      };
      document.addEventListener('visibilitychange', this.visibilityHandler);

      // Listen for tab leave event to stop auto-refresh and cleanup
      this.leaveHandler = () => {
        console.log('Metrics: received observability:leave event, stopping auto-refresh');
        this.cleanup();
      };
      document.addEventListener('observability:leave', this.leaveHandler);

      // Cleanup on page unload as fallback
      window.addEventListener('beforeunload', () => this.cleanup());
    },

    /**
     * Cleanup resources on component destroy
     */
    cleanup() {
      this.destroyAllCharts();
      this.stopAutoRefresh();
      if (this.visibilityHandler) {
        document.removeEventListener('visibilitychange', this.visibilityHandler);
      }
      if (this.leaveHandler) {
        document.removeEventListener('observability:leave', this.leaveHandler);
      }
    },
    /**
     * Load all metrics with proper guards to prevent concurrent refreshes
     */
    async loadAllMetrics() {
      // Prevent concurrent refreshes
      if (this.loading) {
        console.log('Refresh already in progress, skipping');
        return;
      }

      this.loading = true;
      this.error = null;

      try {
        // Destroy existing charts before loading new data
        this.destroyAllCharts();

        // Load all metrics in parallel
        await Promise.all([
          this.loadPercentiles(),
          this.loadTimeSeries(),
          this.loadTopSlow(),
          this.loadTopVolume(),
          this.loadTopErrors(),
          this.loadHeatmap(),
        ]);
      } catch (e) {
        console.error('Failed to load metrics:', e);
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },
    async loadPercentiles() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/metrics/percentiles?hours=${this.timeRange}&interval_minutes=${this.interval}`
      );
      if (!response.ok) throw new Error('Failed to load percentiles');
      const data = await response.json();
      this.renderPercentileChart(data);
    },
    async loadTimeSeries() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/metrics/timeseries?hours=${this.timeRange}&interval_minutes=${this.interval}`
      );
      if (!response.ok) throw new Error('Failed to load time series');
      const data = await response.json();
      this.renderTimeSeriesChart(data);
    },
    async loadTopSlow() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/metrics/top-slow?hours=${this.timeRange}&limit=${this.limit}`
      );
      if (!response.ok) throw new Error('Failed to load top slow endpoints');
      const data = await response.json();
      this.renderTopSlowTable(data);
    },
    async loadTopVolume() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/metrics/top-volume?hours=${this.timeRange}&limit=${this.limit}`
      );
      if (!response.ok) throw new Error('Failed to load top volume endpoints');
      const data = await response.json();
      this.renderTopVolumeTable(data);
    },
    async loadTopErrors() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/metrics/top-errors?hours=${this.timeRange}&limit=${this.limit}`
      );
      if (!response.ok) throw new Error('Failed to load top error endpoints');
      const data = await response.json();
      this.renderTopErrorsTable(data);
    },
    async loadHeatmap() {
      const response = await fetch(
        `${window.ROOT_PATH || ''}/admin/observability/metrics/heatmap?hours=${this.timeRange}&time_buckets=24&latency_buckets=20`
      );
      if (!response.ok) throw new Error('Failed to load heatmap');
      const data = await response.json();
      this.renderHeatmap(data);
    },
    /**
     * Render percentile chart with proper cleanup and error handling
     */
    renderPercentileChart(data) {
      const canvas = document.getElementById('percentileChart');
      if (!canvas) {
        console.warn('percentileChart canvas not found');
        return;
      }

      // Check if canvas is visible before rendering
      if (canvas.offsetParent === null) {
        console.warn('percentileChart canvas is hidden, deferring render');
        return;
      }

      // Destroy existing chart via global registry
      Admin.chartRegistry.destroy('metrics-percentile');

      // Use requestAnimationFrame to ensure canvas is ready
      requestAnimationFrame(() => {
        try {
          // Double-check visibility after animation frame
          if (canvas.offsetParent === null) {
            console.warn('percentileChart canvas became hidden, aborting render');
            return;
          }

          // Verify canvas is still in DOM and get valid context
          const ctx = canvas.getContext('2d');
          if (!ctx) {
            console.error('Failed to get 2d context for percentileChart');
            return;
          }

          const defaults = getChartDefaults();
          const chart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: data.timestamps.map((t) => new Date(t).toLocaleTimeString()),
          datasets: [
            {
              label: 'p50 (median)',
              data: data.p50,
              borderColor: '#10b981',
              backgroundColor: 'rgba(16, 185, 129, 0.1)',
              fill: true,
            },
            {
              label: 'p90',
              data: data.p90,
              borderColor: '#3b82f6',
              backgroundColor: 'rgba(59, 130, 246, 0.1)',
              fill: true,
            },
            {
              label: 'p95',
              data: data.p95,
              borderColor: '#f59e0b',
              backgroundColor: 'rgba(245, 158, 11, 0.1)',
              fill: true,
            },
            {
              label: 'p99',
              data: data.p99,
              borderColor: '#ef4444',
              backgroundColor: 'rgba(239, 68, 68, 0.1)',
              fill: true,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: {
            mode: 'index',
            intersect: false,
          },
          plugins: {
            title: {
              display: true,
              text: 'Latency Percentiles Over Time',
              color: defaults.titleColor,
            },
            legend: {
              position: 'bottom',
              labels: {
                color: defaults.color,
              },
            },
            tooltip: {
              callbacks: {
                label: function (context) {
                  return context.dataset.label + ': ' + context.parsed.y.toFixed(2) + ' ms';
                },
              },
            },
          },
          scales: {
            y: {
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
            x: {
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
          Admin.chartRegistry.register('metrics-percentile', chart);
          this.charts.percentile = chart;
        } catch (e) {
          console.error('Failed to create percentile chart:', e);
          this.error = 'Failed to render percentile chart';
        }
      });
    },
    /**
     * Render time series chart with proper cleanup and error handling
     */
    renderTimeSeriesChart(data) {
      const canvas = document.getElementById('timeSeriesChart');
      if (!canvas) {
        console.warn('timeSeriesChart canvas not found');
        return;
      }

      // Check if canvas is visible before rendering
      if (canvas.offsetParent === null) {
        console.warn('timeSeriesChart canvas is hidden, deferring render');
        return;
      }

      // Destroy existing chart via global registry
      Admin.chartRegistry.destroy('metrics-timeseries');

      // Use requestAnimationFrame to ensure canvas is ready
      requestAnimationFrame(() => {
        try {
          // Double-check visibility after animation frame
          if (canvas.offsetParent === null) {
            console.warn('timeSeriesChart canvas became hidden, aborting render');
            return;
          }

          // Verify canvas is still in DOM and get valid context
          const ctx = canvas.getContext('2d');
          if (!ctx) {
            console.error('Failed to get 2d context for timeSeriesChart');
            return;
          }

          const defaults = getChartDefaults();
          const chart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: data.timestamps.map((t) => new Date(t).toLocaleTimeString()),
          datasets: [
            {
              label: 'Total Requests',
              data: data.request_count,
              borderColor: '#3b82f6',
              backgroundColor: 'rgba(59, 130, 246, 0.1)',
              yAxisID: 'y',
              fill: true,
            },
            {
              label: 'Error Rate (%)',
              data: data.error_rate,
              borderColor: '#ef4444',
              backgroundColor: 'rgba(239, 68, 68, 0.1)',
              yAxisID: 'y1',
              fill: true,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: {
            mode: 'index',
            intersect: false,
          },
          plugins: {
            title: {
              display: true,
              text: 'Request Rate & Error Rate',
              color: defaults.titleColor,
            },
            legend: {
              position: 'bottom',
              labels: {
                color: defaults.color,
              },
            },
          },
          scales: {
            x: {
              ticks: {
                color: defaults.tickColor,
              },
              grid: {
                color: defaults.gridColor,
              },
            },
            y: {
              type: 'linear',
              display: true,
              position: 'left',
              title: {
                display: true,
                text: 'Requests',
                color: defaults.titleColor,
              },
              ticks: {
                color: defaults.tickColor,
              },
              grid: {
                color: defaults.gridColor,
              },
            },
            y1: {
              type: 'linear',
              display: true,
              position: 'right',
              title: {
                display: true,
                text: 'Error Rate (%)',
                color: defaults.titleColor,
              },
              ticks: {
                color: defaults.tickColor,
              },
              grid: {
                drawOnChartArea: false,
              },
            },
          },
        },
      });
          // Register with global registry
          Admin.chartRegistry.register('metrics-timeseries', chart);
          this.charts.timeSeries = chart;
        } catch (e) {
          console.error('Failed to create time series chart:', e);
          this.error = 'Failed to render time series chart';
        }
      });
    },
    renderTopSlowTable(data) {
      const tbody = document.querySelector('#topSlowTable tbody');
      if (!tbody) return;

      tbody.innerHTML = data.endpoints
        .map(
          (ep, idx) => `
            <tr class="hover:bg-gray-50 dark:hover:bg-gray-700/50">
              <td class="px-4 py-2 text-sm text-gray-700 dark:text-gray-400">${idx + 1}</td>
              <td class="px-4 py-2 text-sm font-mono text-gray-900 dark:text-gray-200">${ep.endpoint}</td>
              <td class="px-4 py-2 text-sm text-gray-600 dark:text-gray-400">${ep.count}</td>
              <td class="px-4 py-2 text-sm text-orange-600 dark:text-orange-400 font-medium">${ep.avg_duration_ms} ms</td>
              <td class="px-4 py-2 text-sm text-red-600 dark:text-red-400">${ep.max_duration_ms} ms</td>
            </tr>
          `
        )
        .join('');
    },
    renderTopVolumeTable(data) {
      const tbody = document.querySelector('#topVolumeTable tbody');
      if (!tbody) return;

      tbody.innerHTML = data.endpoints
        .map(
          (ep, idx) => `
            <tr class="hover:bg-gray-50 dark:hover:bg-gray-700/50">
              <td class="px-4 py-2 text-sm text-gray-700 dark:text-gray-400">${idx + 1}</td>
              <td class="px-4 py-2 text-sm font-mono text-gray-900 dark:text-gray-200">${ep.endpoint}</td>
              <td class="px-4 py-2 text-sm font-medium text-blue-600 dark:text-blue-400">${ep.count}</td>
              <td class="px-4 py-2 text-sm text-gray-600 dark:text-gray-400">${ep.avg_duration_ms} ms</td>
            </tr>
          `
        )
        .join('');
    },
    renderTopErrorsTable(data) {
      const tbody = document.querySelector('#topErrorsTable tbody');
      if (!tbody) return;

      tbody.innerHTML = data.endpoints
        .map(
          (ep, idx) => `
            <tr class="hover:bg-gray-50 dark:hover:bg-gray-700/50">
              <td class="px-4 py-2 text-sm text-gray-700 dark:text-gray-400">${idx + 1}</td>
              <td class="px-4 py-2 text-sm font-mono text-gray-900 dark:text-gray-200">${ep.endpoint}</td>
              <td class="px-4 py-2 text-sm text-gray-600 dark:text-gray-400">${ep.total_count}</td>
              <td class="px-4 py-2 text-sm text-red-600 dark:text-red-400 font-medium">${ep.error_count}</td>
              <td class="px-4 py-2 text-sm text-red-700 dark:text-red-300 font-bold">${ep.error_rate}%</td>
            </tr>
          `
        )
        .join('');
    },
    /**
     * Render heatmap chart with proper cleanup and error handling
     */
    renderHeatmap(data) {
      const canvas = document.getElementById('heatmapChart');
      if (!canvas) {
        console.warn('heatmapChart canvas not found');
        return;
      }

      // Check if canvas is visible before rendering
      if (canvas.offsetParent === null) {
        console.warn('heatmapChart canvas is hidden, deferring render');
        return;
      }

      // Destroy existing chart via global registry
      Admin.chartRegistry.destroy('metrics-heatmap');

      // Flatten the 2D heatmap data for Chart.js matrix
      const heatmapData = [];
      for (let y = 0; y < data.data.length; y++) {
        for (let x = 0; x < data.data[y].length; x++) {
          heatmapData.push({
            x: x,
            y: y,
            v: data.data[y][x],
          });
        }
      }

      // Use requestAnimationFrame to ensure canvas is ready
      requestAnimationFrame(() => {
        try {
          // Double-check visibility after animation frame
          if (canvas.offsetParent === null) {
            console.warn('heatmapChart canvas became hidden, aborting render');
            return;
          }

          // Verify canvas is still in DOM and get valid context
          const ctx = canvas.getContext('2d');
          if (!ctx) {
            console.error('Failed to get 2d context for heatmapChart');
            return;
          }

          const defaults = getChartDefaults();
          const chart = new Chart(ctx, {
            type: 'scatter',
            data: {
              datasets: [
                {
                  label: 'Request Count',
                  data: heatmapData,
                  backgroundColor: function (context) {
                    const value = context.raw.v;
                    const maxValue = Math.max(...heatmapData.map((d) => d.v));
                    const alpha = value / maxValue;
                    return `rgba(239, 68, 68, ${alpha})`;
                  },
                  pointRadius: 10,
                  pointHoverRadius: 12,
                },
              ],
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                title: {
                  display: true,
                  text: 'Latency Distribution Heatmap',
                  color: defaults.titleColor,
                },
                legend: {
                  display: false,
                },
                tooltip: {
                  callbacks: {
                    title: function (context) {
                      const timeLabel = data.time_labels[context[0].raw.x];
                      const latencyLabel = data.latency_labels[context[0].raw.y];
                      return `${timeLabel} - ${latencyLabel}`;
                    },
                    label: function (context) {
                      return `Requests: ${context?.raw?.v || 0}`;
                    },
                  },
                },
              },
              scales: {
                x: {
                  type: 'linear',
                  position: 'bottom',
                  ticks: {
                    stepSize: 1,
                    color: defaults.tickColor,
                    callback: function (value) {
                      return data.time_labels[value] || '';
                    },
                  },
                  title: {
                    display: true,
                    text: 'Time',
                    color: defaults.titleColor,
                  },
                  grid: {
                    color: defaults.gridColor,
                  },
                },
                y: {
                  type: 'linear',
                  ticks: {
                    stepSize: 1,
                    color: defaults.tickColor,
                    callback: function (value) {
                      return data.latency_labels[value] || '';
                    },
                  },
                  title: {
                    display: true,
                    text: 'Latency',
                    color: defaults.titleColor,
                  },
                  grid: {
                    color: defaults.gridColor,
                  },
                },
              },
            },
          });
          // Register with global registry
          Admin.chartRegistry.register('metrics-heatmap', chart);
          this.charts.heatmap = chart;
        } catch (e) {
          console.error('Failed to create heatmap chart:', e);
          this.error = 'Failed to render heatmap chart';
        }
      });
    },
    /**
     * Start auto-refresh with proper cleanup
     */
    startAutoRefresh() {
      // Clear any existing interval
      if (this.autoRefreshInterval) {
        clearInterval(this.autoRefreshInterval);
      }

      // Refresh every 60 seconds, only if not already loading
      this.autoRefreshInterval = setInterval(() => {
        if (!this.loading) {
          this.loadAllMetrics();
        }
      }, 60000);
    },
    /**
     * Stop auto-refresh
     */
    stopAutoRefresh() {
      if (this.autoRefreshInterval) {
        clearInterval(this.autoRefreshInterval);
        this.autoRefreshInterval = null;
      }
    },
    async applyFilters() {
      await this.loadAllMetrics();
    }
  };
}
