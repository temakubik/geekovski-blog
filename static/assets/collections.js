(() => {
  const listing = document.querySelector('[data-collection]');
  if (!listing) return;

  const mode = listing.dataset.collection;
  const items = [...listing.querySelectorAll('[data-collection-item]')];
  const controls = listing.querySelector('[data-collection-controls]');
  const count = listing.querySelector('[data-collection-count]');
  const empty = listing.querySelector('[data-collection-empty]');
  const filters = {};
  const plural = new Intl.PluralRules('ru-RU');
  const words = {
    calendar: {one: 'релиз', few: 'релиза', many: 'релизов'},
    digests: {one: 'выпуск', few: 'выпуска', many: 'выпусков'},
    catalog: {one: 'карточка', few: 'карточки', many: 'карточек'}
  };
  const normalize = value => value.toLocaleLowerCase('ru').replaceAll('ё', 'е').trim();
  let query = '';
  let requestedDate = '';

  if (mode === 'calendar') {
    filters.period = items.some(item => item.dataset.period === 'week') ? 'week' : 'later';
  }
  if (mode === 'digests') {
    const day = new URLSearchParams(window.location.search).get('date');
    if (items.some(item => item.dataset.date === day)) requestedDate = day;
    if (requestedDate) {
      filters.month = requestedDate.slice(0, 7);
      controls.querySelector('[data-filter="month"]').value = filters.month;
    }
  }

  function render() {
    let visible = 0;
    for (const item of items) {
      const matchesFilters = Object.entries(filters)
        .every(([key, value]) => !value || item.dataset[key] === value);
      const matchesQuery = !query || normalize(item.dataset.search || '').includes(query);
      const matchesDate = !requestedDate || item.dataset.date === requestedDate;
      item.hidden = !(matchesFilters && matchesQuery && matchesDate);
      if (!item.hidden) visible++;
    }
    empty.hidden = visible > 0;
    count.textContent = `${visible} ${words[mode][plural.select(visible)] || words[mode].many}`;
    for (const button of controls.querySelectorAll('[data-filter-value]')) {
      const group = button.closest('[data-filter]').dataset.filter;
      button.setAttribute('aria-pressed', String(button.dataset.filterValue === (filters[group] || '')));
    }
  }

  controls.addEventListener('click', event => {
    const button = event.target.closest('[data-filter-value]');
    if (!button) return;
    const name = button.closest('[data-filter]').dataset.filter;
    filters[name] = button.dataset.filterValue;
    if (mode === 'digests') requestedDate = '';
    render();
  });
  controls.addEventListener('change', event => {
    if (!event.target.matches('select[data-filter]')) return;
    filters[event.target.dataset.filter] = event.target.value;
    requestedDate = '';
    render();
  });
  controls.addEventListener('input', event => {
    if (!event.target.matches('[data-collection-search]')) return;
    query = normalize(event.target.value);
    render();
  });

  render();
  controls.hidden = false;
})();
