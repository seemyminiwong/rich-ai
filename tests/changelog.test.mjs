// Щоденний звіт про зміни ARTLINE Rich Studio: що потрапляє в канал, а що ні.
// Тести перенесено з Badhairkiller разом зі скриптом; змінено лише приклади областей.
// Запуск: node --test tests/changelog.test.mjs
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const {
  parseCommit,
  bucketOf,
  groupCommits,
  renderReport,
  splitMessage,
  escapeHtml,
  hasNews,
  reportDay,
  localHour,
  shouldReport,
  line,
  shouldReportMonth,
  monthRange,
  monthStart,
  previousMonth,
  currentMonth,
  monthTitle,
  parseCommand,
  resolveCommand,
  dayRange,
  dayTitle,
  periodTitle,
  reportedDays,
  previousDay,
  HELP,
  quarterOf,
  currentQuarter,
  previousQuarter,
  quarterMonths,
  quarterRange,
  quarterTitle,
  shouldReportQuarter,
  quarterBreakdown,
} = await import("../scripts/changelog.mjs");

test("префікс розбирається на тип, область і суть", () => {
  assert.deepEqual(parseCommit("feat(prompts): бюджет фото в кожному промпті"), {
    type: "feat",
    scope: "prompts",
    subject: "бюджет фото в кожному промпті",
  });
  assert.deepEqual(parseCommit("fix: лінія між картками"), {
    type: "fix",
    scope: "",
    subject: "лінія між картками",
  });
  // Позначка «ламає сумісність» не має заважати розбору.
  assert.equal(parseCommit("feat(api)!: нові адреси").type, "feat");
});

test("комміт без префікса не губиться", () => {
  /*
    Уся історія до впровадження домовленості написана без префіксів, і мовчки
    викидати її зі звіту не можна: тоді звіт бреше про те, що робили.
  */
  const commit = parseCommit("Категорії стали деревом");
  assert.equal(commit.type, "");
  assert.equal(commit.subject, "Категорії стали деревом");
  assert.equal(bucketOf(""), "other");
});

test("внутрішні зміни у звіт не йдуть", () => {
  /*
    Звіт показує, що змінилося на сайті, а не скільки було роботи. Правка
    документації чи тестів покупця не стосується.
  */
  for (const type of ["docs", "test", "chore", "build", "ci", "deps"]) {
    assert.equal(bucketOf(type), "silent", type);
  }
});

test("типи розкладаються по трьох розділах", () => {
  assert.equal(bucketOf("feat"), "added");
  assert.equal(bucketOf("fix"), "fixed");
  assert.equal(bucketOf("revert"), "fixed");
  for (const type of ["change", "refactor", "perf", "style", "ui"]) {
    assert.equal(bucketOf(type), "changed", type);
  }
  assert.equal(bucketOf("вигаданий"), "other");
});

const sample = [
  "feat(prompts): бюджет фото в кожному промпті",
  "fix(mobile): панель розділів на телефоні",
  "change: порядок карток у каталозі",
  "docs: опис фільтрів",
  "Категорії стали деревом",
];

test("звіт містить лише розділи, у яких щось є", () => {
  const text = renderReport(groupCommits(sample), { date: new Date("2026-09-18T06:00:00Z") });
  assert.match(text, /18\.09\.2026/);
  assert.match(text, /Додано/);
  assert.match(text, /Змінено/);
  assert.match(text, /Виправлено/);
  assert.match(text, /\[Промпти\] Бюджет фото в кожному промпті/);
  assert.match(text, /Категорії стали деревом/, "комміт без префікса теж у звіті");
  assert.doesNotMatch(text, /опис фільтрів/, "документація у звіт не йде");
});

test("день без змін видно окремо", () => {
  const groups = groupCommits(["docs: правка", "chore: залежності"]);
  assert.equal(hasNews(groups), false);
  assert.match(renderReport(groups), /Змін немає/);
});

test("розмітку в заголовку комміта екрановано", () => {
  /*
    Telegram у режимі HTML спіткнеться на «<» у тексті й відмовить у
    надсиланні — звіт просто не прийде, і ніхто не дізнається чому.
  */
  assert.equal(escapeHtml("a < b & c > d"), "a &lt; b &amp; c &gt; d");
  const text = renderReport(groupCommits(["fix: <b> у описі & лапки"]));
  assert.match(text, /&lt;b&gt; у описі &amp; лапки/);
});

test("довгий звіт ріжеться по розділах, а не посеред рядка", () => {
  const many = Array.from({ length: 300 }, (_, index) => `feat: зміна номер ${index + 1}`);
  const text = renderReport(groupCommits(many));
  const chunks = splitMessage(text);
  assert.ok(chunks.length > 1, "довгий звіт має ділитися");
  for (const chunk of chunks) assert.ok(chunk.length <= 3900, `шматок завдовжки ${chunk.length}`);
  // Жоден рядок не має обірватися: кожен починається з «•» або тегу.
  for (const chunk of chunks) {
    for (const row of chunk.split("\n")) {
      assert.ok(row === "" || row.startsWith("•") || row.includes("<b>"), row.slice(0, 40));
    }
  }

  /*
    Друге й наступні повідомлення починаються просто зі списку, і в чаті це
    читається як уламок без початку.
  */
  for (const chunk of chunks.slice(1)) {
    assert.match(chunk, /^<b>…продовження<\/b>/);
  }
  assert.doesNotMatch(chunks[0], /продовження/);
});

test("короткий звіт лишається одним повідомленням", () => {
  assert.deepEqual(splitMessage("коротко"), ["коротко"]);
});

// ── Розклад ─────────────────────────────────────────────────────────────────

const WARSAW = "Europe/Warsaw";

test("доба рахується за Варшавою, а не за поясом сервера", () => {
  /*
    Опівночі UTC у Варшаві вже наступний день. Якби доба бралася з сервера,
    звіт за понеділок приходив би з датою неділі.
  */
  assert.equal(reportDay(new Date("2026-09-17T23:30:00Z"), WARSAW), "2026-09-18");
  assert.equal(reportDay(new Date("2026-09-18T03:00:00Z"), WARSAW), "2026-09-18");
});

test("літній і зимовий час не зсувають годину звіту", () => {
  /*
    Влітку Варшава на дві години попереду UTC, взимку на одну. Тверда година
    в crontab розійшлася б із п'ятою ранку двічі на рік, і помітив би це лише
    той, хто прокинувся о шостій.
  */
  assert.equal(localHour(new Date("2026-07-01T03:00:00Z"), WARSAW), 5, "літо");
  assert.equal(localHour(new Date("2026-12-01T04:00:00Z"), WARSAW), 5, "зима");
});

test("до п'ятої ранку звіт не йде", () => {
  const due = shouldReport({ now: new Date("2026-09-18T01:00:00Z"), timeZone: WARSAW });
  assert.equal(due.run, false);
  assert.match(due.reason, /рано/);
});

test("о п'ятій ранку звіт іде", () => {
  const due = shouldReport({ now: new Date("2026-09-18T03:00:00Z"), timeZone: WARSAW });
  assert.equal(due.run, true);
  assert.equal(due.day, "2026-09-18");
});

test("двічі за добу звіт не повторюється", () => {
  const due = shouldReport({
    now: new Date("2026-09-18T09:00:00Z"),
    timeZone: WARSAW,
    lastDay: "2026-09-18",
  });
  assert.equal(due.run, false);
  assert.match(due.reason, /вже надіслано/);
});

test("пропущена п'ята ранку не з'їдає звіт", () => {
  /*
    Сервер о п'ятій спав або перезавантажувався. Звіт із твердою годиною
    просто зник би; цей приходить наступною годиною, бо умова — «сьогодні ще
    не слали і вже не раніше п'ятої».
  */
  const due = shouldReport({
    now: new Date("2026-09-18T07:00:00Z"),
    timeZone: WARSAW,
    lastDay: "2026-09-17",
  });
  assert.equal(due.run, true);
});

// ── Місячний звіт ───────────────────────────────────────────────────────────

test("межі місяця беруться за Варшавою", () => {
  /*
    Північ першого серпня у Варшаві — це 21:00 попереднього дня за UTC. Якби
    межі бралися в UTC, у звіт за серпень потрапляли б дві останні години
    липня, а два перших дні вересня рахувалися б серпнем.
  */
  const august = monthRange("2026-08", WARSAW);
  assert.equal(august.from.toISOString(), "2026-07-31T22:00:00.000Z");
  assert.equal(august.to.toISOString(), "2026-08-31T22:00:00.000Z");
});

test("перехід на зимовий час не з'їдає годину", () => {
  /*
    Жовтень починається при зсуві +02:00, а закінчується вже при +01:00. Одна
    поправка на обидва краї втратила б годину, і останні 60 хвилин жовтня
    випали б з обох звітів.
  */
  const october = monthRange("2026-10", WARSAW);
  assert.equal(october.from.toISOString(), "2026-09-30T22:00:00.000Z");
  assert.equal(october.to.toISOString(), "2026-10-31T23:00:00.000Z");
});

test("грудень переходить у січень наступного року", () => {
  const december = monthRange("2026-12", WARSAW);
  assert.equal(december.to.toISOString(), "2026-12-31T23:00:00.000Z");
  assert.equal(previousMonth("2026-01"), "2025-12");
  assert.equal(previousMonth("2026-09"), "2026-08");
  assert.equal(monthStart(2027, 1, WARSAW).toISOString(), "2026-12-31T23:00:00.000Z");
});

test("звітується минулий місяць, а не поточний", () => {
  const due = shouldReportMonth({ now: new Date("2026-09-01T04:00:00Z"), timeZone: WARSAW });
  assert.equal(due.run, true);
  assert.equal(due.month, "2026-08");
  assert.equal(currentMonth(new Date("2026-09-01T04:00:00Z"), WARSAW), "2026-09");
});

test("першого числа до п'ятої ранку місячний звіт чекає", () => {
  const due = shouldReportMonth({ now: new Date("2026-09-01T01:00:00Z"), timeZone: WARSAW });
  assert.equal(due.run, false);
  assert.match(due.reason, /рано/);
});

test("пропущене перше число не з'їдає місячний звіт", () => {
  /*
    Підсумок за місяць, який зник через перезавантаження сервера, гірший за
    той, що прийшов на день пізніше.
  */
  const due = shouldReportMonth({ now: new Date("2026-09-03T08:00:00Z"), timeZone: WARSAW });
  assert.equal(due.run, true);
  assert.equal(due.month, "2026-08");
});

test("двічі за місяць звіт не повторюється", () => {
  const due = shouldReportMonth({
    now: new Date("2026-09-05T08:00:00Z"),
    timeZone: WARSAW,
    lastMonth: "2026-08",
  });
  assert.equal(due.run, false);
  assert.match(due.reason, /вже надіслано/);
});

test("у заголовку місяця — назва, а не номер", () => {
  assert.equal(monthTitle("2026-08"), "серпень 2026");
  assert.equal(monthTitle("2026-01"), "січень 2026");
  const text = renderReport(groupCommits(["feat: щось"]), {
    label: monthTitle("2026-08"),
    footer: "Усього змін за місяць: 1.",
  });
  assert.match(text, /серпень 2026/);
  assert.match(text, /Усього змін за місяць: 1\./);
});

test("сухий прогін не чіпає стан розсилки", () => {
  /*
    Перевірка руками вранці не має глушити справжній звіт: якби сухий прогін
    записав сьогоднішню дату, запуск о п'ятій вирішив би, що звіт уже слали.
  */
  const source = readFileSync(new URL("../scripts/changelog.mjs", import.meta.url), "utf8");
  const emptyBranch = source.slice(source.indexOf("if (!hasNews(groups)"));
  assert.match(
    emptyBranch.slice(0, emptyBranch.indexOf("return;")),
    /CHANGELOG_DRY_RUN !== "1"\) saveState/,
  );
  // Після вдалого надсилання стан пишеться, а в сухому прогоні deliver
  // повертає false — і запис не відбувається.
  assert.match(source, /if \(await deliver\(splitMessage\(text\)\)\) saveState/);
});


// ── Людська мова ────────────────────────────────────────────────────────────

test("рядок звіту починається з великої літери", () => {
  /*
    За домовленістю заголовок комміта пишеться з малої: після «feat: » вона
    доречна. У списку, де перед нею значок, а не префікс, мала літера
    читається як недописане речення.
  */
  assert.equal(line({ type: "feat", scope: "", subject: "пошук по каталогу" }), "• Пошук по каталогу");
});

test("крапка в кінці рядка прибирається", () => {
  /*
    У списку з одного речення вона зайва, а коли частина рядків із нею, а
    частина без — список виглядає неохайно.
  */
  assert.equal(line({ type: "fix", scope: "", subject: "лінія зникала." }), "• Лінія зникала");
});

test("область має людську назву, а незнайома лишається як є", () => {
  /*
    «catalog» посеред українського речення — це слід від інструмента, а не
    назва розділу. Але вигадувати переклад незнайомої області на льоту гірше,
    ніж показати те, що написав автор.
  */
  assert.equal(
    line({ type: "fix", scope: "seo", subject: "хибні зауваження" }),
    "• [SEO / GEO] Хибні зауваження",
  );
  assert.equal(
    line({ type: "fix", scope: "mobile", subject: "панель розділів" }),
    "• [Телефон] Панель розділів",
  );
  assert.equal(
    line({ type: "feat", scope: "warehouse", subject: "залишки" }),
    "• [warehouse] Залишки",
  );
});

test("у звіті немає слідів інструмента", () => {
  /*
    Звіт читають люди, яким байдуже до хешів, гілок і номерів коммітів.
  */
  const text = renderReport(groupCommits(sample));
  assert.doesNotMatch(text, /[0-9a-f]{7,40}/, "хеш комміта");
  assert.doesNotMatch(text, /\bHEAD\b|\borigin\/|\bcommit\b/i);
  assert.doesNotMatch(text, /feat[(:]|fix[(:]|chore[(:]/, "префікс домовленості");
});


test("команда розбирається разом з іменем бота й аргументом", () => {
  assert.deepEqual(parseCommand("/zvit"), { name: "zvit", to: "", argument: "" });
  // У групі Telegram дописує «@ім'я», і це повідомлення бачать усі боти чату.
  assert.deepEqual(parseCommand("/zvit@some_bot вчора"), {
    name: "zvit",
    to: "some_bot",
    argument: "вчора",
  });
  assert.equal(parseCommand("що там по сайту"), null, "звичайне повідомлення командою не є");
  assert.equal(parseCommand(""), null);
  assert.equal(parseCommand(undefined), null);
});

test("команда називає день, за який просять звіт", () => {
  const now = new Date("2026-09-19T09:00:00Z");
  assert.deepEqual(resolveCommand(parseCommand("/zvit"), { now }), {
    kind: "day",
    day: "2026-09-19",
  });
  assert.deepEqual(resolveCommand(parseCommand("/zvit вчора"), { now }), {
    kind: "day",
    day: "2026-09-18",
  });
  assert.deepEqual(resolveCommand(parseCommand("/zvit 2026-08-03"), { now }), {
    kind: "day",
    day: "2026-08-03",
  });
  assert.deepEqual(resolveCommand(parseCommand("/misyats"), { now }), {
    kind: "month",
    month: "2026-09",
  });
  assert.equal(resolveCommand(parseCommand("/stan"), { now }).kind, "state");
  assert.equal(resolveCommand(parseCommand("/dovidka"), { now }).kind, "help");

  // Зрозуміла команда з незрозумілим аргументом відповіді потребує: мовчання
  // на неї не відрізнити від зламаного бота.
  assert.equal(resolveCommand(parseCommand("/zvit позавчора"), { now }).kind, "unclear");
  // А чужа команда — ні: у чаті може бути інший бот зі своїм набором.
  assert.equal(resolveCommand(parseCommand("/karma"), { now }), null);
  assert.equal(resolveCommand(null, { now }), null);
});

test("доба переходу на зимовий час триває двадцять п'ять годин", () => {
  /*
    Кінець доби — це північ наступної дати, а не «плюс двадцять чотири
    години»: у ніч переходу тверда доба втратила б останню годину, і комміт,
    зроблений опівночі, зник би зі звіту.
  */
  const shift = dayRange("2026-10-25");
  assert.equal((shift.to - shift.from) / 3600000, 25);
  const plain = dayRange("2026-09-19");
  assert.equal((plain.to - plain.from) / 3600000, 24);
  // Межа рахується за поясом звіту (типово Київ, UTC+3 влітку), а не за UTC.
  assert.equal(plain.from.toISOString(), "2026-09-18T21:00:00.000Z");
});

test("попередній день не губиться на переході на літній час", () => {
  // У ніч на 29 березня доба коротша за двадцять чотири години.
  assert.equal(previousDay("2026-03-30"), "2026-03-29");
  assert.equal(previousDay("2026-01-01"), "2025-12-31");
  assert.equal(dayTitle("2026-09-19"), "19.09.2026");
});

test("довідка перелічує всі команди, на які бот відповідає", () => {
  for (const name of ["/zvit", "/misyats", "/stan"]) {
    assert.match(HELP, new RegExp(name), `${name} немає в довідці`);
  }
  const script = readFileSync(new URL("../scripts/changelog.mjs", import.meta.url), "utf8");
  // Відповідь іде лише в налаштований чат: історія змін не має йти кожному,
  // хто знайшов бота в пошуку.
  assert.match(script, /isOurChat\(message\.chat, chatId\)/);
  // Зсув черги записується й тоді, коли відповісти не вдалося — інакше та
  // сама команда повторювалася б щохвилини вічно.
  assert.match(script, /if \(last !== state\.lastUpdate\) saveState/);
});

test("звіт датується днями змін, а не днем надсилання", () => {
  /*
    Звіт о п'ятій ранку 26-го приніс зміни 25-го під датою «26.09» — і
    виглядав як новий день із тим самим переліком, що напередодні показав
    /zvit. Дата — це дні самих коммітів.
  */
  assert.equal(periodTitle(["2026-09-25", "2026-09-25"]), "25.09.2026");
  assert.equal(periodTitle(["2026-09-26", "2026-09-25"]), "25–26.09.2026");
  assert.equal(periodTitle(["2026-09-30", "2026-10-01"]), "30.09–01.10.2026");
  assert.equal(periodTitle(["2026-12-31", "2027-01-01"]), "31.12.2026 – 01.01.2027");
  assert.equal(periodTitle([]), "");
});

test("внутрішні комміти не розсувають дату звіту", () => {
  const days = reportedDays([
    { subject: "feat(mail): листи мовою покупця", day: "2026-09-25" },
    { subject: "docs: опис", day: "2026-09-26" },
  ]);
  assert.equal(periodTitle(days), "25.09.2026");
});


// ── Квартальні звіти ───────────────────────────────────────────────────────

test("квартал визначається за місяцем, а попередній переходить через рік", () => {
  assert.equal(quarterOf("2026-08-14"), "2026-Q3");
  assert.equal(quarterOf("2026-01-01"), "2026-Q1");
  assert.equal(quarterOf("2026-12-31"), "2026-Q4");
  assert.equal(previousQuarter("2026-Q3"), "2026-Q2");
  assert.equal(previousQuarter("2026-Q1"), "2025-Q4");
  assert.deepEqual(quarterMonths("2026-Q4"), ["2026-10", "2026-11", "2026-12"]);
  assert.equal(currentQuarter(new Date("2026-10-21T10:00:00Z"), "Europe/Kyiv"), "2026-Q4");
});

test("межі кварталу - північ першого числа за поясом звіту, з переходом часу всередині", () => {
  const { from, to } = quarterRange("2026-Q4", "Europe/Kyiv");
  // 1 жовтня ще літній час (+03:00), 1 січня - зимовий (+02:00).
  assert.equal(from.toISOString(), "2026-09-30T21:00:00.000Z");
  assert.equal(to.toISOString(), "2026-12-31T22:00:00.000Z");
  const q3 = quarterRange("2026-Q3", "Europe/Kyiv");
  assert.equal(q3.to.toISOString(), from.toISOString(), "квартали стикуються без проміжку");
});

test("квартальний звіт іде першого числа кварталу з п'ятої і не повторюється", () => {
  const tz = "Europe/Kyiv";
  const early = shouldReportQuarter({ now: new Date("2026-10-01T01:00:00Z"), timeZone: tz, hour: 5 });
  assert.equal(early.run, false);
  assert.equal(early.reason, "ще рано");
  const due = shouldReportQuarter({ now: new Date("2026-10-01T03:30:00Z"), timeZone: tz, hour: 5 });
  assert.deepEqual([due.run, due.quarter], [true, "2026-Q3"]);
  const sent = shouldReportQuarter({ now: new Date("2026-10-01T06:00:00Z"), timeZone: tz, hour: 5, lastQuarter: "2026-Q3" });
  assert.equal(sent.run, false);
  // Сервер першого числа не працював - звіт іде першим запуском після, а не зникає.
  const late = shouldReportQuarter({ now: new Date("2026-10-03T08:00:00Z"), timeZone: tz, hour: 5, lastQuarter: "2026-Q2" });
  assert.deepEqual([late.run, late.quarter], [true, "2026-Q3"]);
});

test("назва кварталу і розклад змін по місяцях", () => {
  assert.equal(quarterTitle("2026-Q3"), "III квартал 2026 (липень – вересень)");
  assert.equal(quarterTitle("2027-Q1"), "I квартал 2027 (січень – березень)");
  const commits = [
    { subject: "feat: перше", day: "2026-07-03" },
    { subject: "fix: друге", day: "2026-07-20" },
    { subject: "docs: не рахується", day: "2026-08-01" },
    { subject: "change: третє", day: "2026-09-30" },
  ];
  assert.equal(quarterBreakdown("2026-Q3", commits), "Липень: 2 · Серпень: 0 · Вересень: 1");
});

test("команда /kvartal: поточний, минулий і вказаний квартал", () => {
  const now = new Date("2026-10-21T10:00:00Z");
  const opts = { now, timeZone: "Europe/Kyiv" };
  assert.deepEqual(resolveCommand(parseCommand("/kvartal"), opts), { kind: "quarter", quarter: "2026-Q4", partial: true });
  assert.deepEqual(resolveCommand(parseCommand("/kvartal минулий"), opts), { kind: "quarter", quarter: "2026-Q3", partial: false });
  assert.deepEqual(resolveCommand(parseCommand("/kvartal 2026-Q2"), opts), { kind: "quarter", quarter: "2026-Q2", partial: false });
  assert.deepEqual(resolveCommand(parseCommand("/kvartal 2026q4"), opts), { kind: "quarter", quarter: "2026-Q4", partial: true });
  assert.deepEqual(resolveCommand(parseCommand("/kvartal колись"), opts), { kind: "unclear-quarter" });
  assert.match(HELP, /\/kvartal/);
});

test("квартальний звіт запускається службою разом з іншими", () => {
  const compose = readFileSync(new URL("../docker-compose.yml", import.meta.url), "utf8");
  const service = compose.slice(compose.indexOf("  changelog:"));
  for (const run of ["node scripts/changelog.mjs ||", "--month ||", "--quarter ||", "--answer ||"]) {
    assert.ok(service.includes(run), `у службі немає «${run}»`);
  }
  const script = readFileSync(new URL("../scripts/changelog.mjs", import.meta.url), "utf8");
  // Стан кварталу пишеться лише після вдалого надсилання - як і в місячного.
  assert.match(script, /saveState\(statePath, \{ \.\.\.state, lastQuarter: due\.quarter \}\)/);
});
