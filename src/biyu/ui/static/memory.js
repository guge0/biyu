const $=id=>document.getElementById(id);const params=new URLSearchParams(location.search);let book=params.get('book')||'';
function showError(message){const box=$('error-banner');box.replaceChildren();const row=document.createElement('div');row.className='error-banner-row';const icon=document.createElement('span');icon.className='error-banner-icon';icon.textContent='✗';const text=document.createElement('span');text.className='error-banner-msg';text.textContent=message;const close=document.createElement('button');close.className='error-banner-close';close.textContent='×';close.onclick=()=>box.hidden=true;row.append(icon,text,close);box.append(row);box.hidden=false;}
async function api(path,options={}){const response=await fetch(`/api/workbench${path}`,options);if(!response.ok){let detail=`请求失败（${response.status}）`;try{const body=await response.json();detail=body.detail||detail;}catch{}throw new Error(detail);}return response.json();}
function button(label,handler,kind){const value=document.createElement('button');value.textContent=label;value.className=kind||'b2';value.type='button';value.onclick=async()=>{if(value.disabled)return;const original=value.textContent;value.disabled=true;value.textContent=`${label}中…`;try{await handler();}catch(error){showError(error.message);}finally{value.disabled=false;value.textContent=original;}};return value;}
function render(data){const entries=$('entries'),conflicts=$('conflicts');entries.replaceChildren();conflicts.replaceChildren();if(data.error)showError(data.error);
  // S-1/U-1 留白栏：条目数（中文数字）
  const countNum=$('memory-count-num');
  if(countNum){countNum.textContent=String((data.entries||[]).length);}
  const meta=$('memory-margin-meta');
  if(meta){meta.textContent=(data.conflicts||[]).length?`${(data.conflicts||[]).length} 处冲突`:'全部锚定';}
  (data.conflicts||[]).forEach(item=>{const card=document.createElement('article');card.className='memory-conflict';const title=document.createElement('h2');title.textContent=`冲突：${item.key}`;const detail=document.createElement('p');detail.textContent=`正文推算：${item.machine} ｜ 我的锚定：${item.pinned}`;const [file,...parts]=item.key.split(':');const key=parts.join(':');card.append(title,detail,button('保留我的',async()=>render(await api(`/books/${encodeURIComponent(book)}/memory/conflicts/resolve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file,key,choice:'mine'})})),'b2'),button('听正文的',async()=>render(await api(`/books/${encodeURIComponent(book)}/memory/conflicts/resolve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file,key,choice:'machine'})})),'b2'));conflicts.append(card);});
  (data.entries||[]).forEach(item=>{const card=document.createElement('article');card.className='memory-entry';const head=document.createElement('div');head.className='memory-entry-head';const title=document.createElement('h2');title.textContent=item.key;if(item.pinned){const badge=document.createElement('span');badge.className='badge need';badge.textContent='已锚定';head.append(title,badge);}else{head.append(title);}const value=document.createElement('textarea');value.value=item.value;const save=button(item.pinned?'更新锚定':'保存并锚定',async()=>render(await api(`/books/${encodeURIComponent(book)}/memory/pins`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:item.file,key:item.key,value:value.value})})),'b2');card.append(head,value,save);if(item.pinned)card.append(button('解除锚定',async()=>render(await api(`/books/${encodeURIComponent(book)}/memory/pins?file=${encodeURIComponent(item.file)}&key=${encodeURIComponent(item.key)}`,{method:'DELETE'})),'b3'));entries.append(card);});
  if(!(data.entries||[]).length){const empty=document.createElement('div');empty.className='empty-state';const t=document.createElement('p');t.className='es-title';t.textContent='暂无可显示的记忆条目。';const h=document.createElement('p');h.className='es-hint';h.textContent='采用正式稿后，机器会在这里整理世界观与角色的运行事实。';empty.append(t,h);entries.append(empty);}}
async function boot(){
  if(!book){
    const setup=await fetch('/api/setup/status').then(response=>response.json());
    if(!setup.ready){location.href='/?setup=1';return;}
    book=setup.selected_book||'';
    if(!book){
      const data=await api('/books');
      book=data.books?.[0]?.id||'';
    }
  }
  if(!book){
    $('entries').textContent='还没有书，请先从书架新建一本书。';
    return;
  }
  history.replaceState(null,'',`/memory.html?book=${encodeURIComponent(book)}`);
  const encodedBook=encodeURIComponent(book);
  $('back').href=`/workbench.html?book=${encodedBook}`;
  const voiceprintLink=$('voiceprint-link');
  if(voiceprintLink)voiceprintLink.href=`/voiceprint.html?book=${encodedBook}`;
  render(await api(`/books/${encodeURIComponent(book)}/memory`));
}
boot().catch(error=>showError(error.message));
