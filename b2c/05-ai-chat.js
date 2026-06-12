/* AdaptaAI — 05-ai-chat.js
 * Chat wiring: POST /api/v1/chat/messages (SSE streaming)
 * Reads JWT from localStorage.adapta_jwt, lang from localStorage.adapta_lang.
 * Accepts voice text from 06-ai-listening.html via sessionStorage.adapta_voice_text.
 *
 * WS-G: server history fetch + 7-second poll so HR replies are visible to the migrant.
 * GET /api/v1/me/chat/history → {items:[{role,text,created_at,confidence}]}
 * roles from server: "user" | "agent" | "hr"
 */

(function () {
  'use strict';

  window.ADAPTA_API_BASE_URL = window.ADAPTA_API_BASE_URL || window.location.origin;
  const API = window.ADAPTA_API_BASE_URL;

  const HISTORY_KEY = 'adapta_chat_history';
  const HISTORY_USER_KEY = 'adapta_chat_history_user_id';
  const WIPE_FLAG_KEY = 'adapta_chat_needs_wipe';
  const WIPE_THRESHOLD_MS = 5 * 60 * 1000;

  // ─── Welcome message data (first-open, per language) ──────────────────────────
  var WELCOME_DATA = {
    ru: {
      text: 'Здравствуйте! Я — AI-помощник. Спрашивайте про работу и жизнь в России на родном языке. Многие в первые дни решают два вопроса: как переводить деньги домой и как недорого звонить близким. Вот что поможет 👇',
      cards: [
        { badge: 'СВЯЗЬ', title: 'Связь для мигрантов', subtitle: 'Безлимит на звонки домой от ~500 ₽/мес', url: '#' },
        { badge: 'КАРТА', title: 'Карта трудового мигранта', subtitle: 'Переводы домой и оплата патента — по льготному курсу', url: 'https://www.sberbank.ru/ru/person/foreign' }
      ]
    },
    hi: {
      text: 'नमस्ते! मैं आपका AI-सहायक हूँ। रूस में काम और जीवन के बारे में अपनी भाषा में पूछें। शुरुआती दिनों में दो सवाल अक्सर आते हैं: घर पैसे कैसे भेजें और अपनों से सस्ते में कैसे बात करें। ये मदद करेगा 👇',
      cards: [
        { badge: 'कनेक्शन', title: 'प्रवासियों के लिए मोबाइल', subtitle: 'घर असीमित कॉल ~500 ₽/माह से', url: '#' },
        { badge: 'कार्ड', title: 'श्रम प्रवासी कार्ड', subtitle: 'घर पैसे भेजें और पेटेंट भुगतान — रियायती दर पर', url: 'https://www.sberbank.ru/ru/person/foreign' }
      ]
    }
  };

  const thread = document.querySelector('.chat-thread');
  const chatScroll = document.querySelector('.chat-scroll');
  const composerInput = document.querySelector('.composer__input');

  function getEmptyState() { return document.getElementById('chatEmptyState'); }

  function updateEmptyState() {
    var es = getEmptyState();
    if (!es) return;
    var hasMessages = thread && thread.querySelector('.bubble-row');
    if (hasMessages) {
      es.classList.add('is-hidden');
    } else {
      es.classList.remove('is-hidden');
    }
  }

  function getJwt() { return localStorage.getItem('adapta_jwt') || ''; }
  function getLang() {
    // Explicit user choice in localStorage takes priority
    var stored = localStorage.getItem('adapta_lang') ||
                 localStorage.getItem('adapta.lang');
    if (stored) return stored;
    // Fall back to profile preferred_language (reliable server-side source)
    var apiUser = getApiUser();
    var profLang = apiUser && apiUser.preferred_language;
    if (profLang && (profLang === 'hi' || profLang === 'en' || profLang === 'ru')) {
      return profLang;
    }
    return document.documentElement.getAttribute('data-lang') || 'ru';
  }
  function scrollToBottom() {
    if (chatScroll) chatScroll.scrollTop = chatScroll.scrollHeight;
  }

  function getApiUser() {
    try {
      const raw = localStorage.getItem('adapta_user');
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  var chatHistory = [];

  // ─── Rendered-key registry (WS-G dedup) ───────────────────────────────────────
  // Prevents poll from double-rendering messages already shown via SSE or prior fetch.
  // Server items: key = created_at + "|" + role + "|" + text.trim()
  // SSE-rendered:  key = "sse|" + localRole + "|" + text.trim()
  var renderedKeys = new Set();
  var pollTimer = null;

  function serverKey(item) {
    return (item.created_at || '') + '|' + (item.role || '') + '|' + (item.text || '').trim();
  }

  // For SSE-rendered bubbles we don't have a server created_at yet, so we use a
  // synthetic prefix.  The poll will match against this when the row later appears
  // in the server history response.
  function sseKey(localRole, text) {
    return 'sse|' + localRole + '|' + (text || '').trim();
  }

  // Returns true if a server history item was already rendered (via server fetch,
  // prior poll, or SSE optimistic render).
  function isAlreadyRendered(item) {
    if (renderedKeys.has(serverKey(item))) return true;
    // Map server role to local role to match SSE keys
    var local = item.role === 'agent' ? 'ai' : item.role;
    if (renderedKeys.has(sseKey(local, item.text))) return true;
    return false;
  }

  function saveHistory() {
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(chatHistory));
    } catch (e) {}
  }

  function shouldWipeHistory(apiUser) {
    if (localStorage.getItem(WIPE_FLAG_KEY) === '1') return true;
    if (!apiUser) return false;
    var userId = apiUser.id || apiUser.email || '';
    if (!userId) return false;
    var storedUserId = localStorage.getItem(HISTORY_USER_KEY);
    if (storedUserId && storedUserId !== userId) return true;
    if (!storedUserId) {
      var accepted_at = apiUser.accepted_at || apiUser.created_at || null;
      if (accepted_at) {
        var elapsed = Date.now() - new Date(accepted_at).getTime();
        if (elapsed < WIPE_THRESHOLD_MS) return true;
      } else {
        return true;
      }
    }
    return false;
  }

  function initHistory() {
    var apiUser = getApiUser();
    var userId = apiUser ? (apiUser.id || apiUser.email || '') : '';

    if (shouldWipeHistory(apiUser)) {
      localStorage.removeItem(HISTORY_KEY);
      localStorage.removeItem(WIPE_FLAG_KEY);
      chatHistory = [];
    } else {
      try {
        var raw = localStorage.getItem(HISTORY_KEY);
        chatHistory = raw ? JSON.parse(raw) : [];
      } catch (e) { chatHistory = []; }
    }

    if (userId) {
      localStorage.setItem(HISTORY_USER_KEY, userId);
    }
  }

  function renderHistoryMessages() {
    if (!thread) return;
    // Always remove any leftover static markup (there should be none after WS-8,
    // but guard defensively so a cached page version is also cleaned up).
    var staticBubbles = thread.querySelectorAll('.bubble-row, .thinking-row');
    staticBubbles.forEach(function (el) { el.remove(); });
    updateEmptyState();
    if (!chatHistory.length) return;

    chatHistory.forEach(function (msg) {
      if (msg.role === 'user') {
        thread.appendChild(createUserBubble(msg.text));
      } else if (msg.role === 'ai') {
        var row = document.createElement('div');
        row.className = 'bubble-row bubble-row--agent';
        var avatar = document.createElement('div');
        avatar.className = 'bubble-row__avatar';
        avatar.textContent = '✨';
        var bubble = document.createElement('div');
        bubble.className = 'bubble bubble-agent';
        var textSpan = document.createElement('span');
        textSpan.className = 'bubble-agent__text-stream';
        textSpan.textContent = msg.text;
        bubble.appendChild(textSpan);
        if (msg.cards && msg.cards.length) {
          msg.cards.forEach(function (card) { renderProductCard(bubble, card); });
        }
        if (msg.ts) {
          var metaDiv = document.createElement('div');
          metaDiv.className = 'bubble__meta';
          var timeSpan = document.createElement('span');
          timeSpan.textContent = msg.ts;
          metaDiv.appendChild(timeSpan);
          bubble.appendChild(metaDiv);
        }
        row.appendChild(avatar);
        row.appendChild(bubble);
        thread.appendChild(row);
      }
    });
    // Hide empty state now that messages have been rendered from history
    updateEmptyState();
  }

  // ─── Toast ─────────────────────────────────────────────────────────────────────
  function showToast(msg, type) {
    let container = document.getElementById('sp-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'sp-toast-container';
      Object.assign(container.style, {
        position: 'fixed', bottom: '80px', left: '50%',
        transform: 'translateX(-50%)', zIndex: '9999',
        display: 'flex', flexDirection: 'column', gap: '8px',
        pointerEvents: 'none', maxWidth: '360px', width: '90%'
      });
      document.body.appendChild(container);
    }
    const t = document.createElement('div');
    t.className = 'toast';
    t.textContent = msg;
    Object.assign(t.style, {
      background: type === 'error' ? 'var(--danger)' : 'var(--ink)',
      color: '#fff', padding: '10px 16px', borderRadius: '10px',
      fontSize: '14px', lineHeight: '1.4', pointerEvents: 'auto',
      opacity: '0', transition: 'opacity 0.2s'
    });
    container.appendChild(t);
    requestAnimationFrame(() => { t.style.opacity = '1'; });
    setTimeout(() => {
      t.style.opacity = '0';
      setTimeout(() => t.remove(), 300);
    }, 4000);
  }

  // ─── Product card ──────────────────────────────────────────────────────────────
  function renderProductCard(bubble, card) {
    if (!card || !card.title) return;
    const existing = bubble.querySelector('.ai-product-card');
    if (existing) existing.remove();

    const el = document.createElement('div');
    el.className = 'ai-product-card';

    const head = document.createElement('div');
    head.className = 'ai-product-card__head';

    const badge = document.createElement('span');
    badge.className = 'ai-product-card__badge';
    badge.textContent = card.badge || '';

    const title = document.createElement('span');
    title.className = 'ai-product-card__title';
    title.textContent = card.title;

    head.appendChild(badge);
    head.appendChild(title);

    const subtitle = document.createElement('div');
    subtitle.className = 'ai-product-card__subtitle';
    subtitle.textContent = card.subtitle || '';

    const cta = document.createElement('a');
    cta.className = 'ai-product-card__cta btn btn-primary btn-sm';
    cta.href = card.url || '#';
    cta.target = '_blank';
    cta.rel = 'noopener';
    cta.textContent = getLang() === 'hi' ? 'और जानें →' : 'Подробнее →';

    el.appendChild(head);
    el.appendChild(subtitle);
    el.appendChild(cta);
    bubble.appendChild(el);
  }

  // ─── Suggest DMS chip ──────────────────────────────────────────────────────────
  let dmsChipShown = false;
  let firstAnswerReceived = false;

  function showDmsChip(afterBubble) {
    if (dmsChipShown) return;
    dmsChipShown = true;

    const chip = document.createElement('button');
    chip.className = 'quick-chip dms-suggest-chip';
    chip.setAttribute('aria-label', 'Спросить про ДМС');

    const lang = getLang();

    const emojiSpan = document.createElement('span');
    emojiSpan.className = 'emoji';
    emojiSpan.textContent = '💊'; // 💊

    const labelSpan = document.createElement('span');
    if (lang === 'hi') {
      labelSpan.textContent = 'डीएमएस के बारे में क्या?';
    } else if (lang === 'en') {
      labelSpan.textContent = 'What about DMS?';
    } else {
      labelSpan.textContent = 'А что про ДМС?';
    }

    chip.appendChild(emojiSpan);
    chip.appendChild(document.createTextNode(' '));
    chip.appendChild(labelSpan);

    chip.addEventListener('click', function () {
      chip.remove();
      const dmsText = lang === 'hi' ? 'मुझे ДМС कहाँ मिलेगा?' : 'Где получить ДМС?';
      sendMessage(dmsText);
    });

    // Insert after the agent bubble row
    if (afterBubble && afterBubble.parentNode) {
      afterBubble.parentNode.insertBefore(chip, afterBubble.nextSibling);
    } else if (thread) {
      thread.appendChild(chip);
    }
    scrollToBottom();
  }

  // ─── DOM builders ──────────────────────────────────────────────────────────────
  function createUserBubble(text) {
    const row = document.createElement('div');
    row.className = 'bubble-row bubble-row--user';
    const bubble = document.createElement('div');
    bubble.className = 'bubble bubble-user';
    bubble.textContent = text;
    row.appendChild(bubble);
    return row;
  }

  // ─── HR reply bubble (WS-G) ────────────────────────────────────────────────────
  // Left-aligned like agent, but has an "Ответ HR" badge and a teal-left-border accent.
  function createHrBubble(text, hhmm) {
    var row = document.createElement('div');
    row.className = 'bubble-row bubble-row--agent';

    var avatar = document.createElement('div');
    avatar.className = 'bubble-row__avatar';
    // Use a person emoji to visually differentiate HR from AI
    avatar.textContent = '👩‍💼';
    avatar.style.background = 'var(--surface-3, #e5e7eb)';
    avatar.style.color = 'var(--ink)';

    var bubble = document.createElement('div');
    bubble.className = 'bubble bubble-agent';
    bubble.style.borderLeft = '3px solid var(--brand-emerald, #10b981)';
    bubble.style.background = 'var(--surface-1)';

    // Badge row
    var badge = document.createElement('span');
    badge.style.cssText = [
      'display:inline-block',
      'font-size:10px',
      'font-weight:700',
      'letter-spacing:0.5px',
      'text-transform:uppercase',
      'padding:2px 8px',
      'border-radius:var(--rounded-pill,999px)',
      'background:var(--brand-emerald,#10b981)',
      'color:#fff',
      'margin-bottom:6px'
    ].join(';');
    var lang = getLang();
    if (lang === 'hi') {
      badge.textContent = 'HR उत्तर';
    } else if (lang === 'en') {
      badge.textContent = 'HR Reply';
    } else {
      badge.textContent = 'Ответ HR';
    }

    var textNode = document.createElement('div');
    textNode.className = 'bubble-agent__text-stream';
    textNode.textContent = text;

    bubble.appendChild(badge);
    bubble.appendChild(textNode);

    if (hhmm) {
      var metaDiv = document.createElement('div');
      metaDiv.className = 'bubble__meta';
      var timeSpan = document.createElement('span');
      timeSpan.textContent = hhmm;
      metaDiv.appendChild(timeSpan);
      bubble.appendChild(metaDiv);
    }

    row.appendChild(avatar);
    row.appendChild(bubble);
    return row;
  }

  function makeThinkingNode() {
    const thinking = document.createElement('div');
    thinking.className = 'thinking-row';

    const waveform = document.createElement('div');
    waveform.className = 'waveform';
    waveform.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < 5; i++) {
      const bar = document.createElement('span');
      bar.className = 'waveform__bar';
      waveform.appendChild(bar);
    }
    thinking.appendChild(waveform);

    const labelRu = document.createElement('span');
    labelRu.className = 'lang-only-ru';
    labelRu.textContent = 'думаю…';
    thinking.appendChild(labelRu);

    const labelHi = document.createElement('span');
    labelHi.className = 'lang-only-hi';
    labelHi.textContent = 'सोच रहा हूँ…';
    thinking.appendChild(labelHi);

    const labelEn = document.createElement('span');
    labelEn.className = 'lang-only-en';
    labelEn.textContent = 'thinking…';
    thinking.appendChild(labelEn);

    return thinking;
  }

  function createAgentBubble() {
    const row = document.createElement('div');
    row.className = 'bubble-row bubble-row--agent';

    const avatar = document.createElement('div');
    avatar.className = 'bubble-row__avatar';
    avatar.textContent = '✨';

    const bubble = document.createElement('div');
    bubble.className = 'bubble bubble-agent';

    const thinking = makeThinkingNode();
    bubble.appendChild(thinking);

    const textSpan = document.createElement('span');
    textSpan.className = 'bubble-agent__text-stream';
    bubble.appendChild(textSpan);

    const sourcesDiv = document.createElement('div');
    sourcesDiv.className = 'bubble__sources';
    bubble.appendChild(sourcesDiv);

    const metaDiv = document.createElement('div');
    metaDiv.className = 'bubble__meta';
    bubble.appendChild(metaDiv);

    row.appendChild(avatar);
    row.appendChild(bubble);
    return { row, bubble, thinking, textSpan, sourcesDiv, metaDiv, pendingCard: null };
  }

  function renderCitations(sourcesDiv, citations) {
    while (sourcesDiv.firstChild) sourcesDiv.removeChild(sourcesDiv.firstChild);
    citations.forEach(function (c) {
      const chip = document.createElement('span');
      chip.className = 'rag-citation';
      chip.title = c.snippet || '';
      chip.textContent = '📄 ' + (c.document_name || c.document_id || '');
      sourcesDiv.appendChild(chip);
    });
  }

  function renderUnanswerableBadge(sourcesDiv) {
    // Replace any prior chips/badges and show a single "not found" pill.
    while (sourcesDiv.firstChild) sourcesDiv.removeChild(sourcesDiv.firstChild);
    const badge = document.createElement('span');
    badge.className = 'rag-citation rag-citation--empty';
    badge.style.borderColor = 'var(--hairline)';
    badge.style.background = 'var(--surface-2)';
    badge.style.color = 'var(--ink-subtle)';
    const lang = getLang();
    if (lang === 'hi') {
      badge.textContent = 'दस्तावेज़ों में नहीं मिला';
    } else if (lang === 'en') {
      badge.textContent = 'Not found in documents';
    } else {
      badge.textContent = 'Не нашёл в документах';
    }
    sourcesDiv.appendChild(badge);
  }

  function buildMetaNode(hhmm, confidence) {
    const frag = document.createDocumentFragment();

    const timeSpan = document.createElement('span');
    timeSpan.textContent = hhmm;
    frag.appendChild(timeSpan);

    if (confidence != null) {
      const dot = document.createElement('span');
      dot.className = 'bubble__meta-dot';
      frag.appendChild(dot);

      const pct = Math.round(confidence * 100) + '%';

      const ru = document.createElement('span');
      ru.className = 'lang-only-ru';
      ru.textContent = 'уверенность ' + pct;
      frag.appendChild(ru);

      const hi = document.createElement('span');
      hi.className = 'lang-only-hi';
      hi.textContent = 'विश्वास ' + pct;
      frag.appendChild(hi);

      const en = document.createElement('span');
      en.className = 'lang-only-en';
      en.textContent = 'confidence ' + pct;
      frag.appendChild(en);
    }
    return frag;
  }

  // ─── Emergency banner builder ──────────────────────────────────────────────────
  function createEmergencyBanner(lang) {
    const banner = document.createElement('div');
    banner.className = 'emergency-banner';
    banner.setAttribute('role', 'alert');

    const icon = document.createElement('span');
    icon.className = 'emergency-banner__icon';
    icon.textContent = '🚨';

    const body = document.createElement('div');
    body.className = 'emergency-banner__body';

    const title = document.createElement('div');
    title.className = 'emergency-banner__title';
    const sub = document.createElement('div');
    sub.className = 'emergency-banner__sub';

    if (lang === 'hi') {
      title.textContent = 'आपातकालीन स्थिति — HR को सूचित कर दिया गया';
      sub.textContent = 'जीवन के लिए खतरा हो तो 112 पर कॉल करें';
    } else {
      title.textContent = 'Экстренная ситуация — HR уведомлён';
      sub.textContent = 'Если опасно для жизни, звоните 112';
    }

    body.appendChild(title);
    body.appendChild(sub);
    banner.appendChild(icon);
    banner.appendChild(body);
    return banner;
  }

  // ─── SSE streaming via fetch + ReadableStream ──────────────────────────────────
  async function sendMessage(text) {
    if (!text || !text.trim()) return;
    const lang = getLang();
    const jwt = getJwt();

    if (!thread) return;

    thread.appendChild(createUserBubble(text));
    updateEmptyState();
    chatHistory.push({ role: 'user', text: text.trim(), ts: null });
    saveHistory();
    // WS-G: mark as SSE-rendered so poll won't duplicate when row arrives from server
    renderedKeys.add(sseKey('user', text.trim()));
    scrollToBottom();

    const agentNodes = createAgentBubble();
    const { row: agentRow, bubble, thinking, textSpan, sourcesDiv, metaDiv } = agentNodes;
    thread.appendChild(agentRow);
    scrollToBottom();

    let firstToken = false;
    let pendingProductCard = null;
    let emergencyBannerShown = false;

    try {
      const headers = { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' };
      if (jwt) headers['Authorization'] = 'Bearer ' + jwt;

      var apiLang = (lang === 'hi') ? 'hi' : (lang === 'en') ? 'en' : 'ru';
      const res = await fetch(API + '/api/v1/chat/messages', {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({ text: text.trim(), language: apiLang })
      });

      if (!res.ok) {
        const errJson = await res.json().catch(function () { return {}; });
        throw new Error(errJson.detail || 'HTTP ' + res.status);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        const blocks = buf.split('\n\n');
        buf = blocks.pop();

        for (const block of blocks) {
          if (!block.trim()) continue;
          let eventName = 'message';
          let dataStr = '';
          for (const line of block.split('\n')) {
            if (line.startsWith('event:')) eventName = line.slice(6).trim();
            else if (line.startsWith('data:')) dataStr += line.slice(5).trim();
          }

          let payload;
          try { payload = JSON.parse(dataStr); } catch (parseErr) { continue; }

          if (eventName === 'emergency') {
            // Insert red banner before the agent bubble row on first event only
            if (!emergencyBannerShown) {
              emergencyBannerShown = true;
              const currentLang = payload.lang || lang;
              const banner = createEmergencyBanner(currentLang);
              if (agentRow.parentNode) {
                agentRow.parentNode.insertBefore(banner, agentRow);
              }
              scrollToBottom();
            }
            continue;
          } else if (eventName === 'token') {
            // SGR pipeline streams RAW JSON fragments here — never render them
            // as text. The waveform/thinking indicator stays visible until the
            // parsed `answer` event arrives.
            continue;
          } else if (eventName === 'answer') {
            // Final parsed answer text (post-SGR, post-translation for hi).
            if (!firstToken) {
              thinking.style.display = 'none';
              firstToken = true;
            }
            textSpan.textContent = payload.text || '';
            scrollToBottom();
          } else if (eventName === 'meta') {
            // SGR meta: is_answerable + reasoning + (literal) confidence.
            // Surface a small badge when the model said it could not answer
            // from the indexed documents.
            if (payload.is_answerable === false) {
              renderUnanswerableBadge(sourcesDiv);
              scrollToBottom();
            }
          } else if (eventName === 'citations') {
            renderCitations(sourcesDiv, payload.citations || []);
            scrollToBottom();
          } else if (eventName === 'product_card') {
            // Sber product recommendation — render after stream completes.
            pendingProductCard = payload.product_card || null;
          } else if (eventName === 'done') {
            const now = new Date();
            const hhmm = now.getHours().toString().padStart(2, '0') + ':' +
                         now.getMinutes().toString().padStart(2, '0');
            while (metaDiv.firstChild) metaDiv.removeChild(metaDiv.firstChild);
            metaDiv.appendChild(buildMetaNode(hhmm, payload.confidence));
            thinking.style.display = 'none';
            const agentText = textSpan.textContent || '';
            chatHistory.push({ role: 'ai', text: agentText, ts: hhmm });
            saveHistory();
            // WS-G: mark agent reply as SSE-rendered so poll won't duplicate it
            renderedKeys.add(sseKey('ai', agentText));
            // Render product card if received during this stream
            if (pendingProductCard) {
              renderProductCard(bubble, pendingProductCard);
              scrollToBottom();
            }
            // Show DMS suggest chip after first-ever AI answer
            if (!firstAnswerReceived) {
              firstAnswerReceived = true;
              showDmsChip(agentRow);
            }
          } else if (eventName === 'error') {
            thinking.style.display = 'none';
            showToast('AI: ' + (payload.message || payload.code || 'Ошибка AI'), 'error');
          }
        }
      }
    } catch (err) {
      thinking.style.display = 'none';
      showToast('Ошибка соединения: ' + err.message, 'error');
    }
  }

  // ─── Submit ────────────────────────────────────────────────────────────────────
  function handleSubmit() {
    const text = composerInput ? composerInput.value.trim() : '';
    if (!text) return;
    composerInput.value = '';
    sendMessage(text);
  }

  if (composerInput) {
    composerInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    });

    // ─── Send button visibility toggle ────────────────────────────────────────
    var composerSendBtn = document.getElementById('composerSend');
    var composerMicLink = document.querySelector('.composer__mic-link');

    function updateComposerState() {
      var hasText = composerInput.value.trim().length > 0;
      if (composerSendBtn) {
        if (hasText) {
          composerSendBtn.classList.add('is-visible');
        } else {
          composerSendBtn.classList.remove('is-visible');
        }
      }
      if (composerMicLink) {
        if (hasText) {
          composerMicLink.classList.add('is-hidden');
        } else {
          composerMicLink.classList.remove('is-hidden');
        }
      }
    }

    composerInput.addEventListener('input', updateComposerState);

    // Patch Enter path to also restore mic after submit
    composerInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        // handleSubmit already called by first keydown listener; just sync UI
        setTimeout(updateComposerState, 0);
      }
    });

    if (composerSendBtn) {
      composerSendBtn.addEventListener('click', function () {
        handleSubmit();
        updateComposerState();
      });
    }
  }

  // ─── Welcome injection (just-registered users only) ───────────────────────────
  function maybeInjectWelcome() {
    if (chatHistory.length !== 0) return;
    var apiUser = getApiUser();
    var uid = apiUser && (apiUser.id || apiUser.email);
    if (!uid) return;
    if (localStorage.getItem('adapta_new_user') !== String(uid)) return;
    var lang = getLang();
    var data = WELCOME_DATA[lang] || WELCOME_DATA.ru;
    var now = new Date();
    var ts = String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0');
    chatHistory.push({ role: 'ai', text: data.text, ts: ts, welcome: true, cards: data.cards });
    saveHistory();
    localStorage.removeItem('adapta_new_user');
  }

  // ─── Render one server history item into the thread ───────────────────────────
  function renderServerItem(item) {
    if (!thread) return;
    var ts = item.created_at
      ? (function () {
          var d = new Date(item.created_at);
          return isNaN(d.getTime()) ? '' :
            String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
        }())
      : '';

    var el;
    if (item.role === 'user') {
      el = createUserBubble(item.text || '');
    } else if (item.role === 'hr') {
      el = createHrBubble(item.text || '', ts);
    } else {
      // agent / ai
      var row = document.createElement('div');
      row.className = 'bubble-row bubble-row--agent';
      var avatar = document.createElement('div');
      avatar.className = 'bubble-row__avatar';
      avatar.textContent = '✨';
      var bubble = document.createElement('div');
      bubble.className = 'bubble bubble-agent';
      var textSpan = document.createElement('span');
      textSpan.className = 'bubble-agent__text-stream';
      textSpan.textContent = item.text || '';
      bubble.appendChild(textSpan);
      if (ts) {
        var metaDiv = document.createElement('div');
        metaDiv.className = 'bubble__meta';
        if (item.confidence != null) {
          metaDiv.appendChild(buildMetaNode(ts, item.confidence));
        } else {
          var timeSpan = document.createElement('span');
          timeSpan.textContent = ts;
          metaDiv.appendChild(timeSpan);
        }
        bubble.appendChild(metaDiv);
      }
      row.appendChild(avatar);
      row.appendChild(bubble);
      el = row;
    }

    thread.appendChild(el);
    renderedKeys.add(serverKey(item));
    updateEmptyState();
  }

  // ─── Load full server history (WS-G) ──────────────────────────────────────────
  // Clears the thread and renders the canonical server thread.
  // Falls back to localStorage on network/auth failure.
  async function loadServerHistory() {
    var jwt = getJwt();
    if (!jwt) {
      // No auth — fall through to localStorage fallback
      initHistory();
      maybeInjectWelcome();
      renderHistoryMessages();
      scrollToBottom();
      return;
    }

    try {
      var res = await fetch(API + '/api/v1/me/chat/history', {
        method: 'GET',
        headers: { 'Authorization': 'Bearer ' + jwt }
      });

      if (!res.ok) {
        var errJson = await res.json().catch(function () { return {}; });
        throw new Error(errJson.detail || 'HTTP ' + res.status);
      }

      var data = await res.json();
      var items = (data && Array.isArray(data.items)) ? data.items : [];

      // Clear thread — server is source of truth
      if (thread) {
        var existing = thread.querySelectorAll('.bubble-row, .thinking-row');
        existing.forEach(function (el) { el.remove(); });
      }
      renderedKeys.clear();
      updateEmptyState();

      items.forEach(function (item) {
        renderServerItem(item);
      });

      // New user with empty server history — show welcome cards before first message
      if (items.length === 0) {
        initHistory();
        maybeInjectWelcome();
        // If welcome was injected (chatHistory now has one entry), render it
        if (chatHistory.length > 0) {
          renderHistoryMessages();
        }
      }

      scrollToBottom();
      startPoll();

    } catch (err) {
      // Network failure: fall back to localStorage
      initHistory();
      maybeInjectWelcome();
      renderHistoryMessages();
      scrollToBottom();
      // Still start poll so that once connectivity is restored HR replies appear
      startPoll();
    }
  }

  // ─── Poll (WS-G) — append only new server messages every 7 s ─────────────────
  function startPoll() {
    if (pollTimer) return; // already running
    var jwt = getJwt();
    if (!jwt) return; // no auth, skip

    pollTimer = setInterval(async function () {
      var currentJwt = getJwt();
      if (!currentJwt) {
        clearInterval(pollTimer);
        pollTimer = null;
        return;
      }
      try {
        var res = await fetch(API + '/api/v1/me/chat/history', {
          method: 'GET',
          headers: { 'Authorization': 'Bearer ' + currentJwt }
        });
        if (!res.ok) return; // silent — will retry next tick
        var data = await res.json();
        var items = (data && Array.isArray(data.items)) ? data.items : [];
        var appended = false;
        items.forEach(function (item) {
          if (!isAlreadyRendered(item)) {
            renderServerItem(item);
            appended = true;
          }
        });
        if (appended) scrollToBottom();
      } catch (e) {
        // silent poll failure — will retry next tick
      }
    }, 7000);
  }

  // ─── Sync adapta_lang from profile if not explicitly set ───────────────────
  // Ensures the FIRST message already carries the correct language code.
  function syncLangFromProfile() {
    if (localStorage.getItem('adapta_lang') || localStorage.getItem('adapta.lang')) return;
    var apiUser = getApiUser();
    var profLang = apiUser && apiUser.preferred_language;
    if (profLang && (profLang === 'hi' || profLang === 'en' || profLang === 'ru')) {
      localStorage.setItem('adapta_lang', profLang);
    }
  }

  // ─── DOMContentLoaded: init history (wipe or restore) ─────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    // Sync lang before anything else so getLang() returns correct value immediately
    syncLangFromProfile();
    // WS-G: try server history first (async); falls back to localStorage if no JWT / error
    loadServerHistory();

    // WS-9: prefill contract — deep-link from Help Me screen
    var prefill = localStorage.getItem('adapta_chat_prefill');
    if (prefill && prefill.trim()) {
      localStorage.removeItem('adapta_chat_prefill');
      // Reuse the existing send flow: set composer value then invoke handleSubmit.
      // Delay slightly so loadServerHistory clears the thread before we send.
      if (composerInput) composerInput.value = prefill.trim();
      setTimeout(function () { handleSubmit(); }, 400);
    }
  });

  // ─── Page load: scroll + accept voice text + URL ?q= param ────────────────────
  window.addEventListener('load', function () {
    scrollToBottom();

    // Handle ?q= from hub quick-chips
    var urlQ = new URLSearchParams(window.location.search).get('q');
    if (urlQ && urlQ.trim()) {
      if (composerInput) composerInput.value = urlQ.trim();
      setTimeout(function () { sendMessage(urlQ.trim()); }, 300);
      return; // skip voice text if URL param present
    }

    const pending = sessionStorage.getItem('adapta_voice_text');
    if (pending) {
      sessionStorage.removeItem('adapta_voice_text');
      if (composerInput) composerInput.value = pending;
      setTimeout(function () { sendMessage(pending); }, 200);
    }
  });

  // ─── Quick-chip → fill composer ────────────────────────────────────────────────
  document.querySelectorAll('.quick-chip').forEach(function (chip) {
    chip.addEventListener('click', function () {
      // DMS suggest chip handles its own click and sends directly — skip here.
      if (chip.classList.contains('dms-suggest-chip')) return;
      if (!composerInput) return;
      const label = chip.querySelector('[data-i18n]') ||
                    chip.querySelector('.lang-only-ru') ||
                    chip.querySelector('.lang-only-hi') ||
                    chip.querySelector('.lang-only-en');
      composerInput.value = label ? label.textContent.trim() : '';
      composerInput.focus();
    });
  });

  // ─── Voice bubble replay toggle ────────────────────────────────────────────────
  document.querySelectorAll('.bubble-voice__play').forEach(function (btn) {
    btn.addEventListener('click', function () {
      btn.textContent = btn.textContent === '▶' ? '❚❚' : '▶';
    });
  });

}());
