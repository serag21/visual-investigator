'use strict';
const $ = (id) => document.getElementById(id);
let csrf = '', state = {turns: [], pictures: []}, selected = null, busy = false, ready = false;
let selectionMode = false, anchor = null;
let memberInfo=null, privateBeta=false, ledgerEnabled=false;
const statusLabels = {answered: 'Answer supported so far', needs_evidence: 'More evidence needed', concluded: 'Useful conclusion', safety_stop: 'Pause · safety concern'};
const decisions = {unverified: 'Unverified', mismatch: 'Conflict found', requirements_identified: 'Requirements identified'};
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function notify(text) { $('notice').textContent = text; $('notice').hidden = !text; }
function updateButton() {
  $('send').disabled = busy || !ready || !$('consent').checked || (!selected && (!$('question').value.trim() || !state.pictures.length));
  $('send-label').textContent = busy ? 'Investigating…' : state.turns.length ? 'Add evidence & continue' : 'Investigate photo';
  for (const id of ['upload-button', 'camera-button', 'new-case', 'remove-photo']) $(id).disabled = busy;
  $('question').disabled = busy; $('consent').disabled = busy;
  document.querySelectorAll('[data-question]').forEach(button => { button.disabled = busy; });
  $('select-area').disabled = busy; $('clear-area').disabled = busy;
  $('research').disabled = busy;
  for(const id of ['save-device','share-case'])$(id).disabled=busy;
}
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf, ...options.headers}});
  let data;
  try { data = await response.json(); } catch { throw new Error('The service did not return a readable answer. It may be waking up; your evidence is still here.'); }
  if (!response.ok) throw new Error((data.category==='infrastructure'?'Service problem: ':data.category==='answer_format'?'Answer format problem: ':'')+(data.error || 'That request could not be completed. Your evidence is still here.'));
  return data;
}
function clearSelected() {
  selectionMode = false; anchor = null; $('target-actions').hidden = true; $('selector').classList.remove('selecting'); $('target-box').setAttribute('width','0');
  selected = null; $('preview').removeAttribute('src');
  $('pending-photo').hidden = true; $('upload-empty').hidden = false;
  $('upload').value = ''; $('camera').value = ''; updateButton();
}
async function choosePhoto(file) {
  if (!file || busy) return;
  notify('');
  if (file.size > 6_000_000) { notify('Choose a photo smaller than 6 MB.'); return; }
  let mime=file.type;
  if(!mime||mime==='application/octet-stream'){if(/\.heic$/i.test(file.name))mime='image/heic';else if(/\.heif$/i.test(file.name))mime='image/heif';}
  if (!['image/jpeg','image/png','image/webp','image/heic','image/heif'].includes(mime)) { notify('Choose a still JPEG, PNG, WebP, HEIC or HEIF photo.'); return; }
  try {
    busy=true;updateButton();
    // Ordinary formats preview locally; HEIC conversion is disclosed before upload.
    const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file); });
    selected = {data: data.split(',')[1], mime_type: mime};
    if(mime==='image/heic'||mime==='image/heif'){
      busy=true;updateButton();notify('Converting HEIC on the private server. No model request is made.');
      const converted=await api('/api/prepare-image',{method:'POST',body:JSON.stringify(selected)});
      selected={data:converted.data,mime_type:'image/jpeg',conversion_receipt:converted.conversion_receipt};
      notify(converted.capture_warning||'HEIC converted. Review the photo before sending to Gemini.');
    }
    $('preview').src = `data:${selected.mime_type};base64,${selected.data}`; $('pending-photo').hidden = false; $('upload-empty').hidden = true;
    $('spec-record').hidden=!ledgerEnabled;
    $('target-actions').hidden = false; selectionMode = false; $('selector').classList.remove('selecting'); $('target-box').setAttribute('width','0'); $('clear-area').hidden=true; $('target-hint').textContent=''; $('select-area').setAttribute('aria-pressed','false');
  } catch(error) { selected=null;notify(error.message||'That photo could not be opened. Try another file.'); }
  finally{busy=false;}
  updateButton();
}
function render() {
  document.body.classList.toggle('has-turns', state.turns.length > 0);
  $('welcome').hidden = state.turns.length > 0;
  $('examples').hidden = state.turns.length > 0;
  $('photo-count').textContent = state.pictures.length ? `${state.pictures.length} of 4 photos` : 'Start with one photo';
  $('photo-strip').replaceChildren();
  for (const picture of state.pictures) {
    const link = element('a'); link.href = picture.url; link.target = '_blank'; link.rel = 'noopener';
    const img = element('img'); img.src = picture.url; img.alt = `Evidence photo ${picture.id}`;
    link.append(img, element('span', picture.id)); $('photo-strip').append(link);
  }
  $('conversation').replaceChildren();
  for (const turn of state.turns) {
    const f = turn.finding, card = element('article', undefined, 'card turn');
    card.append(element('p', turn.question.trim() ? `${turn.id} · You asked: ${turn.question}` : `${turn.id} · Photo-only investigation`, 'user-question'));
    const heading = element('div', undefined, 'answer-heading');
    heading.append(element('h2', f.title), element('span', statusLabels[f.status], `tag ${f.status === 'safety_stop' ? 'danger' : f.status === 'needs_evidence' ? 'amber' : ''}`));
    card.append(heading, element('p', f.answer, 'answer-text'));
    if (f.interpretations.length) {
      const details=element('details',undefined,'reasoning-details'); details.append(element('summary','Possible interpretations'),element('p',f.interpretations.join(' '),'interpretations')); card.append(details);
    }
    if (f.unknowns.length) {
      const unknowns = element('div', undefined, 'unknowns'); unknowns.append(element('strong', 'Still unverified'));
      const list = element('ul'); f.unknowns.forEach(t => list.append(element('li', t.replaceAll('_',' ')))); unknowns.append(list); card.append(unknowns);
    }
    if (f.next_question) {
      const next = element('div', undefined, 'next-step'); next.append(element('p', 'ONE USEFUL NEXT STEP', 'detail-label'), element('p', f.next_question));
      const reply = element('button', 'Add that evidence →', 'text-button'); reply.type = 'button'; reply.addEventListener('click', () => { $('question').focus(); $('question').scrollIntoView({behavior:'smooth',block:'center'}); });
      next.append(reply); card.append(next);
    }
    if (f.next_action) card.append(element('p', f.next_action, 'next-action'));
    card.append(element('p', turn.provider_called ? 'AI interpretation · source details may be misread' : turn.response_kind==='reported_evidence_rule'?'Reported evidence rule · no model request made':'Precautionary safety response · no model request made', 'turn-footnote'));
    $('conversation').append(card);
  }
  const latest = state.turns.at(-1)?.finding;
  $('research-record').hidden = !latest;
  renderReferences();
  $('evidence-record').hidden = !latest;
  $('decision-record').hidden = !latest || latest.compatibility.decision === 'not_applicable';
  if (!latest) return;
  if (latest.compatibility.decision !== 'not_applicable') {
    const c = latest.compatibility;
    $('decision-status').textContent = decisions[c.decision];
    $('decision-status').className = `tag ${c.decision === 'mismatch' || c.decision === 'unverified' ? 'amber' : ''}`;
    $('decision-summary').textContent = c.summary;
    $('constraints').replaceChildren();
    for (const constraint of c.constraints) {
      const row = element('div', undefined, 'constraint'), content = element('div');
      content.append(element('strong', constraint.name), element('p', `Original: ${constraint.original || 'Not established'}`), element('p', `Candidate: ${constraint.candidate || 'Not supplied'}`));
      if (constraint.source_ids.length) content.append(element('p', `Sources: ${constraint.source_ids.join(', ')}`));
      row.append(content, element('span', {missing:'Unverified', matches:'Reported match', conflicts:'Conflict'}[constraint.status], `tag ${constraint.status !== 'matches' ? 'amber' : ''}`));
      $('constraints').append(row);
    }
  }
  $('facts').replaceChildren();
  const evidenceHistory = new Map();
  for (const turn of state.turns) for (const fact of turn.finding.facts) {
    const key = `${fact.name.toLowerCase()}|${fact.value}|${fact.kind}`;
    const previous = evidenceHistory.get(key);
    evidenceHistory.set(key, {...fact, source_ids:[...new Set([...(previous?.source_ids || []), ...fact.source_ids])]});
  }
  if (!evidenceHistory.size) $('facts').append(element('p', state.reports?.length?'Your reported specifications are recorded above. They are not independently verified.':'No specifications have been established yet.', 'muted'));
  for (const fact of evidenceHistory.values()) {
    const row = element('div', undefined, 'fact'), content = element('div');
    content.append(element('strong', fact.name), element('p', fact.value));
    const corrected=(state.reports||[]).filter(r=>r.superseded_by&&fact.source_ids.includes(r.id));
    row.append(content, element('span', `${{image_reading:'AI image reading',user_report:'You reported',inference:'Interpretation'}[fact.kind]} · ${fact.source_ids.join(', ')}${corrected.length?' · historical, corrected by '+corrected.map(r=>r.superseded_by).join(', '):''}`, 'fact-source'));
    $('facts').append(row);
  }
}
function renderReferences() {
  const holder=$('references'); holder.replaceChildren();
  if (!state.references) return;
  holder.append(element('p',`References consulted for ${state.references.context_turn}. Recheck relevance after adding evidence.`,'small muted'));
  holder.append(element('p',state.references.verification,'record-footnote'));
  if (!state.references.sources.length) holder.append(element('p','This source library has no relevant entry yet. No search or product match was established.'));
  for (const source of state.references.sources) {
    const card=element('div',undefined,'reference-source'), link=element('a',`${source.publisher} · ${source.title}`);
    link.href=source.url; link.target='_blank'; link.rel='noopener noreferrer';
    card.append(link,element('p',`${source.kind} · ${source.status==='retrieved'?'Fetched document excerpt':'Document not retrieved'}`,'small muted'));
    if(source.excerpt){const details=element('details');details.append(element('summary','Read source excerpt'),element('p',source.excerpt));card.append(details);}
    card.append(element('p',`Retrieval: ${source.retrieved_at}${source.document_sha256?' · SHA-256 '+source.document_sha256:''}`,'source-receipt'));
    holder.append(card);
  }
}
$('research').addEventListener('click',async()=>{
  if(busy)return; busy=true;updateButton();$('research').textContent='Fetching references…';
  try{state.references=await api('/api/research',{method:'POST',body:'{}'});renderReferences();}
  catch(error){notify(error.message);}
  finally{busy=false;$('research').textContent='Refresh references ↗';updateButton();}
});
$('upload-button').addEventListener('click', () => $('upload').click());
$('camera-button').addEventListener('click', () => $('camera').click());
for (const id of ['upload','camera']) $(id).addEventListener('change', e => {const file=e.target.files[0];e.target.value='';choosePhoto(file);});
$('remove-photo').addEventListener('click', clearSelected);
function photoRect() {
  const image=$('preview'), rect=image.getBoundingClientRect();
  const scale=Math.min(rect.width/image.naturalWidth,rect.height/image.naturalHeight);
  const width=image.naturalWidth*scale, height=image.naturalHeight*scale;
  return {left:(rect.width-width)/2,top:(rect.height-height)/2,width,height,rect};
}
function drawTarget() {
  if (!selected?.region) return;
  const r=selected.region, p=photoRect(), box=$('target-box');
  box.setAttribute('x',String(p.left+r.x*p.width)); box.setAttribute('y',String(p.top+r.y*p.height));
  box.setAttribute('width',String(r.width*p.width)); box.setAttribute('height',String(r.height*p.height));
}
function targetPoint(event) {
  const p=photoRect();
  return {x:Math.min(1,Math.max(0,(event.clientX-p.rect.left-p.left)/p.width)),y:Math.min(1,Math.max(0,(event.clientY-p.rect.top-p.top)/p.height))};
}
$('select-area').addEventListener('click',()=>{
  if (!selected) return;
  selectionMode=true; selected.region ||= {x:.25,y:.25,width:.5,height:.5};
  $('selector').classList.add('selecting'); $('select-area').setAttribute('aria-pressed','true');
  $('clear-area').hidden=false; $('target-hint').textContent='Drag a box. The selected crop is sent with the full photo.'; drawTarget(); $('selector').focus();
});
$('clear-area').addEventListener('click',()=>{delete selected.region;selectionMode=false;$('selector').classList.remove('selecting');$('target-box').setAttribute('width','0');$('select-area').setAttribute('aria-pressed','false');$('clear-area').hidden=true;$('target-hint').textContent='';});
$('selector').addEventListener('pointerdown',e=>{if(!selectionMode||busy)return;anchor=targetPoint(e);$('selector').setPointerCapture(e.pointerId);});
$('selector').addEventListener('pointermove',e=>{
  if(!anchor||!selected)return;
  const p=targetPoint(e),x=Math.min(p.x,anchor.x),y=Math.min(p.y,anchor.y);
  if(Math.abs(p.x-anchor.x)>=.03&&Math.abs(p.y-anchor.y)>=.03){selected.region={x,y,width:Math.abs(p.x-anchor.x),height:Math.abs(p.y-anchor.y)};drawTarget();}
});
$('selector').addEventListener('pointerup',()=>{anchor=null;});
$('selector').addEventListener('pointercancel',()=>{anchor=null;});
$('selector').addEventListener('keydown',e=>{
  if(!selected?.region||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;
  e.preventDefault();const r=selected.region;const dx=e.key==='ArrowLeft'?-.025:e.key==='ArrowRight'?.025:0;const dy=e.key==='ArrowUp'?-.025:e.key==='ArrowDown'?.025:0;
  r.x=Math.max(0,Math.min(1-r.width,r.x+dx));r.y=Math.max(0,Math.min(1-r.height,r.y+dy));drawTarget();
});
window.addEventListener('resize',drawTarget);
$('preview').addEventListener('load',drawTarget);
$('question').addEventListener('input', updateButton); $('consent').addEventListener('change', updateButton);
document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => { $('question').value = button.dataset.question; updateButton(); $('question').focus(); }));
for (const event of ['dragenter','dragover']) $('drop-zone').addEventListener(event, e => {e.preventDefault(); $('drop-zone').classList.add('drag');});
for (const event of ['dragleave','drop']) $('drop-zone').addEventListener(event, e => {e.preventDefault(); $('drop-zone').classList.remove('drag');});
$('drop-zone').addEventListener('drop', e => {if (!busy) choosePhoto(e.dataTransfer.files[0]);});
$('question-form').addEventListener('submit', async event => {
  event.preventDefault(); if ($('send').disabled) return;
  busy = true; updateButton(); notify(''); $('loading').hidden = false;
  try {
    state = await api('/api/turn', {method:'POST', body: JSON.stringify({question:$('question').value, image:selected, consent:$('consent').checked})});
    $('question').value = ''; clearSelected(); render();
    $('conversation').lastElementChild?.scrollIntoView({behavior:'smooth',block:'start'});
  } catch (error) { notify(error.message); $('notice').scrollIntoView({behavior:'smooth',block:'center'}); }
  finally { busy = false; $('loading').hidden = true; updateButton(); }
});
$('new-case').addEventListener('click', async () => {
  try {
    await api('/api/reset', {method:'POST', body:'{}'}); state = {turns:[],pictures:[]};
    $('question').value = ''; $('consent').checked = false; clearSelected(); notify(''); render(); window.scrollTo({top:0,behavior:'smooth'});
  } catch (error) { notify(error.message); }
});
$('export').addEventListener('click', async () => {
  try {
    const record = await api('/api/export');
    const url = URL.createObjectURL(new Blob([JSON.stringify(record,null,2)], {type:'application/json'}));
    const link = element('a'); link.href = url; link.download = 'visual-investigation.json'; link.click(); URL.revokeObjectURL(url);
  } catch (error) { notify(error.message); }
});
api('/api/session').then(data => {
  memberInfo=data.member;
  privateBeta=data.private_beta;
  ledgerEnabled=data.ledger_enabled;
  csrf = data.csrf; state = data; ready = data.model_ready;
  if (data.mode === 'test') notify('Test provider · responses are fixtures, not live image analysis.');
  else if (!ready) notify('The server needs its existing Gemini configuration before it can investigate photos.');
  render(); updateButton(); window.dispatchEvent(new Event('vi-ready'));
}).catch(error => notify(error.message));
