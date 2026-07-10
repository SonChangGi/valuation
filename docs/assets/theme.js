(() => {
  'use strict';

  const STORAGE_KEY = 'valuation-theme';
  const root = document.documentElement;

  function storedTheme() {
    try {
      return window.localStorage?.getItem(STORAGE_KEY);
    } catch (error) {
      return null;
    }
  }

  function saveTheme(theme) {
    try {
      window.localStorage?.setItem(STORAGE_KEY, theme);
    } catch (error) {
      // Theme persistence is optional.
    }
  }

  function currentTheme() {
    return root.dataset.theme === 'dark' ? 'dark' : 'light';
  }

  function applyTheme(theme) {
    const normalized = theme === 'dark' ? 'dark' : 'light';
    root.dataset.theme = normalized;
    const button = document.querySelector('#theme-toggle');
    if (!button) return;
    const isDark = normalized === 'dark';
    button.setAttribute('aria-pressed', String(isDark));
    button.setAttribute('aria-label', isDark ? '라이트 모드로 전환' : '다크 모드로 전환');
    const label = button.querySelector('.theme-toggle-text');
    if (label) label.textContent = isDark ? '라이트 모드' : '다크 모드';
  }

  function bindThemeToggle() {
    applyTheme(storedTheme() || currentTheme());
    const button = document.querySelector('#theme-toggle');
    if (!button) return;
    button.addEventListener('click', () => {
      const nextTheme = currentTheme() === 'dark' ? 'light' : 'dark';
      applyTheme(nextTheme);
      saveTheme(nextTheme);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindThemeToggle, { once: true });
  } else {
    bindThemeToggle();
  }
})();
