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
  var HERO_COVERS = {
    'theme-1': '/static/hero-covers/forest-green.jpg',
    'theme-2': '/static/hero-covers/night-purple.jpg',
    'theme-3': '/static/hero-covers/haze-blue.jpg',
    'theme-4': '/static/hero-covers/mist-gray-blue.jpg',
    'theme-5': '/static/hero-covers/lake-cyan.jpg',
    'theme-6': '/static/hero-covers/sky-blue.jpg',
    'theme-7': '/static/hero-covers/macaron-pink.jpg',
    'theme-8': '/static/hero-covers/warm-night-purple-gray.jpg'
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
    var root = document.documentElement;
    var cover = HERO_COVERS[theme];
    if (!cover) {
      root.style.setProperty('--hero-cover-image', 'none');
      return;
    }
    var img = new Image();
    img.onload = function () {
      root.style.setProperty('--hero-cover-image', "url('" + cover + "')");
    };
    img.onerror = function () {
      // Missing image should gracefully fall back to default gradient style.
      root.style.setProperty('--hero-cover-image', 'none');
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

  var initial = safeGetTheme();
  applyTheme(initial);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      buildSwitcher(initial);
    });
  } else {
    buildSwitcher(initial);
  }
})();
