(function () {
  var STORAGE_KEY = 'site_theme';
  var DEFAULT_THEME = 'theme-6';
  var THEMES = [
    { value: 'theme-1', label: '1 森林绿' },
    { value: 'theme-2', label: '2 紫粉渐变' },
    { value: 'theme-3', label: '3 粉紫蓝渐变' },
    { value: 'theme-4', label: '4 冷灰蓝' },
    { value: 'theme-5', label: '5 湖蓝青' },
    { value: 'theme-6', label: '6 浅蓝渐变' },
    { value: 'theme-7', label: '7 马卡龙粉绿' },
    { value: 'theme-8', label: '8 暖紫灰' }
  ];

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
