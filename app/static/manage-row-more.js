(function () {
  const menuSelector = "details.manage-row-more";

  function closeMenus(except) {
    document.querySelectorAll(`${menuSelector}[open]`).forEach((menu) => {
      if (menu !== except) {
        menu.removeAttribute("open");
      }
    });
  }

  document.addEventListener("toggle", (event) => {
    const menu = event.target;
    if (menu.matches && menu.matches(menuSelector) && menu.open) {
      closeMenus(menu);
    }
  }, true);

  document.addEventListener("click", (event) => {
    const currentMenu = event.target.closest(menuSelector);
    if (!currentMenu) {
      closeMenus();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMenus();
    }
  });
})();
