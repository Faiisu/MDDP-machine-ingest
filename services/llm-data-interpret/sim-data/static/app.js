const $ = (selector, parent = document) => parent.querySelector(selector);
let config;
let mlConfig;
const machineSignals = {
  speed_rpm: ['Motor speed', 'rpm'], load_percent: ['Machine load', '%'],
  vibration_mm_s: ['Vibration RMS', 'mm/s'], bearing_temperature_c: ['Bearing temperature', 'degC'],
  motor_current_a: ['Motor current', 'A'], displacement_mm: ['Shaft displacement', 'mm'],
  acoustic_db: ['Acoustic level', 'dB'], health_state: ['Simulator ground truth', 'class']
};

function message(text, error = false) {
  const node = $('#message'); node.textContent = text; node.className = error ? 'error' : '';
}
function showDatabase(database) {
  $('#database').innerHTML = Object.entries(database).filter(([key]) => key !== 'password')
    .map(([key, value]) => `<dt>${key}</dt><dd>${value}</dd>`).join('');
}
function setTableOptions(tables, selected) {
  const select = $('#database-table');
  select.replaceChildren();
  if (!tables.length) {
    const option = new Option(selected || 'No compatible tables found', selected || '');
    option.disabled = true; option.selected = true; select.add(option); return;
  }
  tables.forEach(table => select.add(new Option(table, table, false, table === selected)));
  if (!select.value && selected) select.add(new Option(selected, selected, true, true));
}
async function loadDatabaseTables() {
  const refreshButton = $('#refresh-tables'); refreshButton.disabled = true;
  try {
    const response = await fetch('/api/database-tables');
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not load database tables');
    setTableOptions(payload.tables, config.database.table);
  } catch (error) {
    setTableOptions([config.database.table], config.database.table);
    message(`${error.message}. Keeping the configured table.`, true);
  } finally { refreshButton.disabled = false; }
}
function refreshJson() { $('#json-editor').value = JSON.stringify(config, null, 2); }
function renderMlConfig() {
  const summary = mlConfig.summarization || {};
  const source = mlConfig.database_source || {};
  const llm = mlConfig.llm || {};
  $('#summary-enabled').checked = summary.enabled !== false;
  $('#summary-source-table').value = source.table || '';
  $('#summary-output-table').value = summary.output_table || 'public.ai-summarize';
  $('#summary-interval').value = summary.interval_seconds ?? 60;
  $('#summary-range').value = summary.range_seconds ?? 300;
  $('#summary-timezone').value = summary.timezone || 'Asia/Bangkok';
  $('#llm-model').value = llm.model || '';
  $('#llm-api-url').value = llm.api_url || '';
  $('#llm-api-key-env').value = llm.api_key_env || 'OPENAI_API_KEY';
}
function readMlForm() {
  mlConfig.database_source = mlConfig.database_source || {};
  mlConfig.summarization = mlConfig.summarization || {};
  mlConfig.llm = mlConfig.llm || {};
  mlConfig.database_source.table = $('#summary-source-table').value.trim();
  mlConfig.summarization.enabled = $('#summary-enabled').checked;
  mlConfig.summarization.output_table = $('#summary-output-table').value.trim();
  mlConfig.summarization.interval_seconds = Number($('#summary-interval').value);
  mlConfig.summarization.range_seconds = Number($('#summary-range').value);
  mlConfig.summarization.timezone = $('#summary-timezone').value.trim();
  mlConfig.llm.model = $('#llm-model').value.trim();
  mlConfig.llm.api_url = $('#llm-api-url').value.trim();
  mlConfig.llm.api_key_env = $('#llm-api-key-env').value.trim();
  return mlConfig;
}
function updateChannelFields(card) {
  const type = $('.channel-type', card).value;
  card.querySelectorAll('.digital-field').forEach(node => node.hidden = type !== 'digital');
  $('.equation-field', card).hidden = type !== 'equation';
  $('.machine-field', card).hidden = type !== 'machine';
}
function addChannel(channel = {channel: 0, type: 'digital', stages: [0, 1], stage_period_seconds: 2}) {
  const card = $('#channel-template').content.firstElementChild.cloneNode(true);
  $('.channel-number', card).value = channel.channel;
  $('.channel-type', card).value = channel.type;
  $('.digital-stages', card).value = (channel.stages || [channel.value ?? 0, 1]).join(', ');
  $('.stage-period', card).value = channel.stage_period_seconds ?? channel.toggle_period_seconds ?? 0;
  $('.equation', card).value = channel.equation || '';
  $('.machine-signal', card).value = channel.signal || 'vibration_mm_s';
  $('.dependencies', card).value = (channel.depends_on || []).map(dependency => {
    if (typeof dependency === 'number') return dependency;
    return `${dependency.multiplier ?? 1} * channel ${dependency.channel}`;
  }).join(', ');
  $('.channel-label', card).textContent = `SIGNAL ${channel.channel}`;
  $('.channel-number', card).addEventListener('input', event => $('.channel-label', card).textContent = `SIGNAL ${event.target.value || '?'}`);
  $('.channel-type', card).addEventListener('change', () => {
    if ($('.channel-type', card).value === 'equation' && !$('.equation', card).value.trim()) $('.equation', card).value = '0';
    updateChannelFields(card);
  });
  $('.remove', card).addEventListener('click', () => card.remove());
  updateChannelFields(card); $('#channels').append(card);
}
function readForm() {
  config.enabled = $('#enabled').checked;
  config.period_seconds = Number($('#period').value);
  config.config_reload_seconds = Number($('#reload').value);
  config.database.table = $('#database-table').value;
  config.channels = [...document.querySelectorAll('.channel-card')].map(card => {
    const type = $('.channel-type', card).value;
    const channel = {channel: Number($('.channel-number', card).value), type};
    if (type === 'digital') {
      const stages = $('.digital-stages', card).value.split(',').map(value => Number(value.trim()));
      if (!stages.length || stages.some(value => ![0, 1].includes(value))) throw new Error('Digital stages must be comma-separated 0 or 1 values.');
      channel.stages = stages;
      channel.stage_period_seconds = Number($('.stage-period', card).value);
    }
    else if (type === 'equation') channel.equation = $('.equation', card).value;
    else {
      channel.signal = $('.machine-signal', card).value;
      [channel.name, channel.unit] = machineSignals[channel.signal];
      if (channel.signal === 'health_state') channel.training_label = true;
    }
    const dependencyText = $('.dependencies', card).value.trim();
    const dependencies = dependencyText ? dependencyText.split(',').map(part => {
      const match = part.trim().match(/^(?:(-?\d+(?:\.\d+)?)\s*\*\s*)?(?:channel\s*)?(\d+)$/i);
      if (!match) throw new Error('Add channels must use values such as "2" or "10 * channel 1".');
      const multiplier = Number(match[1] ?? 1);
      const channelNumber = Number(match[2]);
      return multiplier === 1 ? channelNumber : {channel: channelNumber, multiplier};
    }) : [];
    channel.depends_on = dependencies;
    return channel;
  });
  return config;
}
function render() {
  $('#enabled').checked = config.enabled;
  $('#period').value = config.period_seconds;
  $('#reload').value = config.config_reload_seconds;
  $('#channels').replaceChildren(); config.channels.forEach(addChannel); showDatabase(config.database);
  // Keep the current table usable immediately. Database discovery is optional
  // and must never block the table selector while a connection is slow.
  setTableOptions([config.database.table], config.database.table);
  refreshJson();
}
async function load() {
  const response = await fetch('/api/config'); if (!response.ok) throw new Error(`Could not load configuration (${response.status})`);
  config = await response.json(); render(); loadDatabaseTables();
  const mlResponse = await fetch('/api/ml-config'); if (!mlResponse.ok) throw new Error(`Could not load ML configuration (${mlResponse.status})`);
  mlConfig = await mlResponse.json(); renderMlConfig(); $('#status-dot').classList.add('live'); $('#status-text').textContent = 'Configuration service online';
}
async function save() {
  try { const response = await fetch('/api/config', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(readForm())}); if (!response.ok) throw new Error((await response.json()).error || 'Save failed'); config = await response.json(); refreshJson(); message('Changes saved. The simulator will apply them within the reload interval.'); }
  catch (error) { message(error.message, true); }
}
async function saveMlConfig() {
  try {
    const response = await fetch('/api/ml-config', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(readMlForm())});
    if (!response.ok) throw new Error((await response.json()).error || 'Save failed');
    mlConfig = await response.json(); renderMlConfig(); message('ML summary configuration saved. Restart the summary worker to apply connection settings.');
  } catch (error) { message(error.message, true); }
}
$('#save').addEventListener('click', save); $('#add-channel').addEventListener('click', () => addChannel());
$('#save-ml-config').addEventListener('click', saveMlConfig);
$('#refresh-tables').addEventListener('click', loadDatabaseTables);
$('#apply-json').addEventListener('click', () => { try { config = JSON.parse($('#json-editor').value); render(); loadDatabaseTables(); message('JSON applied to the form. Save changes to write it.'); } catch (error) { message(`Invalid JSON: ${error.message}`, true); } });
load().catch(error => { $('#status-text').textContent = 'Configuration unavailable'; message(error.message, true); });
