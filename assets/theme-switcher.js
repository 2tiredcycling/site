(function () {
  var STORAGE_KEY = 'site_theme';
  var DEFAULT_THEME = 'theme-1';
  var THEMES = [
    { value: 'theme-1', label: '森林绿' },
    { value: 'theme-2', label: '夜幕紫' },
    { value: 'theme-3', label: '霞影蓝' },
    { value: 'theme-4', label: '冷雾灰蓝' },
    { value: 'theme-5', label: '湖湾青' },
    { value: 'theme-6', label: '晴空蓝' },
    { value: 'theme-7', label: '马卡龙粉' },
    { value: 'theme-8', label: '暖夜紫灰' }
  ];
  var HOME_HERO_COVERS = {
    'theme-1': 'assets/hero-covers/home/forest.jpg',
    'theme-2': 'assets/hero-covers/home/night.jpg',
    'theme-3': 'assets/hero-covers/home/haze.jpg',
    'theme-4': 'assets/hero-covers/home/mist.jpg',
    'theme-5': 'assets/hero-covers/home/lake.jpg',
    'theme-6': 'assets/hero-covers/home/sky.jpg',
    'theme-7': 'assets/hero-covers/home/pink.jpg',
    'theme-8': 'assets/hero-covers/home/warm.jpg'
  };
  var ABOUT_HERO_COVERS = {
    'theme-1': 'assets/hero-covers/about/forest.jpg',
    'theme-2': 'assets/hero-covers/about/night.jpg',
    'theme-3': 'assets/hero-covers/about/haze.jpg',
    'theme-4': 'assets/hero-covers/about/mist.jpg',
    'theme-5': 'assets/hero-covers/about/lake.jpg',
    'theme-6': 'assets/hero-covers/about/sky.jpg',
    'theme-7': 'assets/hero-covers/about/pink.jpg',
    'theme-8': 'assets/hero-covers/about/warm.jpg'
  };
  function safeGetTheme(){try{var s=localStorage.getItem(STORAGE_KEY);if(s&&THEMES.some(function(i){return i.value===s;})){return s;}}catch(e){}return DEFAULT_THEME;}
  function saveTheme(t){try{localStorage.setItem(STORAGE_KEY,t);}catch(e){}}
  function resolveCoverUrl(cover){return new URL(cover, document.baseURI).href;}
  function applySingleCoverVar(name,cover){var root=document.documentElement;if(!cover){root.style.setProperty(name,'none');return;}var resolved=resolveCoverUrl(cover);var img=new Image();img.onload=function(){root.style.setProperty(name,"url('"+resolved+"')");};img.onerror=function(){root.style.setProperty(name,'none');};img.src=resolved;}
  function applyTheme(t){var root=document.documentElement;root.setAttribute('data-theme',t);applySingleCoverVar('--hero-cover-image-home',HOME_HERO_COVERS[t]);applySingleCoverVar('--hero-cover-image-about',ABOUT_HERO_COVERS[t]);}
  function bindThemeEntry(){var triggers=document.querySelectorAll('.theme-entry-link');if(!triggers.length)return;var panel=document.createElement('div');panel.className='theme-quick-panel';panel.setAttribute('aria-hidden','true');var title=document.createElement('div');title.className='theme-quick-title';title.textContent='选择主题';panel.appendChild(title);var list=document.createElement('div');list.className='theme-quick-list';var active=safeGetTheme();THEMES.forEach(function(item){var btn=document.createElement('button');btn.type='button';btn.className='theme-quick-item'+(item.value===active?' is-active':'');btn.setAttribute('data-theme',item.value);btn.textContent=item.label;btn.addEventListener('click',function(){var next=btn.getAttribute('data-theme');applyTheme(next);saveTheme(next);list.querySelectorAll('.theme-quick-item').forEach(function(n){n.classList.remove('is-active');});btn.classList.add('is-active');});list.appendChild(btn);});panel.appendChild(list);document.body.appendChild(panel);function closePanel(){panel.classList.remove('is-open');panel.setAttribute('aria-hidden','true');}triggers.forEach(function(trigger){trigger.addEventListener('click',function(e){e.preventDefault();if(panel.classList.contains('is-open')){closePanel();}else{panel.classList.add('is-open');panel.setAttribute('aria-hidden','false');}});});document.addEventListener('click',function(e){var target=e.target;if(!panel.contains(target)&&!Array.prototype.some.call(triggers,function(n){return n.contains(target);})){closePanel();}});}
  var initial=safeGetTheme();applyTheme(initial);if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',bindThemeEntry);}else{bindThemeEntry();}
})();
