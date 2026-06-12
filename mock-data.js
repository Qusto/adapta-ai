/**
 * AdaptaAI — Shared mock data
 * Все экраны B2C показывают одного мигранта, B2B показывает того же + 5-7 коллег.
 * Это обеспечивает консистентность между экранами.
 */
window.AdaptaMock = {
  // ============ B2C HERO PERSONA ============
  me: {
    id: 'usr_4321',
    fullName: {
      ru: 'Раджу Шарма',
      hi: 'राजू शर्मा',
      en: 'Raju Sharma',
      latin: 'Raju Sharma',
    },
    nativeLang: 'hi',
    birth: '1991-08-14',
    age: 34,
    country: { ru: 'Индия', hi: 'भारत', en: 'India', code: 'IN', flag: '🇮🇳' },
    phone: '+91 98765 43210',
    phoneRu: '+7 916 555 12 34',
    passport: { number: 'P1234567', issuedBy: 'Ministry of External Affairs, New Delhi', validUntil: '2030-12-31' },
    arrivedAt: '2026-02-12',
    employer: 'pik_3422',
    objectId: 'metropolia_14',
    role: { ru: 'Монолитчик', hi: 'मोनोलिथिक वर्कर', en: 'Concrete worker' },
    quotaPlace: { current: 32, total: 150 },
    avatar: null, // place for emoji or initials
  },

  // ============ EMPLOYER ============
  employer: {
    id: 'pik_3422',
    name: { ru: 'Застройщик№1', hi: 'Застройщик№1', en: 'Застройщик№1' },
    legalName: 'Застройщик№1',
    logo: '🏗️',
    hqAddress: { ru: 'Москва, Баррикадная ул., 19', hi: 'Moscow, Barrikadnaya St., 19', en: 'Moscow, Barrikadnaya St., 19' },
    site: {
      id: 'metropolia_14',
      name: { ru: 'ЖК «Метрополия», корп. 14', hi: 'मेट्रोपोलिया परिसर, बिल्डिंग 14', en: 'Metropoliya complex, block 14' },
      address: { ru: 'Котельническая наб., д. 12, Москва', hi: 'कोटेलनिचेस्काया तटबंध, 12, मॉस्को', en: 'Kotelnicheskaya emb., 12, Moscow' },
      geo: { lat: 55.7456, lon: 37.6428 },
    },
    dorm: {
      number: '4',
      address: { ru: '1-й Котельнический пер., 5, Москва', hi: '1-я Котेलनिचेस्की लेन, 5, मॉस्को', en: '1st Kotelnicheskiy lane, 5, Moscow' },
      directions: { ru: 'Метро «Таганская», 10 минут пешком', hi: 'मेट्रो "तगानस्काया", 10 मिनट पैदल', en: 'Taganskaya metro, 10 min walk' },
      amenities: { ru: 'Wi-Fi, кухня, душевые, прачечная', hi: 'Wi-Fi, रसोई, स्नान, लॉन्ड्री', en: 'Wi-Fi, kitchen, showers, laundry' },
    },
    schedule: { ru: 'Пн-Сб: 8:00–18:00, обед 12:00–13:00', hi: 'सोम-शनि: 8:00–18:00, लंच 12:00–13:00', en: 'Mon-Sat: 8:00–18:00, lunch 12:00–13:00' },
    foreman: {
      name: { ru: 'Иван Петров', hi: 'इवान पेत्रोव', en: 'Ivan Petrov' },
      phone: '+7 916 123 45 67',
      avatar: '👷',
    },
    hr: {
      name: { ru: 'Дарья Клименко', hi: 'दारिया क्लिमेंको', en: 'Daria Klimenko' },
      phone: '+7 495 987 65 43',
      email: 'hr@zastroyshchik1.ru',
      avatar: '👩‍💼',
    },
    quota: { total: 150, used: 32 },
  },

  // ============ DOCUMENTS ============
  documents: [
    { id: 'passport',  type: 'passport', titleKey: 'docs.passport', icon: '📕',
      number: 'P1234567', validUntil: '2030-12-31', status: 'ok' },
    { id: 'patent',    type: 'migration', titleKey: 'doc.patent', icon: '📋',
      label: { ru: 'Патент на работу', hi: 'कार्य पेटेंट', en: 'Work patent' },
      validUntil: '2027-03-12', status: 'expiring-soon', daysLeft: 14, note: { ru: 'Оплатить налог за следующий месяц', hi: 'अगले माह का कर भुगतान करें', en: 'Pay tax for next month' }
    },
    { id: 'snils',     type: 'migration', icon: '📋',
      label: { ru: 'СНИЛС', hi: 'SNILS', en: 'SNILS' },
      number: '123-456-789 00', status: 'ok' },
    { id: 'inn',       type: 'migration', icon: '📋',
      label: { ru: 'ИНН', hi: 'INN', en: 'INN' },
      number: '7707083893', status: 'ok' },
    { id: 'partnerCard',  type: 'financial', icon: '💳',
      label: { ru: 'Карта банка-партнёра', hi: 'Карта банка-партнёра', en: 'Partner bank card' },
      number: '**** 1234', validUntil: '2030-02', status: 'ok', balance: 47820 },
    { id: 'dms',       type: 'financial', icon: '🏥',
      label: { ru: 'ДМС полис', hi: 'DMS पॉलिसी', en: 'Insurance policy' },
      validUntil: '2027-02-12', status: 'ok' },
  ],

  // ============ STATUS TIMELINE ============
  timeline: [
    { key: 'arrived',  date: '2026-02-12', state: 'done' },
    { key: 'snils',    date: '2026-02-15', state: 'done' },
    { key: 'inn',      date: '2026-02-16', state: 'done' },
    { key: 'biometry', date: '2026-02-18', state: 'done' },
    { key: 'patent',   date: '2026-03-01', state: 'in-progress' },
    { key: 'card',     date: '2026-03-05', state: 'pending' },
    { key: 'sim',      date: '2026-03-08', state: 'pending' },
    { key: 'dms',      date: '2026-03-12', state: 'pending' },
  ],

  // ============ AI CHAT HISTORY (sample) ============
  aiHistory: [
    {
      role: 'user', lang: 'hi',
      text: { hi: 'मैं कहाँ रहूँगा?', ru: '[пер.] Где я буду жить?', en: '[trans.] Where will I live?' },
      audio: true, time: '14:32'
    },
    {
      role: 'agent', lang: 'hi',
      text: {
        hi: 'आप पते कोटेलनिचेस्काया तटबंध, 12 के पास छात्रावास #4 में रहेंगे। पैदल मेट्रो "तगानस्काया" से 10 मिनट।',
        ru: 'Вы будете жить в общежитии №4 рядом с адресом Котельническая наб., 12. От метро «Таганская» 10 минут пешком.',
        en: 'You will live in dormitory #4 near Kotelnicheskaya emb., 12. 10 min walk from Taganskaya metro.'
      },
      sources: [
        { type: 'rag', collection: 'employer_docs_pik_3422', title: 'Общежитие №4 — Правила', page: 1 },
        { type: 'rag', collection: 'ru_onboarding', title: 'Транспорт до общежитий', page: 3 },
      ],
      time: '14:32'
    },
    {
      role: 'user', lang: 'hi',
      text: { hi: 'और WiFi है?', ru: '[пер.] А WiFi есть?', en: '[trans.] Is there WiFi?' },
      time: '14:33'
    },
    {
      role: 'agent', lang: 'hi',
      text: {
        hi: 'हाँ, Wi-Fi मुफ्त है, साथ ही रसोई और लॉन्ड्री।',
        ru: 'Да, Wi-Fi бесплатно, есть кухня и прачечная.',
        en: 'Yes, Wi-Fi is free, also kitchen and laundry.'
      },
      sources: [{ type: 'rag', collection: 'employer_docs_pik_3422', title: 'Общежитие — удобства' }],
      time: '14:33'
    },
  ],

  // ============ B2B WORKERS LIST ============
  workers: [
    { id: 'usr_4321', name: 'Раджу Шарма', country: '🇮🇳', object: 'Метрополия-14', status: 'on-site',     docs: 'ok',         updated: '5 мин', flagAi: false },
    { id: 'usr_4322', name: 'Ахмед Хан',   country: '🇺🇿', object: 'Метрополия-14', status: 'sos',          docs: 'expiring',   updated: '5 мин', flagAi: true, ticket: { type: 'medical', text: 'Болит зуб, нужна помощь', lang: 'uz', confidence: 0.42 } },
    { id: 'usr_4323', name: 'Нгуен Ван',   country: '🇻🇳', object: 'Метрополия-14', status: 'on-site',     docs: 'ok',         updated: '1 ч',   flagAi: false },
    { id: 'usr_4324', name: 'Бахром Каримов', country: '🇹🇯', object: 'Метрополия-14', status: 'on-site', docs: 'ok',         updated: '2 ч',   flagAi: false },
    { id: 'usr_4325', name: 'Викрам Сингх', country: '🇮🇳', object: 'Метрополия-14', status: 'arriving',    docs: 'pending',    updated: '3 ч',   flagAi: false },
    { id: 'usr_4326', name: 'Тушар Мехта',  country: '🇮🇳', object: 'Метрополия-14', status: 'on-site',    docs: 'expired',    updated: '1 д',   flagAi: true,  ticket: { type: 'docs', text: 'Patent expired', lang: 'en', confidence: 0.95 } },
    { id: 'usr_4327', name: 'Анил Кумар',   country: '🇮🇳', object: 'Метрополия-14', status: 'on-leave',   docs: 'ok',         updated: '2 д',   flagAi: false },
    { id: 'usr_4328', name: 'Прия Шарма',    country: '🇮🇳', object: 'Метрополия-14', status: 'on-site',   docs: 'ok',         updated: '3 д',   flagAi: false },
  ],

  // ============ B2B KPI ============
  kpi: {
    active: 32,
    awaitingArrival: 8,
    escalationsToday: 3,
    expiringPatents: 5,
    quotaUsed: 32,
    quotaTotal: 150,
  },

  // ============ B2B TICKETS ============
  tickets: [
    {
      id: 'tk_001', severity: 'critical', icon: '🔴',
      worker: 'Ахмед Хан', workerId: 'usr_4322', flag: '🇺🇿',
      time: '5 мин назад',
      original: { lang: 'uz', text: 'Tishim og\'riyapti, yordam kerak' },
      translated: { ru: 'Болит зуб, нужна помощь', en: 'My tooth hurts, I need help' },
      category: 'medical',
      aiConfidence: 0.42,
      audio: true,
      suggestion: 'Передать в мед-службу + назначить визит в стоматологию',
    },
    {
      id: 'tk_002', severity: 'high', icon: '🟡',
      worker: 'Раджу Шарма', workerId: 'usr_4321', flag: '🇮🇳',
      time: '12 мин назад',
      original: { lang: 'hi', text: 'पास में दवा कहाँ खरीदें?' },
      translated: { ru: 'Где купить лекарство рядом?', en: 'Where to buy medicine nearby?' },
      category: 'life',
      aiConfidence: 0.78,
      audio: false,
    },
    {
      id: 'tk_003', severity: 'medium', icon: '🟢',
      worker: 'Нгуен Ван', workerId: 'usr_4323', flag: '🇻🇳',
      time: '1 ч назад',
      original: { lang: 'vi', text: 'Có thể nghỉ phép bao nhiêu ngày?' },
      translated: { ru: 'Сколько отгулов положено?', en: 'How many leave days?' },
      category: 'employment',
      aiConfidence: 0.81,
      audio: false,
    },
  ],

  // ============ RAG DOCUMENTS ============
  ragDocs: [
    { name: 'ТБ_строительство_2026.pdf',      collection: 'employer_docs_pik_3422', chunks: 12, status: 'indexed', uploaded: '2026-02-12', size: '1.4 MB' },
    { name: 'Welcome_pack_PIK.docx',           collection: 'employer_docs_pik_3422', chunks: 8,  status: 'indexed', uploaded: '2026-02-10', size: '420 KB' },
    { name: 'Общежитие_правила.pdf',           collection: 'employer_docs_pik_3422', chunks: 5,  status: 'indexed', uploaded: '2026-02-09', size: '210 KB' },
    { name: 'Трудовой_договор_шаблон.docx',    collection: 'employer_docs_pik_3422', chunks: 14, status: 'indexed', uploaded: '2026-02-08', size: '180 KB' },
    { name: 'График_смен_февраль.xlsx',        collection: 'employer_docs_pik_3422', chunks: 3,  status: 'processing', uploaded: '2026-02-20', size: '50 KB' },
  ],

  // ============ FINANCE ============
  finance: {
    card: { number: '**** 1234', balance: 47820, currency: 'RUB' },
    transactions: [
      { id: 't1', merchant: { ru: 'Пятёрочка', hi: 'Pyaterochka', en: 'Pyaterochka' }, amount: -842, time: '14:20', icon: '🛒' },
      { id: 't2', merchant: { ru: 'Зарплата Застройщик№1', hi: 'Застройщик№1 वेतन', en: 'Застройщик№1 Salary' }, amount: 47000, time: 'вчера', icon: '💰' },
      { id: 't3', merchant: { ru: 'Метро Москвы', hi: 'Moscow Metro', en: 'Moscow Metro' }, amount: -67, time: 'вчера', icon: '🚇' },
      { id: 't4', merchant: { ru: 'Перевод в Индию', hi: 'भारत में स्थानांतरण', en: 'Transfer to India' }, amount: -30000, time: '3 дня', icon: '↗️' },
      { id: 't5', merchant: { ru: 'Связь от партнёра', hi: 'पार्टनर मोबाइल', en: 'Partner Mobile' }, amount: -390, time: '5 дней', icon: '📱' },
    ],
    exchangeRate: { rub_to_inr: 1.04, displayed: '1 ₽ = 1.04 ₹' },
    nextPayday: '2026-03-15',
    salaryAmount: 47000,
  },

  // ============ PROMOS ============
  promos: [
    { id: 'p1', title: { ru: 'Связь «Мигрант»', hi: 'मोबाइल "मिग्रांत"', en: 'Mobile Migrant' }, subtitle: { ru: '500₽/мес — звонки в Индию', hi: '₹500/माह — भारत कॉल', en: '500₽/mo — calls to India' }, badge: '-30%', accent: '#10b981' },
    { id: 'p2', title: { ru: 'Купер · бесплатная доставка', hi: 'Kuper · मुफ्त डिलीवरी', en: 'Kuper · free delivery' }, subtitle: { ru: 'Промокод KUPER300', hi: 'प्रोमो KUPER300', en: 'Code KUPER300' }, badge: '300₽', accent: '#fb923c' },
    { id: 'p3', title: { ru: 'Телемедицина', hi: 'टेलीमेड', en: 'Telehealth' }, subtitle: { ru: 'Первый приём бесплатно', hi: 'पहली नियुक्ति मुफ्त', en: 'First visit free' }, badge: '🎁', accent: '#06b6d4' },
  ],
};
