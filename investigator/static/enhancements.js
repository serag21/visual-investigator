'use strict';
const originalRender=render;
render=function(){originalRender();renderEnhancements();};
let installPrompt=null;
const requirementLabel=element('label'),requirementCheck=element('input');
requirementCheck.type='checkbox';requirementCheck.id='spec-current-requirement';
requirementLabel.append(requirementCheck,element('span'," This is the device's required minimum current, checked on its own label/manual, not the old adapter's maximum."));
requirementLabel.hidden=true;$('spec-form').insertBefore(requirementLabel,$('spec-form').querySelector('button'));
function showRequirement(){requirementLabel.hidden=$('spec-subject').value!=='original'||$('spec-name').value!=='current';requirementCheck.checked=false;}
function downloadObject(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const link=element('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function renderEnhancements(){
  const latest=state.turns.at(-1);
  $('feedback-record').hidden=!latest;$('spec-record').hidden=!ledgerEnabled||(!latest&&!selected);
  $('logout').hidden=!privateBeta;
  $('owner-feedback').hidden=memberInfo?.role!=='owner';$('owner-review').hidden=memberInfo?.role!=='owner';
  $('reported-specs').replaceChildren();
  for(const report of state.reports||[]){
    $('reported-specs').append(element('p',`${report.id} · ${report.subject} · ${report.name.replaceAll('_',' ')}: ${report.value} ${report.unit==='text'?'':report.unit} · ${report.basis}${report.current_is_requirement?' · device required minimum':''}${report.superseded_by?' · corrected by '+report.superseded_by:''}`,'small'));
  }
  const record=state.reported_decision;
  if(record){$('reported-specs').prepend(element('p',`${record.decision.replaceAll('_',' ')} · ${record.verification}`,'unknowns'));
    if(record.source){const link=element('a','Rule reference — not verification of this object');link.href=record.source;link.target='_blank';link.rel='noopener noreferrer';$('reported-specs').append(link);}}
  if(latest?.capture_action?.kind==='photo'){
    const card=$('conversation').lastElementChild,button=element('button','Take the requested evidence photo','button secondary');
    button.type='button';button.addEventListener('click',()=>{notify(latest.capture_action.instruction);$('camera').click();});card.append(button);
  }
  // Readback is explicit: never silently promote model OCR to a checked specification.
  for(const fact of ledgerEnabled?(latest?.finding?.facts||[]):[]){
    const match=/^\s*(\d+(?:\.\d+)?)\s*(V(?:\s*DC)?|A)\s*$/i.exec(fact.value);
    if(fact.kind!=='image_reading'||!match)continue;
    const button=element('button',`Check label reading: ${fact.value}`,'text-button');button.type='button';
    button.addEventListener('click',()=>{$('spec-record').querySelector('details').open=true;$('spec-goal').value='dc_adapter';$('spec-name').value=/a/i.test(match[2])?'current':'voltage';$('spec-value').value=match[1];$('spec-unit').value=/a/i.test(match[2])?'A':'V';$('spec-basis').value='label';showRequirement();notify('This number came from AI. Check the original photo and correct it before recording.');$('spec-value').focus();});
    $('conversation').lastElementChild.append(button);
  }
}
function unitForName(){const name=$('spec-name').value;$('spec-unit').value=name==='voltage'?'V':name==='current'?'A':['polarity','regulated_dc','thread_standard'].includes(name)?'text':'mm';}
$('spec-name').addEventListener('change',()=>{unitForName();showRequirement();});
$('spec-subject').addEventListener('change',showRequirement);
$('spec-form').addEventListener('submit',async event=>{
  event.preventDefault();if(busy)return;busy=true;updateButton();
  try{const report={subject:$('spec-subject').value,name:$('spec-name').value,value:$('spec-value').value,unit:$('spec-unit').value,basis:$('spec-basis').value};
    if(!requirementLabel.hidden&&requirementCheck.checked)report.current_is_requirement=true;
    if($('spec-replaces').value.trim())report.replaces_id=$('spec-replaces').value.trim();
    state=await api('/api/specifications',{method:'POST',body:JSON.stringify({goal:$('spec-goal').value,reports:[report]})});
    $('spec-value').value='';$('spec-replaces').value='';render();notify('Checked user report recorded. No model request was made.');
  }catch(error){notify(error.message);}finally{busy=false;updateButton();}
});
async function refreshDrafts(){
  if(!memberInfo)return;
  try{const rows=(await DeviceStore.list(memberInfo.id)).filter(row=>row.kind==='draft');$('device-drafts').replaceChildren();
    for(const row of rows){const container=element('div',undefined,'draft-row'),resume=element('button',`Resume: ${row.title}`,'text-button'),forget=element('button','Delete device save','text-button');
      resume.type=forget.type='button';resume.addEventListener('click',async()=>{if(busy)return;busy=true;updateButton();try{state=await api('/api/restore',{method:'POST',body:JSON.stringify({token:row.token,decision_goal:row.decision_goal})});clearSelected();$('consent').checked=false;render();notify('Device save restored. Nothing was sent to Gemini. Review the old evidence before continuing.');}catch(error){notify(error.message);}finally{busy=false;updateButton();}});
      forget.addEventListener('click',async()=>{await DeviceStore.remove(row.id);await refreshDrafts();});container.append(resume,forget);$('device-drafts').append(container);}
  }catch(error){notify(error.message);}
}
$('save-device').addEventListener('click',async()=>{
  if(busy||!state.turns.length){notify('Complete an investigation turn before saving.');return;}busy=true;updateButton();
  try{const saved=await api('/api/checkpoint',{method:'POST',body:'{}'});let rows=(await DeviceStore.list(memberInfo.id)).filter(r=>r.kind==='draft');
    if(rows.length>=5){notify('Five investigations are saved. Delete a device save before adding another.');return;}
    await DeviceStore.put({...saved,id:crypto.randomUUID(),member:memberInfo.id,kind:'draft',expires:saved.expires*1000});await refreshDrafts();notify('Saved on this device for seven days, including photos. Not uploaded to an analytics service.');
  }catch(error){notify(error.message);}finally{busy=false;updateButton();}
});
$('feedback-form').addEventListener('submit',async event=>{
  event.preventDefault();if(busy)return;busy=true;updateButton();
  const entry={id:crypto.randomUUID(),kind:'feedback',member:memberInfo.id,created:new Date().toISOString(),expires:Date.now()+14*86400000,outcome:$('feedback-outcome').value,note:$('feedback-note').value};
  if($('feedback-detail-consent').checked)entry.detail={completion:$('feedback-completion').value,source_usefulness:$('feedback-sources').value,unsupported_advice:$('feedback-unsupported').value,infrastructure_problem:$('feedback-infrastructure').value};
  try{await DeviceStore.put(entry);const result=await api('/api/feedback',{method:'POST',body:JSON.stringify({outcome:entry.outcome,note:entry.note,...(entry.detail?{detail:entry.detail}:{})})});entry.receipt=result.id;await DeviceStore.put(entry);notify(result.notice);}
  catch(error){notify(`${error.message} Your device feedback copy is retained when storage is available.`);}finally{busy=false;updateButton();}
});
$('download-feedback').addEventListener('click',async()=>{try{downloadObject({feedback:(await DeviceStore.list(memberInfo.id)).filter(row=>row.kind==='feedback'),verification:'Tester-reported outcomes, not independent task verification.'},'my-investigator-feedback.json');}catch(error){notify(error.message);}});
$('share-case').addEventListener('click',async()=>{if(!$('share-consent').checked){notify('Choose explicitly whether to include the photos and conversation.');return;}try{const record=await api('/api/share-case',{method:'POST',body:'{"consent":true}'});downloadObject(record,'private-case-evidence.json');notify('Case file downloaded locally. Review it before voluntarily sharing it.');}catch(error){notify(error.message);}});
$('owner-feedback').addEventListener('click',async()=>{try{downloadObject(await api('/api/feedback/export'),'submitted-beta-feedback.json');}catch(error){notify(error.message);}});
$('logout').addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST',body:'{}'});location.replace('/');}catch(error){notify(error.message);}});
window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt=event;$('install').hidden=false;});
$('install').addEventListener('click',async()=>{if(installPrompt){await installPrompt.prompt();installPrompt=null;$('install').hidden=true;}});
window.addEventListener('vi-ready',()=>{renderEnhancements();refreshDrafts();});
if('serviceWorker' in navigator&&(location.protocol==='https:'||location.hostname==='127.0.0.1'||location.hostname==='localhost'))navigator.serviceWorker.register('/sw.js').catch(()=>{});
if(memberInfo){renderEnhancements();refreshDrafts();}

$('owner-review').addEventListener('click',async()=>{
 try{const report=await api('/api/owner/report');$('owner-panel').hidden=false;const panel=$('owner-report');panel.replaceChildren();
 panel.append(element('p',Object.entries(report.reported_outcomes).map(([k,v])=>`${k.replaceAll('_',' ')}: ${v}`).join(' · ')));
 panel.append(element('p',`${report.responding_members} responding members · ${report.members_with_multiple_submissions} with multiple submissions (not verified repeat usage)`,'small'));
 for(const limitation of report.limitations)panel.append(element('p',limitation,'small muted'));
 for(const row of report.feedback){const card=element('div',undefined,'owner-feedback-entry');card.append(element('strong',`${row.member} · ${row.outcome.replaceAll('_',' ')}`),element('p',row.note||'No optional note'));if(row.optional_detail){const d=row.optional_detail;card.append(element('p',`Task completion: ${d.completion||'not reported'} · Sources: ${d.source_usefulness||'not reported'} · Unsupported advice: ${d.unsupported_advice||'not reported'} · Service problem: ${d.infrastructure_problem||'not reported'}`,'small'),element('p',`${d.successful_turns} recorded turns · ${d.photos} photos (including restored history). ${d.session_seconds}s since this session began or was restored; includes idle time.`,'small muted'));}panel.append(card);}
 for(const member of report.members){if(member.id===memberInfo.id)continue;const button=element('button',`${member.revoked?'Revoked':'Revoke invite'}: ${member.id}`,'text-button');button.disabled=member.revoked;button.addEventListener('click',async()=>{if(!confirm(`Revoke ${member.id}? Previously saved device copies cannot be remotely erased.`))return;try{await api('/api/owner/access',{method:'POST',body:JSON.stringify({revoke:member.id})});button.disabled=true;button.textContent=`Revoked: ${member.id}`;}catch(error){notify(error.message);}});panel.append(button);}
 if(privateBeta){const disable=element('button','Disable all beta access','text-button');disable.addEventListener('click',async()=>{if(!confirm('Disable access for everyone, including you? Re-enabling requires the private host operator command.'))return;try{await api('/api/owner/access',{method:'POST',body:'{"disable":true}'});location.replace('/');}catch(error){notify(error.message);}});panel.append(disable);}
 const download=element('button','Download this owner report','text-button');download.addEventListener('click',()=>downloadObject(report,'private-beta-owner-report.json'));panel.append(download);$('owner-panel').scrollIntoView({behavior:'smooth',block:'start'});
 }catch(error){notify(error.message);}
});
