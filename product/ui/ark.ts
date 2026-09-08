// Copyright 2026 Arkapravo Ghosh
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {PageHandler} from './ark.mojom-webui.js';

function get<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`Missing Ark element: ${id}`);
  }
  return element as T;
}

const routes = ['home', 'chat', 'models', 'advanced', 'about'] as const;
type Route = typeof routes[number];
const draft = get<HTMLTextAreaElement>('draft');
const clearButton = get<HTMLButtonElement>('clear-draft');
const dialog = get<HTMLDialogElement>('clear-dialog');
const theme = get<HTMLSelectElement>('theme');
const themeKey = 'ark.preview.theme.v1';
let currentRoute: Route = 'home';
let newChatPending = false;
let conversationId = '';
let draftSaveTimer = 0;
let aiSearchMode = false;
const isSidePanel = location.host === 'ark-side-panel';

if (isSidePanel) {
  document.documentElement.classList.add('side-panel-surface');
}

function readSession(key: string): string {
  try {
    return sessionStorage.getItem(key) || '';
  } catch {
    return '';
  }
}

function saveDraft(): void {
  clearButton.disabled = !draft.value;
  window.clearTimeout(draftSaveTimer);
  if (!conversationId) {
    return;
  }
  draftSaveTimer = window.setTimeout(async () => {
    try {
      const {success} = await PageHandler.getRemote().saveDraft(
          conversationId, draft.value);
      if (!success) {
        throw new Error('Draft was not stored');
      }
    } catch {
      get('draft-status').textContent = 'Ark could not save this draft locally.';
    }
  }, 180);
}

draft.addEventListener('input', saveDraft);

async function loadChatState(): Promise<void> {
  try {
    const {state} = await PageHandler.getRemote().getChatState();
    if (!state.id) {
      throw new Error('Conversation storage unavailable');
    }
    conversationId = state.id;
    document.documentElement.dataset['storageReady'] = 'true';
    if (document.activeElement !== draft) {
      draft.value = state.draft.slice(0, 32000);
      clearButton.disabled = !draft.value;
    }
  } catch {
    get('draft-status').textContent =
        'Local conversation storage is unavailable for this profile.';
  }
}
void loadChatState();
window.addEventListener('focus', () => void loadChatState());
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    void loadChatState();
  }
});

const visitedKey = 'ark.has_opened';
let hasOpened = false;
try {
  hasOpened = Boolean(localStorage.getItem(visitedKey));
  if (!hasOpened) {
    localStorage.setItem(visitedKey, 'true');
  }
} catch {
  // Local storage unavailable in private or restricted contexts.
}

if (hasOpened) {
  const eyebrow = document.getElementById('home-eyebrow');
  const title = document.getElementById('home-title');
  const tagline = document.getElementById('home-tagline');
  if (eyebrow && title && tagline) {
    eyebrow.textContent = 'A FRESH START';
    title.textContent = 'Where to next';
    const accent = document.createElement('span');
    accent.className = 'accent';
    accent.textContent = '?';
    title.append(accent);
    tagline.textContent = 'Follow a thought. Find something good.';
  }
}

function renderRoute(focus: boolean): void {
  const requested = location.hash.slice(1) || 'home';
  currentRoute = routes.includes(requested as Route) ? requested as Route : 'home';
  for (const route of routes) {
    get(`${route}-page`).hidden = route !== currentRoute;
  }
  document.querySelectorAll<HTMLAnchorElement>('[data-route]').forEach(link => {
    if (link.dataset['route'] === currentRoute) {
      link.setAttribute('aria-current', 'page');
    } else {
      link.removeAttribute('aria-current');
    }
  });
  const composer = get('composer');
  composer.hidden = currentRoute !== 'chat';
  if (!composer.hidden) {
    get('chat-composer-slot').append(composer);
  }
  get('breadcrumb').textContent = currentRoute === 'home' ?
      'Your everyday, with more possibility.' :
      `Your workspace / ${currentRoute === 'advanced' ? 'Advanced options' :
          currentRoute.charAt(0).toUpperCase() + currentRoute.slice(1)}`;
  document.title = currentRoute === 'home' ? 'New Tab — Ark Browser' :
      `${currentRoute === 'advanced' ? 'Advanced options' :
          currentRoute.charAt(0).toUpperCase() + currentRoute.slice(1)} — Ark Browser`;
  if (focus) {
    get('main').focus();
    window.scrollTo(0, 0);
  }
}
window.addEventListener('hashchange', () => renderRoute(true));
if (isSidePanel && location.hash !== '#chat') {
  location.hash = 'chat';
} else {
  renderRoute(false);
}

get('new-chat').addEventListener('click', async () => {
  if (draft.value) {
    newChatPending = true;
    dialog.showModal();
  } else {
    try {
      const {state} = await PageHandler.getRemote().createConversation();
      conversationId = state.id;
      draft.value = state.draft;
    } catch {
      get('draft-status').textContent = 'Ark could not create a conversation.';
    }
    location.hash = 'chat';
    draft.focus();
  }
});
clearButton.addEventListener('click', () => {
  newChatPending = false;
  dialog.showModal();
});
dialog.addEventListener('close', () => {
  if (dialog.returnValue === 'clear') {
    draft.value = '';
    saveDraft();
    get('draft-status').textContent = 'Draft cleared.';
    if (newChatPending) {
      void PageHandler.getRemote().createConversation().then(({state}) => {
        conversationId = state.id;
      });
      location.hash = 'chat';
    }
  }
  newChatPending = false;
  draft.focus();
});
// Escape must not reuse a previous affirmative dialog result.
dialog.addEventListener('cancel', () => { dialog.returnValue = 'cancel'; });

document.querySelectorAll<HTMLButtonElement>('[data-prompt]').forEach(button => {
  button.addEventListener('click', () => {
    if (draft.value) {
      get('draft-status').textContent =
          'Your draft is already started. Clear it to use a suggestion.';
    } else {
      draft.value = button.dataset['prompt'] || '';
      saveDraft();
      get('draft-status').textContent = 'Suggestion added to your draft. Nothing was sent.';
    }
    draft.focus();
    draft.setSelectionRange(draft.value.length, draft.value.length);
  });
});

const savedTheme = readSession(themeKey);
if (['system', 'light', 'dark'].includes(savedTheme)) {
  theme.value = savedTheme;
}
function applyTheme(): void {
  if (theme.value === 'system') {
    delete document.documentElement.dataset['theme'];
  } else {
    document.documentElement.dataset['theme'] = theme.value;
  }
}
applyTheme();
theme.addEventListener('change', () => {
  applyTheme();
  try {
    sessionStorage.setItem(themeKey, theme.value);
  } catch {
    // Appearance still works when tab-session storage is unavailable.
  }
});

const searchInput = get<HTMLInputElement>('search-input');
const searchForm = get<HTMLFormElement>('search-form');
const searchBoxWrapper = get<HTMLDivElement>('search-box-wrapper');
const searchSuggestions = get<HTMLDivElement>('search-suggestions');

let suggestionsList: string[] = [];
let selectedSuggestionIndex = -1;
let originalUserQuery = '';
let suggestDebounceTimer = 0;

function hideSuggestions(): void {
  searchSuggestions.hidden = true;
  searchSuggestions.replaceChildren();
  searchBoxWrapper.classList.remove('has-suggestions');
  selectedSuggestionIndex = -1;
}

function selectSuggestion(index: number): void {
  const items = searchSuggestions.querySelectorAll<HTMLButtonElement>('.suggestion-item');
  items.forEach((item, i) => {
    const isSelected = i === index;
    item.classList.toggle('active', isSelected);
    item.setAttribute('aria-selected', String(isSelected));
  });
  selectedSuggestionIndex = index;
  if (index >= 0 && index < suggestionsList.length) {
    searchInput.value = suggestionsList[index]!;
  } else {
    searchInput.value = originalUserQuery;
  }
}

function submitSearch(query: string): void {
  searchInput.value = query;
  hideSuggestions();
  searchForm.requestSubmit();
}

function renderSuggestions(query: string, suggestions: string[]): void {
  suggestionsList = suggestions;
  selectedSuggestionIndex = -1;
  searchSuggestions.replaceChildren();

  if (suggestions.length === 0 || aiSearchMode) {
    hideSuggestions();
    return;
  }

  const queryLower = query.toLowerCase();
  for (let i = 0; i < suggestions.length; i++) {
    const text = suggestions[i]!;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'suggestion-item';
    btn.setAttribute('role', 'option');
    btn.setAttribute('aria-selected', 'false');

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'mat-icon suggestion-icon');
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', '#mat-search');
    svg.appendChild(use);

    const textSpan = document.createElement('span');
    textSpan.className = 'suggestion-text';

    if (text.toLowerCase().startsWith(queryLower)) {
      const matchSpan = document.createElement('span');
      matchSpan.className = 'suggestion-match';
      matchSpan.textContent = text.slice(0, query.length);
      const rest = document.createTextNode(text.slice(query.length));
      textSpan.append(matchSpan, rest);
    } else {
      textSpan.textContent = text;
    }

    btn.append(svg, textSpan);

    btn.addEventListener('mouseenter', () => {
      selectSuggestion(i);
    });

    btn.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      submitSearch(text);
    });

    searchSuggestions.appendChild(btn);
  }

  searchSuggestions.hidden = false;
  searchBoxWrapper.classList.add('has-suggestions');
}

function fetchSuggestions(query: string): void {
  window.clearTimeout(suggestDebounceTimer);
  const trimmed = query.trim();
  if (aiSearchMode || !trimmed) {
    hideSuggestions();
    return;
  }
  suggestDebounceTimer = window.setTimeout(async () => {
    const currentInput = searchInput.value.trim();
    if (aiSearchMode || !currentInput) {
      hideSuggestions();
      return;
    }
    try {
      const {suggestions} = await PageHandler.getRemote().getSearchSuggestions(currentInput);
      if (searchInput.value.trim().toLowerCase() === currentInput.toLowerCase()) {
        renderSuggestions(currentInput, suggestions);
      }
    } catch (err) {
      console.error('Failed to fetch search suggestions:', err);
      hideSuggestions();
    }
  }, 100);
}

searchInput.addEventListener('input', () => {
  originalUserQuery = searchInput.value;
  selectedSuggestionIndex = -1;
  fetchSuggestions(searchInput.value);
});

searchInput.addEventListener('focus', () => {
  if (!aiSearchMode && searchInput.value.trim()) {
    fetchSuggestions(searchInput.value);
  }
});

searchInput.addEventListener('keydown', (e: KeyboardEvent) => {
  if (e.key === 'ArrowDown') {
    if (searchSuggestions.hidden) {
      if (suggestionsList.length > 0) {
        searchSuggestions.hidden = false;
        searchBoxWrapper.classList.add('has-suggestions');
      } else {
        return;
      }
    }
    e.preventDefault();
    const next = selectedSuggestionIndex < suggestionsList.length - 1 ?
        selectedSuggestionIndex + 1 : -1;
    selectSuggestion(next);
  } else if (e.key === 'ArrowUp') {
    if (searchSuggestions.hidden) {
      return;
    }
    e.preventDefault();
    const prev = selectedSuggestionIndex === -1 ?
        suggestionsList.length - 1 : selectedSuggestionIndex - 1;
    selectSuggestion(prev);
  } else if (e.key === 'Escape') {
    if (!searchSuggestions.hidden) {
      e.preventDefault();
      searchInput.value = originalUserQuery;
      hideSuggestions();
    }
  }
});

document.addEventListener('pointerdown', (e: PointerEvent) => {
  if (!searchBoxWrapper.contains(e.target as Node)) {
    hideSuggestions();
  }
});

function setSearchMode(ai: boolean): void {
  aiSearchMode = ai;
  hideSuggestions();
  get('web-mode').setAttribute('aria-pressed', String(!ai));
  get('ai-mode').setAttribute('aria-pressed', String(ai));
  searchInput.placeholder = ai ? 'Ask Ark anything' : 'Search the web or enter an address';
  searchInput.setAttribute('aria-label', ai ? 'Ask Ark AI' : 'Search the web or enter an address');
  searchInput.focus();
}
get('web-mode').addEventListener('click', () => setSearchMode(false));
get('ai-mode').addEventListener('click', () => setSearchMode(true));

searchForm.addEventListener('submit', async event => {
  event.preventDefault();
  const query = searchInput.value.trim();
  hideSuggestions();
  if (!query) {
    return;
  }
  get('search-status').textContent = '';
  try {
    if (aiSearchMode) {
      const {success} = await PageHandler.getRemote().openSidebarWithDraft(query);
      if (!success) {
        throw new Error('Sidebar could not be opened');
      }
      get('search-status').textContent = 'Opened in Ark AI.';
      return;
    }
    const {success} = await PageHandler.getRemote().navigate(query);
    if (!success) {
      throw new Error('Navigation rejected');
    }
  } catch {
    get('search-status').textContent =
        'This address could not be opened. Try the browser’s address bar.';
  }
});

function setModelTab(local: boolean): void {
  get('local-models').hidden = !local;
  get('cloud-models').hidden = local;
  get('local-tab').setAttribute('aria-pressed', String(local));
  get('cloud-tab').setAttribute('aria-pressed', String(!local));
}
get('local-tab').addEventListener('click', () => setModelTab(true));
get('cloud-tab').addEventListener('click', () => setModelTab(false));

function textElement<K extends keyof HTMLElementTagNameMap>(
    tag: K, text: string, className = ''): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  element.textContent = text;
  element.className = className;
  return element;
}

const providers = [
  ['OpenAI', 'Connect with your own API key and choose a model.'],
  ['Anthropic', 'Use Claude through your own Anthropic connection.'],
  ['Amazon Bedrock', 'Choose an AWS region, credential source, and model.'],
  ['Together AI', 'Connect to models hosted by Together AI.'],
  ['Custom endpoint', 'Bring an OpenAI-compatible endpoint and model identifier.'],
];
for (const [name, description] of providers) {
  const card = document.createElement('article');
  card.className = 'provider-card';
  const title = document.createElement('div');
  title.className = 'provider-title';
  title.append(textElement('h3', name!), textElement('span', 'Coming soon', 'tag'));
  card.append(title, textElement('p', description!));
  get('provider-grid').append(card);
}

const parameterGroups: Array<[string, Array<[string, string]>]> = [
  ['Generation', [
    ['Temperature', 'Controls randomness. Lower values tend to give more consistent answers; higher values allow more variety.'],
    ['Top P', 'Limits choices to tokens covering a probability mass. Lower values narrow the choices.'],
    ['Top K', 'Limits each next-token choice to the K most likely tokens, where supported.'],
    ['Maximum output tokens', 'Caps the tokens generated for one response. Reasoning may share this budget, depending on the model.'],
    ['Repetition penalty', 'Discourages repeating tokens that already appeared. The scale depends on the runtime.'],
    ['Frequency penalty', 'Discourages tokens in proportion to how often they have appeared.'],
    ['Presence penalty', 'Discourages reusing tokens that have already appeared.'],
    ['Stop sequences', 'Ends generation when one of the chosen text sequences is produced.'],
    ['Seed', 'Requests repeatable sampling when supported. Results can still vary across hardware and model versions.'],
    ['Reasoning effort / budget', 'Adjusts how much work a supported reasoning model spends before answering. This can affect latency and usage.'],
  ]],
  ['Instructions', [
    ['System instructions', 'Sets the assistant’s preferred behavior. Does not grant browser permissions or change context rules.'],
  ]],
  ['Connection', [
    ['Request timeout', 'Sets how long Ark waits before ending an unresponsive request.'],
  ]],
  ['Local performance · local models only', [
    ['Context window', 'Sets how much text a local model can hold while generating an answer. Larger values use more memory. Cloud limits are usually read-only.'],
    ['GPU offload', 'Moves supported parts of a local model to the GPU, using GPU memory.'],
    ['CPU threads', 'Sets how many CPU threads local inference can use.'],
    ['Batch size', 'Controls how many input tokens a local model processes together. Larger batches can use more memory.'],
    ['Idle unload delay', 'Releases an unused local model from memory. Never unloads during generation.'],
  ]],
];
for (const [name, parameters] of parameterGroups) {
  const section = document.createElement('section');
  section.className = 'parameter-section';
  section.append(textElement('h2', name));
  for (const [label, description] of parameters) {
    const row = document.createElement('div');
    row.className = 'parameter-row';
    row.append(textElement('h3', label), textElement('p', description));
    section.append(row);
  }
  get('parameter-groups').append(section);
}
