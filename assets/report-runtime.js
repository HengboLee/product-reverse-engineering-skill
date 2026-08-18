(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const profile = document.body.dataset.reportProfile || 'report';
  const toast = $('[data-toast]');

  function notify(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add('is-visible');
    clearTimeout(notify.timer);
    notify.timer = setTimeout(() => toast.classList.remove('is-visible'), 1800);
  }

  async function copyText(target) {
    const element = document.getElementById(target);
    if (!element) return false;
    const text = element.innerText || element.textContent || '';
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      const range = document.createRange();
      range.selectNodeContents(element);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      const copied = document.execCommand('copy');
      selection.removeAllRanges();
      return copied;
    }
  }

  $$('[data-copy-target]').forEach((button) => {
    const original = button.textContent;
    button.addEventListener('click', async () => {
      const copied = await copyText(button.dataset.copyTarget);
      button.textContent = copied ? '已复制' : '复制失败';
      notify(copied ? '内容已复制到剪贴板' : '浏览器未授权剪贴板，请手动复制');
      setTimeout(() => { button.textContent = original; }, 1500);
    });
  });

  const navLinks = $$('.page-nav a[href^="#"]');
  const sections = navLinks
    .map((link) => $(link.getAttribute('href')))
    .filter(Boolean);
  if (sections.length && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (!visible) return;
      navLinks.forEach((link) => {
        const active = link.getAttribute('href') === `#${visible.target.id}`;
        link.classList.toggle('is-active', active);
        if (active) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
      });
    }, { rootMargin: '-18% 0px -72% 0px', threshold: 0 });
    sections.forEach((section) => observer.observe(section));
  }

  const filterGroups = new Set($$('[data-filter-group]').map((button) => button.dataset.filterGroup));
  filterGroups.forEach((group) => {
    const buttons = $$(`[data-filter-group="${group}"]`);
    const targets = $$(`[data-filter-item="${group}"]`);
    buttons.forEach((button) => button.addEventListener('click', () => {
      buttons.forEach((item) => item.classList.remove('is-active'));
      button.classList.add('is-active');
      const filter = button.dataset.filter || 'all';
      targets.forEach((target) => {
        const levels = (target.dataset.level || '').split(/\s+/).filter(Boolean);
        target.classList.toggle('is-hidden', filter !== 'all' && !levels.includes(filter));
      });
    }));
  });

  const search = $('[data-contract-search]');
  const contractCards = $$('[data-contract-card]');
  function applyContractSearch() {
    if (!search) return;
    const query = search.value.trim().toLocaleLowerCase('zh-CN');
    contractCards.forEach((card) => {
      const haystack = `${card.dataset.keywords || ''} ${card.textContent}`.toLocaleLowerCase('zh-CN');
      card.classList.toggle('is-hidden', query && !haystack.includes(query));
    });
  }
  if (search) search.addEventListener('input', applyContractSearch);

  $('[data-contract-open-all]')?.addEventListener('click', () => {
    contractCards.filter((card) => !card.classList.contains('is-hidden')).forEach((card) => { card.open = true; });
  });
  $('[data-contract-close-all]')?.addEventListener('click', () => {
    contractCards.forEach((card) => { card.open = false; });
  });

  const noteFields = $$('[data-note-field]');
  const storagePrefix = `productReverseEngineering.${profile}.`;
  noteFields.forEach((field) => {
    field.value = localStorage.getItem(storagePrefix + field.dataset.noteField) || '';
  });

  $('[data-notes-save]')?.addEventListener('click', () => {
    noteFields.forEach((field) => localStorage.setItem(storagePrefix + field.dataset.noteField, field.value));
    notify('补充内容已保存在当前浏览器');
  });

  $('[data-notes-clear]')?.addEventListener('click', () => {
    noteFields.forEach((field) => {
      localStorage.removeItem(storagePrefix + field.dataset.noteField);
      field.value = '';
    });
    notify('本地补充已清空');
  });

  $('[data-notes-export]')?.addEventListener('click', () => {
    const payload = {
      report: document.title,
      profile,
      exported_at: new Date().toISOString(),
      notes: Object.fromEntries(noteFields.map((field) => [field.dataset.noteField, field.value]))
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${profile}-notes.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 0);
    notify('补充内容已导出');
  });

  const unresolved = $$('*').filter((element) => {
    if (['SCRIPT', 'STYLE'].includes(element.tagName)) return false;
    return element.children.length === 0 && /\{\{[A-Z0-9_]+\}\}/.test(element.textContent || '');
  });
  if (unresolved.length) {
    console.warn(`报告仍有 ${unresolved.length} 个未替换占位符。`);
  }
})();
