// Получаем данные из объекта window.dashboardData
var clientsBroughtData = window.dashboardData.clientsBroughtData;
var clientsReceivedData = window.dashboardData.clientsReceivedData;
var partnersInvitedData = window.dashboardData.partnersInvitedData;

// Преобразуем данные для графиков
var broughtLabels = [];
var broughtData = [];
for (var date in clientsBroughtData) {
  broughtLabels.push(date);
  broughtData.push(clientsBroughtData[date]);
}

var receivedLabels = [];
var receivedData = [];
for (var date in clientsReceivedData) {
  receivedLabels.push(date);
  receivedData.push(clientsReceivedData[date]);
}

var invitedLabels = [];
var invitedData = [];
for (var date in partnersInvitedData) {
  invitedLabels.push(date);
  invitedData.push(partnersInvitedData[date]);
}

// Линейная диаграмма "Приведенные клиенты"
var ctxBrought = document.getElementById('clients-brought-chart').getContext('2d');
var clientsBroughtChart = new Chart(ctxBrought, {
  type: 'line',
  data: {
    labels: broughtLabels, 
    datasets: [{
      label: 'Приведенные клиенты',
      data: broughtData, 
      borderColor: '#007bff',
      backgroundColor: 'rgba(0, 123, 255, 0.2)',
      borderWidth: 1,
      fill: true
    }]
  },
  options: {
    scales: {
      y: {
        beginAtZero: true
      }
    },
    plugins: {
      legend: {
        display: false 
      }
    }
  }
});

// Линейная диаграмма "Полученные клиенты"
var ctxReceived = document.getElementById('clients-received-chart').getContext('2d');
var clientsReceivedChart = new Chart(ctxReceived, {
  type: 'line',
  data: {
    labels: receivedLabels, 
    datasets: [{
      label: 'Полученные клиенты',
      data: receivedData, 
      borderColor: '#28a745',
      backgroundColor: 'rgba(40, 167, 69, 0.2)',
      borderWidth: 1,
      fill: true
    }]
  },
  options: {
    scales: {
      y: {
        beginAtZero: true
      }
    },
    plugins: {
      legend: {
        display: false 
      }
    }
  }
});

// Линейная диаграмма "Приглашенные партнеры"
var ctxInvited = document.getElementById('partners-invited-chart').getContext('2d');
var partnersInvitedChart = new Chart(ctxInvited, {
  type: 'line',
  data: {
    labels: invitedLabels, 
    datasets: [{
      label: 'Приглашенные партнеры',
      data: invitedData, 
      borderColor: '#ffc107',
      backgroundColor: 'rgba(255, 193, 7, 0.2)',
      borderWidth: 1,
      fill:        true
    }]
  },
  options: {
    scales: {
      y: {
        beginAtZero: true
      }
    },
    plugins: {
      legend: {
        display: false 
      }
    }
  }
});

// Обработка выбора периода
var periodSelect = document.getElementById('period-select');
var prevPeriodButton = document.getElementById('prev-period');
var nextPeriodButton = document.getElementById('next-period');
var currentPeriodStart = moment().startOf('week'); // Начинаем с текущей недели

periodSelect.addEventListener('change', function() {
  currentPeriodStart = moment().startOf(periodSelect.value); // Обновляем начальную дату периода
  updateCharts();
});

prevPeriodButton.addEventListener('click', function() {
  currentPeriodStart.subtract(1, periodSelect.value); // Переходим к предыдущему периоду
  updateCharts();
});

nextPeriodButton.addEventListener('click', function() {
  currentPeriodStart.add(1, periodSelect.value); // Переходим к следующему периоду
  updateCharts();
});

function updateCharts() {
  var selectedPeriod = periodSelect.value;

  // Обновляем URL с выбранным периодом
  var newUrl = new URL(window.location.href);
  newUrl.searchParams.set('period', selectedPeriod);
  window.history.pushState({}, '', newUrl);

  // Загружаем данные для нового периода
  fetch('/partner/dashboard?period=' + selectedPeriod)
    .then(response => response.json())
    .then(data => {
      // Обновляем данные графиков
      // --- Приведенные клиенты ---
      broughtLabels = []; // Очищаем массивы
      broughtData = [];
      for (var date in data.clients_brought_data) {
        broughtLabels.push(date);
        broughtData.push(data.clients_brought_data[date]);
      }
      clientsBroughtChart.data.labels = broughtLabels; // Обновляем метки
      clientsBroughtChart.data.datasets[0].data = broughtData; // Обновляем данные

      // --- Полученные клиенты ---
      receivedLabels = [];
      receivedData = [];
      for (var date in data.clients_received_data) {
        receivedLabels.push(date);
        receivedData.push(data.clients_received_data[date]);
      }
      clientsReceivedChart.data.labels = receivedLabels;
      clientsReceivedChart.data.datasets[0].data = receivedData;

      // --- Приглашенные партнеры ---
      invitedLabels = [];
      invitedData = [];
      for (var date in data.partners_invited_data) {
        invitedLabels.push(date);
        invitedData.push(data.partners_invited_data[date]);
      }
      partnersInvitedChart.data.labels = invitedLabels;
      partnersInvitedChart.data.datasets[0].data = invitedData;

      // Обновляем счетчики
      document.getElementById('clients-brought-count').textContent = data.partner.clients_brought;
      document.getElementById('clients-received-count').textContent = data.partner.clients_received;
      document.getElementById('partners-invited-count').textContent = data.partner.partners_invited;

      // Перерисовываем графики
      clientsBroughtChart.update();
      clientsReceivedChart.update();
      partnersInvitedChart.update();
    });
}