(function () {
  var STORAGE_KEY = 'site_theme';
  var DEFAULT_THEME = 'theme-1';
  var SHOW_SWITCHER = false;
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
    'theme-1': '/static/hero-covers/home/forest.jpg',
    'theme-2': '/static/hero-covers/home/night.jpg',
    'theme-3': '/static/hero-covers/home/haze.jpg',
    'theme-4': '/static/hero-covers/home/mist.jpg',
    'theme-5': '/static/hero-covers/home/lake.jpg',
    'theme-6': '/static/hero-covers/home/sky.jpg',
    'theme-7': '/static/hero-covers/home/pink.jpg',
    'theme-8': '/static/hero-covers/home/warm.jpg'
  };
  var ABOUT_HERO_COVERS = {
    'theme-1': '/static/hero-covers/about/forest.jpg',
    'theme-2': '/static/hero-covers/about/night.jpg',
    'theme-3': '/static/hero-covers/about/haze.jpg',
    'theme-4': '/static/hero-covers/about/mist.jpg',
    'theme-5': '/static/hero-covers/about/lake.jpg',
    'theme-6': '/static/hero-covers/about/sky.jpg',
    'theme-7': '/static/hero-covers/about/pink.jpg',
    'theme-8': '/static/hero-covers/about/warm.jpg'
  };

  function safeGetTheme() {
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved && THEMES.some(function (item) { return item.value === saved; })) {
        return saved;
      }
    } catch (e) {
      return DEFAULT_THEME;
    }
    return DEFAULT_THEME;
  }

  function applyTheme(theme) {
    var root = document.documentElement;
    root.setAttribute('data-theme', theme);
    applyHeroCover(theme);
  }

  function applyHeroCover(theme) {
    applySingleCoverVar(
      '--hero-cover-image-home',
      HOME_HERO_COVERS[theme]
    );
    applySingleCoverVar(
      '--hero-cover-image-about',
      ABOUT_HERO_COVERS[theme]
    );
  }

  function applySingleCoverVar(cssVarName, cover) {
    var root = document.documentElement;
    if (!cover) {
      root.style.setProperty(cssVarName, 'none');
      return;
    }
    var img = new Image();
    img.onload = function () {
      root.style.setProperty(cssVarName, "url('" + cover + "')");
    };
    img.onerror = function () {
      root.style.setProperty(cssVarName, 'none');
    };
    img.src = cover;
  }

  function saveTheme(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      // ignore storage failures
    }
  }

  function buildSwitcher(activeTheme) {
    if (document.querySelector('.theme-switcher')) {
      return;
    }
    var box = document.createElement('div');
    box.className = 'theme-switcher';

    var label = document.createElement('label');
    label.setAttribute('for', 'theme-switcher-select');
    label.textContent = '主题配色';

    var select = document.createElement('select');
    select.id = 'theme-switcher-select';
    select.setAttribute('aria-label', '主题配色切换');

    THEMES.forEach(function (item) {
      var option = document.createElement('option');
      option.value = item.value;
      option.textContent = item.label;
      if (item.value === activeTheme) {
        option.selected = true;
      }
      select.appendChild(option);
    });

    select.addEventListener('change', function () {
      var next = select.value;
      applyTheme(next);
      saveTheme(next);
    });

    box.appendChild(label);
    box.appendChild(select);
    document.body.appendChild(box);
  }

  function buildQuickThemePanel(activeTheme) {
    if (document.querySelector('.theme-quick-panel')) {
      return;
    }
    var panel = document.createElement('div');
    panel.className = 'theme-quick-panel';
    panel.setAttribute('aria-hidden', 'true');

    var title = document.createElement('div');
    title.className = 'theme-quick-title';
    title.textContent = '选择主题';
    panel.appendChild(title);

    var list = document.createElement('div');
    list.className = 'theme-quick-list';
    THEMES.forEach(function (item) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'theme-quick-item' + (item.value === activeTheme ? ' is-active' : '');
      btn.setAttribute('data-theme', item.value);
      btn.textContent = item.label;
      btn.addEventListener('click', function () {
        var next = btn.getAttribute('data-theme');
        applyTheme(next);
        saveTheme(next);
        list.querySelectorAll('.theme-quick-item').forEach(function (node) {
          node.classList.remove('is-active');
        });
        btn.classList.add('is-active');
      });
      list.appendChild(btn);
    });
    panel.appendChild(list);
    document.body.appendChild(panel);
  }

  function bindThemeEntry() {
    var triggers = document.querySelectorAll('.theme-entry-link');
    if (!triggers.length) {
      return;
    }
    buildQuickThemePanel(safeGetTheme());
    var panel = document.querySelector('.theme-quick-panel');
    if (!panel) {
      return;
    }

    function openPanel() {
      panel.classList.add('is-open');
      panel.setAttribute('aria-hidden', 'false');
    }
    function closePanel() {
      panel.classList.remove('is-open');
      panel.setAttribute('aria-hidden', 'true');
    }

    triggers.forEach(function (trigger) {
      trigger.addEventListener('click', function (event) {
        event.preventDefault();
        if (panel.classList.contains('is-open')) {
          closePanel();
        } else {
          openPanel();
        }
      });
    });

    document.addEventListener('click', function (event) {
      var target = event.target;
      if (!panel.contains(target) && !Array.prototype.some.call(triggers, function (node) { return node.contains(target); })) {
        closePanel();
      }
    });
  }

  var initial = safeGetTheme();
  applyTheme(initial);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      bindThemeEntry();
    });
  } else {
    bindThemeEntry();
  }
  if (!SHOW_SWITCHER) {
    return;
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      buildSwitcher(initial);
    });
  } else {
    buildSwitcher(initial);
  }
})();
