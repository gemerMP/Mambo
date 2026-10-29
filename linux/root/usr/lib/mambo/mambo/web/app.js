'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const preview = location.protocol === 'file:' || window.MAMBO_PREVIEW === true;
const memory = {};
const prefs = {get(k, fallback) { try { return JSON.parse(localStorage.getItem('mambo.' + k)) ?? fallback; } catch { return memory[k] ?? fallback; } }, set(k,v) { memory[k]=v; try { localStorage.setItem('mambo.'+k,JSON.stringify(v)); } catch {} }};
let token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
try { if (token) sessionStorage.setItem('mambo.token',token); else token=sessionStorage.getItem('mambo.token') || ''; } catch {}
if (location.hash.startsWith('#token=')) history.replaceState(null,'',location.pathname);
let state={profiles:[],status:{running:false,engine_available:false,socks_port:10808},rules:{direct:[],block:[]}};
let selected=prefs.get('selected',null), onlyFavorites=false, checks={}, busy=false, apiOnline=false;
let connectionMode=prefs.get('connectionMode','tun');
if(!['tun','socks'].includes(connectionMode))connectionMode='tun';
$('#connectionMode').value=connectionMode;
$('#connectionMode').onchange=()=>{connectionMode=$('#connectionMode').value;prefs.set('connectionMode',connectionMode);render();};
let color=prefs.get('color','pink'), mode=prefs.get('mode','dark');
if(!['pink','green','red'].includes(color))color='pink';
if(!['dark','light'].includes(mode))mode='dark';
const words=[
 'Можно идти маленькими шагами. Это тоже движение вперёд.',
 'Ты не обязан успеть всё. Оставь немного времени для себя.',
 'Пусть сегодня случится что-нибудь маленькое и хорошее.',
 'Даже в шумном мире у тебя может быть тихий уголок.',
 'Твоих стараний больше, чем тебе иногда кажется.',
 'Сделай глоток воды. Выдохни. Дальше — по одному шагу.',
 'Сегодня можно начать заново. Даже с самого маленького.',
 'Пауза — тоже часть пути. Я подожду здесь.',
 'Пусть нужные люди будут ближе, а лишний шум — тише.',
 'Не обязательно быть идеальным, чтобы делать что-то хорошее.',
 'Береги своё любопытство. В мире ещё столько интересного.',
 'Ты уже здесь. Давай начнём с чего-нибудь простого.',
 'Немного тепла тебе в карман. На всякий случай.',
 'Иногда лучший план — спокойно сделать одну вещь.',
 'Пусть этот вечер будет к тебе добрым.',
 'Свой темп — тоже хороший темп. Не теряй его.'
];
function nextQuote(){
 let bag=prefs.get('quoteBag',[]).filter(x=>Number.isInteger(x)&&x>=0&&x<words.length);
 if(!bag.length){ bag=words.map((_,i)=>i); for(let i=bag.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[bag[i],bag[j]]=[bag[j],bag[i]];} if(bag.at(-1)===prefs.get('lastQuote',-1)) [bag[0],bag[bag.length-1]]=[bag.at(-1),bag[0]]; }
 const index=bag.pop();prefs.set('quoteBag',bag);prefs.set('lastQuote',index);$('#quote').textContent=words[index];
}
let toastTimer;
function toast(text){$('#toast').textContent=text;$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),5000);}
const mockProfiles=[{id:'preview-amsterdam',name:'Амстердам · мой основной',host:'nl.example.org',port:443,protocol:'vless',transport:'tcp',security:'reality',favorite:true},{id:'preview-helsinki',name:'Хельсинки · запасной',host:'fi.example.org',port:443,protocol:'trojan',transport:'tcp',security:'tls',favorite:false}];
async function api(path,data){
 if(preview){
  if(path==='state')return state;
  if(path==='favorite'){state.profiles.find(x=>x.id===data.id).favorite=data.enabled;return {};}
  if(path==='delete'){state.profiles=state.profiles.filter(x=>x.id!==data.id);return {};}
  if(path==='rules'){state.rules=data;return {};}
  if(path==='check')throw Error('Это предпросмотр. TCP-проверка доступна в запущенном приложении.');
  throw Error('Это предпросмотр дизайна. Реальное подключение и импорт — после запуска python -m mambo ui.');
 }
 const response=await fetch('/api/'+path,{method:data?'POST':'GET',headers:{Authorization:'Bearer '+token,...(data?{'Content-Type':'application/json'}:{})},body:data?JSON.stringify(data):undefined});
 const result=await response.json();if(!response.ok)throw Error(result.error||'Не удалось выполнить действие.');return result;
}
async function refresh(quiet=false){
 try{state=await api('state');apiOnline=true;if(!state.profiles.some(x=>x.id===selected))selected=state.profiles[0]?.id||null;if(state.status.running)selected=state.status.active;render();}
 catch(e){apiOnline=false;$('#statusBadge').textContent='Нет связи с Mambo';$('#connectionTitle').textContent='Проверим приложение';$('#connectionHint').textContent='Открой адрес из терминала Mambo.';$('#power').disabled=true;$('#footerStatus').textContent='Статус ядра неизвестен';if(!quiet)toast(e.message);}
}
function switchTab(id){if(!$('#'+id)?.classList.contains('page'))return;$$('.page').forEach(x=>x.classList.toggle('active',x.id===id));$$('.nav').forEach(x=>x.classList.toggle('active',x.dataset.tab===id));const titles={home:'Рада тебя видеть',servers:'Твои точки на карте',routes:'Свобода с твоими правилами',themes:'Устраивайся поудобнее',help:'Всё понятно, всё под контролем'};$('#pageTitle').replaceChildren(document.createTextNode(titles[id]+' '));const star=document.createElement('span');star.className='accent';star.textContent='✦';$('#pageTitle').append(star);if(id==='routes'){$('#directRules').value=state.rules.direct.join('\n');$('#blockRules').value=state.rules.block.join('\n');}window.scrollTo({top:0,behavior:'auto'});}
$$('[data-tab]').forEach(x=>x.addEventListener('click',()=>switchTab(x.dataset.tab)));
$('.brand').addEventListener('click',e=>{e.preventDefault();switchTab('home');});
function applyTheme(){
 $$('#heroArt,[data-mascot]').forEach(el=>{el.dataset.poseIndex='0';el.dataset.imageRequest='';});
 document.documentElement.dataset.color=color;document.documentElement.dataset.mode=mode;prefs.set('color',color);prefs.set('mode',mode);$('#modeToggle').textContent=mode==='dark'?'☾':'☀';
 const art=`assets/${color}-hello.png`;
 $('#heroArt').src=window.MAMBO_ASSETS?.[art]||art;$('#heroArt').alt='Мамбо — персонаж выбранной темы';updateMascots();
 $$('.theme-card').forEach(x=>{const active=x.dataset.color===color&&x.dataset.mode===mode;x.classList.toggle('selected',active);x.setAttribute('aria-pressed',String(active));});
}
const themes=[['pink','dark','Сакура · ночь','Розовый свет в темноте','#181319','#eda5ca'],['pink','light','Сакура · день','Тепло розового утра','#faf3f7','#af4d83'],['green','dark','Лес · ночь','Тишина хвойного леса','#141c17','#a5cab0'],['green','light','Лес · день','Свежесть и мягкий свет','#f4f8ef','#4c7858'],['red','dark','Красный закат · ночь','Чёрный фон, красный акцент','#201416','#ed929a'],['red','light','Красный закат · день','Светлая бумага и красные чернила','#fbf4ee','#b54e5e']];
for(const [c,m,title,subtitle,bg,accent] of themes){const b=document.createElement('button');b.className='theme-card';b.dataset.color=c;b.dataset.mode=m;b.style.setProperty('--sample-bg',bg);b.style.setProperty('--sample-accent',accent);b.style.setProperty('--sample-line',m==='dark'?'#ffffff14':'#00000012');b.innerHTML='<div class="theme-preview"><div class="mini-nav"></div><div class="mini-content"><div class="mini-title"></div><div class="mini-panel"><span class="mini-power"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 3v9M6.3 5.8a8 8 0 1 0 11.4 0"/></svg></span></div></div></div><div class="theme-info"><div><strong></strong><small></small></div><span class="check">✓</span></div>';b.querySelector('strong').textContent=title;b.querySelector('small').textContent=subtitle;b.onclick=()=>{color=c;mode=m;applyTheme();};$('#themeGrid').append(b);}
$('#modeToggle').onclick=()=>{mode=mode==='dark'?'light':'dark';applyTheme();};
for(const [id,cls,def] of [['motion','no-motion',!matchMedia('(prefers-reduced-motion: reduce)').matches],['artEnabled','no-art',true],['quotesEnabled','no-quotes',true]]){const input=$('#'+id);input.checked=prefs.get(id,def);document.body.classList.toggle(cls,!input.checked);input.onchange=()=>{prefs.set(id,input.checked);document.body.classList.toggle(cls,!input.checked);if(id==='artEnabled'&&!input.checked){$('#quotesEnabled').checked=true;prefs.set('quotesEnabled',true);document.body.classList.remove('no-quotes');}};}
$('#newQuote').onclick=nextQuote;
function render(){
 const p=state.profiles.find(x=>x.id===selected),s=state.status;
 $('#navCount').textContent=state.profiles.length;
 $('#selectedName').textContent=p?.name||'Добавь первый сервер';$('#selectedMeta').textContent=p?`${p.protocol.toUpperCase()} · ${p.security.toUpperCase()} · ${p.host}`:'Ссылка или подписка от твоего провайдера';
 $('#statusBadge').replaceChildren();const dot=document.createElement('i');$('#statusBadge').append(dot,document.createTextNode(s.tun_pending?'Ожидание VPN':s.running?(s.internet?.ok&&(!s.internet.system||s.internet.system.ok)?'Подключено':s.scope==='tun'?'VPN запущен':'Прокси запущен'):'Отключено'));$('#statusBadge').classList.toggle('running',s.running);
 $('#connectionMode').disabled=busy||s.running||s.tun_pending;$('#scopeLabel').textContent=(s.running?s.scope:connectionMode)==='tun'?'VPN всей системы':'Локальный SOCKS5';$('#power').classList.toggle('running',s.running);$('#power').disabled=busy||!apiOnline;$('#power').setAttribute('aria-label',s.running?'Отключиться':'Подключиться');
 $('#connectionTitle').textContent=s.running?'Твоя точка подключения готова':'Мир ближе, чем кажется';$('#connectionHint').textContent=s.tun_pending?'Подтверди или отмени запрос в системном окне.':s.running?(s.internet?.system&&!s.internet.system.ok?'Прокси отвечает, но системный доступ не прошёл проверку. Открой диагностику.':s.internet?.ok?'HTTPS-проверка через сервер пройдена.':s.scope==='tun'?'TUN запущен. Проверь доступ в интернет.':'Укажи SOCKS5 в нужном приложении.'):p?(connectionMode==='tun'?'Нажми кнопку для подключения VPN.':'Нажми кнопку для запуска локального прокси.'):'Выбери сервер — и начнём.';
 $('#portLabel').textContent=$('#helpPort').textContent='127.0.0.1:'+s.socks_port;
 $('#footerStatus').textContent=preview?'Предпросмотр · без сетевого подключения':s.running?(s.scope==='tun'?'Режим VPN всей системы':'Локальный прокси работает'):'Всё хранится на этом устройстве';
 renderServers();renderDiagnostics();
}
function renderServers(){
 const list=$('#serverList');list.replaceChildren();const search=$('#search').value.toLowerCase();const profiles=state.profiles.filter(p=>(!onlyFavorites||p.favorite)&&(p.name+' '+p.host).toLowerCase().includes(search)).sort((a,b)=>Number(b.favorite)-Number(a.favorite));
 if(!profiles.length){const e=document.createElement('div');e.className='card empty';e.innerHTML='<span>✧</span><h2></h2><p class="subtext"></p><button class="primary">＋ Добавить сервер</button>';e.querySelector('h2').textContent=state.profiles.length?'Здесь пока тихо':'Начнём с первого сервера';e.querySelector('p').textContent=state.profiles.length?'Попробуй другой поиск или переключись на все серверы.':'Вставь ссылку от провайдера. Mambo сохранит её на этом устройстве.';e.querySelector('button').onclick=openImport;list.append(e);return;}
 for(const p of profiles){const row=document.createElement('article');row.className='card server-row'+(selected===p.id?' chosen':'');row.innerHTML='<button class="fav" aria-label="В избранное">♡</button><span class="server-icon">◎</span><div class="info"><strong></strong><small></small><input class="lite-command" readonly aria-label="Команда подключения Mambo Lite"></div><span class="latency"></span><button class="select secondary">Выбрать</button><button class="delete" aria-label="Удалить сервер">×</button>';row.querySelector('strong').textContent=p.name;row.querySelector('small').textContent=`${p.protocol.toUpperCase()} / ${p.transport.toUpperCase()} · ${p.host}:${p.port}`;const lite=row.querySelector('.lite-command');lite.value=`mambo-lite connect ${p.id} --mode tun`;lite.onclick=()=>lite.select();row.querySelector('.latency').textContent=checks[p.id]?(checks[p.id].reachable?checks[p.id].tcp_ms+' мс TCP':'Недоступен'):'Не проверен';const fav=row.querySelector('.fav');fav.classList.toggle('on',p.favorite);fav.textContent=p.favorite?'♥':'♡';fav.setAttribute('aria-pressed',String(p.favorite));fav.onclick=()=>action(async()=>{await api('favorite',{id:p.id,enabled:!p.favorite});await refresh();});const select=row.querySelector('.select');select.textContent=selected===p.id?'Выбран':'Выбрать';select.className=selected===p.id?'select primary':'select secondary';select.onclick=()=>{if(state.status.running&&state.status.active!==p.id)return toast('Отключи текущий сервер перед переключением.');selected=p.id;prefs.set('selected',selected);render();toast('Выбран: '+p.name);};row.querySelector('.delete').onclick=()=>{if(confirm('Удалить «'+p.name+'» с этого устройства?'))action(async()=>{await api('delete',{id:p.id});await refresh();});};list.append(row);}
}
function renderDiagnostics(){const d=$('#diagnostics');d.replaceChildren();const s=state.status;$('#installEngine').hidden=s.engine_available;$('#engineInstallHint').hidden=s.engine_available;$('#checkInternet').disabled=!s.running||busy;for(const [name,value] of [['Ядро Xray',preview?'Предпросмотр':s.engine_available?'Найдено':'Не установлено / не в PATH'],['Локальный SOCKS5',s.running?'Запущен':'Остановлен'],['Интернет через сервер',s.internet?(s.internet.ok?'HTTPS проверен ('+s.internet.ms+' мс)':'Проверка не прошла'):'Не проверен'],['Режим всей системы (TUN)',s.tun_available?'Установлен':preview?'Предпросмотр':'Не установлен компонент VPN'],['Интернет через системные маршруты',s.internet?.system?(s.internet.system.ok?'HTTPS доступен (сам по себе не доказывает маршрут через VPN)':s.internet.system.stage==='dns'?'Ошибка системного DNS':'HTTPS недоступен'):'Не проверен'],['DNS интерфейса VPN',s.system_dns==='windows-tun'?'DNS через Windows TUN':s.system_dns==='configured'?'Настроен через systemd-resolved':s.system_dns==='failed'?'Не удалось настроить':s.system_dns==='unavailable'?'systemd-resolved недоступен; используется перехват DNS':'Не проверен'],['Сохранённые профили',String(state.profiles.length)]]){const row=document.createElement('div');row.className='diagnostic-row';for(const text of [name,value]){const span=document.createElement('span');span.textContent=text;row.append(span);}d.append(row);}if(s.error){const e=document.createElement('p');e.className='error';e.textContent=s.error;d.append(e);}}
async function action(fn){if(busy)return;busy=true;$('#power').disabled=true;$('#connectionMode').disabled=true;try{await fn();}catch(e){toast(e.message);}finally{busy=false;$('#power').disabled=!apiOnline;$('#connectionMode').disabled=state.status.running||state.status.tun_pending;$('#checkInternet').disabled=!state.status.running;}}
$('#power').onclick=()=>action(async()=>{if(state.status.running||state.status.tun_pending){await api('disconnect',{});toast('Подключение остановлено.');}else{if(!selected){openImport();return;}if(state.profiles.find(p=>p.id===selected)?.transport==='xhttp'&&!state.status.engine_available){switchTab('help');toast('Для XHTTP нажми «Установить Xray». Это нужно один раз.');return;}toast('Подключаемся…');await api('connect',{id:selected,mode:connectionMode});await refresh();const result=await api('internet-check',{});toast(result.system&&!result.system.ok?'Прокси отвечает, но системный доступ не работает. Подробности в диагностике.':result.ok?'HTTPS через сервер работает.':result.message);}await refresh();});
function openImport(){$('#importError').textContent='';$('#importDialog').showModal();$('#importText').focus();}
$('#quickImport').onclick=$('#importButton').onclick=openImport;$('#closeDialog').onclick=()=>$('#importDialog').close();
$('#importForm').onsubmit=async e=>{e.preventDefault();const text=$('#importText').value.trim();$('#importError').textContent='';$('#importSubmit').disabled=true;try{const result=await api(/^https:\/\//i.test(text)?'subscribe':'import',/^https:\/\//i.test(text)?{url:text}:{text});$('#importText').value='';$('#importDialog').close();await refresh();switchTab('servers');toast('Добавлено профилей: '+result.count);if(result.skipped?.length){$('#importReport').hidden=false;$('#importReport').textContent='Добавлено: '+result.count+'. Пропущено: '+result.skipped.length+'. '+result.skipped.map(x=>'Строка '+x.index+': '+x.reason).join(' ');}else{$('#importReport').hidden=true;}}catch(err){$('#importError').textContent=err.message;}finally{$('#importSubmit').disabled=false;}};
$('#search').oninput=renderServers;
function filter(on){onlyFavorites=on;$('#allFilter').classList.toggle('selected',!on);$('#favFilter').classList.toggle('selected',on);renderServers();}
$('#allFilter').onclick=()=>filter(false);$('#favFilter').onclick=()=>filter(true);
async function checkServers(){if(!state.profiles.length){openImport();return;}toast('Проверяем доступность адресов…');const result=await api('check',{});checks=Object.fromEntries(result.results.map(x=>[x.id,x]));renderServers();switchTab('servers');toast('TCP-проверка завершена. Авторизация в туннеле не проверялась.');}
$('#quickCheck').onclick=$('#checkAll').onclick=()=>action(checkServers);
$('#bestServer').onclick=()=>action(async()=>{if(state.status.running)throw Error('Сначала отключи текущий сервер.');await checkServers();const candidates=Object.values(checks).filter(x=>x.reachable).sort((a,b)=>a.tcp_ms-b.tcp_ms);if(!candidates.length)return toast('Доступные адреса не найдены.');selected=candidates[0].id;prefs.set('selected',selected);render();toast('Выбран адрес с наименьшим временем TCP.');});
$('#saveRules').onclick=()=>action(async()=>{const lines=id=>[...new Set($(id).value.split(/\n/).map(x=>x.trim().toLowerCase()).filter(Boolean))];const result=await api('rules',{direct:lines('#directRules'),block:lines('#blockRules')});await refresh();$('#rulesNotice').textContent=result.reconnect?'Правила сохранены. Переподключись, чтобы применить их.':'Правила применятся при следующем подключении.';toast('Маршруты сохранены.');});
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b||b.classList.contains('mascot-touch')||document.body.classList.contains('no-motion')||matchMedia('(prefers-reduced-motion: reduce)').matches)return;const r=b.getBoundingClientRect(),dot=document.createElement('span');dot.className='ripple';dot.style.left=(e.clientX?e.clientX-r.left:r.width/2)+'px';dot.style.top=(e.clientY?e.clientY-r.top:r.height/2)+'px';b.append(dot);setTimeout(()=>dot.remove(),650);});
if(preview){state.profiles=mockProfiles;$('#previewBadge').hidden=false;}

if(!preview)setInterval(()=>{if(!document.hidden&&!busy)refresh(true);},5000);
document.addEventListener('visibilitychange',()=>document.body.classList.toggle('paused',document.hidden));

$('#installEngine').onclick=()=>action(async()=>{const button=$('#installEngine');button.disabled=true;button.textContent='Скачиваем и проверяем…';try{const result=await api('engine/install',{});await refresh();toast('Xray '+result.version+' установлен. Можно подключаться.');}finally{button.disabled=false;button.textContent='Установить Xray';}});

$('#checkInternet').onclick=()=>action(async()=>{const result=await api('internet-check',{});await refresh();toast(result.system&&!result.system.ok?'Системный доступ не прошёл проверку. Смотри строки DNS и маршрутов.':result.ok?'Интернет через сервер работает.':result.message);});

// Local, user-triggered sounds: one voice at a time, never autoplay on tabs.
let lastPet=0;
const decodedImages=new Map();
async function readyImage(src){
 if(!decodedImages.has(src)){const img=new Image();img.decoding='async';img.src=window.MAMBO_ASSETS?.[src]||src;decodedImages.set(src,img.decode().then(()=>img));if(decodedImages.size>8)decodedImages.delete(decodedImages.keys().next().value);}
 return decodedImages.get(src);
}
function stopSound(){if(!preview)api('sound/stop',{}).catch(()=>{});}
const soundToggle=$('#soundEnabled'), volumeSlider=$('#soundVolume');
soundToggle.checked=prefs.get('soundEnabled',true);
volumeSlider.value=prefs.get('soundVolume',35);
soundToggle.onchange=()=>{prefs.set('soundEnabled',soundToggle.checked);if(!soundToggle.checked)stopSound();};
volumeSlider.oninput=()=>{prefs.set('soundVolume',Number(volumeSlider.value));};
function updateMascots(){
 const poses={servers:'cool',routes:'wrench',themes:'heart',help:'boss'};
 $$('[data-mascot]').forEach(b=>{const pose=poses[b.dataset.mascot];const src=`assets/${color}-${color==='red'?'hello':pose}.png`;b.querySelector('img').src=window.MAMBO_ASSETS?.[src]||src;});
}
async function petMascot(element,index){
 const now=Date.now();if(now-lastPet<300)return;lastPet=now;
 const pools=color==='green'?{home:['hello','heart','flip-clean3'],servers:['cool','thumb'],routes:['wrench','boss'],themes:['heart','beret','tall'],help:['boss','sad']}:color==='pink'?{home:['hello','flip-clean3'],servers:['cool','flip-clean3'],routes:['wrench','boss'],themes:['heart','hello'],help:['boss','wrench']}:{home:['hello','flip-clean3'],servers:['hello','flip-clean3'],routes:['hello','flip-clean3'],themes:['hello','flip-clean3'],help:['hello','flip-clean3']};
 const place=element.dataset.mascot||'home',poses=pools[place],n=(Number(element.dataset.poseIndex||0)+1)%poses.length;element.dataset.poseIndex=n;
 const img=element.tagName==='IMG'?element:element.querySelector('img'),src=`assets/${color}-${poses[n]}.png`,requestedColor=color;
 const request=String(now);element.dataset.imageRequest=request;
 if(soundToggle.checked&&!preview)api('sound',{index,volume:Number(volumeSlider.value)/100}).catch(e=>toast(e.message));
 try{const prepared=await readyImage(src);if(element.dataset.imageRequest===request&&color===requestedColor){img.src=prepared.src;}}
 catch{toast('Не удалось загрузить позу Мамбо.');}
 // Decode the following pose between interactions rather than on the next click.
 const next=`assets/${requestedColor}-${poses[(n+1)%poses.length]}.png`;
 setTimeout(()=>readyImage(next).catch(()=>{}),100);

}
$('#heroArt').onclick=()=>petMascot($('#heroArt'),0);
$('#heroArt').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();petMascot($('#heroArt'),0);}};
$$('[data-mascot]').forEach((b,i)=>b.onclick=()=>petMascot(b,i+1));
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopSound();});

applyTheme();nextQuote();refresh();
setTimeout(()=>readyImage(`assets/${color}-flip-clean3.png`).catch(()=>{}),700);

// Repair the old saved combination that hid the entire companion card.
if(document.body.classList.contains('no-art')&&!prefs.get('quotePrefsV2',false)){$('#quotesEnabled').checked=true;prefs.set('quotesEnabled',true);document.body.classList.remove('no-quotes');}prefs.set('quotePrefsV2',true);
