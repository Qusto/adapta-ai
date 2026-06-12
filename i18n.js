/**
 * AdaptaAI i18n — словарь RU / HI / EN + live switcher
 *
 * Использование на странице:
 *   <html lang="ru" data-lang="ru">
 *   <script src="../i18n.js" defer></script>
 *
 * Текст: <span data-i18n="nav.home"></span>
 * Атрибуты: <input data-i18n-attr="placeholder:search.placeholder">
 * Скрытие блоков: <div class="lang-hi-only">...</div>  (показывается только на хинди)
 *
 * Переключатель: AdaptaI18n.set('hi')
 */
(function (global) {
  'use strict';

  const dict = {
    /* ============ COMMON ============ */
    'app.name':            { ru: 'AdaptaAI',                 hi: 'AdaptaAI',                en: 'AdaptaAI' },
    'app.tagline':         { ru: 'Адаптация в России — на вашем языке',
                             hi: 'रूस में अनुकूलन — आपकी भाषा में',
                             en: 'Adapt to Russia — in your language' },

    /* ============ LANG NAMES ============ */
    'lang.ru':             { ru: 'Русский',                  hi: 'रूसी',                    en: 'Russian' },
    'lang.hi':             { ru: 'Хинди',                    hi: 'हिन्दी',                   en: 'Hindi' },
    'lang.en':             { ru: 'Английский',               hi: 'अंग्रेज़ी',                 en: 'English' },
    'lang.uz':             { ru: 'Узбекский',                hi: 'उज़्बेक',                  en: 'Uzbek' },

    /* ============ NAVIGATION ============ */
    'nav.home':            { ru: 'Главная',                  hi: 'होम',                     en: 'Home' },
    'nav.ai':              { ru: 'AI-помощник',              hi: 'AI सहायक',                en: 'AI Assistant' },
    'nav.docs':            { ru: 'Документы',                hi: 'दस्तावेज़',                 en: 'Documents' },
    'nav.employer':        { ru: 'Работодатель',             hi: 'नियोक्ता',                 en: 'Employer' },
    'nav.profile':         { ru: 'Профиль',                  hi: 'प्रोफ़ाइल',                en: 'Profile' },
    'nav.help':            { ru: 'Срочно',                   hi: 'तुरंत',                   en: 'Help Me' },

    /* ============ HUB SECTIONS ============ */
    'hub.greeting':        { ru: 'Здравствуйте',             hi: 'नमस्ते',                  en: 'Hello' },
    'hub.statusBar':       { ru: 'Документы в порядке',      hi: 'दस्तावेज़ ठीक हैं',           en: 'Documents OK' },
    'hub.askAI':           { ru: 'Спросите на любом языке',  hi: 'किसी भी भाषा में पूछें',  en: 'Ask in any language' },
    'hub.askExample':      { ru: 'Где платить за патент? · Где банкомат? · Не пришла зарплата',
                             hi: 'पेटेंट कहाँ भुगतान करें? · ATM कहाँ है? · वेतन नहीं आया',
                             en: 'Where to pay tax? · Where is ATM? · Salary not received' },
    'hub.section.status':    { ru: 'Статус',                hi: 'स्थिति',                  en: 'Status' },
    'hub.section.docs':      { ru: 'Документы',             hi: 'दस्तावेज़',               en: 'Documents' },
    'hub.section.employer':  { ru: 'О работодателе',        hi: 'नियोक्ता के बारे में',     en: 'About Employer' },
    'hub.section.life':      { ru: 'Жизнь в РФ',            hi: 'रूस में जीवन',             en: 'Life in Russia' },
    'hub.section.finance':   { ru: 'Финансы',               hi: 'वित्त',                   en: 'Finance' },
    'hub.section.lifestyle': { ru: 'Lifestyle',             hi: 'लाइफस्टाइल',              en: 'Lifestyle' },
    'hub.section.help':      { ru: 'Help Me',               hi: 'मदद चाहिए',                en: 'Help Me' },

    /* ============ AI CHAT ============ */
    'ai.title':            { ru: 'AI-помощник',              hi: 'AI सहायक',                en: 'AI Assistant' },
    'ai.indicator':        { ru: 'отвечает на вашем языке',  hi: 'आपकी भाषा में जवाब देता है', en: 'replies in your language' },
    'ai.placeholder':      { ru: 'Спросите AI или нажмите 🎤 для голоса',  hi: 'AI से पूछें या 🎤 दबाएँ',         en: 'Ask AI or tap 🎤 for voice' },
    'ai.listening':        { ru: 'Слушаю…',                  hi: 'सुन रहा हूँ…',             en: 'Listening…' },
    'ai.understanding':    { ru: 'Понимаю запрос',           hi: 'समझ रहा हूँ',              en: 'Understanding' },
    'ai.searching':        { ru: 'Ищу в базе знаний',        hi: 'जानकारी खोज रहा हूँ',      en: 'Searching knowledge base' },
    'ai.sourceLabel':      { ru: 'Источник',                 hi: 'स्रोत',                   en: 'Source' },
    'ai.escalated':        { ru: 'Передано HR-менеджеру',    hi: 'HR को भेजा गया',          en: 'Sent to HR manager' },
    'ai.quickQ.salary':    { ru: 'Когда зарплата?',          hi: 'वेतन कब आएगा?',           en: 'When is payday?' },
    'ai.quickQ.atm':       { ru: 'Где банкомат?',            hi: 'ATM कहाँ है?',             en: 'Where is the ATM?' },
    'ai.quickQ.clinic':    { ru: 'Поликлиника рядом?',       hi: 'पास में क्लिनिक है?',       en: 'Clinic nearby?' },
    'ai.quickQ.patent':    { ru: 'Как продлить патент?',     hi: 'पेटेंट कैसे बढ़ाएँ?',       en: 'How to extend patent?' },

    /* ============ HELP ME / ESCALATION ============ */
    'help.title':          { ru: 'Срочная помощь',           hi: 'तुरंत मदद',                en: 'Urgent Help' },
    'help.subtitle':       { ru: 'HR ответит в течение 30 минут', hi: 'HR 30 मिनट में जवाब देगा', en: 'HR replies within 30 min' },
    'help.sick':           { ru: 'Я заболел',                hi: 'मैं बीमार हूँ',             en: "I'm sick" },
    'help.accident':       { ru: 'Авария на объекте',        hi: 'काम पर दुर्घटना',           en: 'Accident at work' },
    'help.docs':           { ru: 'Проблема с документами',   hi: 'दस्तावेज़ की समस्या',        en: 'Document issue' },
    'help.salary':         { ru: 'Не пришла зарплата',       hi: 'वेतन नहीं आया',            en: 'Salary not paid' },
    'help.dorm':           { ru: 'Проблема в общежитии',     hi: 'छात्रावास की समस्या',       en: 'Dorm issue' },
    'help.other':          { ru: 'Другое',                   hi: 'अन्य',                    en: 'Other' },
    'help.callHR':         { ru: 'Позвонить HR',             hi: 'HR को कॉल करें',           en: 'Call HR' },
    'help.medical':        { ru: 'Медицинская срочность? Звоните 103', hi: 'चिकित्सा आपात? 103 पर कॉल करें', en: 'Medical emergency? Call 103' },

    /* ============ STATUS / TIMELINE ============ */
    'status.title':        { ru: 'Ваш статус',               hi: 'आपकी स्थिति',              en: 'Your Status' },
    'status.steps':        { ru: 'шагов завершено',          hi: 'चरण पूरे',                en: 'steps done' },
    'status.arrived':      { ru: 'Приехал в РФ',             hi: 'रूस पहुँचा',              en: 'Arrived in Russia' },
    'status.snils':        { ru: 'Получил СНИЛС',            hi: 'SNILS प्राप्त',            en: 'Got SNILS' },
    'status.inn':          { ru: 'Получил ИНН',              hi: 'INN प्राप्त',              en: 'Got INN' },
    'status.biometry':     { ru: 'Сдал биометрию',           hi: 'बायोमेट्रिक दिया',         en: 'Biometry submitted' },
    'status.patent':       { ru: 'Оформляется патент',       hi: 'पेटेंट बन रहा है',          en: 'Patent in progress' },
    'status.card':         { ru: 'Зарплатная карта',         hi: 'वेतन कार्ड',              en: 'Payroll card' },
    'status.sim':          { ru: 'Подключение мобильного',   hi: 'मोबाइल सक्रिय करें',       en: 'Connect mobile' },
    'status.dms':          { ru: 'Полис ДМС',                 hi: 'DMS पॉलिसी',                en: 'Insurance policy' },
    'status.quota':        { ru: 'Ваше место в квоте',       hi: 'कोटा में स्थान',           en: 'Your quota place' },
    'status.alert':        { ru: 'Истекает через',           hi: 'समाप्त होगा',              en: 'Expires in' },
    'status.days':         { ru: 'дней',                     hi: 'दिन',                     en: 'days' },

    /* ============ DOCUMENTS ============ */
    'docs.title':          { ru: 'Мои документы',            hi: 'मेरे दस्तावेज़',            en: 'My Documents' },
    'docs.all':            { ru: 'Все',                      hi: 'सभी',                     en: 'All' },
    'docs.passport':       { ru: 'Паспорт',                  hi: 'पासपोर्ट',                en: 'Passport' },
    'docs.migration':      { ru: 'Миграционные',             hi: 'प्रवासन',                 en: 'Migration' },
    'docs.financial':      { ru: 'Финансовые',               hi: 'वित्तीय',                 en: 'Financial' },
    'docs.add':            { ru: 'Добавить документ',        hi: 'दस्तावेज़ जोड़ें',          en: 'Add document' },
    'docs.valid':          { ru: 'действителен до',          hi: 'मान्य तक',                en: 'valid until' },
    'docs.dms':            { ru: 'ДМС полис',                hi: 'DMS पॉलिसी',              en: 'Insurance policy' },
    'docs.partnerCard':    { ru: 'Карта банка-партнёра',      hi: 'Карта банка-партнёра',    en: 'Partner bank card' },

    /* ============ EMPLOYER ============ */
    'emp.title':           { ru: 'О работодателе',           hi: 'नियोक्ता के बारे में',     en: 'About Employer' },
    'emp.object':          { ru: 'Объект',                   hi: 'साइट',                    en: 'Site' },
    'emp.dorm':            { ru: 'Общежитие',                hi: 'छात्रावास',               en: 'Dormitory' },
    'emp.schedule':        { ru: 'Режим работы',             hi: 'कार्य समय',               en: 'Work hours' },
    'emp.foreman':         { ru: 'Прораб',                   hi: 'फोरमैन',                 en: 'Foreman' },
    'emp.chatHR':          { ru: 'Чат с HR',                 hi: 'HR के साथ चैट',           en: 'Chat with HR' },
    'emp.companyDocs':     { ru: 'Документы компании',       hi: 'कंपनी दस्तावेज़',          en: 'Company documents' },
    'emp.myQR':            { ru: 'Мой QR-код сотрудника',    hi: 'मेरा कर्मचारी QR',         en: 'My employee QR' },

    /* ============ LIFE IN RUSSIA ============ */
    'life.title':          { ru: 'Жизнь в России',           hi: 'रूस में जीवन',             en: 'Life in Russia' },
    'life.search':         { ru: 'Спросите что угодно о жизни в России', hi: 'रूस में जीवन के बारे में पूछें', en: 'Ask anything about life in Russia' },
    'life.money':          { ru: 'Как платить',              hi: 'भुगतान कैसे करें',         en: 'How to pay' },
    'life.transport':      { ru: 'Транспорт',                hi: 'परिवहन',                  en: 'Transport' },
    'life.clinic':         { ru: 'Где лечиться',             hi: 'इलाज कहाँ करें',           en: 'Where to get healthcare' },
    'life.shops':          { ru: 'Магазины и доставки',      hi: 'दुकानें और डिलीवरी',       en: 'Shops & delivery' },
    'life.exchange':       { ru: 'Обмен валюты',             hi: 'मुद्रा विनिमय',           en: 'Currency exchange' },

    /* ============ FINANCE ============ */
    'fin.title':           { ru: 'Финансы',                  hi: 'वित्त',                   en: 'Finance' },
    'fin.balance':         { ru: 'Баланс',                   hi: 'शेष राशि',                en: 'Balance' },
    'fin.transfer':        { ru: 'Перевести',                hi: 'भेजें',                   en: 'Transfer' },
    'fin.pay':             { ru: 'Оплатить',                 hi: 'भुगतान',                  en: 'Pay' },
    'fin.topup':           { ru: 'Пополнить',                hi: 'टॉप अप',                  en: 'Top up' },
    'fin.sbp':             { ru: 'СБП',                      hi: 'SBP',                     en: 'SBP' },
    'fin.sendHome':        { ru: 'Отправить домой',          hi: 'घर भेजें',                en: 'Send home' },
    'fin.toIndia':         { ru: 'рупии в Индию',            hi: 'भारत में रुपये',           en: 'rupees to India' },
    'fin.salaryHistory':   { ru: 'История зарплаты',         hi: 'वेतन इतिहास',             en: 'Salary history' },
    'fin.nextPayday':      { ru: 'Следующая зарплата',       hi: 'अगला वेतन',              en: 'Next payday' },
    'fin.atms':            { ru: 'Ближайшие банкоматы',      hi: 'पास के ATM',              en: 'Nearby ATMs' },

    /* ============ LIFESTYLE ============ */
    'lifestyle.title':     { ru: 'Сервисы партнёров',         hi: 'पार्टनर सेवाएँ',           en: 'Partner Services' },
    'lifestyle.promoDay':  { ru: 'Промокод дня',             hi: 'आज का प्रोमो कोड',         en: "Today's promo" },
    'lifestyle.partnerMobile':{ ru: 'Связь от партнёра',         hi: 'पार्टनर मोबाइल',          en: 'Partner Mobile' },
    'lifestyle.tariff':    { ru: 'Тариф «Мигрант 500₽»',     hi: 'टैरिफ "मिग्रांत 500₽"',   en: '"Migrant 500₽" plan' },
    'lifestyle.health':    { ru: 'Телемедицина партнёра',     hi: 'पार्टनर टेलीमेड',          en: 'Partner Telehealth' },
    'lifestyle.kuper':     { ru: 'Купер · доставка продуктов', hi: 'Kuper · ग्रॉसरी डिलीवरी', en: 'Kuper · grocery delivery' },
    'lifestyle.samokat':   { ru: 'Самокат',                  hi: 'Samokat',                 en: 'Samokat' },
    'lifestyle.okko':      { ru: 'ОККО · фильмы',            hi: 'OKKO · फिल्में',           en: 'OKKO · movies' },
    'lifestyle.zvuk':      { ru: 'Звук · музыка',            hi: 'Zvuk · संगीत',            en: 'Zvuk · music' },
    'lifestyle.maps':      { ru: '2ГИС карты',               hi: '2GIS नक्शे',              en: '2GIS maps' },
    'lifestyle.sbol':      { ru: 'СБОЛ',                     hi: 'SBOL बैंकिंग',            en: 'SBOL Banking' },

    /* ============ PROFILE ============ */
    'profile.title':       { ru: 'Профиль',                  hi: 'प्रोफ़ाइल',                en: 'Profile' },
    'profile.lang':        { ru: 'Язык интерфейса',          hi: 'इंटरफ़ेस भाषा',            en: 'Interface language' },
    'profile.notifs':      { ru: 'Уведомления',              hi: 'सूचनाएँ',                 en: 'Notifications' },
    'profile.security':    { ru: 'Безопасность',             hi: 'सुरक्षा',                 en: 'Security' },
    'profile.history':     { ru: 'История диалогов с AI',    hi: 'AI चैट इतिहास',           en: 'AI chat history' },
    'profile.changeEmp':   { ru: 'Сменить работодателя',     hi: 'नियोक्ता बदलें',          en: 'Change employer' },
    'profile.help':        { ru: 'Помощь и поддержка',       hi: 'सहायता',                  en: 'Help & support' },
    'profile.legal':       { ru: 'Юридическая информация',   hi: 'कानूनी जानकारी',          en: 'Legal info' },
    'profile.logout':      { ru: 'Выйти',                    hi: 'लॉग आउट',                en: 'Log out' },

    /* ============ ONBOARDING ============ */
    'onboard.langPick':    { ru: 'Выберите язык',            hi: 'भाषा चुनें',              en: 'Choose language' },
    'onboard.welcomeStep': { ru: 'Шаг %1 из %2',             hi: 'चरण %1 / %2',             en: 'Step %1 of %2' },
    'onboard.phone':       { ru: 'Введите номер телефона',   hi: 'फ़ोन नंबर दर्ज करें',      en: 'Enter phone number' },
    'onboard.invitation':  { ru: 'Войти по приглашению HR',  hi: 'HR के निमंत्रण से लॉगिन',  en: 'Login with HR invitation' },
    'onboard.scanQR':      { ru: 'Сканировать QR-код',       hi: 'QR स्कैन करें',           en: 'Scan QR code' },
    'onboard.passport':    { ru: 'Сфотографируйте паспорт',  hi: 'पासपोर्ट की फ़ोटो लें',    en: 'Photograph your passport' },
    'onboard.passportNote':{ ru: 'Данные шифруются, передаются только вашему работодателю',
                             hi: 'डेटा एन्क्रिप्टेड है, केवल आपके नियोक्ता को भेजा जाता है',
                             en: 'Data is encrypted, sent only to your employer' },
    'onboard.takePhoto':   { ru: 'Сфотографировать',         hi: 'फ़ोटो लें',               en: 'Take photo' },
    'onboard.enterManual': { ru: 'Ввести вручную',           hi: 'मैन्युअल दर्ज करें',       en: 'Enter manually' },
    'onboard.ready':       { ru: 'Цифровой парашют загружен!', hi: 'डिजिटल पैराशूट लोड हो गया!', en: 'Digital parachute loaded!' },
    'onboard.pkg.map':     { ru: 'Карта аэропорта Шереметьево', hi: 'शेरेमेतेवो हवाई अड्डा नक्शा', en: 'Sheremetyevo airport map' },
    'onboard.pkg.flash':   { ru: 'Карточки-переводчики',     hi: 'अनुवाद कार्ड',            en: 'Translation flashcards' },
    'onboard.pkg.hr':      { ru: 'Контакты HR',              hi: 'HR संपर्क',               en: 'HR contacts' },
    'onboard.pkg.letter':  { ru: 'Гарантийное письмо (PDF)', hi: 'गारंटी पत्र (PDF)',       en: 'Guarantee letter (PDF)' },
    'onboard.toHome':      { ru: 'На главную',               hi: 'होम पर जाएँ',             en: 'Go to home' },

    /* ============ COMMON UI ============ */
    'common.search':       { ru: 'Поиск',                    hi: 'खोज',                     en: 'Search' },
    'common.send':         { ru: 'Отправить',                hi: 'भेजें',                   en: 'Send' },
    'common.cancel':       { ru: 'Отмена',                   hi: 'रद्द',                    en: 'Cancel' },
    'common.done':         { ru: 'Готово',                   hi: 'हो गया',                  en: 'Done' },
    'common.next':         { ru: 'Далее',                    hi: 'आगे',                     en: 'Next' },
    'common.back':         { ru: 'Назад',                    hi: 'पीछे',                    en: 'Back' },
    'common.continue':     { ru: 'Продолжить',               hi: 'जारी रखें',                en: 'Continue' },
    'common.save':         { ru: 'Сохранить',                hi: 'सहेजें',                  en: 'Save' },
    'common.edit':         { ru: 'Редактировать',            hi: 'संपादित करें',            en: 'Edit' },
    'common.add':          { ru: 'Добавить',                 hi: 'जोड़ें',                  en: 'Add' },
    'common.viewAll':      { ru: 'Все',                      hi: 'सभी देखें',               en: 'View all' },
    'common.minutesAgo':   { ru: 'мин назад',                hi: 'मिनट पहले',               en: 'min ago' },
    'common.hoursAgo':     { ru: 'ч назад',                  hi: 'घंटे पहले',                en: 'h ago' },
    'common.daysAgo':      { ru: 'дн назад',                 hi: 'दिन पहले',                en: 'd ago' },
    'common.online':       { ru: 'Онлайн',                   hi: 'ऑनलाइन',                  en: 'Online' },
    'common.offline':      { ru: 'Офлайн',                   hi: 'ऑफ़लाइन',                  en: 'Offline' },
    'common.loading':      { ru: 'Загрузка…',                hi: 'लोड हो रहा है…',           en: 'Loading…' },

    /* ============ B2B ============ */
    'b2b.title':           { ru: 'Панель HR',                hi: 'HR पैनल',                 en: 'HR Console' },
    'b2b.workers':         { ru: 'Сотрудники',               hi: 'कर्मचारी',                en: 'Workers' },
    'b2b.tickets':         { ru: 'Тикеты',                   hi: 'टिकट',                    en: 'Tickets' },
    'b2b.knowledge':       { ru: 'База знаний',              hi: 'जानकारी आधार',            en: 'Knowledge base' },
    'b2b.analytics':       { ru: 'Аналитика',                hi: 'विश्लेषण',                en: 'Analytics' },
    'b2b.settings':        { ru: 'Настройки',                hi: 'सेटिंग्स',                en: 'Settings' },
    'b2b.kpi.active':      { ru: 'Активных сотрудников',     hi: 'सक्रिय कर्मचारी',         en: 'Active workers' },
    'b2b.kpi.pending':     { ru: 'Ожидают приезда',          hi: 'आगमन प्रतीक्षा',          en: 'Awaiting arrival' },
    'b2b.kpi.escalations': { ru: 'Эскалаций сегодня',        hi: 'आज के एस्केलेशन',         en: 'Escalations today' },
    'b2b.kpi.expiring':    { ru: 'Истекают патенты',         hi: 'पेटेंट समाप्ति',          en: 'Expiring patents' },
  };

  /** Текущий язык: <html lang="ru"> по умолчанию */
  let currentLang = (document.documentElement.lang || 'ru').toLowerCase();
  if (!['ru', 'hi', 'en'].includes(currentLang)) currentLang = 'ru';

  function t(key) {
    const entry = dict[key];
    if (!entry) return '⚠️' + key;
    return entry[currentLang] || entry.ru || key;
  }

  function render(scope) {
    const root = scope || document;
    // Текстовое содержимое
    root.querySelectorAll('[data-i18n]').forEach((el) => {
      el.textContent = t(el.getAttribute('data-i18n'));
    });
    // Атрибуты: data-i18n-attr="placeholder:search.placeholder,title:nav.home"
    root.querySelectorAll('[data-i18n-attr]').forEach((el) => {
      el.getAttribute('data-i18n-attr').split(',').forEach((pair) => {
        const [attr, key] = pair.split(':').map((s) => s.trim());
        if (attr && key) el.setAttribute(attr, t(key));
      });
    });
    // Класс-фильтры: .lang-only-ru/.lang-only-hi/.lang-only-en
    ['ru', 'hi', 'en'].forEach((lang) => {
      root.querySelectorAll('.lang-only-' + lang).forEach((el) => {
        el.style.display = lang === currentLang ? '' : 'none';
      });
    });
    // Devanagari font triger
    document.documentElement.classList.toggle('lang-hi-active', currentLang === 'hi');
    document.documentElement.lang = currentLang;
    document.documentElement.setAttribute('data-lang', currentLang);
  }

  function set(lang) {
    if (!['ru', 'hi', 'en'].includes(lang)) return;
    currentLang = lang;
    localStorage.setItem('adapta.lang', lang);
    localStorage.setItem('adapta_lang', lang);
    render();
    // Notify lang switcher buttons
    document.querySelectorAll('[data-lang-switch]').forEach((btn) => {
      btn.classList.toggle('is-active', btn.getAttribute('data-lang-switch') === lang);
    });
  }

  /** Авто-инициализация */
  document.addEventListener('DOMContentLoaded', () => {
    const saved = localStorage.getItem('adapta.lang') || localStorage.getItem('adapta_lang');
    if (saved && ['ru', 'hi', 'en'].includes(saved)) currentLang = saved;
    render();
    // Привязка к кнопкам-переключателям
    document.querySelectorAll('[data-lang-switch]').forEach((btn) => {
      btn.addEventListener('click', () => set(btn.getAttribute('data-lang-switch')));
      btn.classList.toggle('is-active', btn.getAttribute('data-lang-switch') === currentLang);
    });
  });

  /** Публичный API */
  global.AdaptaI18n = { t, set, render, get lang() { return currentLang; }, dict };
})(window);
