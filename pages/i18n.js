(function(){
const D={
ru:{
'Bosh sahifa':'Главная','Tizimga kirish':'Вход в систему','YUKNOVA akkauntingizga xush kelibsiz!':'Добро пожаловать в ваш аккаунт YUKNOVA!','Telefon raqam':'Номер телефона','Parol':'Пароль','Parolingizni kiriting':'Введите пароль','Kirish':'Войти','Akkauntingiz yo‘qmi?':'Нет аккаунта?','Ro‘yxatdan o‘tish':'Регистрация','YUKNOVA — Tizimga kirish':'YUKNOVA — Вход','YUKNOVA — Ro‘yxatdan o‘tish':'YUKNOVA — Регистрация','YUKNOVA — Yuk va transport platformasi':'YUKNOVA — Платформа грузов и транспорта',
'YUKNOVA platformasiga xush kelibsiz!':'Добро пожаловать на платформу YUKNOVA!','Ism va familiya':'Имя и фамилия','Masalan: Azizbek Sharopov':'Например: Иван Иванов','Parolni tasdiqlang':'Подтвердите пароль','Kamida 8 ta belgi':'Не менее 8 символов','Parolni qayta kiriting':'Повторите пароль','Platformadagi rolingiz':'Ваша роль на платформе','🚚 Haydovchi':'🚚 Водитель','📦 Yuk egasi':'📦 Владелец груза','YUKNOVA foydalanish shartlari va maxfiylik':'Условия использования и политика конфиденциальности YUKNOVA','siyosatiga roziman.':'Я согласен.','YUKNOVA foydalanish shartlari va maxfiylik siyosatiga roziman.':'Я согласен с условиями использования и политикой конфиденциальности YUKNOVA.','Akkauntingiz bormi?':'Уже есть аккаунт?','Telefon raqam +998901234567 ko‘rinishida bo‘lishi kerak':'Номер телефона должен быть в формате +998901234567',
'Yuk joylash':'Разместить груз','Yuklarni tanlash':'Выбрать грузы','Shaxsiy kabinet':'Личный кабинет','Ma’lumot yuklanmoqda...':'Загрузка данных...','👤 Profilim':'👤 Мой профиль','Yuklanmoqda...':'Загрузка...','Profilni saqlash':'Сохранить профиль','Amaldagi parol':'Текущий пароль','Yangi parol (kamida 8 belgi)':'Новый пароль (не менее 8 символов)','Parolni almashtirish':'Изменить пароль','Chiqish':'Выйти','🤖 YUKNOVA AI yordamchisi':'🤖 AI-помощник YUKNOVA','Savollaringizga avtomatik javob oling: yuk joylash, buyurtma, tarif va texnik yordam.':'Получайте автоматические ответы о размещении грузов, заказах, тарифах и технической поддержке.','AI bilan suhbat':'Чат с AI','📦 Yuk joylashtirish':'📦 Размещение груза','Yuk nomi':'Название груза','Og‘irligi (tonna)':'Вес (тонн)','Qayerdan':'Откуда','Qayerga':'Куда','Transport turi':'Тип транспорта','Tanlang':'Выберите','Yuk mashinasi':'Грузовик','Gazel':'Газель','Fura / Tirkama':'Фура / Прицеп','Refrijerator':'Рефрижератор','Boshqa':'Другое','Yuk olinadigan va yetkaziladigan joylar':'Места загрузки и доставки','Xaritani bosing: avval olish, keyin yetkazish joyini belgilang.':'Нажмите на карту: сначала отметьте место загрузки, затем доставки.','1. Olish joyi':'1. Место загрузки','2. Yetkazish joyi':'2. Место доставки','Manzilni topish':'Найти адрес','Xaritadagi nuqtalarni tozalash':'Очистить точки на карте','Ikki nuqtani belgilang — yo‘nalish xaritada ko‘rsatiladi.':'Отметьте две точки — маршрут появится на карте.','Olish joyi: belgilanmagan':'Место загрузки: не указано','Yetkazish joyi: belgilanmagan':'Место доставки: не указано','Izoh (ixtiyoriy)':'Комментарий (необязательно)','Buyurtmani yuborish':'Отправить заказ','🚚 Yuk qidirish':'🚚 Поиск груза','Qayerdan yoki qayerga':'Откуда или куда','Barchasi':'Все','Eng ko‘p og‘irlik (tonna)':'Максимальный вес (тонн)','Qidirish':'Поиск','Tozalash':'Очистить','Yangilash':'Обновить','📋 Mening buyurtmalarim':'📋 Мои заказы',
'🧭 Istalgan yo‘lni xaritada ko‘rish':'🧭 Посмотреть любой маршрут на карте','Boshlanish va borish manzilini yozing. Xarita yo‘nalish va mavjud yo‘l variantlarini ko‘rsatadi.':'Укажите начальный и конечный адрес. Карта покажет маршрут и доступные варианты.','Qayerdan?':'Откуда?','Qayerga?':'Куда?','📍 Hozirgi joyimdan':'📍 От моего местоположения','Yo‘lni ko‘rsat':'Показать маршрут','Manzillarni kiriting yoki hozirgi joyingizdan foydalaning.':'Введите адреса или используйте своё текущее местоположение.','Mavjud yuklarni qidiring va mos buyurtmani tanlang.':'Найдите доступные грузы и выберите подходящий заказ.','Yuklarni tanlash kabineti':'Кабинет выбора грузов'
},
en:{
'Bosh sahifa':'Home','Tizimga kirish':'Log in','YUKNOVA akkauntingizga xush kelibsiz!':'Welcome to your YUKNOVA account!','Telefon raqam':'Phone number','Parol':'Password','Parolingizni kiriting':'Enter your password','Kirish':'Log in','Akkauntingiz yo‘qmi?':'Don’t have an account?','Ro‘yxatdan o‘tish':'Sign up','YUKNOVA — Tizimga kirish':'YUKNOVA — Log in','YUKNOVA — Ro‘yxatdan o‘tish':'YUKNOVA — Sign up','YUKNOVA — Yuk va transport platformasi':'YUKNOVA — Cargo and transport platform',
'YUKNOVA platformasiga xush kelibsiz!':'Welcome to the YUKNOVA platform!','Ism va familiya':'Full name','Masalan: Azizbek Sharopov':'Example: John Smith','Parolni tasdiqlang':'Confirm password','Kamida 8 ta belgi':'At least 8 characters','Parolni qayta kiriting':'Re-enter your password','Platformadagi rolingiz':'Your role on the platform','🚚 Haydovchi':'🚚 Driver','📦 Yuk egasi':'📦 Cargo owner','YUKNOVA foydalanish shartlari va maxfiylik':'YUKNOVA terms of use and privacy policy','siyosatiga roziman.':'I agree.','YUKNOVA foydalanish shartlari va maxfiylik siyosatiga roziman.':'I agree to YUKNOVA’s terms of use and privacy policy.','Akkauntingiz bormi?':'Already have an account?','Telefon raqam +998901234567 ko‘rinishida bo‘lishi kerak':'Phone number must be in the format +998901234567',
'Yuk joylash':'Post a load','Yuklarni tanlash':'Browse loads','Shaxsiy kabinet':'Dashboard','Ma’lumot yuklanmoqda...':'Loading your information...','👤 Profilim':'👤 My profile','Yuklanmoqda...':'Loading...','Profilni saqlash':'Save profile','Amaldagi parol':'Current password','Yangi parol (kamida 8 belgi)':'New password (at least 8 characters)','Parolni almashtirish':'Change password','Chiqish':'Log out','🤖 YUKNOVA AI yordamchisi':'🤖 YUKNOVA AI assistant','Savollaringizga avtomatik javob oling: yuk joylash, buyurtma, tarif va texnik yordam.':'Get automatic answers about posting loads, orders, pricing, and technical support.','AI bilan suhbat':'Chat with AI','📦 Yuk joylashtirish':'📦 Post a load','Yuk nomi':'Cargo name','Og‘irligi (tonna)':'Weight (tonnes)','Qayerdan':'From','Qayerga':'To','Transport turi':'Vehicle type','Tanlang':'Select','Yuk mashinasi':'Truck','Gazel':'Van','Fura / Tirkama':'Semi-trailer','Refrijerator':'Refrigerated truck','Boshqa':'Other','Yuk olinadigan va yetkaziladigan joylar':'Pickup and delivery locations','Xaritani bosing: avval olish, keyin yetkazish joyini belgilang.':'Click the map: mark the pickup point first, then the delivery point.','1. Olish joyi':'1. Pickup location','2. Yetkazish joyi':'2. Delivery location','Manzilni topish':'Find address','Xaritadagi nuqtalarni tozalash':'Clear map markers','Ikki nuqtani belgilang — yo‘nalish xaritada ko‘rsatiladi.':'Mark two points — the route will appear on the map.','Olish joyi: belgilanmagan':'Pickup: not selected','Yetkazish joyi: belgilanmagan':'Delivery: not selected','Izoh (ixtiyoriy)':'Note (optional)','Buyurtmani yuborish':'Submit order','🚚 Yuk qidirish':'🚚 Search loads','Qayerdan yoki qayerga':'From or to','Barchasi':'All','Eng ko‘p og‘irlik (tonna)':'Maximum weight (tonnes)','Qidirish':'Search','Tozalash':'Clear','Yangilash':'Refresh','📋 Mening buyurtmalarim':'📋 My orders',
'🧭 Istalgan yo‘lni xaritada ko‘rish':'🧭 View any route on the map','Boshlanish va borish manzilini yozing. Xarita yo‘nalish va mavjud yo‘l variantlarini ko‘rsatadi.':'Enter your start and destination. The map will show the route and available options.','Qayerdan?':'From?','Qayerga?':'To?','📍 Hozirgi joyimdan':'📍 From my location','Yo‘lni ko‘rsat':'Show route','Manzillarni kiriting yoki hozirgi joyingizdan foydalaning.':'Enter addresses or use your current location.','Mavjud yuklarni qidiring va mos buyurtmani tanlang.':'Find available loads and choose a suitable order.','Yuklarni tanlash kabineti':'Load browser'
}};
const attrs=['placeholder','title','aria-label'];
const original=new WeakMap();
function translateNode(n,lang){
 if(!n||!n.isConnected)return;
 const dict=D[lang]||{};
 if(n.nodeType===3){
   if(!original.has(n))original.set(n,n.nodeValue);
   const src=original.get(n),key=src.trim();
   if(dict[key]){const next=src.replace(key,dict[key]);if(n.nodeValue!==next)n.nodeValue=next;}
 }else if(n.nodeType===1){
   attrs.forEach(a=>{if(n.hasAttribute(a)){const k='data-i18n-original-'+a;if(!n.hasAttribute(k))n.setAttribute(k,n.getAttribute(a));const src=n.getAttribute(k);if(dict[src])n.setAttribute(a,dict[src]);}});
   n.childNodes.forEach(ch=>translateNode(ch,lang));
 }
}
const baseTitle=document.title;
function apply(lang){
 lang=['uz','ru','en'].includes(lang)?lang:'uz';
 document.documentElement.lang=lang;
 translateNode(document.body,lang);
 const s=document.getElementById('languageSwitch');if(s)s.value=lang;
 document.title=lang==='ru'?(baseTitle.includes('Ro‘yxatdan')?'YUKNOVA — Регистрация':baseTitle.includes('Tizimga')?'YUKNOVA — Вход':baseTitle.includes('Yuk joylash')?'YUKNOVA — Кабинет владельца груза':baseTitle.includes('Yuk tanlash')?'YUKNOVA — Кабинет водителя':baseTitle):lang==='en'?(baseTitle.includes('Ro‘yxatdan')?'YUKNOVA — Sign up':baseTitle.includes('Tizimga')?'YUKNOVA — Log in':baseTitle.includes('Yuk joylash')?'YUKNOVA — Cargo owner dashboard':baseTitle.includes('Yuk tanlash')?'YUKNOVA — Driver dashboard':baseTitle):baseTitle;
 try{localStorage.setItem('yuknova-language',lang)}catch(e){}
}
function addSelector(){
 const header=document.querySelector('header');if(!header||document.getElementById('languageSwitch'))return;
 const s=document.createElement('select');s.id='languageSwitch';s.className='yuknova-language';s.setAttribute('aria-label','Select language');
 s.innerHTML='<option value="uz">🇺🇿 UZ</option><option value="ru">🇷🇺 RU</option><option value="en">🇬🇧 EN</option>';
 s.addEventListener('change',()=>apply(s.value));
 header.appendChild(s);
}
function start(){
 addSelector();
 let lang='uz';try{lang=localStorage.getItem('yuknova-language')||'uz'}catch(e){}
 apply(lang);
 const observer=new MutationObserver(records=>{const current=document.getElementById('languageSwitch')?.value||lang;records.forEach(r=>{if(r.type==='childList')r.addedNodes.forEach(n=>translateNode(n,current));else if(r.type==='characterData')translateNode(r.target,current)});});
 observer.observe(document.body,{subtree:true,childList:true,characterData:true});
 document.addEventListener('change',e=>{if(e.target.id==='languageSwitch')apply(e.target.value)});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();