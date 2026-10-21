#!/usr/bin/env node
/**
 * Щоденний звіт про зміни ARTLINE Rich Studio в Telegram.
 *
 * Перенесено з проєкту Badhairkiller (там же - історія рішень), змінено лише
 * назву, пояс за замовчуванням і людські назви областей.
 *
 * Читає комміти, яких ще не було в жодному звіті, розкладає їх на «Додано /
 * Змінено / Виправлено» за префіксом і надсилає одним повідомленням.
 *
 * Межа звіту — не доба, а останній звітований комміт: доба залежить від того,
 * о котрій спрацював cron, і комміт, зроблений за хвилину до нього, або
 * губиться, або приходить двічі. Файл зі станом лежить поруч із репозиторієм.
 *
 * Запуск (у теці репозиторію на сервері):
 *   node scripts/changelog.mjs            щоденний звіт
 *   node scripts/changelog.mjs --month    звіт за минулий місяць
 *   node scripts/changelog.mjs --month=2026-08 --force   за вказаний місяць
 *   node scripts/changelog.mjs --quarter  звіт за минулий квартал
 *   node scripts/changelog.mjs --quarter=2026-Q3 --force за вказаний квартал
 *   node scripts/changelog.mjs --answer   відповісти на команди з чату
 *
 * Змінні оточення:
 *   CHANGELOG_BOT_TOKEN   токен бота від @BotFather
 *   CHANGELOG_CHAT_ID     куди слати: -1001234567890 або @channelname
 *   CHANGELOG_STATE       файл зі станом, типово .changelog-state
 *   CHANGELOG_TZ          пояс розкладу, типово Europe/Kyiv
 *   CHANGELOG_HOUR        година, з якої можна слати звіт, типово 5
 *   CHANGELOG_FORCE       «1» — надіслати негайно, повз розклад
 *   CHANGELOG_SEND_EMPTY  «1» — слати звіт і тоді, коли змін немає
 *   CHANGELOG_DRY_RUN     «1» — надрукувати замість надсилання
 *   CHANGELOG_TITLE       заголовок звіту, типово «ARTLINE Rich Studio»
 *   CHANGELOG_POLL        скільки секунд чекати команду, типово 45
 */
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

/**
 * Куди потрапляє комміт за своїм префіксом.
 *
 * Внутрішні зміни — документація, тести, залежності — у звіт не йдуть: він
 * для того, щоб бачити, що змінилося на сайті, а не скільки було роботи.
 * Комміт без префікса не губиться, а падає в «Інше»: тихо зникнути не має
 * право жоден.
 */
const BUCKETS = [
  { key: "added", label: "Додано", mark: "🔥", types: ["feat"] },
  {
    key: "changed",
    label: "Змінено",
    mark: "🔄",
    types: ["change", "refactor", "perf", "style", "ui"],
  },
  { key: "fixed", label: "Виправлено", mark: "🛠", types: ["fix", "revert"] },
  { key: "other", label: "Інше", mark: "", types: [] },
];

const SILENT = ["docs", "test", "tests", "chore", "build", "ci", "deps"];

/**
 * Розклад живе в скрипті, а не тільки в cron.
 *
 * Cron рахує години в поясі сервера, а звіт потрібен о п'ятій ранку за
 * Києвом. Твердий час у crontab розійшовся б із нею двічі на рік — на
 * переході на літній час, — і ніхто б цього не помітив, крім того, хто
 * прокинувся о шостій замість п'ятої.
 *
 * Тому cron можна ставити щогодини, а вирішує сам скрипт.
 */
const DEFAULT_TZ = "Europe/Kyiv";
const DEFAULT_TITLE = "ARTLINE Rich Studio";
const DEFAULT_HOUR = 5;

/** Дата в заданому поясі, `РРРР-ММ-ДД`. Саме вона й позначає «сьогодні». */
export function reportDay(date, timeZone = DEFAULT_TZ) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export function localHour(date, timeZone = DEFAULT_TZ) {
  return Number(
    new Intl.DateTimeFormat("en-GB", { timeZone, hour: "2-digit", hour12: false }).format(date),
  );
}

/**
 * Чи час слати звіт.
 *
 * Не «рівно о п'ятій», а «сьогодні ще не слали і вже не раніше п'ятої».
 * Різниця видно тоді, коли сервер о п'ятій спав або перезавантажувався:
 * звіт із твердою годиною просто зник би, а цей прийде наступною годиною.
 */
export function shouldReport({
  now = new Date(),
  timeZone = DEFAULT_TZ,
  hour = DEFAULT_HOUR,
  lastDay = "",
} = {}) {
  const day = reportDay(now, timeZone);
  if (day === lastDay) return { run: false, day, reason: "звіт за сьогодні вже надіслано" };
  if (localHour(now, timeZone) < hour) return { run: false, day, reason: "ще рано" };
  return { run: true, day, reason: "" };
}

/**
 * Зсув пояса в мілісекундах на заданий момент.
 *
 * Потрібен, щоб перевести «перше число, північ у Варшаві» в мітку часу, яку
 * зрозуміє git. Поправка одноразова: переходи на літній час у Польщі
 * відбуваються о третій ночі, а не опівночі, тож межа місяця в них не
 * потрапляє.
 */
function offsetAt(date, timeZone) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(date);
  const at = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const asUtc = Date.UTC(
    Number(at.year),
    Number(at.month) - 1,
    Number(at.day),
    Number(at.hour) % 24,
    Number(at.minute),
    Number(at.second),
  );
  return asUtc - date.getTime();
}

/** Північ першого числа місяця за вказаним поясом. */
export function monthStart(year, month, timeZone = DEFAULT_TZ) {
  const guess = Date.UTC(year, month - 1, 1);
  return new Date(guess - offsetAt(new Date(guess), timeZone));
}

/**
 * Межі місяця як мітки часу.
 *
 * Початок і кінець рахуються окремо: у жовтні місяць починається при зсуві
 * +02:00, а закінчується вже при +01:00, і одна поправка на обидва краї
 * з'їла б годину.
 */
export function monthRange(key, timeZone = DEFAULT_TZ) {
  const [year, month] = key.split("-").map(Number);
  const from = monthStart(year, month, timeZone);
  const to = month === 12 ? monthStart(year + 1, 1, timeZone) : monthStart(year, month + 1, timeZone);
  return { from, to };
}

/** Північ заданої дати «РРРР-ММ-ДД» у вказаному поясі. */
export function dayStart(day, timeZone = DEFAULT_TZ) {
  const [year, month, date] = day.split("-").map(Number);
  const guess = Date.UTC(year, month - 1, date);
  return new Date(guess - offsetAt(new Date(guess), timeZone));
}

/**
 * Межі доби як мітки часу.
 *
 * Кінець рахується не «плюс двадцять чотири години», а північчю наступної
 * дати: у ніч переходу на зимовий час доба триває двадцять п'ять годин, і
 * тверда доба втратила б останню.
 */
export function dayRange(day, timeZone = DEFAULT_TZ) {
  const from = dayStart(day, timeZone);
  // Півтори доби вперед потрапляють у наступну дату за будь-якого переходу.
  const after = new Date(from.getTime() + 36 * 3600 * 1000);
  return { from, to: dayStart(reportDay(after, timeZone), timeZone) };
}

/** Дата для заголовка: «2026-09-19» → «19.09.2026». */
export function dayTitle(day) {
  const [year, month, date] = day.split("-").map(Number);
  return new Intl.DateTimeFormat("uk-UA", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, date)));
}

/**
 * Заголовок звіту за днями, у які зроблено зміни.
 *
 * Звіт іде о п'ятій ранку, а зміни в ньому — здебільшого вчорашні. Коли
 * заголовок брав дату надсилання, вчорашня робота приходила під сьогоднішнім
 * числом, і той самий перелік, який напередодні показав `/zvit`, виглядав як
 * новий день. Тепер дата — це дні самих коммітів: один день — одна дата,
 * кілька — проміжок від першого до останнього.
 */
export function periodTitle(days) {
  const sorted = [...new Set(days.filter(Boolean))].sort();
  if (sorted.length === 0) return "";
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  if (first === last) return dayTitle(first);

  const [fy, fm, fd] = first.split("-");
  const [ly, lm, ld] = last.split("-");
  if (fy === ly && fm === lm) return `${fd}–${ld}.${lm}.${ly}`;
  if (fy === ly) return `${fd}.${fm}–${ld}.${lm}.${ly}`;
  return `${dayTitle(first)} – ${dayTitle(last)}`;
}

/** Дата перед заданою. */
export function previousDay(day, timeZone = DEFAULT_TZ) {
  return reportDay(new Date(dayStart(day, timeZone).getTime() - 12 * 3600 * 1000), timeZone);
}

/** Місяць перед заданим: «2026-01» → «2025-12». */
export function previousMonth(key) {
  const [year, month] = key.split("-").map(Number);
  return month === 1
    ? `${year - 1}-12`
    : `${year}-${String(month - 1).padStart(2, "0")}`;
}

/** Місяць, у якому ми зараз, за вказаним поясом: «2026-09». */
export function currentMonth(date, timeZone = DEFAULT_TZ) {
  return reportDay(date, timeZone).slice(0, 7);
}

/**
 * Чи час слати місячний звіт.
 *
 * Звітується минулий місяць, першого числа з п'ятої ранку. Умова знову не
 * «рівно першого о п'ятій»: якщо сервер того дня не працював, звіт піде
 * другого — місячна підсумкова сторінка, яка зникла через перезавантаження,
 * гірша за ту, що прийшла на день пізніше.
 */
export function shouldReportMonth({
  now = new Date(),
  timeZone = DEFAULT_TZ,
  hour = DEFAULT_HOUR,
  lastMonth = "",
} = {}) {
  const today = reportDay(now, timeZone);
  const target = previousMonth(today.slice(0, 7));
  if (target === lastMonth) {
    return { run: false, month: target, reason: "звіт за цей місяць вже надіслано" };
  }
  const day = Number(today.slice(8));
  if (day === 1 && localHour(now, timeZone) < hour) {
    return { run: false, month: target, reason: "ще рано" };
  }
  return { run: true, month: target, reason: "" };
}

/** Назва місяця для заголовка: «серпень 2026». */
export function monthTitle(key) {
  const [year, month] = key.split("-").map(Number);
  const name = new Intl.DateTimeFormat("uk-UA", { month: "long", timeZone: "UTC" }).format(
    new Date(Date.UTC(year, month - 1, 15)),
  );
  return `${name} ${year}`;
}

/* --------------------------------------------------------------------------
   Квартали
   --------------------------------------------------------------------------
   Місячний звіт відповідає на «що було в серпні», квартальний - на «що ми
   зробили за літо»: його несуть на планування й звітність перед керівництвом.
   Ключ кварталу - «2026-Q3».                                                 */

/** Квартал дати «РРРР-ММ-ДД» або «РРРР-ММ»: «2026-08-14» → «2026-Q3». */
export function quarterOf(day) {
  const [year, month] = day.split("-").map(Number);
  return `${year}-Q${Math.floor((month - 1) / 3) + 1}`;
}

/** Квартал, у якому ми зараз, за вказаним поясом. */
export function currentQuarter(date, timeZone = DEFAULT_TZ) {
  return quarterOf(reportDay(date, timeZone));
}

/** Квартал перед заданим: «2026-Q1» → «2025-Q4». */
export function previousQuarter(key) {
  const [year, q] = key.split("-Q").map(Number);
  return q === 1 ? `${year - 1}-Q4` : `${year}-Q${q - 1}`;
}

/** Три місяці кварталу: «2026-Q3» → ["2026-07", "2026-08", "2026-09"]. */
export function quarterMonths(key) {
  const [year, q] = key.split("-Q").map(Number);
  const first = (q - 1) * 3 + 1;
  return [0, 1, 2].map((shift) => `${year}-${String(first + shift).padStart(2, "0")}`);
}

/** Межі кварталу як мітки часу: від півночі першого числа до півночі наступного кварталу. */
export function quarterRange(key, timeZone = DEFAULT_TZ) {
  const months = quarterMonths(key);
  return { from: monthRange(months[0], timeZone).from, to: monthRange(months[2], timeZone).to };
}

const ROMAN = ["I", "II", "III", "IV"];

/** Назва кварталу: «III квартал 2026 (липень – вересень)». */
export function quarterTitle(key) {
  const [year, q] = key.split("-Q").map(Number);
  const [first, , last] = quarterMonths(key).map((month) => monthTitle(month).split(" ")[0]);
  return `${ROMAN[q - 1]} квартал ${year} (${first} – ${last})`;
}

/**
 * Чи час слати квартальний звіт.
 *
 * Та сама логіка, що й у місячного: звітується минулий квартал, першого числа
 * кварталу з п'ятої ранку, а якщо сервер того дня не працював - першим же
 * запуском після.
 */
export function shouldReportQuarter({
  now = new Date(),
  timeZone = DEFAULT_TZ,
  hour = DEFAULT_HOUR,
  lastQuarter = "",
} = {}) {
  const today = reportDay(now, timeZone);
  const target = previousQuarter(quarterOf(today));
  if (target === lastQuarter) {
    return { run: false, quarter: target, reason: "звіт за цей квартал вже надіслано" };
  }
  const firstDay = quarterMonths(quarterOf(today))[0] === today.slice(0, 7) && today.slice(8) === "01";
  if (firstDay && localHour(now, timeZone) < hour) {
    return { run: false, quarter: target, reason: "ще рано" };
  }
  return { run: true, quarter: target, reason: "" };
}

/**
 * Скільки змін у кожному місяці кварталу: «Липень: 12 · Серпень: 30 · Вересень: 0».
 * Розклад по місяцях показує ритм роботи, якого не видно в загальному списку.
 */
export function quarterBreakdown(key, commits) {
  const counts = Object.fromEntries(quarterMonths(key).map((month) => [month, 0]));
  for (const commit of commits) {
    const month = (commit.day || "").slice(0, 7);
    if (month in counts && bucketOf(parseCommit(commit.subject).type) !== "silent") counts[month] += 1;
  }
  return Object.entries(counts)
    .map(([month, count]) => {
      const name = monthTitle(month).split(" ")[0];
      return `${name.charAt(0).toLocaleUpperCase("uk")}${name.slice(1)}: ${count}`;
    })
    .join(" · ");
}

/* --------------------------------------------------------------------------
   Команди з чату
   --------------------------------------------------------------------------
   Звіт о п'ятій ранку відповідає на питання «що змінилося за ніч». Питання
   «а що вже зроблено сьогодні» виникає серед дня, і чекати до наступного
   ранку заради нього нема сенсу — тому бот відповідає на команду.           */

export const HELP = [
  "<b>Команди</b>",
  "/zvit — що зробили сьогодні",
  "/zvit вчора — за вчора",
  "/zvit 2026-09-15 — за вказаний день",
  "/misyats — з початку місяця",
  "/kvartal — з початку кварталу",
  "/kvartal минулий — за минулий квартал",
  "/kvartal 2026-Q3 — за вказаний квартал",
  "/stan — що бот бачить і коли слав звіт",
].join("\n");

/**
 * Текст повідомлення як команда.
 *
 * `@ім'я` після команди Telegram дописує в групах. Повідомлення при цьому
 * бачать усі боти в чаті, тож команду, адресовану іншому, відпрацьовувати не
 * можна — звідси друге поле.
 */
export function parseCommand(text) {
  const match = /^\/([a-z_]+)(?:@([\w_]+))?(?:\s+([\s\S]*))?$/i.exec((text ?? "").trim());
  if (!match) return null;
  return {
    name: match[1].toLowerCase(),
    to: (match[2] ?? "").toLowerCase(),
    argument: (match[3] ?? "").trim(),
  };
}

/**
 * Що саме просять командою.
 *
 * Чужа команда — не помилка й відповіді не потребує: у чаті може бути інший
 * бот зі своїм набором. А от зрозуміла команда з незрозумілим аргументом
 * відповіді потребує, інакше мовчання не відрізнити від зламаного бота.
 */
export function resolveCommand(command, { now = new Date(), timeZone = DEFAULT_TZ } = {}) {
  if (!command) return null;
  const today = reportDay(now, timeZone);

  if (command.name === "zvit") {
    const argument = command.argument.toLowerCase();
    if (!argument) return { kind: "day", day: today };
    if (argument === "вчора") return { kind: "day", day: previousDay(today, timeZone) };
    if (argument === "сьогодні") return { kind: "day", day: today };
    if (/^\d{4}-\d{2}-\d{2}$/.test(argument)) return { kind: "day", day: argument };
    return { kind: "unclear" };
  }
  if (command.name === "misyats") return { kind: "month", month: currentMonth(now, timeZone) };
  if (command.name === "kvartal") {
    const argument = command.argument.toLowerCase();
    const current = currentQuarter(now, timeZone);
    if (!argument || argument === "поточний") return { kind: "quarter", quarter: current, partial: true };
    if (argument === "минулий") return { kind: "quarter", quarter: previousQuarter(current), partial: false };
    const match = /^(\d{4})-?q([1-4])$/i.exec(argument);
    if (match) {
      const quarter = `${match[1]}-Q${match[2]}`;
      return { kind: "quarter", quarter, partial: quarter === current };
    }
    return { kind: "unclear-quarter" };
  }
  if (command.name === "stan") return { kind: "state" };
  if (["dovidka", "help", "start"].includes(command.name)) return { kind: "help" };
  return null;
}

/** Один рядок `git log`: заголовок, розібраний на префікс, область і суть. */
export function parseCommit(subject) {
  const match = /^([a-z]+)(?:\(([^)]*)\))?!?:\s*(.+)$/.exec(subject.trim());
  if (!match) return { type: "", scope: "", subject: subject.trim() };
  return { type: match[1], scope: (match[2] ?? "").trim(), subject: match[3].trim() };
}

export function bucketOf(type) {
  if (!type) return "other";
  if (SILENT.includes(type)) return "silent";
  const found = BUCKETS.find((bucket) => bucket.types.includes(type));
  return found ? found.key : "other";
}

export function groupCommits(subjects) {
  const groups = { added: [], changed: [], fixed: [], other: [], silent: [] };
  for (const subject of subjects) {
    const commit = parseCommit(subject);
    groups[bucketOf(commit.type)].push(commit);
  }
  return groups;
}

/** Telegram у режимі HTML розуміє лише свої теги; решту треба екранувати. */
export function escapeHtml(value) {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/*
  Звіт читають люди, а не збирає машина.

  Область комміта пишеться латиницею, бо вона йде в код і в адреси. У рядку
  звіту вона нікому нічого не каже: «catalog» посеред українського речення —
  це слід від інструмента, а не назва розділу. Тому відомі області мають
  людську назву, а незнайома лишається як є: вигадувати переклад на льоту
  гірше, ніж показати те, що написав автор.
*/
const SCOPES = {
  admin: "Адмінка",
  api: "Сервер",
  bot: "Telegram",
  critics: "Перевірки",
  csv: "Імпорт CSV",
  deploy: "Сервер",
  export: "Експорт",
  extract: "Аналіз товару",
  facts: "Факти",
  faq: "FAQ",
  feature: "Фіча",
  geo: "SEO / GEO",
  images: "Зображення",
  infographic: "Інфографіка",
  landing: "Лендінги",
  master: "ARTLINE Master",
  media: "Медіа",
  mobile: "Телефон",
  palette: "Кольори",
  projects: "Проєкти",
  promo: "Промо-сторінки",
  prompts: "Промпти",
  review: "Перевірка",
  rich: "Rich-контент",
  security: "Безпека",
  seo: "SEO / GEO",
  showcase: "ARTLINE Showcase",
  styles: "Стилі",
  telegram: "Telegram",
  text: "Тексти",
  ui: "Інтерфейс студії",
  usage: "Використання",
  video: "Відео",
  web: "Інтерфейс студії",
  worker: "Генерація",
};

/**
 * Рядок звіту.
 *
 * Заголовок комміта за домовленістю починається з малої літери — після
 * «feat: » вона доречна. У списку, де перед нею стоїть значок, а не префікс,
 * мала літера читається як недописане речення, тому тут вона велика. Крапка
 * в кінці прибирається: у списку з одного речення вона зайва, а коли частина
 * рядків із нею, а частина без — список виглядає неохайно.
 */
export function line(commit) {
  const name = SCOPES[commit.scope] ?? commit.scope;
  const scope = name ? `[${name}] ` : "";
  const subject = commit.subject.replace(/\.$/, "");
  const human = subject.charAt(0).toLocaleUpperCase("uk") + subject.slice(1);
  return `• ${escapeHtml(scope)}${escapeHtml(human)}`;
}

export function renderReport(
  groups,
  { title = DEFAULT_TITLE, date = new Date(), label = "", footer = "" } = {},
) {
  const when =
    label ||
    new Intl.DateTimeFormat("uk-UA", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(date);

  const parts = [`<b>${escapeHtml(title)} · ${escapeHtml(when)}</b>`];

  for (const bucket of BUCKETS) {
    const commits = groups[bucket.key];
    if (!commits || commits.length === 0) continue;
    // Позначка «Іншого» порожня: значок «•» перед заголовком не відрізнявся б
    // від тих, з яких починається кожен рядок під ним.
    const head = bucket.mark ? `${bucket.mark} <b>${bucket.label}</b>` : `<b>${bucket.label}</b>`;
    parts.push(`${head}\n${commits.map(line).join("\n")}`);
  }

  if (parts.length === 1) parts.push("Змін немає.");
  if (footer) parts.push(escapeHtml(footer));
  return parts.join("\n\n");
}

/** Позначка на другому й наступних повідомленнях довгого звіту. */
const CONTINUED = "<b>…продовження</b>\n\n";

/**
 * Telegram не приймає повідомлення довше за 4096 символів, а мовчазна відмова
 * означала б звіт, якого ніхто не отримав. Тому довгий звіт ріжеться по
 * розділах, а не по символах: половина рядка в одному повідомленні й половина
 * в наступному не читається.
 */
export function splitMessage(text, limit = 3900) {
  if (text.length <= limit) return [text];

  /*
    Місце під позначку «продовження» віднімається заздалегідь, до різання.
    Інакше вона дописується до вже готового шматка й виштовхує його за межу —
    рівно те, заради чого різання й робилося.
  */
  const budget = limit - CONTINUED.length;

  const chunks = [];
  let current = "";
  for (const block of text.split("\n\n")) {
    const piece = current ? `${current}\n\n${block}` : block;
    if (piece.length <= budget) {
      current = piece;
      continue;
    }
    if (current) chunks.push(current);
    // Сам розділ довший за межу — ріжемо його по рядках.
    if (block.length <= budget) {
      current = block;
      continue;
    }
    let buffer = "";
    for (const row of block.split("\n")) {
      const next = buffer ? `${buffer}\n${row}` : row;
      if (next.length <= budget) buffer = next;
      else {
        if (buffer) chunks.push(buffer);
        buffer = row.slice(0, budget);
      }
    }
    current = buffer;
  }
  if (current) chunks.push(current);

  /*
    Друге й наступні повідомлення починаються просто зі списку, і в чаті це
    читається як уламок без початку. Позначка коштує рядок і знімає питання
    «а це звідки».
  */
  return chunks.map((chunk, index) => (index === 0 ? chunk : CONTINUED + chunk));
}

export function hasNews(groups) {
  return BUCKETS.some((bucket) => (groups[bucket.key] ?? []).length > 0);
}

function git(args) {
  return execFileSync("git", args, { encoding: "utf8" }).trim();
}

function readState(path) {
  try {
    const raw = JSON.parse(readFileSync(path, "utf8"));
    return {
      lastCommit: typeof raw?.lastCommit === "string" ? raw.lastCommit : "",
      lastDay: typeof raw?.lastDay === "string" ? raw.lastDay : "",
      lastMonth: typeof raw?.lastMonth === "string" ? raw.lastMonth : "",
      lastQuarter: typeof raw?.lastQuarter === "string" ? raw.lastQuarter : "",
      lastUpdate: Number.isInteger(raw?.lastUpdate) ? raw.lastUpdate : 0,
    };
  } catch {
    return { lastCommit: "", lastDay: "", lastMonth: "", lastQuarter: "", lastUpdate: 0 };
  }
}

function saveState(path, state) {
  writeFileSync(path, `${JSON.stringify(state, null, 2)}\n`);
}

async function send(token, chatId, text, replyTo = 0) {
  const response = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      parse_mode: "HTML",
      disable_web_page_preview: true,
      // Відповідь стає в гілку до команди — у робочому чаті так видно, на що
      // вона. Видалене повідомлення при цьому не має ламати надсилання.
      ...(replyTo ? { reply_to_message_id: replyTo, allow_sending_without_reply: true } : {}),
    }),
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    if (body.includes("USER_BOT_TO_BOT_DISABLED")) throw new Error(BOT_TO_BOT_HINT);
    throw new Error(`Telegram відповів ${response.status}: ${body.slice(0, 300)}`);
  }
}

/** Боти не пишуть ботам: у CHANGELOG_CHAT_ID стоїть id бота, а не людини чи групи. */
const BOT_TO_BOT_HINT = [
  "CHANGELOG_CHAT_ID — це id бота, а боти не можуть писати іншим ботам.",
  "Число перед «:» у токені — id самого бота, а не чату.",
  "Напишіть /start нашому боту або додайте його в групу: у журналі з'явиться рядок «Чат <id>: …».",
  "Це число і вкажіть у CHANGELOG_CHAT_ID (для групи воно від'ємне, -100…).",
].join("\n");

/** Заголовки коммітів у заданому проміжку. */
function subjectsIn(range) {
  return commitsIn(range).map((commit) => commit.subject);
}

/**
 * Комміти з днем, коли їх зроблено.
 *
 * День — за датою комміту (`%cI`), як і в `/zvit`, що вибирає за
 * `--since`/`--until`: інакше звіт і відповідь на команду відносили б ту
 * саму зміну до різних днів.
 */
function commitsIn(range, timeZone = DEFAULT_TZ) {
  const raw = git(["log", "--no-merges", "--format=%H%x1f%cI%x1f%s", ...range]);
  if (!raw) return [];
  return raw.split("\n").map((row) => {
    const [, when = "", subject = ""] = row.split("\x1f");
    const date = new Date(when);
    return { subject, day: Number.isNaN(date.getTime()) ? "" : reportDay(date, timeZone) };
  });
}

/** Дні, у які зроблено зміни, що потрапляють у звіт; внутрішні не рахуються. */
export function reportedDays(commits) {
  return commits
    .filter((commit) => bucketOf(parseCommit(commit.subject).type) !== "silent")
    .map((commit) => commit.day);
}

async function deliver(chunks) {
  if (process.env.CHANGELOG_DRY_RUN === "1") {
    console.log(chunks.join("\n\n— — —\n\n"));
    return false;
  }

  const token = process.env.CHANGELOG_BOT_TOKEN;
  const chatId = process.env.CHANGELOG_CHAT_ID;
  if (!token || !chatId) {
    throw new Error("Немає CHANGELOG_BOT_TOKEN або CHANGELOG_CHAT_ID.");
  }

  for (const chunk of chunks) await send(token, chatId, chunk);
  console.log(`Надіслано повідомлень: ${chunks.length}.`);
  return true;
}

async function daily(state, statePath, timeZone, hour, forced) {
  const due = shouldReport({ timeZone, hour, lastDay: state.lastDay });
  if (!due.run && !forced) {
    console.log(`Не час: ${due.reason}.`);
    return;
  }

  /*
    Перший запуск не має вивалити в канал усю історію репозиторію: без стану
    береться остання доба, далі — рівно те, чого ще не звітували.
  */
  const range = state.lastCommit ? [`${state.lastCommit}..HEAD`] : ["--since=24 hours ago"];
  const commits = commitsIn(range, timeZone);
  const groups = groupCommits(commits.map((commit) => commit.subject));
  const head = git(["rev-parse", "HEAD"]);
  const next = { ...state, lastCommit: head || state.lastCommit, lastDay: due.day };

  if (!hasNews(groups) && process.env.CHANGELOG_SEND_EMPTY !== "1") {
    /*
      Порожній звіт щодня перетворює канал на шум, у якому не видно справжніх.
      День усе одно вважається звітованим — крім сухого прогону: інакше
      перевірка руками вранці записала б сьогоднішню дату, і справжній звіт о
      п'ятій вирішив би, що його вже слали.
    */
    if (process.env.CHANGELOG_DRY_RUN !== "1") saveState(statePath, next);
    console.log("Змін немає — звіт не надсилався.");
    return;
  }

  const text = renderReport(groups, {
    title: process.env.CHANGELOG_TITLE,
    label: periodTitle(reportedDays(commits)),
  });
  /*
    Стан записується лише після вдалого надсилання: якщо Telegram не відповів,
    наступний запуск має повторити ті самі комміти, а не вважати їх
    звітованими. У сухому прогоні стан не чіпаємо взагалі.
  */
  if (await deliver(splitMessage(text))) saveState(statePath, next);
}

async function monthly(state, statePath, timeZone, hour, forced, explicit) {
  const due = explicit
    ? { run: true, month: explicit, reason: "" }
    : shouldReportMonth({ timeZone, hour, lastMonth: state.lastMonth });

  if (!due.run && !forced) {
    console.log(`Не час: ${due.reason}.`);
    return;
  }

  /*
    Місяць береться датами, а не станом щоденних звітів: підсумок за серпень
    має бути тим самим, скільки б разів його не перезапускали, і не залежати
    від того, чи ходили щоденні.
  */
  const { from, to } = monthRange(due.month, timeZone);
  const groups = groupCommits(
    subjectsIn([`--since=${from.toISOString()}`, `--until=${to.toISOString()}`]),
  );
  const total = ["added", "changed", "fixed", "other"].reduce(
    (sum, key) => sum + groups[key].length,
    0,
  );

  const text = renderReport(groups, {
    title: process.env.CHANGELOG_TITLE,
    label: monthTitle(due.month),
    footer: total > 0 ? `Усього змін за місяць: ${total}.` : "",
  });

  /*
    Місячний звіт іде навіть порожнім — на відміну від щоденного. Раз на
    місяць це не шум, а відповідь на питання «а що взагалі було»: мовчання в
    каналі першого числа не відрізнити від зламаного бота.
  */
  if (await deliver(splitMessage(text))) {
    saveState(statePath, { ...state, lastMonth: due.month });
  }
}

async function quarterly(state, statePath, timeZone, hour, forced, explicit) {
  const due = explicit
    ? { run: true, quarter: explicit, reason: "" }
    : shouldReportQuarter({ timeZone, hour, lastQuarter: state.lastQuarter });

  if (!due.run && !forced) {
    console.log(`Не час: ${due.reason}.`);
    return;
  }

  // Як і місячний: квартал береться датами, тож підсумок той самий за будь-якого перезапуску.
  const { from, to } = quarterRange(due.quarter, timeZone);
  const commits = commitsIn([`--since=${from.toISOString()}`, `--until=${to.toISOString()}`], timeZone);
  const groups = groupCommits(commits.map((commit) => commit.subject));
  const total = countNews(groups);

  const text = renderReport(groups, {
    title: process.env.CHANGELOG_TITLE,
    label: quarterTitle(due.quarter),
    footer: total > 0
      ? `${quarterBreakdown(due.quarter, commits)}\nУсього змін за квартал: ${total}.`
      : "",
  });

  // Квартальний, як і місячний, іде навіть порожнім: мовчання першого числа кварталу
  // не відрізнити від зламаного бота.
  if (await deliver(splitMessage(text))) {
    saveState(statePath, { ...state, lastQuarter: due.quarter });
  }
}

/** Скільки змін у розкладених коммітах, без мовчазних. */
function countNews(groups) {
  return ["added", "changed", "fixed", "other"].reduce(
    (sum, key) => sum + groups[key].length,
    0,
  );
}

/** Текст відповіді на команду. Гілки навмисно окремі: питання в них різні. */
function replyText(asked, { timeZone, hour, state }) {
  const title = process.env.CHANGELOG_TITLE;

  if (asked.kind === "help") return HELP;
  if (asked.kind === "unclear") {
    return "Не зрозумів, за який день. Приклад: <code>/zvit 2026-09-15</code>";
  }

  if (asked.kind === "day") {
    const { from, to } = dayRange(asked.day, timeZone);
    const groups = groupCommits(
      subjectsIn([`--since=${from.toISOString()}`, `--until=${to.toISOString()}`]),
    );
    return renderReport(groups, { title, label: dayTitle(asked.day) });
  }

  if (asked.kind === "unclear-quarter") {
    return "Не зрозумів, за який квартал. Приклад: <code>/kvartal 2026-Q3</code> або <code>/kvartal минулий</code>";
  }

  if (asked.kind === "quarter") {
    const { from, to } = quarterRange(asked.quarter, timeZone);
    const range = asked.partial ? [`--since=${from.toISOString()}`] : [`--since=${from.toISOString()}`, `--until=${to.toISOString()}`];
    const commits = commitsIn(range, timeZone);
    const groups = groupCommits(commits.map((commit) => commit.subject));
    const total = countNews(groups);
    return renderReport(groups, {
      title,
      label: asked.partial ? `${quarterTitle(asked.quarter)}, з початку` : quarterTitle(asked.quarter),
      footer: total > 0 ? `${quarterBreakdown(asked.quarter, commits)}\nУсього змін: ${total}.` : "",
    });
  }

  if (asked.kind === "month") {
    const { from } = monthRange(asked.month, timeZone);
    const groups = groupCommits(subjectsIn([`--since=${from.toISOString()}`]));
    const total = countNews(groups);
    return renderReport(groups, {
      title,
      label: `${monthTitle(asked.month)}, з початку`,
      footer: total > 0 ? `Усього змін: ${total}.` : "",
    });
  }

  /*
    Стан.

    Звіт збирається з історії тієї теки, у якій стоїть сайт, а не з GitHub.
    Тому «змін немає» означає одне з двох: або їх справді немає, або на сервер
    ще не приїхало. Розрізнити це можна лише тут — звідси остання зміна, яку
    бачить сервер.
  */
  const [hash, when, subject] = git(["log", "-1", "--format=%h%x1f%cI%x1f%s"]).split("\x1f");
  const stamp = new Intl.DateTimeFormat("uk-UA", {
    timeZone,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(when));
  return [
    `<b>${escapeHtml(title || DEFAULT_TITLE)} · стан</b>`,
    `Остання зміна на сервері: ${escapeHtml(stamp)} · <code>${escapeHtml(hash)}</code>`,
    escapeHtml(subject),
    state.lastDay
      ? `Щоденний звіт востаннє надсилався ${escapeHtml(dayTitle(state.lastDay))}.`
      : "Щоденний звіт ще не йшов жодного разу.",
    state.lastQuarter
      ? `Квартальний звіт востаннє: ${escapeHtml(quarterTitle(state.lastQuarter))}.`
      : "Квартальний звіт ще не йшов жодного разу.",
    `Розклад: щодня з ${hour}:00 за поясом ${escapeHtml(timeZone)}.`,
  ].join("\n");
}

/** Чи саме цей чат налаштований як адресат звітів. */
function isOurChat(chat, chatId) {
  if (String(chatId).startsWith("@")) return `@${chat?.username ?? ""}` === String(chatId);
  return String(chat?.id) === String(chatId);
}

/**
 * Відповіді на команди з чату.
 *
 * Не окремий процес, а той самий запуск із cron: щохвилини скрипт на
 * сорок п'ять секунд стає в чергу оновлень Telegram і виходить. Постійного
 * процесу на сервері немає — нема чому непомітно померти, — а відповідь
 * приходить одразу, бо запити висять довше за паузу між ними.
 */
async function answer(state, statePath, timeZone, hour) {
  const token = process.env.CHANGELOG_BOT_TOKEN;
  const chatId = process.env.CHANGELOG_CHAT_ID;
  if (!token || !chatId) throw new Error("Немає CHANGELOG_BOT_TOKEN або CHANGELOG_CHAT_ID.");

  const wait = Number(process.env.CHANGELOG_POLL ?? 45);
  const response = await fetch(`https://api.telegram.org/bot${token}/getUpdates`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      ...(state.lastUpdate ? { offset: state.lastUpdate + 1 } : {}),
      timeout: wait,
      allowed_updates: ["message"],
    }),
  });

  if (response.status === 409) {
    /*
      Чергу оновлень Telegram віддає комусь одному. 409 означає, що
      попередній запуск ще не вийшов — наступна хвилина застане чергу
      вільною, і робити з цього помилку не треба.
    */
    console.log("Чергу оновлень слухає інший запуск.");
    return;
  }
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Telegram відповів ${response.status}: ${body.slice(0, 300)}`);
  }

  const updates = (await response.json())?.result ?? [];
  /*
    Порожня черга — найчастіший і найменш зрозумілий випадок: команду
    відправили, а бот мовчить. Причин рівно дві, і розрізняє їх Telegram.

    Вебхук: поки він стоїть, оновлення йдуть на нього, а getUpdates
    лишається ні з чим. Порожня черга без вебхука означає інше — у той
    момент, коли скрипт слухав, нових повідомлень просто не було; ті, що
    надійшли між запусками, чекають і прийдуть наступним.
  */
  if (updates.length === 0) await explainSilence(token);

  let last = state.lastUpdate;
  let answered = 0;

  for (const update of updates) {
    last = Math.max(last, update.update_id);
    const message = update.message;
    if (!message?.text) continue;

    /*
      Кожне оновлення видно в журналі разом із чатом, з якого воно прийшло.
      Без цього «оновлень нуль» і «оновлення прийшло не з того чату» в
      журналі виглядають однаково, і шукати різницю нема по чому.
    */
    console.log(`Чат ${message.chat?.id}: ${message.text.slice(0, 40)}`);
    // Історія змін не має йти кожному, хто знайшов бота в пошуку.
    if (!isOurChat(message.chat, chatId)) {
      console.log(`Пропущено: очікуваний чат ${chatId}.`);
      continue;
    }

    const command = parseCommand(message.text);
    if (command?.to && command.to !== (await botName(token))) continue;
    const asked = resolveCommand(command, { timeZone });
    if (!asked) continue;

    try {
      for (const chunk of splitMessage(replyText(asked, { timeZone, hour, state }))) {
        await send(token, chatId, chunk, message.message_id);
      }
      answered += 1;
    } catch (error) {
      // Зсув усе одно посунеться: команда, на яку не вдалося відповісти,
      // інакше повторювалася б щохвилини вічно.
      console.error(`Команда /${command.name}: ${error.message}`);
    }
  }

  if (last !== state.lastUpdate) saveState(statePath, { ...state, lastUpdate: last });
  console.log(`Оновлень: ${updates.length}, відповідей: ${answered}.`);
}

/** Чому черга порожня — питаємо в Telegram, а не здогадуємося. */
async function explainSilence(token) {
  const response = await fetch(`https://api.telegram.org/bot${token}/getWebhookInfo`);
  const info = response.ok ? (await response.json())?.result : null;
  if (!info) {
    console.log("Черга порожня; стан вебхука дізнатися не вдалося.");
    return;
  }
  if (info.url) {
    console.log(`Черга порожня: оновлення забирає вебхук ${info.url}.`);
    console.log("Прибрати: deleteWebhook у того ж бота.");
  } else {
    console.log("Черга порожня, вебхука немає: нових повідомлень у цю мить не було.");
  }
  if (info.pending_update_count) {
    console.log(`Чекають на доставку: ${info.pending_update_count}.`);
  }
  if (info.last_error_message) {
    console.log(`Остання помилка Telegram: ${info.last_error_message}.`);
  }
}

/** Ім'я бота питаємо лише тоді, коли команда адресована комусь поіменно. */
let ownName = "";
async function botName(token) {
  if (ownName) return ownName;
  const response = await fetch(`https://api.telegram.org/bot${token}/getMe`);
  const body = response.ok ? await response.json() : null;
  ownName = (body?.result?.username ?? "").toLowerCase();
  return ownName;
}

async function main() {
  const statePath = process.env.CHANGELOG_STATE || ".changelog-state";
  const state = readState(statePath);
  const timeZone = process.env.CHANGELOG_TZ || DEFAULT_TZ;
  const hour = Number(process.env.CHANGELOG_HOUR ?? DEFAULT_HOUR);
  const forced = process.env.CHANGELOG_FORCE === "1" || process.argv.includes("--force");

  const monthArg = process.argv.find((arg) => arg === "--month" || arg.startsWith("--month="));
  const monthly_ = Boolean(monthArg) || process.env.CHANGELOG_PERIOD === "month";
  const explicit = monthArg?.includes("=") ? monthArg.split("=")[1] : "";

  const quarterArg = process.argv.find((arg) => arg === "--quarter" || arg.startsWith("--quarter="));
  const quarterKey = quarterArg?.includes("=") ? quarterArg.split("=")[1].toUpperCase() : "";

  if (process.argv.includes("--answer")) await answer(state, statePath, timeZone, hour);
  else if (quarterArg || process.env.CHANGELOG_PERIOD === "quarter") {
    if (quarterKey && !/^\d{4}-Q[1-4]$/.test(quarterKey)) throw new Error("Квартал пишеться як 2026-Q3.");
    await quarterly(state, statePath, timeZone, hour, forced, quarterKey);
  } else if (monthly_) await monthly(state, statePath, timeZone, hour, forced, explicit);
  else await daily(state, statePath, timeZone, hour, forced);
}

// Файл і запускають, і імпортують у тестах — головна частина лише при запуску.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}
