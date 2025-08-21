/* global io */
const socket = io();

function clampNonNegative(input) {
  let v = parseInt(input.value, 10);
  if (isNaN(v) || v < 0) v = 0;
  input.value = v;
  return v;
}

function applyPriorityRowClass(tableId) {
  const table = document.getElementById(tableId);
  for (const tr of table.querySelectorAll('tbody tr')) {
    tr.classList.remove('p1', 'p2');
    const sel = tr.querySelector('select[data-field="priority"]');
    if (sel) {
      if (sel.value === 'P1') tr.classList.add('p1');
      else if (sel.value === 'P2') tr.classList.add('p2');
    }
  }
}

function bindInputs() {
  document.querySelectorAll('input[type="number"]').forEach(input => {
    input.addEventListener('change', ev => {
      const v = clampNonNegative(input);
      const tr = input.closest('tr');
      const agent = tr.getAttribute('data-agent');
      const table = input.dataset.table;
      const field = input.dataset.field;
      socket.emit('update_cell', { table, agent, field, value: v });
    });
  });
  document.querySelectorAll('select[data-field="priority"]').forEach(sel => {
    sel.addEventListener('change', ev => {
      const tr = sel.closest('tr');
      const agent = tr.getAttribute('data-agent');
      const table = sel.dataset.table;
      const field = sel.dataset.field;
      socket.emit('update_cell', { table, agent, field, value: sel.value });
      applyPriorityRowClass('status-table');
    });
  });
  applyPriorityRowClass('status-table');
}

socket.on('connect', () => {
  // Nothing needed; server will push full_state
});

socket.on('full_state', (state) => {
  // Sync UI (optional; initial render is server-side).
  // We will also ensure priority classes are applied.
  try { applyPriorityRowClass('status-table'); } catch(e) {}
});

socket.on('cell_updated', (msg) => {
  const { table, agent, field, value } = msg;
  const tableId = table === 'status' ? 'status-table' : 'assignment-table';
  const row = document.querySelector(`#${tableId} tbody tr[data-agent="${agent}"]`);
  if (!row) return;
  if (field === 'priority') {
    const sel = row.querySelector('select[data-field="priority"]');
    if (sel) { sel.value = (value || '').toString().toUpperCase(); }
    applyPriorityRowClass('status-table');
  } else {
    const input = row.querySelector(`input[data-field="${field}"]`);
    if (input) {
      const v = parseInt(value, 10);
      input.value = isNaN(v) || v < 0 ? 0 : v;
    }
  }
});

socket.on('error_msg', (data) => {
  alert(data.message || 'Error');
});

// Show today's date (already server-rendered, but keep it fresh if page lives long)
document.getElementById('today').textContent = new Date().toISOString().slice(0,10);

document.addEventListener('DOMContentLoaded', bindInputs);
