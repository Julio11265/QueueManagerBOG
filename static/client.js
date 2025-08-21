/* global io */
const socket = io({
  transports: ['websocket', 'polling'],
  path: '/socket.io/'
});

// ---- utils ----
function clampNonNegative(input) {
  let v = parseInt(input.value, 10);
  if (isNaN(v) || v < 0) v = 0;
  input.value = v;
  return v;
}

function debounce(fn, wait = 300) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

function applyPriorityRowClass(tableId) {
  const table = document.getElementById(tableId);
  if (!table) return;
  for (const tr of table.querySelectorAll('tbody tr')) {
    tr.classList.remove('p1', 'p2');
    const sel = tr.querySelector('select[data-field="priority"]');
    if (sel) {
      if (sel.value === 'P1') tr.classList.add('p1');
      else if (sel.value === 'P2') tr.classList.add('p2');
    }
  }
}

function hydrateFromState(state) {
  if (!state) return;

  // Status
  state.status.forEach(row => {
    const tr = document.querySelector(`#status-table tbody tr[data-agent="${row.name}"]`);
    if (!tr) return;
    tr.querySelector('input[data-field="backlog"]').value = row.backlog;
    tr.querySelector('input[data-field="active"]').value = row.active;
    const sel = tr.querySelector('select[data-field="priority"]');
    if (sel) sel.value = row.priority || '';
  });

  // Assignment
  state.assignment.forEach(row => {
    const tr = document.querySelector(`#assignment-table tbody tr[data-agent="${row.name}"]`);
    if (!tr) return;
    const nameInput = tr.querySelector('.agent-input');
    if (nameInput) nameInput.value = row.name;
    tr.querySelector('input[data-field="easy_to_handle"]').value = row.easy_to_handle;
    tr.querySelector('input[data-field="investigation"]').value = row.investigation;
    tr.querySelector('input[data-field="autoclose_tickets"]').value = row.autoclose_tickets;
  });

  applyPriorityRowClass('status-table');
}

// ---- binders ----
function bindInputs() {
  // number inputs: emite al cambiar y mientras escribes (debounce)
  document.querySelectorAll('input[type="number"]').forEach(input => {
    const send = () => {
      const v = clampNonNegative(input);
      const tr = input.closest('tr');
      const agent = tr.getAttribute('data-agent');
      const table = input.dataset.table;
      const field = input.dataset.field;
      socket.emit('update_cell', { table, agent, field, value: v });
    };
    input.addEventListener('change', send);
    input.addEventListener('input', debounce(send, 250));
  });

  // priority selects
  document.querySelectorAll('select[data-field="priority"]').forEach(sel => {
    sel.addEventListener('change', () => {
      const tr = sel.closest('tr');
      const agent = tr.getAttribute('data-agent');
      const table = sel.dataset.table;
      const field = sel.dataset.field;
      socket.emit('update_cell', { table, agent, field, value: sel.value });
      applyPriorityRowClass('status-table'); // pinta al instante
    });
  });

  // rename agent (in Assignment table)
  document.querySelectorAll('#assignment-table .agent-input').forEach(inp => {
    const commitRename = () => {
      const tr = inp.closest('tr');
      const oldName = tr.getAttribute('data-agent');
      const newName = inp.value.trim();
      if (!newName) { inp.value = oldName; return; }
      if (newName !== oldName) {
        socket.emit('rename_agent', { old_name: oldName, new_name: newName });
      }
    };
    inp.addEventListener('blur', commitRename);
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }
      if (e.key === 'Escape') { inp.value = inp.closest('tr').getAttribute('data-agent'); inp.blur(); }
    });
  });

  applyPriorityRowClass('status-table');
  console.log('[client] bindInputs attached');
}

// ---- socket events ----
socket.on('connect', () => {
  console.log('[socket] connected');
});

socket.on('connect_error', (err) => {
  console.error('[socket] connect_error', err);
});

socket.on('full_state', (state) => {
  console.log('[socket] full_state');
  hydrateFromState(state);
});

socket.on('cell_updated', (msg) => {
  const { table, agent, field, value } = msg;
  const tableId = table === 'status' ? 'status-table' : 'assignment-table';
  const row = document.querySelector(`#${tableId} tbody tr[data-agent="${agent}"]`);
  if (!row) return;

  if (field === 'priority') {
    const sel = row.querySelector('select[data-field="priority"]');
    if (sel) sel.value = (value || '').toString().toUpperCase();
    applyPriorityRowClass('status-table');
  } else {
    const input = row.querySelector(`input[data-field="${field}"]`);
    if (input) input.value = Math.max(0, parseInt(value, 10) || 0);
  }
});

socket.on('agent_renamed', ({ old_name, new_name }) => {
  ['status-table', 'assignment-table'].forEach(id => {
    const row = document.querySelector(`#${id} tbody tr[data-agent="${old_name}"]`);
    if (row) {
      row.setAttribute('data-agent', new_name);
      const nameCell = row.querySelector('.agent-name');
      const inp = nameCell && nameCell.querySelector('.agent-input');
      if (inp) inp.value = new_name;
      else if (nameCell) nameCell.textContent = newNameSafe(new_name);
    }
  });
});

function newNameSafe(s) {
  return s.replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
}

socket.on('error_msg', (data) => {
  alert(data.message || 'Error');
});

// fecha (redundante con server, pero útil)
const todayEl = document.getElementById('today');
if (todayEl) todayEl.textContent = new Date().toISOString().slice(0,10);

// *** CLAVE: ejecutar bindInputs siempre, esté o no disparado DOMContentLoaded ***
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bindInputs);
} else {
  bindInputs();
}
