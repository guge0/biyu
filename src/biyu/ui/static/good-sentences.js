const $=id=>document.getElementById(id);
let current={entries:[],chapters:[]};

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

function timeText(raw){
  const value=new Date(raw);
  if(Number.isNaN(value.getTime()))return raw;
  return value.toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
}

function render(){
  const selected=$('chapter-filter').value;
  const entries=selected==='all'
    ? current.entries
    : current.entries.filter(item=>item.chapter===Number(selected));
  const list=$('good-sentences-list');
  list.replaceChildren();
  if(!entries.length){
    const empty=document.createElement('div');
    empty.className='empty-state';
    const t=document.createElement('p');
    t.className='es-title';
    t.textContent=selected==='all'?'还没有标记过好句。':'这一章还没有标记过好句。';
    const h=document.createElement('p');
    h.className='es-hint';
    h.textContent='在读稿定夺里选中文字、点「记录好句」就会收进来。';
    empty.append(t,h);
    list.append(empty);
  }
  entries.forEach(item=>{
    const card=document.createElement('article');
    card.className='good-sentence-card';
    const meta=document.createElement('p');
    meta.className='good-sentence-meta';
    meta.textContent=`第 ${item.chapter} 章 · ${timeText(item.created_at)}`;
    const text=document.createElement('blockquote');
    text.textContent=item.text;
    card.append(meta,text);
    list.append(card);
  });
  $('load-status').textContent=`共 ${entries.length} 句`;
  // S-1 留白栏：句数 + 跨章数
  const countNum=$('good-count-num');
  if(countNum){
    countNum.textContent=String(current.entries.length);
  }
  const chapterCount=$('good-chapter-count');
  if(chapterCount){
    const chapters=new Set(current.entries.map(item=>item.chapter));
    chapterCount.textContent=String(chapters.size);
  }
  // S-1 pill 高亮同步
  document.querySelectorAll('#chapter-pills .pill').forEach(pill=>{
    const on=pill.dataset.value===selected;
    pill.style.borderColor=on?'var(--ink-solid)':'';
    pill.style.color=on?'var(--ink)':'';
  });
  list.hidden=false;
}

function syncPage(book,data){
  const encoded=encodeURIComponent(book);
  history.replaceState(null,'',`/good-sentences.html?book=${encoded}`);
  $('workbench-link').href=`/workbench.html?book=${encoded}`;
  $('book-name').textContent=`《${data.book.display_name}》`;
  const filter=$('chapter-filter');
  filter.replaceChildren(new Option('全部章节','all'));
  data.chapters.forEach(chapter=>filter.append(new Option(`第 ${chapter} 章`,String(chapter))));
  filter.disabled=false;
  // S-1 pill 筛选行（视觉用，同步 select 值）
  const pills=$('chapter-pills');
  pills.replaceChildren();
  const makePill=(value,label)=>{
    const pill=document.createElement('button');
    pill.type='button';
    pill.className='pill';
    pill.dataset.value=value;
    pill.textContent=label;
    pill.onclick=()=>{
      filter.value=value;
      render();
    };
    pills.append(pill);
  };
  makePill('all','全部');
  data.chapters.forEach(chapter=>makePill(String(chapter),`第 ${chapter} 章`));
}

async function boot(){
  const params=new URLSearchParams(location.search);
  const requested=params.get('book');
  const books=await api('/api/workbench/books');
  const setup=await fetch('/api/setup/status').then(response=>response.ok?response.json():({}));
  const valid=books.books.some(item=>item.id===requested);
  const book=valid?requested:(setup.selected_book||books.books[0]?.id||'');
  if(!book)throw new Error('还没有书，请先从书架新建一本书。');
  current=await api(`/api/good-sentences/books/${encodeURIComponent(book)}`);
  syncPage(book,current);
  render();
}

$('chapter-filter').addEventListener('change',render);
boot().catch(error=>{
  $('load-status').textContent='好句没有读成功';
  showError(error.message);
});
