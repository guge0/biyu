const $ = id => document.getElementById(id);
const STAGES = ['细纲', '写作方案', '生成正文', '读稿定夺', '评章摘句'];
const LABELS = Object.freeze({pending:'待定夺', official:'正式正文'});
const RUN_LABELS = Object.freeze({write:'正文已生成',rewrite:'候选稿已修订',diagnose:'返工根因已诊断',adopt:'已采用为正式正文',refresh_memory:'本章记忆已重算',regenerate:'候选稿已重新生成',excerpt:'摘句已记录',archive_excerpt:'摘句已移除',retag_excerpt:'摘句分类已更新',chapter_review:'章评已保存',revoke_planning:'方案已退回'});
const QUOTE_NORMALIZE_RE = /[\s\u3000,，。.!！?？;；:：·、"“”‘’()（）\[\]【】\-—…]+/g;
function normalizeQuotedText(text) { return String(text || '').replace(QUOTE_NORMALIZE_RE, ''); }
function quoteStillExists(quote,text) { const needle=normalizeQuotedText(quote);return Boolean(needle)&&normalizeQuotedText(text).includes(needle); }
function shouldShowOfficialMode(snapshot){return snapshot?.manuscript_state==='candidate'&&Boolean(String(snapshot?.official_text||'').trim());}
let current = {}, shownStage = 0, selectedText = '', selectedAnchor = 0, selectedSnapshot = null, dirty = new Set(), busy = false, revisionLines = [], sessionNotes = [], sessionNotesContext = '', diagnosisClosedForSha = '', failureDismissedFor = '', runStartedAt = 0, runTimer = 0, pendingImport = null, importedOfficialChapters = [], remainingMemoryChapters = [], readingView = 'read';
let readingAsideOpen=false;
let activeIssueId='';
let readingMoreOpen=false;
let readingOfficialRestore=null;
let readingChromeTimer=0;
let readingChromeLastTop=0;
let bookRoots=new Map();
let generationVoiceprintWorkspace = null, generationVoiceprintBook = '', generationVoiceprintDirty = false, generationVoiceprintLoading = false, generationVoiceprintError = false;
const workbenchSelfLink = $('workbench-self-link');
const memoryLink = $('memory-link');
const voiceprintLink = $('voiceprint-link');
const selectedBook = new URLSearchParams(location.search).get('book');
if (selectedBook) {
  workbenchSelfLink.href = `/workbench.html?book=${encodeURIComponent(selectedBook)}`;
  memoryLink.href = `/memory.html?book=${encodeURIComponent(selectedBook)}`;
  voiceprintLink.href = `/voiceprint.html?book=${encodeURIComponent(selectedBook)}`;
}
function locationDraftKey(book){return `biyu:workbench:location:${book}`;}
function syncWorkbenchLocation(){
  const params=new URLSearchParams();
  params.set('book',$('book').value);
  params.set('chapter',String(current.chapter));
  history.replaceState(null,'',`/workbench.html?${params}`);
  const book=$('book').value;
  localStorage.setItem(locationDraftKey(book),String(current.chapter));
  const encodedBook=encodeURIComponent(book),chapter=encodeURIComponent(current.chapter);
  workbenchSelfLink.href=`/workbench.html?book=${encodedBook}&chapter=${chapter}`;
  memoryLink.href=`/memory.html?book=${encodedBook}&chapter=${chapter}`;
  voiceprintLink.href=`/voiceprint.html?book=${encodedBook}&chapter=${chapter}`;
}

function showError(message) {
  const banner = $('error-banner'); banner.replaceChildren(); banner.classList.remove('notice-banner'); banner.setAttribute('role','alert');
  const row = document.createElement('div'); row.className = 'error-banner-row';
  const icon = document.createElement('span'); icon.className = 'error-banner-icon'; icon.textContent = '✗';
  const text = document.createElement('span'); text.className = 'error-banner-msg'; text.textContent = message;
  const close = document.createElement('button'); close.type='button'; close.className = 'error-banner-close'; close.textContent = '×'; close.onclick = () => { banner.hidden = true; syncTopNoticePriority(); };
  row.append(icon, text, close); banner.append(row); banner.hidden = false; syncTopNoticePriority();
}
function showNotice(message) {
  const banner=$('error-banner');banner.replaceChildren();banner.classList.add('notice-banner');banner.setAttribute('role','status');
  const row=document.createElement('div');row.className='error-banner-row';
  const icon=document.createElement('span');icon.className='error-banner-icon';icon.textContent='i';
  const text=document.createElement('span');text.className='error-banner-msg';text.textContent=message;
  const close=document.createElement('button');close.type='button';close.className='error-banner-close';close.textContent='×';close.onclick=()=>{banner.hidden=true;syncTopNoticePriority();};
  row.append(icon,text,close);banner.append(row);banner.hidden=false;syncTopNoticePriority();
}
function syncTopNoticePriority(){
  const ordered=['error-banner','failure-card','reading-failure-card','setup-restore-notice','replica-warning','memory-banner'];
  const wanted=ordered.map((id,index)=>{
    const element=$(id);
    return index===0?!element.hidden:element.dataset.noticeWanted==='true';
  });
  const visibleIndex=wanted.findIndex(Boolean);
  ordered.forEach((id,index)=>{$(id).hidden=index!==visibleIndex;});
  document.querySelector('.workbench')?.classList.toggle('reading-has-top-notice',visibleIndex>=0);
}
function setReadingMoreOpen(open){
  readingMoreOpen=Boolean(open);$('reading-more-menu').hidden=!readingMoreOpen;$('reading-more-toggle').setAttribute('aria-expanded',String(readingMoreOpen));
}
function clearTransientStatus() {
  if(runTimer){clearInterval(runTimer);runTimer=0;}
  runStartedAt=0;
  $('error-banner').hidden=true;
  $('run-surface').hidden=true;
  $('run-result').hidden=true;
  $('copy-chapter-status').textContent='';
  $('log-drawer').hidden=true;
  $('log-drawer').open=false;
  $('log').textContent='';
  syncTopNoticePriority();
}
function md(text) {
  if (!window.MiniMd || typeof window.MiniMd.render !== 'function') throw new Error('阅读排版没有加载成功，请重新打开工作台；当前内容不会被改写');
  return window.MiniMd.render(text || '暂无内容');
}
async function writeClipboard(text){
  if(navigator.clipboard&&typeof navigator.clipboard.writeText==='function'){
    await navigator.clipboard.writeText(text);
    return;
  }
  const fallback=document.createElement('textarea');
  fallback.value=text;
  fallback.setAttribute('readonly','');
  fallback.style.position='fixed';
  fallback.style.opacity='0';
  document.body.append(fallback);
  fallback.select();
  const copied=document.execCommand('copy');
  fallback.remove();
  if(!copied)throw new Error('浏览器没有允许复制，请手动选择正文复制。');
}
async function copyChapterText(){
  const button=$('copy-chapter'),status=$('copy-chapter-status');
  if(button.disabled)return;
  const text=readingView==='official'?(current.official_text||''):(dirty.has('chapter')?$('chapter-edit').value:(current.chapter_text||''));
  if(!text){status.textContent='当前没有可复制的正文。';return;}
  const original=button.textContent;
  button.disabled=true;
  button.textContent='正在复制…';
  status.textContent='正在复制…';
  try{await writeClipboard(text);status.textContent='全文已复制。';}
  catch(error){status.textContent='复制没有完成。';showError(error.message);}
  finally{button.disabled=false;button.textContent=original;}
}
async function refreshActiveVoiceprint(){
  const book=$('book').value,link=$('active-voiceprint');
  if(!book||!link)return;
  const encoded=encodeURIComponent(book);
  link.href=`/voiceprint.html?book=${encoded}`;
  try{
    const response=await fetch(`/api/voiceprint/books/${encoded}`);
    if(!response.ok)throw new Error();
    const workspace=await response.json();
    const active=(workspace.catalog||[]).find(item=>item.id===workspace.active);
    link.textContent=`声纹：${active?active.name:'未选择'}`;
  }catch{
    link.textContent='声纹：读取失败，点此查看';
  }
}
function generationVoiceprintUrl(){
  return `/api/voiceprint/books/${encodeURIComponent($('book').value)}`;
}
function renderGenerationVoiceprint(){
  const panel=$('generation-voiceprint');
  if(!panel)return;
  panel.hidden=!current.first_generation;
  if(!current.first_generation)return;
  const encoded=encodeURIComponent($('book').value);
  $('generation-voiceprint-link').href=`/voiceprint.html?book=${encoded}&chapter=${encodeURIComponent(current.chapter)}`;
  const root=$('generation-voiceprint-options');
  if(!generationVoiceprintWorkspace||generationVoiceprintBook!==$('book').value){
    root.textContent=generationVoiceprintLoading?'正在读取声纹…':'等待读取声纹…';
    $('generation-voiceprint-current').textContent='正在读取当前生效声纹…';
    $('save-generation-voiceprint').disabled=true;
    if(!generationVoiceprintLoading&&!generationVoiceprintError)loadGenerationVoiceprint();
    return;
  }
  const catalog=generationVoiceprintWorkspace.catalog||[];
  const active=generationVoiceprintWorkspace.active||null;
  const activeProfile=catalog.find(item=>item.id===active);
  $('generation-voiceprint-current').textContent=`当前生效：${activeProfile?activeProfile.name:'未选择'}`;
  root.replaceChildren();
  catalog.forEach(profile=>{
    const label=document.createElement('label');label.className='generation-voiceprint-option';
    const input=document.createElement('input');input.type='radio';input.name='generation-active-voiceprint';input.value=profile.id;input.checked=active===profile.id;
    input.onchange=()=>{generationVoiceprintDirty=true;$('generation-voiceprint-status').textContent='选择尚未保存；点“生成正文”时也会先保存。';};
    const text=document.createElement('span');text.textContent=`${profile.name}（${(profile.lines||[]).length} 条）`;
    label.append(input,text);root.append(label);
  });
  $('save-generation-voiceprint').disabled=false;
  if(!catalog.length)$('generation-voiceprint-status').textContent='目前没有可选声纹；仍可不带声纹生成正文。';
}
async function loadGenerationVoiceprint(){
  if(generationVoiceprintLoading||!current.first_generation)return false;
  generationVoiceprintLoading=true;generationVoiceprintError=false;
  try{
    const response=await fetch(generationVoiceprintUrl());
    if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail||`声纹读取失败（${response.status}）`);}
    generationVoiceprintWorkspace=await response.json();generationVoiceprintBook=$('book').value;generationVoiceprintDirty=false;
    $('generation-voiceprint-status').textContent='';
    return true;
  }catch(error){
    generationVoiceprintWorkspace=null;generationVoiceprintError=true;$('generation-voiceprint-status').textContent='声纹没有读取成功，正文尚未生成。';showError(error.message);return false;
  }finally{generationVoiceprintLoading=false;renderGenerationVoiceprint();}
}
async function saveGenerationVoiceprintSelection(){
  if(!generationVoiceprintWorkspace&&!(await loadGenerationVoiceprint()))return false;
  const button=$('save-generation-voiceprint'),original=button.textContent;
  button.disabled=true;button.textContent='正在保存…';
  try{
    const chosen=document.querySelector('#generation-voiceprint-options input:checked');
    const active=chosen?chosen.value:null;
    const response=await fetch(`${generationVoiceprintUrl()}/selection`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({active})});
    if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail||`声纹保存失败（${response.status}）`);}
    const merged=await response.json();
    generationVoiceprintWorkspace={...generationVoiceprintWorkspace,active:merged.active_profile_id,active_profile:merged.active_profile,merged};
    generationVoiceprintDirty=false;$('generation-voiceprint-status').textContent='声纹选择已保存。';
    await refreshActiveVoiceprint();renderGenerationVoiceprint();return true;
  }catch(error){$('generation-voiceprint-status').textContent='声纹没有保存，正文尚未生成。';showError(error.message);return false;}
  finally{button.textContent=original;button.disabled=false;}
}
async function prepareFirstGenerationVoiceprint(){
  if(!current.first_generation)return true;
  if((!generationVoiceprintWorkspace||generationVoiceprintBook!==$('book').value)&&!(await loadGenerationVoiceprint()))return false;
  if(generationVoiceprintDirty)return saveGenerationVoiceprintSelection();
  return true;
}
async function api(path, options) {
  const response = await fetch('/api/workbench' + path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({})), detail = body.detail;
    let message = `请求失败（${response.status}）`;
    if (typeof detail === 'string') message = detail;
    else if (Array.isArray(detail)) {
      const reasons = detail.map(item => item && item.msg).filter(Boolean);
      message = reasons.length ? `提交内容格式不正确：${reasons.join('；')}` : '提交内容格式不正确，请刷新后再试';
    } else if (detail && typeof detail === 'object') message = detail.message || '请求没有完成，请刷新后再试';
    throw new Error(message);
  }
  return response;
}
function setStage(stage) {
  shownStage = stage;
  document.querySelectorAll('[data-panel]').forEach(panel => { panel.hidden = Number(panel.dataset.panel) !== stage; });
  renderStageBar();
  renderFailureState();
}
async function requestStage(stage) {
  if (stage === shownStage || !await resolveDirty()) return;
  setStage(stage);
}
function syncDirtyUi() {
  $('global-dirty').hidden = dirty.size === 0;
  $('global-dirty-reading').hidden = dirty.size === 0;
  $('planning-dirty').hidden = !dirty.has('planning');
}
function markDirty(kind) { dirty.add(kind); syncDirtyUi(); }
function clearDirty(kind) { dirty.delete(kind); syncDirtyUi(); }
function revisionDraftKey(){return `biyu:revision:${$('book').value}:${current.chapter}:${current.chapter_sha}`;}
function persistRevisionDraft(){
  if(!current.chapter_sha)return;
  localStorage.setItem(revisionDraftKey(),JSON.stringify(revisionLines));
}
function restoreRevisionDraft(){
  revisionLines=[];
  if(!current.chapter_sha)return;
  try{
    const saved=JSON.parse(localStorage.getItem(revisionDraftKey())||'[]');
    if(Array.isArray(saved))revisionLines=saved.filter(item=>item&&item.source==='author_selection'&&item.id&&item.text).map(item=>({...item,selected:item.selected!==false}));
  }catch{localStorage.removeItem(revisionDraftKey());}
}
function revisionQueue(){return [...revisionLines,...(current.issue_cards||[])];}
function visibleSelectedCards(){return revisionQueue().filter(card=>card.selected);}
function unhandledCards(){return revisionQueue().filter(card=>!card.selected&&!card.ignored);}
function updateRevisionCount(){
  const cards=revisionQueue(),selected=visibleSelectedCards();
  // 读稿页收敛 A2:顶部计数=清单卡片总数(与列表来源一致);勾选数由「提交本轮修改(N 项)」承担
  $('revision-count').textContent=cards.length;
  $('submit-revision').textContent=`提交本轮修改（${selected.length} 项）`;
  $('revision-select-all').disabled=!cards.length||selected.length===cards.length;
  $('revision-clear-all').disabled=!selected.length;
}
function setRevisionSelection(selected){
  revisionQueue().forEach(card=>{if(!card.ignored)card.selected=selected;});
  persistRevisionDraft();markDirty('annotations');renderIssues();
}
function readingScrollElement(){return $('reading-scroll');}
function isPureReadingChrome(){return (readingView==='read'||readingView==='official')&&!readingAsideOpen;}
function revealReadingChrome(){
  clearTimeout(readingChromeTimer);readingChromeTimer=0;
  $('reading-decision').classList.remove('reading-chrome-hidden');
}
function syncReadingChromeMode(){
  const panel=$('reading-decision'),pure=isPureReadingChrome();
  panel.classList.toggle('reading-pure',pure);
  if(!pure)revealReadingChrome();
  readingChromeLastTop=readingScrollElement().scrollTop;
}
function handleReadingChromeScroll(){
  const scroller=readingScrollElement(),scrollTop=scroller.scrollTop;
  const nearTop=scrollTop<=40,nearBottom=scroller.scrollHeight-scroller.clientHeight-scrollTop<=40;
  if(!isPureReadingChrome()||nearTop||nearBottom||scrollTop<readingChromeLastTop)revealReadingChrome();
  else if(scrollTop>8&&scrollTop>readingChromeLastTop)$('reading-decision').classList.add('reading-chrome-hidden');
  readingChromeLastTop=scrollTop;
  clearTimeout(readingChromeTimer);
  if(isPureReadingChrome())readingChromeTimer=setTimeout(revealReadingChrome,1400);
}
function sizeChapterEditor(){
  const editor=$('chapter-edit');
  if(editor.hidden)return;
  editor.style.height='auto';
  editor.style.height=`${Math.max(editor.scrollHeight,readingScrollElement().clientHeight)}px`;
}
function setReadingAside(open,focusIssueId=''){
  readingAsideOpen=Boolean(open);
  if(!readingAsideOpen)activeIssueId='';
  else if(focusIssueId)activeIssueId=focusIssueId;
  const panel=$('reading-decision');
  panel.classList.toggle('reading-aside-open',readingAsideOpen);
  $('reading-aside-backdrop').hidden=!readingAsideOpen;
  $('review-exit').hidden=!readingAsideOpen;
  const issueCount=(current.issue_cards||[]).length,entry=$('review-entry');
  if(issueCount){entry.textContent=readingAsideOpen?`${issueCount} 项待处理`:`${issueCount} 处待看`;entry.disabled=readingAsideOpen;}
  renderReviewPaneMode();
  syncReadingChromeMode();
  if(focusIssueId&&readingAsideOpen){requestAnimationFrame(()=>openIssueDetail(focusIssueId));}
}
function setReadingView(view,focusIssueId=''){
  if(!['read','review','edit','official'].includes(view))return;
  if(view==='official'&&$('reading-mode-official').hidden)return;
  readingView=view;
  const panel=$('reading-decision');
  panel.classList.remove('reading-view-read','reading-view-review','reading-view-edit','reading-view-official');
  panel.classList.add(`reading-view-${view}`);
  $('chapter-read').hidden=view==='edit'||view==='official';
  $('chapter-edit').hidden=view!=='edit';
  $('official-chapter').hidden=view!=='official';
  $('reading-mode-read').classList.toggle('current',view==='read'||view==='review');
  $('reading-mode-edit').classList.toggle('current',view==='edit');
  $('reading-mode-official').classList.toggle('current',view==='official');
  if(view==='edit')requestAnimationFrame(sizeChapterEditor);
  if(view==='official'){setReadingAside(false);return;}
  if(view==='read')setReadingAside(false);
  else if(view==='review')setReadingAside(true,focusIssueId);
  else{
    if(readingAsideOpen&&!focusIssueId)activeIssueId='';
    setReadingAside(readingAsideOpen,focusIssueId);
  }
}
async function requestOfficialReadingView(){
  if($('reading-mode-official').hidden||readingView==='official')return;
  if(dirty.has('chapter')&&!await resolveDirty())return;
  readingOfficialRestore={
    asideOpen:readingAsideOpen,
    activeIssueId,
    chapterScroll:readingScrollElement().scrollTop,
    reviewScroll:$('revision-list-shell').scrollTop,
    detailScroll:$('issue-detail').scrollTop,
  };
  setReadingMoreOpen(false);
  setReadingView('official');
  renderReadingDecisionState();
  readingScrollElement().scrollTop=0;
}
function restoreCandidateReadingView(target='read'){
  const restore=readingOfficialRestore;
  readingOfficialRestore=null;
  if(target==='edit'){
    setReadingView('edit');
    if(restore?.asideOpen)setReadingAside(true,restore.activeIssueId||'');
  }else setReadingView(restore?.asideOpen?'review':'read',restore?.activeIssueId||'');
  renderReadingDecisionState();
  requestAnimationFrame(()=>{
    readingScrollElement().scrollTop=restore?.chapterScroll||0;
    $('revision-list-shell').scrollTop=restore?.reviewScroll||0;
    $('issue-detail').scrollTop=restore?.detailScroll||0;
  });
}
function currentChapterText(){return dirty.has('chapter')?$('chapter-edit').value:(current.chapter_text||'');}
function findQuoteAnchor(quote){
  const paragraphs=[...$('chapter-read').querySelectorAll('p')];
  const index=paragraphs.findIndex(paragraph=>quoteStillExists(quote,paragraph.textContent||''));
  return index<0?0:index+1;
}
function normalizedRawRange(quote,text){
  const needle=normalizeQuotedText(quote),normalized=[],rawIndexes=[];
  if(!needle)return null;
  [...String(text||'')].forEach((char,index)=>{if(normalizeQuotedText(char)){normalized.push(char);rawIndexes.push(index);}});
  const start=normalized.join('').indexOf(needle);
  if(start<0)return null;
  return [rawIndexes[start],rawIndexes[start+needle.length-1]+1];
}
function locateQuotedText(quote,card){
  if(readingView==='edit'){
    const range=normalizedRawRange(quote,$('chapter-edit').value);
    if(!range)return;
    $('chapter-edit').focus();$('chapter-edit').setSelectionRange(range[0],range[1]);return;
  }
  const anchor=findQuoteAnchor(quote);if(anchor)focusAnchor(anchor,false,card);
}
function showExcerptReceipt(kind){
  showNotice(kind==='note_problem'?'已记下问题，暂不修改本章；见右栏「本章记录」。':'已记为好句；见右栏「本章记录」。');
}
function canOpenStage(index) {
  return index<=current.stage||(index===4&&((current.samples||[]).length>0||current.actions?.excerpt?.enabled));
}
function renderStageBar() {
  const bar = $('stage-bar'); bar.replaceChildren();
  STAGES.forEach((label, index) => {
    const button = document.createElement('button'); button.className = 'stage-button'; button.textContent = label;
    if (index < current.stage) button.classList.add('done');
    if (index === shownStage) { button.classList.add('current'); button.setAttribute('aria-current', 'step'); }
    const locked = !canOpenStage(index);
    if (locked) button.classList.add('locked');
    if(index===4&&index>current.stage&&!locked)button.classList.add('available');
    button.setAttribute('aria-disabled', locked ? 'true' : 'false');
    button.tabIndex = 0;
    button.title = locked ? (index===4?'采用为正式正文后才能保存章评':'完成前一阶段后自动解锁') : (index===4&&index>current.stage?'查看已记录摘句；采用为正式正文后可保存章评':index < current.stage ? '点回查看已完成阶段' : '当前阶段');
    button.onclick = () => { if (locked) { showNotice(button.title); return; } requestStage(index); }; bar.append(button);
  });
}
function failureIdentity() {
  return current.failure_card?.run_id || current.failure_card?.reason || '';
}
function renderFailureState() {
  const failed = current.axes?.run === 'fail' && failureDismissedFor !== failureIdentity();
  const readingFailed = failed && shownStage === 3;
  $('failure-card').hidden = !failed || readingFailed;
  $('reading-failure-card').hidden = !readingFailed;
  $('failure-card').dataset.noticeWanted=String(failed&&!readingFailed);
  $('reading-failure-card').dataset.noticeWanted=String(readingFailed);
  const reason = current.failure_card?.reason || '操作没有完成，请重试';
  $('failure-reason').textContent = reason;
  $('reading-failure-reason').textContent = `${reason}。正文和当前步骤都没有改变，可以直接重试。`;
}
function applyNavigationState() {
  $('previous-chapter').disabled = busy || Number(current.chapter || 1) <= 1;
}
function applyActionState() {
  const running=busy||current.axes?.run==='busy';
  document.querySelectorAll('[data-action]').forEach(button => {
    const rule = (current.actions || {})[button.dataset.action] || {enabled:false, reason:'当前阶段暂不可使用'};
    button.disabled = busy || !rule.enabled;
  });
  document.querySelectorAll('[data-reason]').forEach(el => {
    const rule = (current.actions || {})[el.dataset.reason]; el.textContent=running?'':(rule && !rule.enabled ? rule.reason : '');
  });
  document.querySelectorAll('[data-save="outline"]').forEach(b => { b.disabled = busy || !(current.actions?.save_outline?.enabled); });
  document.querySelectorAll('[data-save="planning"]').forEach(b => { b.disabled = busy || !(current.actions?.save_planning?.enabled); });
  $('save-confirm-planning').disabled = busy || !(current.actions?.approve_planning?.enabled || (dirty.has('planning') && current.actions?.save_planning?.enabled));
  $('run-architect').disabled = busy || current.web_architect?.state==='running' || !(current.actions?.architect?.enabled);
  $('prefill-outline').disabled = busy || !(current.actions?.prefill_outline?.enabled);
  $('save-chapter').disabled = busy || readingView==='official' || !(current.actions?.edit_chapter?.enabled);
  $('save-review').disabled = busy || !(current.actions?.chapter_review?.enabled);
  $('chapter-review').disabled = busy || !(current.actions?.chapter_review?.enabled);
  $('submit-revision').disabled = busy || dirty.has('chapter') || !(current.actions?.rewrite?.enabled);
  applyNavigationState();
}
function renderSamples() {
  const list=$('sample-list'),preview=$('sample-preview-list'); list.replaceChildren();preview.replaceChildren(); const samples=[...(current.samples||[]),...sessionNotes]; const goodCount=samples.filter(item=>item.type==='good').length,problemCount=samples.length-goodCount; $('sample-total').textContent=samples.length;$('sample-preview-problems').textContent=problemCount;$('sample-preview-good').textContent=goodCount;$('good-count').textContent=goodCount;$('bad-count').textContent=problemCount;
  if(!samples.length){const empty=document.createElement('p');empty.className='aside-hint';empty.textContent='还没有保存摘句。请先在正文中选中文字。';preview.append(empty);}
  samples.forEach(item=>{const row=document.createElement('div');row.className='sample-item';row.dataset.anchor=item.anchor||0;if(item.anchor)row.onclick=event=>{if(event.target.tagName!=='BUTTON')focusAnchor(item.anchor,false,row);};const kind=document.createElement('span');kind.className=item.type;kind.textContent=item.type==='good'?'好句':'问题';const text=document.createElement('p');text.textContent=item.text;const controls=document.createElement('div');if(!item.sessionOnly){const archive=document.createElement('button');archive.textContent='移除';archive.onclick=()=>stream('archive_excerpt',{'entry-id':item.id});controls.append(archive);}row.append(kind,text,controls);list.append(row);});
  samples.forEach(item=>{const row=document.createElement('div');row.className='sample-preview-item';const kind=document.createElement('span');kind.className=item.type;kind.textContent=item.type==='good'?'好句':'问题';const text=document.createElement('p');text.textContent=item.text;row.append(kind,text);preview.append(row);});
}
function issueViewState(card){
  const manual=card.source==='author_selection',feedbackStale=Boolean(current.review_stale||dirty.has('chapter'));
  const hasQuote=Boolean(String(card.quote||'').trim()),quoteAlive=!feedbackStale||!hasQuote||quoteStillExists(card.quote,currentChapterText());
  const exactAnchor=hasQuote&&quoteAlive?findQuoteAnchor(card.quote):0;
  const anchor=manual?Number(card.anchor||0):(exactAnchor||Number(card.anchor||card.line||0));
  const position=feedbackStale?(quoteAlive&&hasQuote?String(card.quote).trim().slice(0,8):'已找不到'):(card.position_label||(manual?`第 ${Math.max(1,Number(card.anchor||1))} 段`:'整章'));
  return {manual,feedbackStale,hasQuote,quoteAlive,anchor,position};
}

function renderArchitectState(){
  const state=current.web_architect?.state||'idle', hasPlan=Boolean((current.planning||'').trim());
  $('planning-empty').hidden=hasPlan||state==='running'||state==='rejected';
  $('planning-run').hidden=state!=='running';
  $('planning-reject').hidden=state!=='rejected';
  if(state==='running') $('planning-source').textContent='方案来源：导演正在写';
  $('planning-read').hidden=state==='running'||state==='rejected'||!hasPlan||$('planning').hidden===false;
  $('planning-compare').hidden=$('planning-read').hidden;
  $('architect-cost-line').hidden=state==='running';
  $('architect-cost-num').textContent=`¥${Number(current.web_architect?.estimate||0.1132).toFixed(2)}`;
  $('run-architect').textContent=hasPlan||state==='rejected'?'让导演重写':'让导演写方案';
  const list=$('planning-missing-list');list.replaceChildren();
  (current.web_architect?.missing_labels||[]).forEach(label=>{const li=document.createElement('li');li.textContent=`缺「${label}」这一类`;list.append(li);});
}
function renderPlanningAssetNotice(){
  const prior=document.getElementById('planning-asset-notice');if(prior)prior.remove();
  const notice=current.planning_asset_notice||{};if(!notice.message)return;
  const row=document.createElement('p');row.id='planning-asset-notice';row.className='outline-character-notice';row.textContent=notice.message;
  $('planning-read').after(row);
}

async function runArchitect(){
  if(busy||$('run-architect').disabled)return;
  busy=true;applyActionState();
  current.web_architect={...(current.web_architect||{}),state:'running'};renderArchitectState();
  const started=Date.now(),timer=setInterval(()=>{$('planning-run-elapsed').textContent=`已用 ${runDuration(Date.now()-started)} · 页面可以离开，写完会留在这里`;},1000);
  try{
    const response=await api(`/books/${encodeURIComponent($('book').value)}/chapters/${$('chapter').value}/architect`,{method:'POST'});
    const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',failed='';
    while(true){const {done,value}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const parts=buffer.split('\n\n');buffer=parts.pop();for(const part of parts){if(!part.startsWith('data: '))continue;const raw=part.slice(6);if(raw==='[DONE]')continue;const event=JSON.parse(raw);if(event.type==='error')failed=event.message||'导演没有写完，盘上方案未改变';}}
    if(failed)showError(failed);
    await fetchSnapshot();
  }catch(error){showError(error.message);}finally{clearInterval(timer);busy=false;applyActionState();}
}
const ISSUE_SOURCE_LABELS=Object.freeze({editor:'编辑提出',auditor:'规则检查',checklist:'戏核核对',author_selection:'我划的'});
function issueSourceLabel(card){return ISSUE_SOURCE_LABELS[card.source]||'来源未识别';}
function updateIssueSelection(card,selected){
  card.selected=selected;if(card.source==='author_selection')persistRevisionDraft();markDirty('annotations');updateRevisionCount();renderReadingDecisionState();
}
function renderReviewPaneMode(){
  const detail=Boolean(readingAsideOpen&&activeIssueId&&revisionQueue().some(card=>card.id===activeIssueId));
  $('review-list-view').hidden=detail;$('review-detail-view').hidden=!detail;if(detail)renderIssueDetail();
}
function openIssueDetail(issueId){
  if(!revisionQueue().some(card=>card.id===issueId))return;activeIssueId=issueId;renderReviewPaneMode();
}
function moveIssueDetail(offset){
  const cards=revisionQueue(),index=cards.findIndex(card=>card.id===activeIssueId),next=index+offset;if(index<0||next<0||next>=cards.length)return;activeIssueId=cards[next].id;renderIssueDetail();
}
function renderIssueDetail(){
  const cards=revisionQueue(),index=cards.findIndex(card=>card.id===activeIssueId),card=cards[index];if(!card){activeIssueId='';renderReviewPaneMode();return;}
  const state=issueViewState(card),detail=$('issue-detail');detail.className='issue-detail';if(card.ignored)detail.classList.add('ignored');if(state.feedbackStale&&state.hasQuote&&!state.quoteAlive)detail.classList.add('dead');
  const flag=card.ignored?' · 已忽略':state.feedbackStale&&!state.manual?` · ${state.quoteAlive?'基于旧版本':'原句已不在正文中'}`:'';
  $('review-detail-position').textContent=`第 ${index+1} 条 / 共 ${cards.length} 条`;$('issue-detail-meta').textContent=`${state.manual?'我划的':`${card.severity_label||'需要核对'} · ${card.type}`} · ${state.position} · ${issueSourceLabel(card)}${flag}`;
  $('issue-detail-conclusion').innerHTML=md(state.manual?(card.text||''):(card.judgment||'暂无结论'));
  $('issue-detail-quote-wrap').hidden=!state.hasQuote;$('issue-detail-quote').textContent=card.quote||'';
  $('issue-detail-explanation-wrap').hidden=!String(card.explanation||'').trim();$('issue-detail-explanation').innerHTML=md(card.explanation||'');$('issue-detail-suggestion').innerHTML=md(state.manual?'按你的补充意见处理。':(card.suggestion||'请结合正文判断'));
  const comment=$('issue-detail-comment');comment.value=card.author_comment||'';comment.oninput=()=>{card.author_comment=comment.value;if(state.manual)persistRevisionDraft();markDirty('annotations');};
  const selected=$('issue-detail-selected');selected.checked=!!card.selected;selected.onchange=async()=>{if(card.ignored&&selected.checked){await cancelIgnoreIssue(card.id,true);return;}updateIssueSelection(card,selected.checked);};
  const locate=$('issue-detail-locate'),canLocate=state.manual?Boolean(state.anchor):(state.hasQuote&&state.quoteAlive);locate.disabled=!canLocate;locate.textContent=canLocate?'定位正文':'定位不可用';locate.onclick=canLocate?()=>state.manual?focusAnchor(state.anchor,false,detail):locateQuotedText(card.quote,detail):null;
  const ignore=$('issue-detail-ignore');
  if(state.manual){ignore.textContent='移除';ignore.onclick=()=>{revisionLines=revisionLines.filter(item=>item.id!==card.id);activeIssueId='';persistRevisionDraft();markDirty('annotations');renderIssues();};}
  else{ignore.textContent=card.ignored?'取消忽略':'本轮忽略';ignore.onclick=()=>card.ignored?cancelIgnoreIssue(card.id):ignoreIssue(card.id);}
  $('issue-detail-prev').disabled=index<=0;$('issue-detail-next').disabled=index>=cards.length-1;
}
function renderIssues(){
  const list=$('issue-list');list.replaceChildren();const cards=revisionQueue();
  $('check-summary').textContent=`检查完成 ${current.check_completed||0} 项 · 未处理 ${unhandledCards().length} 项`;$('completed-count').textContent=current.check_completed||0;
  const completed=$('completed-check-list');completed.replaceChildren();(current.completed_checks||[]).forEach(item=>{const p=document.createElement('p');p.textContent=`${item.severity_label||'已检查'} · ${item.type} · ${item.message}`;completed.append(p);});
  if(!cards.length){const empty=document.createElement('p');empty.textContent='没有需要提交的问题。';list.append(empty);activeIssueId='';updateRevisionCount();renderReviewPaneMode();return;}
  cards.forEach(card=>{
    const state=issueViewState(card),row=document.createElement('article');row.className='issue-list-row';if(card.ignored)row.classList.add('ignored');if(state.feedbackStale&&state.hasQuote&&!state.quoteAlive)row.classList.add('dead');row.dataset.issueId=card.id;row.dataset.anchor=state.anchor||0;row.onclick=()=>openIssueDetail(card.id);
    const pick=document.createElement('label');pick.className='issue-list-pick';pick.onclick=event=>event.stopPropagation();const choose=document.createElement('input');choose.type='checkbox';choose.checked=!!card.selected;choose.setAttribute('aria-label','这条送去返修');choose.onchange=async()=>{if(card.ignored&&choose.checked){await cancelIgnoreIssue(card.id,true);return;}updateIssueSelection(card,choose.checked);};pick.append(choose);
    const copy=document.createElement('div');copy.className='issue-list-copy',meta=document.createElement('div');meta.className='issue-list-meta';const label=document.createElement('span');label.textContent=`${state.manual?'我划的':card.type} · ${state.position}`;const flag=document.createElement('span');flag.className='issue-list-flag';if(card.ignored){flag.classList.add('ignored');flag.textContent='已忽略';}else if(state.feedbackStale&&!state.manual)flag.textContent=state.quoteAlive?'基于旧版本':'原句已不在正文中';const source=document.createElement('span');source.className='issue-list-source';source.textContent=issueSourceLabel(card);meta.append(label,flag,source);
    const conclusion=document.createElement('p');conclusion.className='issue-list-conclusion';conclusion.textContent=state.manual?(card.text||''):(card.judgment||card.suggestion||'请结合正文判断');copy.append(meta,conclusion);row.append(pick,copy);list.append(row);
  });
  if(activeIssueId&&!cards.some(card=>card.id===activeIssueId))activeIssueId='';updateRevisionCount();renderReviewPaneMode();
}
function renderReadingDecisionState(){
  const labels={candidate:'当前候选稿',official:'已定稿',missing:'未生成'};
  const readingState=$('reading-state');readingState.hidden=false;readingState.textContent=labels[current.manuscript_state]||'正文状态未知';
  $('reading-planning-source').textContent=`方案来源：${current.planning_source||'尚未保存'}`;
  $('review-stale').hidden=!(current.review_stale||dirty.has('chapter'));
  const checklistState=current.check_sources?.checklist;
  const checklistMeta=current.check_source_meta?.checklist||{};
  let featureLine='';
  if(checklistState==='feature_off')featureLine='戏核核对：未开启';
  else if(checklistState==='legacy_no_items')featureLine='本章戏核为旧格式，无必检项';
  else if(checklistState==='version_mismatch')featureLine='戏核核对结果对应的是另一版正文';
  else if(checklistState==='unversioned')featureLine='本章戏核核对结果无版本信息，不予采用';
  else if(checklistState==='checked_with_issues'||checklistState==='checked_clean'){
    const total=Number(checklistMeta.total||0),unresolved=Number(checklistMeta.unresolved||0);
    featureLine=unresolved?`戏核核对：${total} 条，${unresolved} 条判不了`:`戏核核对：${total} 条`;
  }
  const checkLine=current.check_state==='unchecked'?'这一章还没有做过检查':current.check_state==='checked_with_issues'?'':current.check_state==='checked_clean'?'这一版没有查出问题':'';
  $('reading-check-state').textContent=[checkLine,featureLine].filter(Boolean).join(' · ');
  const entry=$('review-entry'),issueCount=(current.issue_cards||[]).length;
  entry.textContent=readingAsideOpen?`${issueCount} 项待处理`:`${issueCount} 处待看`;entry.disabled=readingAsideOpen;entry.hidden=current.check_state!=='checked_with_issues'||!issueCount;
  const adopt=$('adopt-button'),reason=$('adopt-reason'),unhandled=unhandledCards().length;
  if(current.manuscript_state==='candidate'){
    adopt.textContent=current.check_state==='unchecked'||unhandled===0?'采 用':`采用（还有 ${unhandled} 处没处理）`;
    reason.textContent=current.check_state==='unchecked'?'这一章还没有做过检查':'';
  }else{
    adopt.textContent='采 用';
    reason.textContent=current.manuscript_state==='official'?'这一章已定稿':'还没有正文，先去生成正文';
  }
  $('revision-dirty-reason').textContent=dirty.has('chapter')?'先保存修改，或放弃修改':'';
  if(readingView==='official'){
    readingState.hidden=true;
    $('review-stale').hidden=true;
    $('reading-check-state').textContent='正在看正式稿 · 只读';
    entry.hidden=true;
  }
  setReadingView(readingView);
}
function cardPosition(card){
  if(current.review_stale){return quoteStillExists(card.quote,currentChapterText())?String(card.quote||'').trim().slice(0,8):'已找不到';}
  return card.position_label||'整章';
}
function renderAdoptGate(cards){
  $('adopt-gate-title').textContent=`还有 ${cards.length} 处没有处理`;
  const list=$('adopt-gate-list');list.replaceChildren();
  cards.forEach(card=>{const item=document.createElement('article');item.className='adopt-item';const head=document.createElement('div');head.className='adopt-item-head';const meta=document.createElement('span');meta.textContent=`${card.severity_label||'需要核对'} · ${card.type} · ${cardPosition(card)}`;const source=document.createElement('span');source.className='adopt-item-source';source.textContent=issueSourceLabel(card);const body=document.createElement('div');body.className='adopt-item-text markdown';body.innerHTML=md(card.judgment||card.suggestion||'请结合正文判断');head.append(meta,source);item.append(head,body);list.append(item);});
  $('adopt-confirm').disabled=false;$('adopt-confirm').textContent='仍然采用';$('adopt-gate').hidden=false;
}
async function requestAdopt(){
  if(busy||current.manuscript_state!=='candidate')return;
  if(dirty.size&&!await resolveDirty())return;
  const cards=unhandledCards();
  if(current.check_state==='unchecked'||cards.length===0){await stream('adopt');return;}
  renderAdoptGate(cards);
}
function closeAdoptGate(){$('adopt-gate').hidden=true;}
async function requestRegenerate(){
  if(busy||!(current.actions?.regenerate?.enabled))return;
  if(dirty.size&&!await resolveDirty())return;
  $('regenerate-word-count').textContent=String((currentChapterText()||'').replace(/\s/g,'').length);
  $('regenerate-confirm').disabled=false;
  $('regenerate-confirm').textContent='重新生成';
  $('regenerate-gate').hidden=false;
}
function closeRegenerateGate(){$('regenerate-gate').hidden=true;}
function openHistoryDialog(){setReadingMoreOpen(false);renderFileDrawer();$('history-dialog').hidden=false;$('history-dialog-close').focus();}
function closeHistoryDialog(){$('history-dialog').hidden=true;}
function renderOutlineFactCheck(){
  const box=$('outline-fact-status'),check=current.outline_fact_check||{issues:[],categories:[]};box.replaceChildren();
  const heading=document.createElement('h3');heading.textContent=check.issues?.length?'和前面对不上':'细纲事实核对';box.append(heading);
  const coverage=document.createElement('ul');(check.categories||[]).forEach(item=>{const row=document.createElement('li');row.textContent=item.checked?`已查：${item.label}，没发现矛盾。`:`未查：${item.label}。${item.reason||'没有可确定比对的记录。'}`;coverage.append(row);});box.append(coverage);
  (check.issues||[]).forEach(item=>{const card=document.createElement('article');card.className='outline-fact-card';const text=document.createElement('p');text.textContent=item.message;const evidence=document.createElement('p');evidence.className='outline-fact-evidence';evidence.textContent=`依据：${item.evidence}`;const actions=document.createElement('div');actions.className='action-row';const continueButton=document.createElement('button');continueButton.type='button';continueButton.textContent='我知道，继续';continueButton.onclick=()=>card.remove();const editButton=document.createElement('button');editButton.type='button';editButton.textContent='回去改这一条';editButton.onclick=()=>{toggleView('outline-edit');$('outline').focus();};actions.append(continueButton,editButton);card.append(text,evidence,actions);box.append(card);});
  const characterNotice=current.outline_character_notice||{};
  if(characterNotice.count){const notice=document.createElement('p');notice.className='outline-character-notice';notice.textContent=characterNotice.message;box.append(notice);}
  box.hidden=false;
}
function renderReplicaStatus(){
  const status=current.replica_status||{},notice=current.replica_notice||{},warning=$('replica-warning'),message=$('replica-warning-message'),button=$('replica-warning-ack');
  const finish=()=>{warning.dataset.noticeWanted=String(!warning.hidden);};
  $('reading-more-replica').textContent='正在读取防手滑副本状态…';
  const acknowledged=notice.replica_unconfigured_acknowledged===true;
  warning.hidden=true;warning.classList.remove('is-error');button.hidden=false;
  if(notice.load_error&&!acknowledged&&$('error-banner').hidden)showError(notice.load_error);
  if(!status.configured&&!acknowledged){
    message.textContent='防手滑副本尚未设置。它不是防灾措施：机器丢失或损坏时会和原件一起丢失。';
    warning.hidden=false;$('reading-more-replica').textContent='防手滑副本尚未设置。';
    finish();return;
  }
  if(status.configured&&status.failed){
    message.textContent=`防手滑副本最近一次没有完成：${status.last_error||'请联系维护者查看。'} 上次成功：${status.last_success||'尚无记录'}。`;
    warning.classList.add('is-error');button.hidden=true;warning.hidden=false;$('reading-more-replica').textContent='防手滑副本最近一次未完成。';
    finish();return;
  }
  if(status.configured){
    $('reading-more-replica').textContent=`防手滑副本上次成功：${status.last_success||'尚无记录'}；当前保留 ${status.snapshot_count||0} 份；最早可恢复到：${status.earliest_recovery||'尚无记录'}。它和原件在同一台机器上，机器丢失或损坏时会一起丢失。`;
    finish();return;
  }
  $('reading-more-replica').textContent='当前没有任何防手滑副本，机器丢失或损坏时会全部丢失。';
  finish();
}
async function acknowledgeReplicaNotice(){
  const button=$('replica-warning-ack');
  if(button.disabled)return;
  const original=button.textContent;
  button.disabled=true;
  button.textContent='正在保存…';
  try{
    const response=await api('/replica-notice/acknowledge',{method:'POST'});
    current.replica_notice=await response.json();
    renderReplicaStatus();
    syncTopNoticePriority();
  }catch(error){
    showError(error.message||'没有保存成功，请稍后再试；顶部提醒仍会保留。');
  }finally{
    button.disabled=false;
    button.textContent=original;
  }
}
function renderSetupRestoreNotice(){
  const notice=current.setup_restore_notice||{},banner=$('setup-restore-notice');
  banner.hidden=notice.active!==true;
  banner.dataset.noticeWanted=String(!banner.hidden);
  if(banner.hidden)return;
  $('setup-restore-message').textContent=notice.message||'角色资料刚刚发生过一次恢复；覆盖前的内容已经保存在历史版本中。';
  $('setup-restore-link').href=`/book.html?book=${encodeURIComponent($('book').value)}#setup-asset-history`;
}
async function acknowledgeSetupRestoreNotice(){
  const button=$('setup-restore-ack');
  if(button.disabled)return;
  button.disabled=true;
  try{
    const response=await api(`/books/${encodeURIComponent($('book').value)}/setup-assets/notice/acknowledge`,{method:'POST'});
    current.setup_restore_notice=await response.json();
    renderSetupRestoreNotice();
    syncTopNoticePriority();
  }catch(error){showError(error.message||'提醒状态没有保存，重新打开时仍会显示。');}
  finally{button.disabled=false;}
}
function wireAnchors(){
  const paragraphs=[...$('chapter-read').querySelectorAll('p')];
  const issueAnchors=new Set([...document.querySelectorAll('.issue-list-row[data-anchor]')].map(card=>Number(card.dataset.anchor)).filter(Boolean));
  paragraphs.forEach((paragraph,index)=>{const anchor=index+1;paragraph.dataset.anchor=anchor;paragraph.classList.toggle('review-mark',issueAnchors.has(anchor));paragraph.onclick=issueAnchors.has(anchor)?()=>{setReadingView('review');focusAnchor(anchor,true,paragraph);}:null;});
}
function focusAnchor(anchor,fromText,source){
  if(fromText&&readingView==='read')setReadingView('review');
  if(!fromText&&$('chapter-read').hidden){setReadingView('review');wireAnchors();}
  const paragraph=$('chapter-read').querySelector(`[data-anchor="${anchor}"]`);
  const cards=[...document.querySelectorAll(`.issue-card[data-anchor="${anchor}"],.sample-item[data-anchor="${anchor}"]`)];
  document.querySelectorAll('.anchor-active').forEach(item=>item.classList.remove('anchor-active'));
  if(paragraph)paragraph.classList.add('anchor-active');cards.forEach(item=>item.classList.add('anchor-active'));
  const target=fromText?cards[0]:paragraph;if(target){const container=fromText?$('revision-list-shell'):readingScrollElement();const top=target.getBoundingClientRect().top-container.getBoundingClientRect().top+container.scrollTop-80;container.scrollTo({top:Math.max(0,top),behavior:'smooth'});}
  if(source)source.classList.add('anchor-active');
}
function versionButton(label, onclick, primary=false){const b=document.createElement('button');b.textContent=label;if(primary)b.className='primary';b.onclick=onclick;return b;}
function formatCandidateLabel(item){
  const parsed=new Date(item.created_at||'');
  const time=Number.isNaN(parsed.getTime())?'时间未知':parsed.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false});
  return `第 ${item.version} 版 · ${time} · ${item.word_count} 字`;
}
function sanitizeAuthorReport(text){
  const technical=/(?:^\s*(?:[$>]\s*)?biyu\s+|\s--[\w-]+|(?:[A-Za-z]:\\|(?:^|\s)(?:data|src|prompts|tests|logs|truth_files)\/)\S+)/i;
  return String(text||'').split(/\r?\n/).filter(line=>!technical.test(line)).join('\n').trim();
}
function renderVersions(){
  const outlines=$('outline-version-list');outlines.replaceChildren();
  if(!current.outline_versions?.length)outlines.textContent='还没有保存过的细纲版本。';
  (current.outline_versions||[]).forEach(item=>{const row=document.createElement('div');row.className='history-item';const head=document.createElement('p');head.textContent=`细纲 v${item.version}${item.current?' · 当前':''}`;const detail=document.createElement('details');const summary=document.createElement('summary');summary.textContent='查看';const pre=document.createElement('pre');pre.textContent=item.content;detail.append(summary,pre);row.append(head,detail);if(!item.current)row.append(versionButton('回到这一版',()=>selectOutline(item.version),true));outlines.append(row);});
  const plans=$('plan-version-list');plans.replaceChildren();
  if(!current.plan_versions?.length)plans.textContent='还没有确认过的方案版本。';
  (current.plan_versions||[]).forEach(item=>{const row=document.createElement('div');row.className='history-item';const head=document.createElement('p');head.textContent=`方案 v${item.version}${item.current?' · 当前':''}`;const detail=document.createElement('details');const summary=document.createElement('summary');summary.textContent='查看';const pre=document.createElement('pre');pre.textContent=item.content;detail.append(summary,pre);row.append(head,detail);if(!item.current)row.append(versionButton('回到这一版',()=>selectPlan(item.version),true));plans.append(row);});
  const candidates=$('candidate-version-list');candidates.replaceChildren();
  if(!current.candidate_versions?.length)candidates.textContent='还没有成功生成的正文版本。';
  (current.candidate_versions||[]).forEach(item=>{const row=document.createElement('div');row.className='history-item';const cmp=item.compare?` · 比${item.compare.label} ${item.compare.delta>=0?'+':''}${item.compare.delta} 字`:'';const head=document.createElement('p');head.textContent=`${formatCandidateLabel(item)} · ${item.state==='current'?'当前':item.state==='trash'?'回收站':'归档'}${cmp}`;const detail=document.createElement('details');const summary=document.createElement('summary');summary.textContent='查看正文';const pre=document.createElement('pre');pre.textContent=item.content;detail.append(summary,pre);const technical=document.createElement('details');const technicalSummary=document.createElement('summary');technicalSummary.textContent='技术详情';const technicalText=document.createElement('p');technicalText.textContent=`方案 v${item.from_plan||'—'}${item.sha?` · ${item.sha}`:item.run_id?` · 运行 ${item.run_id}`:''}`;technical.append(technicalSummary,technicalText);row.append(head,detail,technical);if(item.state!=='current'&&item.state!=='trash')row.append(versionButton('设为当前候选',()=>selectCandidate(item.version),true));if(item.state==='current')row.append(versionButton('移到回收站',discardCandidate));candidates.append(row);});
}
function rootCauseFromReason(reason){
  // 读稿页收敛 A1:从诊断正文提取「首要根因:XX」,与解析字段 layer 比对
  const m=/首要根因[:：]\s*([^，。、\n\s]+)/.exec(reason||'');
  return m?m[1]:null;
}
function renderDiagnosis(){
  const card=$('diagnosis-card'), button=$('diagnose-button'), route=$('diagnosis-route'), reason=$('diagnosis-reason');
  const rounds=Number(current.revision_rounds||0), result=current.diagnosis||{};
  card.hidden=current.axes?.run==='fail'||(rounds<3&&!result.layer)||diagnosisClosedForSha===current.chapter_sha;
  if(card.hidden)return;
  button.disabled=busy||!(current.actions?.diagnose?.enabled);
  if(result.layer){
    // A1:标题结论只在与正文提取的根因一致时写;对不上只保留正文,标题不写结论
    const causeInReason=rootCauseFromReason(result.reason);
    const consistent=!!causeInReason&&causeInReason===result.layer;
    $('diagnosis-message').textContent=`已完成 ${result.rounds||rounds} 轮返工${consistent?`。首要根因：${result.layer}`:''}`;
    button.textContent='重新诊断';
    route.textContent=result.action;
    route.hidden=false;
    route.disabled=busy||result.fresh===false;
    if(result.fresh===false){route.hidden=true;$('diagnosis-message').textContent='诊断已过期，请针对当前候选重新诊断';}
    reason.innerHTML=md(result.reason||'');
    reason.hidden=!result.reason;
  }else{
    $('diagnosis-message').textContent=`同一章已完成 ${rounds} 轮返工。先看历次意见，再按需核对对应候选稿，判断应退回哪一层。`;
    button.textContent='诊断首要根因';
    route.hidden=true;
    reason.hidden=true;
  }
}
function runDuration(milliseconds){
  const seconds=Math.max(0,Math.floor(milliseconds/1000));
  return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
}
function progressStageFromLog(text){
  const value=String(text||'');
  if(/\[1\/4\]|Architect/.test(value))return '规划结构';
  if(/\[2\/4\]|Writer/.test(value))return '写手生成正文';
  if(/\[3\/4\]|WordGuard|grammar_check|dash_fixer|wenyan_fixer/.test(value))return '字数与本地检查';
  if(/\[Editor\]/.test(value))return '编辑审读';
  if(/\[4\/4\]|Polish/.test(value))return '润色正文';
  if(/\[Auditor\]/.test(value))return '规则核查';
  if(/\[audit_report\]/.test(value))return '整理审读报告';
  if(/\[F-4\]|必检项核对/.test(value))return '戏核核对';
  if(/写入 _pending|保存.*候选|snapshot/i.test(value))return '保存候选稿';
  return '';
}
function renderRunProgress(activeIndex=0, label='正在启动…'){
  const progress=$('run-progress');progress.replaceChildren();progress.hidden=false;
  const stages=[label||'正在启动…'];
  stages.forEach((label,index)=>{
    const item=document.createElement('li');
    item.className=`progress-item ${index<activeIndex?'pi-done':index===activeIndex?'pi-active':'pi-wait'}`;
    const icon=document.createElement('span');icon.className='pi-icon';
    const stage=document.createElement('span');stage.className='pi-stage';stage.textContent=label;
    const status=document.createElement('span');status.className='pi-status';
    status.textContent=index<activeIndex?'完成':index===activeIndex?'进行中…':'未开始';
    const timing=document.createElement('span');timing.className='pi-cost';
    item.append(icon,stage,status,timing);progress.append(item);
  });
  updateRunElapsed();
}
function updateRunElapsed(){
  const elapsed=runStartedAt?Date.now()-runStartedAt:0;
  $('run-elapsed').textContent=`已用 ${runDuration(elapsed)}`;
  const active=document.querySelector('#run-progress .pi-active .pi-cost');
  if(active)active.textContent=runDuration(elapsed);
}
function finishRunProgress(action=''){
  if(runTimer){clearInterval(runTimer);runTimer=0;}
  renderRunProgress(1,RUN_LABELS[action]||'完成');
  const rows=$('run-progress').querySelectorAll('.progress-item');
  if(rows.length)rows[rows.length-1].querySelector('.pi-cost').textContent=runDuration(Date.now()-runStartedAt);
}
function renderPersistedRunState(){
  if(current.axes?.run!=='busy'||busy)return;
  $('run-surface').hidden=false;
  $('run-surface-close').hidden=false;
  $('run-surface-close').textContent='在后台继续';
  $('run-result').hidden=true;
  $('log-drawer').hidden=true;
  if(!runStartedAt)runStartedAt=Date.now();
  renderRunProgress(0,'正在恢复运行状态…');
  if(!runTimer)runTimer=setInterval(updateRunElapsed,1000);
}
function render({preserveDirty=false}={}) {
  try {
    document.querySelectorAll('[data-panel]').forEach(panel => { panel.hidden = Number(panel.dataset.panel) !== shownStage; });
    renderStageBar(); applyActionState();
    if (!preserveDirty || !dirty.has('outline')) $('outline').value = current.outline || '';
    if (!preserveDirty || !dirty.has('planning')) $('planning').value = (current.planning || '').replace(/^(?:status|source):[^\n]*\r?\n?/gm, '').replace(/^\s+/, '');
    if (!preserveDirty || !dirty.has('chapter')) $('chapter-edit').value = current.chapter_text || '';
    $('outline-read').innerHTML = md(current.outline);
    renderOutlineFactCheck();
    renderReplicaStatus();
    renderSetupRestoreNotice();
    $('planning-source').textContent=current.planning_has_draft
      ? `方案来源：${current.planning_source||'尚未保存'} · 这是待确认新稿，写手仍使用${current.current_plan_version?`方案 v${current.current_plan_version}`:'已确认方案'}`
      : `方案来源：${current.planning_source||'尚未保存'}`;
    $('planning-read').innerHTML = md((current.planning || '').replace(/^(?:status|source):[^\n]*\r?\n?/gm, '').replace(/^\s+/, ''));
    $('planning-outline-read').innerHTML = current.outline
      ? md(current.outline)
      : '<p class="aside-hint">本章还没有保存的细纲。</p>';
    renderPlanningAssetNotice();
    renderArchitectState();
    $('chapter-read').innerHTML = md(current.chapter_text);
    if(readingView==='edit')requestAnimationFrame(sizeChapterEditor);
    // S-1 读稿留白栏：章号（中文数字）+ 候选稿字数
    const readNum = $('read-chapter-num');
    if (readNum) {
      // 读稿页收敛 B7:章号中文数字(规范 34px 衬线 #C3BCA9,样式见 styles.css)
      readNum.textContent=String(current.chapter||0);
    }
    const readMeta = $('read-margin-meta');
    if (readMeta) {
      const words = (current.chapter_text || '').replace(/\s/g, '').length;
      readMeta.textContent = words ? `${words} 字` : '';
      $('reading-word-count').textContent=readMeta.textContent;
    }
    $('official-chapter').innerHTML = md(current.official_text);
    const officialMode=$('reading-mode-official'),hasOfficial=shouldShowOfficialMode(current);
    officialMode.hidden=!hasOfficial;officialMode.title=hasOfficial?(current.official_lock_reason||'查看已经进书的正式稿'):'';
    if(!hasOfficial&&readingView==='official'){readingOfficialRestore=null;readingView='read';}
    const readonlyTag=$('reading-readonly-tag'),rootLabel=String(bookRoots.get($('book').value)||'');
    readonlyTag.hidden=!rootLabel.startsWith('开发根');readonlyTag.title=readonlyTag.hidden?'':`书「${$('book').selectedOptions[0]?.textContent||$('book').value}」位于${rootLabel}，本单只读开放，写入暂不开放。`;
    $('report').innerHTML = md(sanitizeAuthorReport(current.report || '审读报告尚未生成'));
    $('stale-badge').hidden = !current.stale;
    $('memory-banner').hidden = !current.memory_dirty;
    $('memory-banner').dataset.noticeWanted=String(current.memory_dirty===true);
    const runState=current.axes.run, stepState=current.axes.step;
    $('generation-status').textContent = runState === 'busy' && stepState === 'generation' ? '正文生成中，进度正在写入日志…' : '写作方案确认后，可以从这里生成正文。';
    renderGenerationVoiceprint();
    renderPersistedRunState();
    renderFailureState();
    syncTopNoticePriority();
    const writeButton=document.querySelector('[data-action="write"]');
    if(writeButton)writeButton.textContent=runState==='fail'?'重试生成':'生成正文';
    renderSamples();
    renderIssues();
    renderReadingDecisionState();
    renderVersions();
    renderDiagnosis();
    $('diagnosis-restore').hidden=!current.diagnosis_return_available;
    renderFileDrawer();
    wireAnchors();
    $('entry-status').textContent = `已读取第 ${current.chapter} 章 · ${current.next_step?.label || ''}`;
    syncDirtyUi();
    $('complete-chapter').hidden = !current.chapter_complete;
    $('undo-adopt').disabled = busy || current.axes.asset !== 'official';
  } catch (error) { showError(error.message); }
}
async function fetchSnapshot({auto=false}={}) {
  const book = $('book').value, chapter = Number($('chapter').value);
  const incoming = await (await api(`/books/${encodeURIComponent(book)}/chapters/${chapter}`)).json();
  const unchanged = ['outline_sha','planning_sha','chapter_sha','report_sha','verdict_sha','positive_sha','negative_sha'].every(key => incoming[key] === current[key]) && JSON.stringify(incoming.axes) === JSON.stringify(current.axes) && JSON.stringify(incoming.setup_restore_notice) === JSON.stringify(current.setup_restore_notice) && incoming.stale === current.stale && incoming.review_stale === current.review_stale && incoming.memory_dirty === current.memory_dirty && incoming.running_action === current.running_action;
  if (auto && unchanged) return;
  const localIssueCards = auto && dirty.has('annotations') ? current.issue_cards : null;
  if (auto && dirty.size) {
    const changed = (dirty.has('outline') && incoming.outline_sha !== current.outline_sha) || (dirty.has('planning') && incoming.planning_sha !== current.planning_sha) || (dirty.has('chapter') && incoming.chapter_sha !== current.chapter_sha) || (dirty.has('annotations') && incoming.report_sha !== current.report_sha) || (dirty.has('review') && incoming.verdict_sha !== current.verdict_sha);
    if (changed) { showError('盘面出现了新版本；你正在编辑的文字已保留。请先保存，系统会让你选择载入最新版或对照差异'); return; }
  }
  if (localIssueCards) incoming.issue_cards = current.issue_cards;
  const previousDraftKey=current.chapter_sha?revisionDraftKey():'';const stageChanged = incoming.stage !== current.stage;
  const incomingNotesContext=`${book}:${incoming.chapter}:${incoming.chapter_sha}`;if(sessionNotesContext&&sessionNotesContext!==incomingNotesContext)sessionNotes=[];sessionNotesContext=incomingNotesContext;current = incoming;
  if(!auto||previousDraftKey!==revisionDraftKey())restoreRevisionDraft();
  if (!auto || stageChanged || !canOpenStage(shownStage)) shownStage = current.stage;
  render({preserveDirty:auto});
  if(!auto) renderFileDrawer();
}
async function undoAdopt(){
  if(busy||$('undo-adopt').disabled)return;
  if(!confirm('撤销采用后，本章会回到候选状态，世界观和角色卡自动跟着退回。继续？'))return;
  busy=true;const button=$('undo-adopt'),original=button.textContent;button.disabled=true;button.textContent='撤销中…';
  try{current=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${current.chapter}/undo-adopt`,{method:'POST'})).json();shownStage=current.stage;render();$('run-result').textContent=current.undo_notice;$('run-result').hidden=false;}
  catch(error){showError(error.message);}finally{busy=false;button.textContent=original;applyActionState();}
}
function renderFileDrawer(){
  const list=$('history-list');list.replaceChildren();
  const currentBox=document.createElement('section');const title=document.createElement('h3');title.textContent='当前';const text=document.createElement('p');text.textContent=`${current.axes.asset==='none'?'暂无正文':current.axes.asset==='official'?'正式正文':current.axes.asset==='candidate'?'当前候选稿':'正式正文 + 当前候选稿'}${current.current_plan_version?` · 方案 v${current.current_plan_version}`:''}`;currentBox.append(title,text);list.append(currentBox);
  const archive=document.createElement('section');const archiveTitle=document.createElement('h3');archiveTitle.textContent='归档';archive.append(archiveTitle);const archived=(current.candidate_versions||[]).filter(item=>item.state==='archived');if(!archived.length)archive.append(document.createTextNode('空的。'));else archived.forEach(item=>{const p=document.createElement('p');p.textContent=`正文第 ${item.version} 版`;archive.append(p);});list.append(archive);
  const trash=document.createElement('section');const trashTitle=document.createElement('h3');trashTitle.textContent='回收站（保留 30 天）';trash.append(trashTitle);if(!current.trash?.length)trash.append(document.createTextNode('空的。'));(current.trash||[]).forEach(item=>{const row=document.createElement('div');row.className='history-item';const p=document.createElement('p');p.textContent=item.kind==='excerpt'?`${item.excerpt_type==='good'?'好句':'问题句'} · ${item.text}`:item.kind==='official'?`旧正式稿 · ${new Date(item.deleted_at).toLocaleString()}`:`候选稿${item.version?`第 ${item.version} 版`:''} · ${new Date(item.deleted_at).toLocaleString()}`;row.append(p,versionButton('取回',()=>restoreTrash(item.id),true));trash.append(row);});list.append(trash);
}
async function selectPlan(version){if(!await resolveDirty())return;try{current=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${current.chapter}/plans/${version}/select`,{method:'POST'})).json();shownStage=current.stage;render();}catch(e){showError(e.message);}}
async function selectOutline(version){if(!await resolveDirty())return;try{current=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${current.chapter}/outlines/${version}/select`,{method:'POST'})).json();shownStage=current.stage;render();}catch(e){showError(e.message);}}
async function selectCandidate(version){try{current=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${current.chapter}/candidates/${version}/select`,{method:'POST'})).json();shownStage=current.stage;render();}catch(e){showError(e.message);}}
async function discardCandidate(){if(!confirm('把当前候选稿移到回收站？正式稿不受影响，30 天内可以取回。'))return;try{current=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${current.chapter}/candidate/discard`,{method:'POST'})).json();shownStage=current.stage;render();}catch(e){showError(e.message);}}
async function restoreTrash(id){try{current=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${current.chapter}/trash/${encodeURIComponent(id)}/restore`,{method:'POST'})).json();shownStage=current.stage;closeHistoryDialog();render();}catch(e){showError(e.message);}}
async function routeDiagnosis(){
  if(busy||!current.diagnosis?.layer)return;
  try{
    current=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${current.chapter}/diagnosis/route`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({layer:current.diagnosis.layer})})).json();
    shownStage=current.stage;render();
    $('run-result').textContent='已进入本轮返修：请在右栏勾选问题、补充意见，或划句加入本轮返修。';
    $('run-result').hidden=false;
    requestAnimationFrame(()=>$('issue-list').focus({preventScroll:true}));
  }catch(error){showError(error.message);}
}
async function restoreDiagnosis(){
  if(busy)return;
  try{current=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${current.chapter}/diagnosis/restore`,{method:'POST'})).json();shownStage=current.stage;render();}
  catch(error){showError(error.message);}
}
async function load() {
  return navigateChapter(Number($('chapter').value));
}
function resolveDirty() {
  if (!dirty.size) return Promise.resolve(true);
  $('leave-dialog').hidden=false;
  return new Promise(resolve=>{
    $('leave-save').onclick=async()=>{
      if(dirty.has('annotations')){showError('审读批注还没有提交；请留在本页点“提交本轮修改”，或选择放弃本次修改');resolve(false);return;}
      let saved=true;
      if(dirty.has('outline'))saved=(await save('outline'))&&saved;
      if(dirty.has('planning'))saved=(await save('planning'))&&saved;
      if(dirty.has('chapter'))saved=(await saveChapter())&&saved;
      if(dirty.has('review'))saved=(await saveReview())&&saved;
      if(saved){$('leave-dialog').hidden=true;resolve(true);}else resolve(false);
    };
    $('leave-discard').onclick=async()=>{$('leave-dialog').hidden=true;dirty.clear();syncDirtyUi();$('chapter-review').value='';$('general-comment').value='';document.querySelectorAll('input[name="revision-mode"]').forEach(input=>{input.checked=false;});await fetchSnapshot();resolve(true);};
    $('leave-stay').onclick=()=>{$('leave-dialog').hidden=true;resolve(false);};
  });
}
async function navigateChapter(chapter) {
  if(busy)return; const old=Number(current.chapter||$('chapter').value||1); if(chapter!==old&&!await resolveDirty()){$('chapter').value=old;return;}
  const button=$('load');button.disabled=true;button.textContent='读取中…';$('chapter').value=Math.max(1,chapter);
  try{dirty.clear();syncDirtyUi();generationVoiceprintWorkspace=null;generationVoiceprintBook='';generationVoiceprintDirty=false;generationVoiceprintError=false;clearTransientStatus();await fetchSnapshot();syncWorkbenchLocation();await refreshActiveVoiceprint();if(current.axes.step==='outline'){const r=await api(`/books/${encodeURIComponent($('book').value)}/chapters/${current.chapter}/outline-template`);$('outline').value=(await r.json()).content;markDirty('outline');toggleView('outline-edit');render({preserveDirty:true});}}
  catch(error){$('chapter').value=old;showError(error.message);}finally{button.disabled=false;button.textContent='读取此章';}
}
function appendLog(text) { if (!text) return; $('log').textContent += text + '\n'; $('log').scrollTop = $('log').scrollHeight; }
async function stream(action, extra={}, confirmed=false, options={}) {
  if (busy) return; const rule = current.actions?.[action]; if (rule && !rule.enabled) { showError(rule.reason); return; }
  const inline=options.inline===true;
  if(action==='diagnose')diagnosisClosedForSha='';
  if(action!=='rewrite'||!runStartedAt)runStartedAt=Date.now();
  busy=true;applyActionState();$('log').textContent='';
  if(!inline){$('run-surface').hidden=false;$('run-surface-close').hidden=false;$('run-surface-close').textContent='在后台继续';$('run-result').hidden=true;$('log-drawer').hidden=false;$('log-drawer').open=true;renderRunProgress(0,'正在启动…');if(runTimer)clearInterval(runTimer);runTimer=setInterval(updateRunElapsed,1000);}
  try {
    const response = await api(`/books/${encodeURIComponent($('book').value)}/chapters/${$('chapter').value}/actions/${action}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...extra, confirmed})});
    const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '', repeat = false, failed = false, asked = false;
    while (true) {
      const {done,value}=await reader.read(); if(done) break; buffer += decoder.decode(value,{stream:true}); const parts=buffer.split('\n\n'); buffer=parts.pop();
      for (const part of parts) { if(!part.startsWith('data: ')) continue; const raw=part.slice(6); if(raw==='[DONE]') continue; const event=JSON.parse(raw);
        if(event.type==='confirmation_required'){ asked=true; repeat=confirm(`确认执行？预计费用：${event.estimate}`); break; }
        if(event.type==='error'){failed=true;showError(event.message);}
        const liveStage=progressStageFromLog(event.text||event.message||'');if(liveStage&&!inline)renderRunProgress(0,liveStage);
        appendLog(event.text || event.message || '');
      }
      if(repeat) break;
    }
    if(repeat){ busy=false; return stream(action,extra,true,options); }
    if(asked&&!repeat){if(!inline){$('log-drawer').open=false;$('log-drawer').hidden=true;$('run-result').textContent='已取消，本次没有执行';$('run-result').hidden=false;}return false;}
    if(failed){if(runTimer){clearInterval(runTimer);runTimer=0;}await fetchSnapshot();if(!inline)$('run-surface').hidden=true;return false;}
    await fetchSnapshot();
    if(!inline){$('log-drawer').open = false;$('log-drawer').hidden=true;finishRunProgress(action);$('run-result').textContent=`已完成：${RUN_LABELS[action]||'操作成功'}`;$('run-result').hidden=false;$('run-surface-close').textContent='返回读稿';}
    return true;
  } catch(error){ showError(error.message); return false; } finally { busy=false; applyActionState(); }
}
async function save(kind, confirmPlanning=false, candidateChoice='') {
  if (busy) return; busy=true; applyActionState();
  try {
    const content=$(kind).value, base_sha=current[`${kind}_sha`];
    const payload={content,base_sha};
    if(kind==='planning'){payload.confirm=confirmPlanning;payload.candidate_choice=candidateChoice;}
    current=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${$('chapter').value}/${kind}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})).json();
    clearDirty(kind); shownStage=current.stage; render(); return true;
  } catch(error){ showError(error.message); return false; } finally {busy=false;applyActionState();}
}
function confirmPlanning(){
  if(current.chapter_source!=='pending')return save('planning',true);
  $('candidate-dialog').hidden=false;
  $('candidate-continue').onclick=()=>{$('candidate-dialog').hidden=true;save('planning',true,'continue');};
  $('candidate-regenerate').onclick=()=>{$('candidate-dialog').hidden=true;save('planning',true,'regenerate');};
  $('candidate-cancel').onclick=()=>{$('candidate-dialog').hidden=true;};
}
async function saveChapter() {
  if(busy)return; busy=true; applyActionState();
  try { current=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${$('chapter').value}/chapter`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:$('chapter-edit').value,base_sha:current.chapter_sha,target:current.chapter_target})})).json(); clearDirty('chapter'); render(); return true; }
  catch(error){showError(error.message);return false;} finally{busy=false;applyActionState();}
}
async function ignoreIssue(issueId){
  if(busy)return;busy=true;applyActionState();
  try{current=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${$('chapter').value}/issues/${encodeURIComponent(issueId)}/ignore`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_sha:current.chapter_sha})})).json();render();}
  catch(error){showError(error.message);}
  finally{busy=false;applyActionState();}
}
async function cancelIgnoreIssue(issueId,selectAfter=false){
  if(busy)return;busy=true;applyActionState();
  try{
    current=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${$('chapter').value}/issues/${encodeURIComponent(issueId)}/ignore?candidate_sha=${encodeURIComponent(current.chapter_sha)}`,{method:'DELETE'})).json();
    if(selectAfter){const card=(current.issue_cards||[]).find(item=>item.id===issueId);if(card){card.selected=true;markDirty('annotations');}}
    render();
  }catch(error){showError(error.message);}
  finally{busy=false;applyActionState();}
}
async function submitRevision(){
  if(busy)return;const selected=visibleSelectedCards(),cards=current.issue_cards||[],general=$('general-comment').value.trim();
  if(!selected.length&&!general){showError('请至少勾选一个问题、加入一句本轮返修，或填写整体修改意见');return;}
  const chosenModes=[...document.querySelectorAll('input[name="revision-mode"]:checked')];
  const revisionMode=chosenModes.length===1?chosenModes[0].value:'';
  if(!['local_revision','deep_rewrite'].includes(revisionMode)){showError('返修模式无效');return;}
  busy=true;applyActionState();runStartedAt=Date.now();
  const issues=cards.map(card=>({id:card.id,selected:!!card.selected,author_comment:card.author_comment||''}));
  try{
    current=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${$('chapter').value}/annotations`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_sha:current.chapter_sha,issues,general_comment:general})})).json();
    const packed=await(await api(`/books/${encodeURIComponent($('book').value)}/chapters/${$('chapter').value}/revision-package`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_sha:current.chapter_sha,visible_selected_ids:selected.map(card=>card.id),selected_issue_ids:selected.filter(card=>card.source!=='author_selection').map(card=>card.id),issue_comments:Object.fromEntries(selected.map(card=>[card.id,card.author_comment||''])),general_comment:general,revision_problem_ids:selected.filter(card=>card.source==='author_selection').map(card=>card.id),revision_problem_lines:selected.filter(card=>card.source==='author_selection'),sample_problem_ids:[],mode:revisionMode})})).json();
    clearDirty('annotations');busy=false;applyActionState();
    const draftKey=revisionDraftKey();await stream('rewrite',{package:packed.package});localStorage.removeItem(draftKey);$('general-comment').value='';revisionLines=[];document.querySelectorAll('input[name="revision-mode"]').forEach(input=>{input.checked=false;});
  }catch(error){showError(error.message);}finally{busy=false;applyActionState();}
}
function toggleView(target) {
  const prefix=target.split('-')[0], edit=target.endsWith('-edit');
  if(prefix==='chapter'){setReadingView(edit?'edit':'read');return;}
  const readId=prefix==='chapter'?'chapter-read':`${prefix}-read`, editId=prefix==='chapter'?'chapter-edit':prefix;
  $(readId).hidden=edit; $(editId).hidden=!edit;
  if(!edit&&dirty.has(prefix))$(readId).innerHTML=md($(editId).value);
  document.querySelectorAll(`[data-view^="${prefix}-"]`).forEach(b=>b.classList.toggle('current',b.dataset.view===target));
}
async function requestView(target) {
  if(target==='chapter-official'){await requestOfficialReadingView();return;}
  if(readingView==='official'&&target.startsWith('chapter-')){restoreCandidateReadingView(target==='chapter-edit'?'edit':'read');return;}
  const stage = shownStage;
  setStage(stage);
  toggleView(target);
}
async function saveReview() {
  const ok=await stream('chapter_review',{content:$('chapter-review').value});
  if(!ok)return false;
  clearDirty('review');$('chapter-review').value='';
  $('save-receipt').textContent=`章评已归档 · 好句候选 ${current.verdict_receipt?.positive_count||0} · 问题句候选 ${current.verdict_receipt?.negative_count||0}`;
  $('save-receipt').hidden=false;render();return true;
}
function selectionOffset(paragraph,node,offset){
  const probe=document.createRange();probe.selectNodeContents(paragraph);probe.setEnd(node,offset);return probe.toString().length;
}
function snapSelectionWithinParagraph(selection){
  if(!selection||selection.rangeCount!==1||selection.isCollapsed)return null;
  const range=selection.getRangeAt(0),startNode=range.startContainer,endNode=range.endContainer;
  const startParagraph=(startNode.nodeType===1?startNode:startNode.parentElement)?.closest?.('p');
  const endParagraph=(endNode.nodeType===1?endNode:endNode.parentElement)?.closest?.('p');
  if(!startParagraph||!endParagraph||startParagraph!==endParagraph)return null;
  const whole=startParagraph.textContent||'';
  const rawStart=selectionOffset(startParagraph,startNode,range.startOffset);
  const rawEnd=selectionOffset(startParagraph,endNode,range.endOffset);
  let start=0,end=whole.length;
  for(let index=0;index<rawStart;index+=1)if('。！？；'.includes(whole[index]))start=index+1;
  for(let index=Math.max(rawEnd-1,0);index<whole.length;index+=1){
    if('。！？；'.includes(whole[index])){end=index+1;while(end<whole.length&&'”’」』》'.includes(whole[end]))end+=1;break;}
  }
  const text=whole.slice(start,end).trim();
  return text?{text,anchor:Number(startParagraph.dataset.anchor||1),paragraph:startParagraph}:null;
}
function captureSelection(event) {
  const selection=getSelection(),raw=selection.toString().trim();if(!raw){$('selection-tools').hidden=true;return;}
  const snapped=snapSelectionWithinParagraph(selection);
  const paragraph=event.target.closest('p');
  selectedSnapshot=snapped||{text:raw,anchor:Number(paragraph?.dataset.anchor||1),paragraph};
  selectedText=selectedSnapshot.text;selectedAnchor=Math.max(1,selectedSnapshot.anchor);
  $('selection-preview').textContent=selectedText;$('selection-tools').hidden=false;
}
async function appendFeedback(action){
  if(!selectedSnapshot||busy)return null;
  busy=true;applyActionState();
  try{
    const response=await api(`/books/${encodeURIComponent($('book').value)}/chapters/${current.chapter}/feedback`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,text:selectedSnapshot.text,anchor:String(selectedAnchor),candidate_sha:current.chapter_sha,author_comment:''})});
    const value=await response.json();current=value.snapshot;return value.entry;
  }catch(error){showError(error.message);return null;}
  finally{busy=false;applyActionState();}
}
function revisionEcho(entry){
  const echo=$('revision-echo');echo.textContent=`已加入本轮返修 · 第 ${entry.anchor} 段`;echo.hidden=false;
}
async function addSelectionToRevision(){
  const entry=await appendFeedback('revise');if(!entry)return;
  revisionLines.unshift({id:`manual-${entry.id}`,text:entry.text,book:entry.book,chapter:entry.chapter,candidate_sha:entry.candidate_sha,anchor:entry.anchor,author_comment:'',selected:true,source:'author_selection',severity:'manual',type:'作者划定问题句'});
  sessionNotes.push({id:entry.id,type:'problem',text:entry.text,anchor:entry.anchor,sessionOnly:true});
  $('selection-tools').hidden=true;getSelection().removeAllRanges();revisionEcho(entry);renderIssues();persistRevisionDraft();markDirty('annotations');
  requestAnimationFrame(()=>$('issue-list').querySelector('.author-picked textarea')?.focus());
}
async function recordSelection(action){
  const entry=await appendFeedback(action);if(!entry)return;
  if(action==='note_problem')sessionNotes.push({id:entry.id,type:'problem',text:entry.text,anchor:entry.anchor,sessionOnly:true});
  $('selection-tools').hidden=true;getSelection().removeAllRanges();render();showExcerptReceipt(action);
}
async function selectedImportPayload(){
  const identity=document.querySelector('input[name="import-identity"]:checked')?.value||'';
  if(!identity)throw new Error('请先选择作为候选稿或正式稿');
  const start=Math.max(1,Number($('import-chapter').value||1)),files=[...$('import-files').files];
  if(files.length){
    const items=[];for(let index=0;index<files.length;index+=1){items.push({chapter:start+index,content:await files[index].text(),identity,source:files[index].name});}
    return {items};
  }
  const text=$('import-text').value.trim();if(!text)throw new Error('请粘贴正文或选择 .md/.txt 文件');
  const markers=(text.match(/^第[0-9]+章.*$/gm)||[]).length;
  return {chapter:start,text,identity,source:'paste',split_explicit:markers>1};
}
function openImportDialog(){
  pendingImport=null;$('import-dialog').hidden=false;$('import-preview').hidden=true;$('import-confirm').hidden=true;$('import-next').hidden=false;$('import-chapter').value=current.chapter||1;
}
async function previewImportDialog(){
  try{
    const payload=await selectedImportPayload();
    const preview=await(await api(`/books/${encodeURIComponent($('book').value)}/imports/preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})).json();
    pendingImport={...payload,confirmed:preview.requires_confirmation};
    $('import-preview').textContent=preview.items.map(item=>`第 ${item.chapter} 章 · ${item.identity==='official'?'正式稿':'候选稿'}${item.exists?' · 已有同身份内容，将移入回收站':''}`).join('\n');
    $('import-preview').hidden=false;$('import-next').hidden=true;$('import-confirm').hidden=false;
  }catch(error){showError(error.message);}
}
async function commitImportDialog(){
  if(!pendingImport)return;
  try{
    const result=await(await api(`/books/${encodeURIComponent($('book').value)}/imports`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pendingImport)})).json();
    importedOfficialChapters=result.imported.filter(item=>item.identity==='official').map(item=>item.chapter);
    $('import-dialog').hidden=true;await navigateChapter(result.imported[0]?.chapter||current.chapter);
    if(importedOfficialChapters.length){
      $('memory-cost').textContent=`章数 ${importedOfficialChapters.length} · 调用 ${importedOfficialChapters.length} 次 · 预计 ¥${(importedOfficialChapters.length*.03).toFixed(2)}`;
      $('memory-preview').textContent='先只处理首章，把结果给你确认。';$('memory-import-dialog').hidden=false;
    }else showNotice('候选稿已导入，记忆没有改变。');
  }catch(error){showError(error.message);}
}
async function previewImportedMemory(){
  try{
    const result=await(await api(`/books/${encodeURIComponent($('book').value)}/imports/memory/preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chapters:importedOfficialChapters})})).json();
    remainingMemoryChapters=result.remaining;
    const values=Object.values(result.preview.files||{}).flatMap(group=>Object.values(group||{})).filter(Boolean);
    $('memory-preview').textContent=`第 ${result.preview_chapter} 章提取结果：\n${values.join('\n')||'已建立分片，请核对记忆页。'}`;
    $('memory-start').hidden=true;$('memory-stop').hidden=false;$('memory-continue').hidden=!remainingMemoryChapters.length;
  }catch(error){showError(error.message);}
}
async function continueImportedMemory(){
  try{
    await api(`/books/${encodeURIComponent($('book').value)}/imports/memory/continue`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chapters:remainingMemoryChapters,confirmed:true})});
    $('memory-import-dialog').hidden=true;showNotice('导入章节的记忆已经建立。');
  }catch(error){showError(error.message);}
}
document.querySelectorAll('[data-action]').forEach(button=>{if(!['write','adopt','regenerate'].includes(button.dataset.action))button.onclick=()=>stream(button.dataset.action);});
// v5.1 把低频件移出正文唯一滚动面；保留原 id 与行为，不复制组件。
$('revision-list-shell').append($('diagnosis-card'));
document.querySelector('[data-action="write"]').onclick=async()=>{if(await prepareFirstGenerationVoiceprint())await stream("write");};
$('adopt-button').onclick=requestAdopt;
document.querySelector('[data-action="regenerate"]').onclick=requestRegenerate;
document.querySelectorAll('[data-save]').forEach(button=>button.onclick=()=>save(button.dataset.save));
document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>requestView(button.dataset.view));
document.querySelectorAll('.selectable').forEach(el=>el.addEventListener('mouseup',captureSelection));
document.querySelectorAll('[data-feedback]').forEach(button=>button.onclick=()=>recordSelection(button.dataset.feedback));
$('save-review').onclick=saveReview;
$('undo-adopt').onclick=undoAdopt;
$('save-chapter').onclick=saveChapter; $('load').onclick=load;
$('copy-chapter').onclick=copyChapterText;
$('save-confirm-planning').onclick=confirmPlanning;
$('run-architect').onclick=runArchitect;
$('previous-chapter').onclick=()=>navigateChapter(Number(current.chapter||1)-1);
$('next-chapter').onclick=()=>navigateChapter(Number(current.chapter||1)+1);
$('complete-chapter').onclick=()=>navigateChapter(Number(current.chapter||1)+1);
$('submit-revision').onclick=submitRevision;
$('diagnose-button').onclick=()=>stream('diagnose');
$('diagnosis-route').onclick=routeDiagnosis;
$('diagnosis-restore').onclick=restoreDiagnosis;
$('diagnosis-close').onclick=()=>{diagnosisClosedForSha=current.chapter_sha;$('diagnosis-card').hidden=true;};
$('failure-close').onclick=()=>{failureDismissedFor=failureIdentity();renderFailureState();syncTopNoticePriority();};
$('reading-failure-close').onclick=()=>{failureDismissedFor=failureIdentity();renderFailureState();syncTopNoticePriority();};
$('run-surface-close').onclick=()=>{$('run-surface').hidden=true;};
$('selection-revision').onclick=addSelectionToRevision;
$('open-import').onclick=openImportDialog;
$('import-cancel').onclick=()=>{$('import-dialog').hidden=true;};
$('import-next').onclick=previewImportDialog;
$('import-confirm').onclick=commitImportDialog;
$('memory-later').onclick=()=>{$('memory-import-dialog').hidden=true;};
$('memory-stop').onclick=()=>{$('memory-import-dialog').hidden=true;};
$('memory-start').onclick=previewImportedMemory;
$('memory-continue').onclick=continueImportedMemory;
$('revision-select-all').onclick=()=>setRevisionSelection(true);
$('revision-clear-all').onclick=()=>setRevisionSelection(false);
$('review-entry').onclick=()=>readingView==='edit'?setReadingAside(true):setReadingView('review');
$('review-exit').onclick=()=>{if(readingView==='edit')setReadingAside(false);else setReadingView('read');};
$('reading-aside-backdrop').onclick=()=>{if(readingView==='edit')setReadingAside(false);else setReadingView('read');};
$('review-detail-back').onclick=()=>{activeIssueId='';renderReviewPaneMode();};
$('issue-detail-prev').onclick=()=>moveIssueDetail(-1);
$('issue-detail-next').onclick=()=>moveIssueDetail(1);
$('reading-more-toggle').onclick=event=>{event.stopPropagation();setReadingMoreOpen(!readingMoreOpen);};
$('reading-more-menu').onclick=event=>event.stopPropagation();
$('reading-history-toggle').onclick=openHistoryDialog;
$('history-dialog-close').onclick=closeHistoryDialog;
$('history-dialog').onclick=event=>{if(event.target===$('history-dialog'))closeHistoryDialog();};
document.addEventListener('click',()=>setReadingMoreOpen(false));
$('adopt-confirm').onclick=async()=>{const button=$('adopt-confirm');if(button.disabled)return;button.disabled=true;button.textContent='采用中…';closeAdoptGate();await stream('adopt');};
$('adopt-review').onclick=()=>{closeAdoptGate();setReadingView('review');};
$('adopt-cancel').onclick=closeAdoptGate;
$('regenerate-confirm').onclick=async()=>{const button=$('regenerate-confirm');if(button.disabled)return;button.disabled=true;button.textContent='正在开始…';closeRegenerateGate();await stream('regenerate');};
$('regenerate-cancel').onclick=closeRegenerateGate;
$('replica-warning-ack').onclick=acknowledgeReplicaNotice;
$('setup-restore-ack').onclick=acknowledgeSetupRestoreNotice;
$('save-generation-voiceprint').onclick=saveGenerationVoiceprintSelection;
$('prefill-outline').onclick=async()=>{try{const r=await api(`/books/${encodeURIComponent($('book').value)}/chapters/${$('chapter').value}/outline-template`);$('outline').value=(await r.json()).content;markDirty('outline');toggleView('outline-edit');}catch(e){showError(e.message);}};
['outline','planning'].forEach(id=>$(id).addEventListener('input',()=>{markDirty(id);applyActionState();})); $('chapter-edit').addEventListener('input',()=>{sizeChapterEditor();markDirty('chapter');current.review_stale=true;renderIssues();renderReadingDecisionState();applyActionState();});
$('general-comment').addEventListener('input',()=>{$('general-comment-status').textContent=$('general-comment').value.trim()?'已填写':'未填写';markDirty('annotations');});
document.querySelectorAll('input[name="revision-mode"]').forEach(input=>input.addEventListener('change',()=>markDirty('annotations')));
$('chapter-review').addEventListener('input',()=>markDirty('review'));
$('reading-scroll').addEventListener('scroll',handleReadingChromeScroll,{passive:true});
document.addEventListener('pointermove',event=>{if(event.clientY>=window.innerHeight-90)revealReadingChrome();},{passive:true});
window.addEventListener('focus',()=>{if(!busy){fetchSnapshot({auto:true}).catch(e=>showError(e.message));refreshActiveVoiceprint();}}); setInterval(()=>{if(!busy)fetchSnapshot({auto:true}).catch(()=>{});},5000);
window.addEventListener('beforeunload',event=>{if(dirty.size){event.preventDefault();event.returnValue='';}});
window.addEventListener('keydown',event=>{if(event.key==='Escape'){setReadingMoreOpen(false);if(!$('adopt-gate').hidden)closeAdoptGate();if(!$('regenerate-gate').hidden)closeRegenerateGate();if(!$('history-dialog').hidden)closeHistoryDialog();}});
async function boot(){
  const setup=await fetch('/api/setup/status').then(r=>r.json());
  if(!setup.ready){location.href='/?setup=1';return;}
  const data=await api('/books').then(r=>r.json());
  const params=new URLSearchParams(location.search);
  const requestedBook=params.get('book');
  const validRequested=data.books.some(item=>item.id===requestedBook);
  const wanted=validRequested?requestedBook:(setup.selected_book||data.books[0]?.id||'');
  const chapter=Number(params.get('chapter')||localStorage.getItem(locationDraftKey(wanted))||'1');
  bookRoots=new Map(data.books.map(item=>[item.id,item.root||'']));
  $('book').replaceChildren(...data.books.map(b=>new Option(b.display_name,b.id,false,b.id===wanted)));
  $('chapter').value=Number.isInteger(chapter)&&chapter>0?chapter:1;
  if(data.books.length){
    await load();
    if(requestedBook&&!validRequested){
      const fallbackName=data.books.find(item=>item.id===wanted)?.display_name||wanted;
      showNotice(`找不到书籍“${requestedBook}”，已回到${fallbackName}`);
    }
  }else $('entry-status').textContent='还没有书，请先从书架新建一本书。';
}
boot().catch(e=>showError(e.message));
