export const pingPoints = [];
export const batteryPoints = [];

const chartAreaBg = {
    id: 'chartAreaBg',
    beforeDraw(chart, args, opts) {
      const {ctx, chartArea} = chart;
      if (!chartArea) return;
      ctx.save();
      ctx.fillStyle = opts?.color || 'rgba(255, 255, 255, 0.06)'; // прозрачность фона
      ctx.fillRect(chartArea.left, chartArea.top, chartArea.right - chartArea.left, chartArea.bottom - chartArea.top);
      ctx.restore();
    }
  };


function getChartConfig(pts,  lineColor, fillAlpha = 0.15, title = '', ymax=100) {
      // цвета
    const borderColor = lineColor.replace(/rgba?\(([^)]+)\)/, (_, nums) => {
      const [r,g,b] = nums.split(',').map(v => Number(v.trim()));
      return `rgba(${r}, ${g}, ${b}, 0.9)`; // насыщённая линия
    });
    const backgroundColor = lineColor.replace(/rgba?\(([^)]+)\)/, (_, nums) => {
      const [r,g,b] = nums.split(',').map(v => Number(v.trim()));
      return `rgba(${r}, ${g}, ${b}, ${fillAlpha})`; // полупрозрачная заливка
    });

    return {
    type: 'line',
    data: {
      datasets: [{
        label: title,
        data: pts,
        borderWidth: 1,
        borderColor: borderColor,
        backgroundColor: backgroundColor,
        tension: 0.25,
        pointRadius: 0,
        fill: 'origin'
      }]
    },
    options: {
      scales: {
        x: {
          type: 'time',
          time: {
            unit: 'minute',
            displayFormats: { minute: 'HH:mm', second: 'HH:mm:ss' }
          },
          grid: {
            color: 'rgba(255,255,255,0.10)', // Grid lines color
          },
          ticks: {
            source: 'data',
            fontColor: 'rgba(255, 255, 255, 0.70)', // Y-axis label color
          }
        },
        y: {
          beginAtZero: true,
          max: ymax,
          grid: {
            color: 'rgba(255, 255, 255, 0.1)', // Grid lines color
          },
          ticks: {
            fontColor: 'rgba(255, 255, 255, 0.7)', // Y-axis label color
          }
        }
      },
      plugins: [chartAreaBg]
    }
  };
}

const ctxPing = document.getElementById('chart-ping');
const ctxBattery = document.getElementById('chart-battery');
export const chartPing = new Chart(ctxPing, getChartConfig(pingPoints, 'rgba(192, 57, 43, 0.7)',  0.18, 'Controls Ping Time (ms)', 250));
export const chartBattery = new Chart(ctxBattery, getChartConfig(batteryPoints, 'rgba(41, 128, 185, 0.7)', 0.18, 'Battery %', 100));
