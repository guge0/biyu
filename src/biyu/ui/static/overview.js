const $=id=>document.getElementById(id);
let currentBook='';
let currentData=null;
const selectedChapters=new Set();

function showError(message){
  const box=$('error-banner');
  box.replaceChildren();
  const row=document.createElement('div');
  row.className='error-banner-row';
  const icon=document.createElement('span');
  icon.className='error-banner-icon';
  icon.textContent='✗';
  const text=document.createElement('span');
  text.className='error-banner-msg';
  text.textContent=message;
  const close=document.createElement('button');
  close.type='button';
  close.className='error-banner-close';
  close.textContent='×';
  close.onclick=()=>box.hidden=true;
  row.append(icon,text,close);
  box.append(row);
  box.hidden=false;
}

async function api(path){
  const response=await fetch(path);
  if(!response.ok){
    let detail=`请求失败（${response.status}）`;
    try{const body=await response.json();detail=body.detail||detail;}catch{}
    throw new Error(detail);
  }
  return response.json();
}

function syncNavigation(book){
  const encoded=encodeURIComponent(book);
  history.replaceState(null,'',`/overview.html?book=${encoded}`);
  $('workbench-link').href=`/workbench.html?book=${encoded}`;
}

function numberText(value){return Number(value).toLocaleString('zh-CN');}

function costText(value){
  const fixed=Number(value).toFixed(6).replace(/0+$/,'').replace(/\.$/,'');
  return `¥${fixed||'0'}`;
}

function relativeTime(raw){
  if(!raw)return '';
  const value=new Date(raw);
  if(Number.isNaN(value.getTime()))return '';
  const now=new Date();
  const today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
  const then=new Date(value.getFullYear(),value.getMonth(),value.getDate());
  const days=Math.max(0,Math.floor((today-then)/86400000));
  if(days===0)return '今天';
  if(days===1)return '昨天';
  if(days<14)return `${days} 天前`;
  if(days<30)return '两周前';
  return '一个月前';
}

function metricCard(label,value,note=''){
  const card=document.createElement('article');
  card.className='metric-card';
  const name=document.createElement('span');
  name.className='metric-label';
  name.textContent=label;
  const number=document.createElement('strong');
  number.className='metric-value';
  number.textContent=value;
  card.append(name,number);
  if(note){
    const small=document.createElement('small');
    small.textContent=note;
    card.append(small);
  }
  return card;
}

function renderBreakpoint(data){
  const root=$('breakpoint-card');
  root.replaceChildren();
  // S-1 留白栏：当前章号
  const chapterNum=$('overview-chapter-num');
  if(chapterNum){
    chapterNum.textContent=String(data.breakpoint?.chapter || 0);
  }
  if(!data.breakpoint){
    root.classList.add('breakpoint-empty');
    const empty=document.createElement('p');
    empty.textContent=data.breakpoint_empty;
    root.append(empty);
    return;
  }
  root.classList.remove('breakpoint-empty');
  const icon=document.createElement('span');
  icon.className='breakpoint-icon';
  icon.textContent='↪';
  const copy=document.createElement('div');
  copy.className='breakpoint-copy';
  const title=document.createElement('h2');
  title.textContent=`你停在第 ${data.breakpoint.chapter} 章`;
  const detail=document.createElement('p');
  detail.textContent=data.breakpoint.status;
  copy.append(title,detail);
  const link=document.createElement('a');
  link.className='breakpoint-link';
  link.href=data.breakpoint.href;
  link.textContent=`回到第 ${data.breakpoint.chapter} 章`;
  root.append(icon,copy,link);
}

function renderMetrics(metrics){
  const root=$('metrics');
  // S-1 留白栏：已定稿数
  const finalizedNum=$('overview-finalized-num');
  if(finalizedNum){
    finalizedNum.textContent=String(metrics.finalized_chapters);
  }
  root.replaceChildren(
    metricCard('已定稿',numberText(metrics.finalized_chapters)),
    metricCard('总字数',numberText(metrics.total_words)),
    metricCard('等你处理',numberText(metrics.waiting_chapters)),
  );
  if(Object.hasOwn(metrics,'writing_cost')){
    root.append(metricCard(
      '写作花费',
      costText(metrics.writing_cost),
      '只算生成正文，不含起名和对话',
    ));
  }
}

function rowInfo(item,type){
  const info=document.createElement('span');
  info.className='chapter-info';
  if(type==='waiting'){
    info.classList.add('status-badge');
    if(item.status==='等着生成')info.classList.add('status-generate');
    else if(item.status==='有稿等你读')info.classList.add('status-read');
    else if(item.state_error)info.classList.add('status-error');
    else info.classList.add('status-other');
    info.textContent=item.status;
  }else if(type==='problem'){
    info.textContent=`记了 ${item.problem_count} 处问题`;
  }else{
    info.textContent=`${numberText(item.word_count)} 字`;
  }
  return info;
}

function updateExportState(){
  const button=$('export-selected');
  if(!button.disabled||button.dataset.busy!=='true')button.disabled=selectedChapters.size===0;
  if(button.dataset.busy!=='true')$('export-status').textContent=selectedChapters.size?`已选择 ${selectedChapters.size} 章`:'尚未选择章节';
}

function chapterRow(item,type){
  const row=document.createElement('div');
  row.className='chapter-row';
  if(type!=='waiting'){
    const choice=document.createElement('input');
    choice.type='checkbox';
    choice.className='export-choice';
    choice.value=String(item.chapter);
    choice.setAttribute('aria-label',`选择第 ${item.chapter} 章导出`);
    choice.checked=selectedChapters.has(item.chapter);
    choice.onchange=()=>{
      if(choice.checked)selectedChapters.add(item.chapter);else selectedChapters.delete(item.chapter);
      updateExportState();
    };
    row.append(choice);
  }else row.classList.add('chapter-row-waiting');
  const link=document.createElement('a');
  link.className='chapter-row-link';
  link.href=item.href;
  const number=document.createElement('span');
  number.className='chapter-number';
  number.textContent=`第 ${item.chapter} 章`;
  const title=document.createElement('span');
  title.className='chapter-title';
  title.textContent=item.title;
  const time=document.createElement('span');
  time.className='chapter-time';
  time.textContent=relativeTime(item.updated_at);
  link.append(number,title,rowInfo(item,type),time);
  row.append(link);
  return row;
}

function renderGroup(rootId,name,items,type,{collapsed=false}={}){
  const root=$(rootId);
  root.replaceChildren();
  const heading=document.createElement('h2');
  heading.className='group-heading';
  heading.textContent=`${name} · ${items.length} 章`;
  const list=document.createElement('div');
  list.className='chapter-list';
  items.forEach(item=>list.append(chapterRow(item,type)));
  root.append(heading,list);
  if(!items.length){
    const empty=document.createElement('div');
    empty.className='empty-state';
    const t=document.createElement('p');
    t.className='es-title';
    t.textContent='这一组暂时没有章节';
    const h=document.createElement('p');
    h.className='es-hint';
    h.textContent='写下去就会出现在这里。';
    empty.append(t,h);
    root.append(empty);
    return;
  }
  if(collapsed){
    list.hidden=true;
    const toggle=document.createElement('button');
    toggle.type='button';
    toggle.className='group-toggle';
    toggle.textContent=`展开其余 ${items.length} 章`;
    toggle.onclick=()=>{
      const opening=list.hidden;
      list.hidden=!opening;
      toggle.textContent=opening?`收起已定稿`:`展开其余 ${items.length} 章`;
      toggle.setAttribute('aria-expanded',String(opening));
    };
    toggle.setAttribute('aria-expanded','false');
    root.append(toggle);
  }
}

function render(data){
  currentData=data;
  selectedChapters.clear();
  $('book-name').textContent=`《${data.book.display_name}》`;
  renderBreakpoint(data);
  renderMetrics(data.metrics);
  renderGroup('waiting-group','等你处理',data.groups.waiting,'waiting');
  renderGroup(
    'problem-group',
    '定稿了但你记过问题',
    data.groups.problem_finalized,
    'problem',
  );
  renderGroup(
    'finalized-group',
    '已定稿',
    data.groups.finalized,
    'finalized',
    {collapsed:true},
  );
  $('load-status').textContent='已读到当前进度';
  $('overview-content').hidden=false;
  updateExportState();
}

async function exportSelected(){
  const button=$('export-selected');
  if(button.disabled||!selectedChapters.size)return;
  const original=button.textContent;
  button.dataset.busy='true';
  button.disabled=true;
  button.textContent='正在导出…';
  $('export-status').textContent='正在导出…';
  try{
    const response=await fetch(`/api/overview/books/${encodeURIComponent(currentBook)}/export`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({chapters:[...selectedChapters]}),
    });
    if(!response.ok){
      let detail=`请求失败（${response.status}）`;
      try{const body=await response.json();detail=body.detail||detail;}catch{}
      throw new Error(detail);
    }
    const blob=await response.blob();
    const url=URL.createObjectURL(blob);
    const link=document.createElement('a');
    link.href=url;
    link.download=`${currentData.book.display_name}.txt`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    $('export-status').textContent=`已导出 ${selectedChapters.size} 章`;
  }catch(error){
    $('export-status').textContent='导出没有完成';
    showError(error.message);
  }finally{
    button.dataset.busy='false';
    button.textContent=original;
    button.disabled=selectedChapters.size===0;
  }
}

async function boot(){
  const params=new URLSearchParams(location.search);
  const requested=params.get('book');
  const books=await api('/api/workbench/books');
  const setup=await fetch('/api/setup/status').then(response=>response.ok?response.json():({}));
  const valid=books.books.some(item=>item.id===requested);
  const book=valid?requested:(setup.selected_book||books.books[0]?.id||'');
  if(!book)throw new Error('还没有书，请先从书架新建一本书。');
  currentBook=book;
  syncNavigation(book);
  const data=await api(`/api/overview/books/${encodeURIComponent(book)}`);
  render(data);
}

$('export-selected').onclick=exportSelected;
boot().catch(error=>{
  $('load-status').textContent='概览没有读成功';
  showError(error.message);
});
