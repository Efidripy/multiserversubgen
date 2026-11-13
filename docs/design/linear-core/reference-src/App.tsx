import { useState, type ReactNode } from "react";

type IconName =
  | "grid"
  | "server"
  | "users"
  | "chart"
  | "pulse"
  | "link"
  | "bot"
  | "search"
  | "bell"
  | "menu"
  | "arrow"
  | "more"
  | "check"
  | "filter"
  | "receipt";

const paths: Record<IconName, ReactNode> = {
  grid: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="2" />
      <rect x="14" y="3" width="7" height="7" rx="2" />
      <rect x="3" y="14" width="7" height="7" rx="2" />
      <rect x="14" y="14" width="7" height="7" rx="2" />
    </>
  ),
  server: (
    <>
      <rect x="3" y="4" width="18" height="6" rx="2" />
      <rect x="3" y="14" width="18" height="6" rx="2" />
      <path d="M7 7h.01M7 17h.01M11 7h6M11 17h6" />
    </>
  ),
  users: (
    <>
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
    </>
  ),
  chart: (
    <>
      <path d="M4 19V9M10 19V5M16 19v-7M22 19H2" />
    </>
  ),
  pulse: (
    <>
      <path d="M3 12h4l2-7 4 14 2-7h6" />
    </>
  ),
  link: (
    <>
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </>
  ),
  bot: (
    <>
      <rect x="4" y="7" width="16" height="13" rx="3" />
      <path d="M12 3v4M8 12h.01M16 12h.01M8 16h8" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-4-4" />
    </>
  ),
  bell: (
    <>
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
    </>
  ),
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  arrow: (
    <>
      <path d="m7 17 10-10M7 7h10v10" />
    </>
  ),
  more: (
    <>
      <circle cx="5" cy="12" r="1" />
      <circle cx="12" cy="12" r="1" />
      <circle cx="19" cy="12" r="1" />
    </>
  ),
  check: <path d="m5 12 4 4L19 6" />,
  filter: <path d="M4 5h16M7 12h10M10 19h4" />,
  receipt: (
    <>
      <path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3Z" />
      <path d="M9 8h6M9 12h6M9 16h3" />
    </>
  ),
};

function Icon({ name, size = 17 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

type Theme = {
  id: number;
  slug: string;
  name: string;
  source: string;
  note: string;
};

const themes: Theme[] = [
  {
    id: 1,
    slug: "spectrum",
    name: "Spectrum Ops",
    source: "User Management",
    note: "Плотные таблицы и цветные статусы",
  },
  {
    id: 2,
    slug: "linear",
    name: "Linear Core",
    source: "Linear Design System",
    note: "Минимализм и строгая иерархия",
  },
  {
    id: 3,
    slug: "ember",
    name: "Ember Admin",
    source: "Free Admin Dashboard",
    note: "Тёплый orange-accent dark UI",
  },
  {
    id: 4,
    slug: "saasify",
    name: "Saasify Air",
    source: "Saasify UI Kit",
    note: "Воздушный продуктовый интерфейс",
  },
  {
    id: 5,
    slug: "venture",
    name: "Venture Mono",
    source: "Venture CRM",
    note: "Монохромный редакционный стиль",
  },
  {
    id: 6,
    slug: "violet",
    name: "Violet Control",
    source: "Admin Dashboard UI Kit",
    note: "Светлый SaaS с фиолетовым акцентом",
  },
  {
    id: 7,
    slug: "tesla",
    name: "Telemetry",
    source: "Analytics Dashboard",
    note: "Чистая аналитика и яркие графики",
  },
  {
    id: 8,
    slug: "glass",
    name: "Glass Command",
    source: "Sidebar Navigation",
    note: "Стекло, глубина и яркий фон",
  },
  {
    id: 9,
    slug: "rhombus",
    name: "Rhombus Cloud",
    source: "Rhombus Dashboard",
    note: "Мягкие карточки и teal-акцент",
  },
  {
    id: 10,
    slug: "vision",
    name: "Vision Black",
    source: "Marketing Dashboard",
    note: "Контрастный black & mint",
  },
  {
    id: 11,
    slug: "finebank",
    name: "Finebank Navy",
    source: "Financial Dashboard",
    note: "Финансовая точность и navy-палитра",
  },
];

const finalists = themes.filter((theme) => [3, 10, 2].includes(theme.id));

const nav = [
  ["grid", "Панель управления"],
  ["server", "Inbound"],
  ["users", "Клиенты"],
  ["chart", "Статистика"],
  ["pulse", "Мониторинг"],
  ["check", "Резервные копии"],
  ["link", "Подписки"],
  ["bot", "Telegram"],
] as const;

function getPageIcon(page: string): IconName {
  return nav.find(([, label]) => label === page)?.[0] ?? "grid";
}

const servers = [
  {
    name: "RU-5-EKT",
    ip: "192.0.2.11",
    load: 62,
    users: 14,
    traffic: "3.8 TB",
    status: "Работает",
  },
  {
    name: "NL-104-F1",
    ip: "192.0.2.12",
    load: 38,
    users: 9,
    traffic: "2.9 TB",
    status: "Работает",
  },
  {
    name: "DE-65-F3",
    ip: "192.0.2.13",
    load: 81,
    users: 18,
    traffic: "4.7 TB",
    status: "Нагрузка",
  },
  {
    name: "UK-138-LT",
    ip: "192.0.2.14",
    load: 44,
    users: 11,
    traffic: "3.2 TB",
    status: "Работает",
  },
  {
    name: "US-89-LT",
    ip: "192.0.2.15",
    load: 29,
    users: 7,
    traffic: "1.8 TB",
    status: "Работает",
  },
];

const stats = [
  { label: "Серверы", value: "13 / 13", sub: "все онлайн", trend: "+2" },
  { label: "Клиенты", value: "96", sub: "в системе", trend: "+13" },
  { label: "Активные", value: "68", sub: "сейчас", trend: "71%" },
  { label: "Трафик", value: "38.1 TB", sub: "за месяц", trend: "+8.4%" },
];

function ThemeRail({ active, onChange }: { active: number; onChange: (id: number) => void }) {
  return (
    <aside className="concept-rail">
      <div className="rail-head">
        <div className="rail-logo">SM</div>
        <div>
          <strong>3 финалиста</strong>
          <span>Расширенные версии</span>
        </div>
      </div>
      <div className="rail-list">
        {finalists.map((theme) => (
          <button
            key={theme.id}
            className={active === theme.id ? "active" : ""}
            onClick={() => onChange(theme.id)}
          >
            <span className={`theme-swatch swatch-${theme.slug}`}>
              <i />
              <i />
              <i />
            </span>
            <span className="theme-copy">
              <strong>
                {String(theme.id).padStart(2, "0")} · {theme.name}
              </strong>
              <small>{theme.source}</small>
            </span>
            {active === theme.id && <Icon name="check" size={14} />}
          </button>
        ))}
      </div>
      <div className="rail-help">
        Все разделы в каждом варианте кликабельны. Переключайте стиль здесь, а экраны — во
        внутреннем меню.
      </div>
    </aside>
  );
}

function MainNav({
  collapsed,
  onToggle,
  active,
  onSelect,
}: {
  collapsed: boolean;
  onToggle: () => void;
  active: string;
  onSelect: (page: string) => void;
}) {
  const [language, setLanguage] = useState("Русский");
  return (
    <aside className={`admin-nav ${collapsed ? "collapsed" : ""}`}>
      <div className="sidebar-top">
        <span className="version-badge">v3.1</span>
        <button
          className="nav-collapse"
          onClick={onToggle}
          aria-label={collapsed ? "Развернуть меню" : "Свернуть меню"}
          title={collapsed ? "Развернуть меню" : "Свернуть меню"}
        >
          <span>{collapsed ? "›" : "‹"}</span>
        </button>
      </div>
      <nav>
        {nav.map(([icon, label]) => (
          <button
            key={label}
            className={active === label ? "active" : ""}
            onClick={() => onSelect(label)}
            title={collapsed ? label : undefined}
          >
            <Icon name={icon} />
            <span>{label}</span>
            {label === "Клиенты" && <em>96</em>}
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="sidebar-user">
          <span className="user-dot">
            <Icon name="users" size={13} />
          </span>
          <p>
            <strong>root</strong>
            <small>ЯЗЫК</small>
          </p>
        </div>
        <div className="language-switch">
          {["ENGLISH", "Русский"].map((item) => (
            <button
              key={item}
              className={language === item ? "active" : ""}
              onClick={() => setLanguage(item)}
            >
              {item}
            </button>
          ))}
        </div>
        <div className="footer-tools">
          <button>
            <Icon name="menu" size={13} />
            <span>Горячие клавиши</span>
          </button>
          <button>
            <Icon name="receipt" size={13} />
            <span>Activity Log</span>
          </button>
          <button>
            <Icon name="link" size={13} />
            <span>API Docs</span>
          </button>
          <button className="logout-button">
            <Icon name="arrow" size={13} />
            <span>Выход</span>
          </button>
        </div>
        <button className="home-button">
          <Icon name="grid" size={13} />
          <span>Главная</span>
        </button>
      </div>
    </aside>
  );
}

const trafficRanges = {
  "24 часа": {
    value: 2.8,
    unit: "TB",
    change: 8.4,
    labels: ["00:00", "06:00", "12:00", "18:00", "Сейчас"],
  },
  "7 дней": { value: 12.4, unit: "TB", change: 12.7, labels: ["Пн", "Вт", "Ср", "Чт", "Сегодня"] },
  "30 дней": {
    value: 38.1,
    unit: "TB",
    change: 8.4,
    labels: ["1 июн", "7 июн", "14 июн", "21 июн", "28 июн"],
  },
  "12 месяцев": {
    value: 418.6,
    unit: "TB",
    change: 21.3,
    labels: ["Июль", "Окт", "Янв", "Апр", "Июнь"],
  },
};

const compareLabels: Record<string, string> = {
  previous: "Предыдущий период",
  week: "Прошлая неделя",
  month: "Прошлый месяц",
  year: "Год назад",
  none: "Без сравнения",
};

function ComparativeTrafficChart({
  range,
  node,
  compare,
}: {
  range: keyof typeof trafficRanges;
  node: string;
  compare: string;
}) {
  const labels = trafficRanges[range].labels;
  const nodeOffset =
    Math.max(
      0,
      servers.findIndex((item) => item.name === node),
    ) * 6;
  const currentPath = `M0 ${190 - nodeOffset / 2} C45 ${182 - nodeOffset},70 ${157 + nodeOffset / 3},115 ${165 - nodeOffset} S175 ${128 + nodeOffset / 2},220 ${140 - nodeOffset} S290 ${102 + nodeOffset / 2},335 ${114 - nodeOffset / 2} S410 ${77 + nodeOffset / 2},465 ${88 - nodeOffset / 3} S535 ${48 + nodeOffset / 2},590 ${63 - nodeOffset / 3} S690 ${27 + nodeOffset / 3},800 ${31 - nodeOffset / 4}`;
  const comparePath = `M0 ${202 - nodeOffset / 3} C70 ${190 - nodeOffset / 2},100 ${196 - nodeOffset / 2},160 ${176 - nodeOffset / 2} S260 ${166 - nodeOffset / 3},315 ${141 - nodeOffset / 2} S420 ${147 - nodeOffset / 3},490 ${116 - nodeOffset / 2} S590 ${121 - nodeOffset / 3},650 ${94 - nodeOffset / 2} S750 ${82 - nodeOffset / 3},800 ${66 - nodeOffset / 2}`;
  return (
    <div className="traffic-chart comparative-chart">
      <div className="axis">
        <span>40 TB</span>
        <span>30 TB</span>
        <span>20 TB</span>
        <span>10 TB</span>
        <span>0</span>
      </div>
      <svg viewBox="0 0 800 220" preserveAspectRatio="none">
        <defs>
          <linearGradient id="area-current" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--accent)" stopOpacity=".3" />
            <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[15, 62, 109, 156, 203].map((y) => (
          <line key={y} x1="0" x2="800" y1={y} y2={y} stroke="var(--line)" strokeDasharray="4 6" />
        ))}
        <path d={`${currentPath} V220 H0Z`} fill="url(#area-current)" />
        {compare !== "none" && (
          <path
            className="compare-line"
            d={comparePath}
            fill="none"
            stroke="var(--accent-2)"
            strokeWidth="2"
            strokeDasharray="7 5"
          />
        )}
        <path
          d={currentPath}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <line x1="590" x2="590" y1="12" y2="205" stroke="var(--line)" strokeDasharray="3 4" />
        <circle
          cx="590"
          cy={63 - nodeOffset / 3}
          r="5"
          fill="var(--surface)"
          stroke="var(--accent)"
          strokeWidth="3"
        />
      </svg>
      <div className="chart-labels">
        {labels.map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>
      <div className="traffic-tooltip">
        <span>{labels[3]}</span>
        <strong>
          {node === "Все ноды" ? "29.7 TB" : `${(5.9 + nodeOffset / 10).toFixed(1)} TB`}
        </strong>
        <small>+{trafficRanges[range].change}% к сравнению</small>
      </div>
    </div>
  );
}

function TrafficAnalytics() {
  const [range, setRange] = useState<keyof typeof trafficRanges>("30 дней");
  const [node, setNode] = useState("Все ноды");
  const [compare, setCompare] = useState("previous");
  const base = trafficRanges[range];
  const nodeIndex = servers.findIndex((item) => item.name === node);
  const factor = nodeIndex < 0 ? 1 : [0.17, 0.14, 0.21, 0.12, 0.09][nodeIndex];
  const current = base.value * factor;
  const previous = current / (1 + base.change / 100);
  return (
    <article className="dash-card chart-card traffic-analytics-card">
      <div className="card-head traffic-head">
        <div>
          <span>ОБЩИЙ ТРАФИК</span>
        </div>
        <div className="traffic-controls">
          <label>
            <select aria-label="Выбор ноды" value={node} onChange={(e) => setNode(e.target.value)}>
              <option>Все ноды</option>
              {servers.map((item) => (
                <option key={item.name}>{item.name}</option>
              ))}
            </select>
          </label>
          <label>
            <select
              aria-label="Период сравнения"
              value={compare}
              onChange={(e) => setCompare(e.target.value)}
            >
              {Object.entries(compareLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <div className="range-tabs">
            {(Object.keys(trafficRanges) as Array<keyof typeof trafficRanges>).map((item) => (
              <button
                key={item}
                className={range === item ? "active" : ""}
                onClick={() => setRange(item)}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
      </div>
      <ComparativeTrafficChart range={range} node={node} compare={compare} />
      <div className="traffic-summary-row traffic-underbar">
        <div className="period-summary current-period">
          <span>ТЕКУЩИЙ ПЕРИОД</span>
          <p>
            <strong>
              {current.toFixed(1)} {base.unit}
            </strong>
            <em>↑ {base.change}%</em>
          </p>
          <small>входящий и исходящий трафик</small>
        </div>
        <div className={`period-summary previous-period ${compare === "none" ? "disabled" : ""}`}>
          {compare !== "none" ? (
            <>
              <span>{compareLabels[compare].toUpperCase()}</span>
              <p>
                <strong>
                  {previous.toFixed(1)} {base.unit}
                </strong>
              </p>
              <small>
                − {(current - previous).toFixed(1)} {base.unit} разницы
              </small>
            </>
          ) : (
            <>
              <span>СРАВНЕНИЕ</span>
              <p>
                <strong>Выключено</strong>
              </p>
              <small>выберите период в меню</small>
            </>
          )}
        </div>
        <div className="chart-legend">
          <span>
            <i />
            Текущий период
          </span>
          {compare !== "none" && (
            <span>
              <i className="previous" /> {compareLabels[compare]}
            </span>
          )}
        </div>
      </div>
    </article>
  );
}

function UserTrafficRanking() {
  const [scope, setScope] = useState("Текущий");
  const users = [
    ["d632-pc", 3.5, 2.8, 18.4],
    ["krasnikov", 2.4, 2.7, -6.2],
    ["alexandrp", 2.3, 1.9, 11.8],
    ["alex12", 1.7, 1.5, 7.3],
    ["shatoon", 1.7, 1.8, -2.6],
    ["mashka_a", 1.5, 1.2, 14.2],
    ["ALEXANDRA", 1.3, 1.4, -4.8],
    ["andrey-bekezov", 1.2, 0.9, 16.1],
    ["ANNAMARTEZOO", 1.1, 0.8, 13.7],
    ["ALDIK2", 0.9, 1.0, -5.4],
  ] as const;
  return (
    <article className="dash-card user-traffic-card">
      <div className="card-head">
        <div>
          <span>ПОЛЬЗОВАТЕЛИ</span>
          <h2>Топ по трафику</h2>
          <p>Текущий период относительно прошлого</p>
        </div>
        <button>
          <Icon name="more" size={17} />
        </button>
      </div>
      <div className="ranking-tabs">
        {["Текущий", "Рост"].map((item) => (
          <button
            key={item}
            className={scope === item ? "active" : ""}
            onClick={() => setScope(item)}
          >
            {item}
          </button>
        ))}
      </div>
      <div className="ranking-legend">
        <span>
          <i />
          Текущий
        </span>
        <span>
          <i />
          Прошлый период
        </span>
      </div>
      <div className="user-ranking-list">
        {users.map((user, index) => {
          const max = 3.5;
          const currentWidth =
            scope === "Рост" ? Math.max(20, 50 + user[3] * 2) : (user[1] / max) * 100;
          return (
            <div className="user-rank-row" key={user[0]}>
              <span className="rank-number">{index + 1}</span>
              <button>{user[0]}</button>
              <div className="rank-bars">
                <i className="previous-bar" style={{ width: `${(user[2] / max) * 100}%` }} />
                <i className="current-bar" style={{ width: `${currentWidth}%` }} />
              </div>
              <strong>{user[1]} TB</strong>
              <em className={user[3] < 0 ? "down" : ""}>
                {user[3] > 0 ? "↑" : "↓"} {Math.abs(user[3])}%
              </em>
            </div>
          );
        })}
      </div>
      <div className="ranking-total">
        <div>
          <span>Топ-10 используют</span>
          <strong>17.9 TB</strong>
        </div>
        <div>
          <span>Доля общего трафика</span>
          <strong>46.9%</strong>
        </div>
      </div>
    </article>
  );
}

function ServerTable({ onOpen }: { onOpen: (server: (typeof servers)[number]) => void }) {
  return (
    <div className="server-table">
      <div className="server-row server-labels">
        <span>СЕРВЕР</span>
        <span>IP-АДРЕС</span>
        <span>ЗАГРУЗКА</span>
        <span>КЛИЕНТЫ</span>
        <span>ТРАФИК</span>
        <span>СТАТУС</span>
        <span />
      </div>
      {servers.map((server, index) => (
        <div className="server-row" key={server.name}>
          <span className="server-name">
            <i>{index + 1}</i>
            <strong>{server.name}</strong>
          </span>
          <span className="mono">{server.ip}</span>
          <span className="load">
            <i>
              <b style={{ width: `${server.load}%` }} />
            </i>
            <small>{server.load}%</small>
          </span>
          <strong>{server.users}</strong>
          <span>{server.traffic}</span>
          <span className={`status ${server.status === "Нагрузка" ? "warning" : ""}`}>
            <i />
            {server.status}
          </span>
          <button onClick={() => onOpen(server)} aria-label={`Открыть ${server.name}`}>
            <Icon name="more" size={16} />
          </button>
        </div>
      ))}
    </div>
  );
}

function ServerStatusToolbar() {
  const [sort, setSort] = useState("name");
  const [checking, setChecking] = useState(false);
  return (
    <div className="server-status-toolbar">
      <div className="status-title">
        <h3>СТАТУС СЕРВЕРОВ</h3>
        <strong>13/13 online</strong>
        <em>active</em>
      </div>
      <div className="server-sort">
        <span>Sort:</span>
        {["name", "cpu", "status", "clients"].map((item) => (
          <button
            key={item}
            className={sort === item ? "active" : ""}
            onClick={() => setSort(item)}
          >
            {item}
          </button>
        ))}
      </div>
      <div className="fleet-commands">
        <button className="restart-command">Перезапустить весь Xray</button>
        <button
          onClick={() => {
            setChecking(true);
            window.setTimeout(() => setChecking(false), 1000);
          }}
        >
          {checking ? "Обновляем…" : "Обновить все geofile"}
        </button>
        <button>Копировать сводку</button>
      </div>
      <div className="fleet-stat-badges">
        <span className="ok">
          Online: <b>13/13</b>
        </span>
        <span className="warn">
          Проверка: <b>0</b>
        </span>
        <span className="bad">
          Offline: <b>0</b>
        </span>
        <span className="ok">
          Средний CPU: <b>4.3%</b>
        </span>
        <span className="ok">
          RAM флота: <b>7.6 GB/17.9 GB</b>
        </span>
        <span>
          Клиентов онлайн: <b>60</b>
        </span>
      </div>
    </div>
  );
}

function ServerCards({ onOpen }: { onOpen: (server: (typeof servers)[number]) => void }) {
  const [menu, setMenu] = useState<string | null>(null);
  const cpu = [2.61, 4.32, 7.18, 3.04, 5.67];
  const ram = [65.94, 43.2, 71.8, 38.6, 56.1];
  const disk = [53.74, 41.8, 67.2, 35.9, 48.3];
  return (
    <div className="server-card-grid">
      {servers.map((server, index) => (
        <article className="server-tile" key={server.name}>
          <div className="tile-head node-tile-head">
            <i className="online-dot" />
            <div>
              <strong>{server.name}</strong>
              <small>
                3.{index % 2 ? "11.0" : "8.5"} · {server.ip}
              </small>
            </div>
            <span className="online-label">online</span>
            <button onClick={() => setMenu(menu === server.name ? null : server.name)}>
              <Icon name="more" size={16} />
            </button>
            {menu === server.name && (
              <div className="context-menu">
                <button onClick={() => onOpen(server)}>Открыть детали</button>
                <button>Редактировать</button>
                <button>Перезапустить</button>
                <button className="danger-item">Остановить</button>
              </div>
            )}
          </div>
          <div className="tile-bars">
            <div>
              <span>Использование ЦП</span>
              <i>
                <b style={{ width: `${Math.max(cpu[index], 5)}%` }} />
              </i>
              <strong>{cpu[index]}%</strong>
            </div>
            <div>
              <span>Использование ОЗУ</span>
              <i>
                <b style={{ width: `${ram[index]}%` }} />
              </i>
              <strong>
                {ram[index]}% <small>{633 + index * 81}.8 MB/961.2 MB</small>
              </strong>
            </div>
            <div>
              <span>Использование диска</span>
              <i>
                <b style={{ width: `${disk[index]}%` }} />
              </i>
              <strong>
                {disk[index]}% <small>{3 + index}.6 GB/6.8 GB</small>
              </strong>
            </div>
          </div>
          <div className="node-system-stats">
            <span>
              <small>NET</small>
              <strong>
                {42 + index * 8}.5 KB / {38 + index * 3}…
              </strong>
            </span>
            <span>
              <small>UPTIME</small>
              <strong>
                {14 + index}h {57 - index * 4}m
              </strong>
            </span>
            <span>
              <small>LOAD</small>
              <strong>
                0.{15 + index} / 0.{10 + index}
              </strong>
            </span>
            <span>
              <small>SWAP</small>
              <strong>{4 + index}.5 MB/512.0…</strong>
            </span>
            <span>
              <small>TCP RTT</small>
              <strong className="rtt">{47 + index * 3}.19 ms</strong>
            </span>
            <span>
              <small>SEEN</small>
              <strong>11:{57 - index * 3} PM</strong>
            </span>
          </div>
          <div className="node-core-row">
            <span>
              Core 26.7.28{" "}
              <i>
                <Icon name="check" size={10} />
              </i>
            </span>
            <div>
              <button title="Перезапустить">↻</button>
              <button title="Остановить">□</button>
              <button onClick={() => onOpen(server)}>Логи</button>
            </div>
          </div>
          <div className="node-action-row">
            <button title="Запустить">▷</button>
            <button title="Клиенты">
              <Icon name="users" size={11} />
            </button>
            <button title="Копировать">
              <Icon name="receipt" size={11} />
            </button>
            <button title="Ключ">
              <Icon name="link" size={11} />
            </button>
            <button title="График">
              <Icon name="chart" size={11} />
            </button>
            <button title="Защита">
              <Icon name="check" size={11} />
            </button>
            <button title="Отчёт">
              <Icon name="menu" size={11} />
            </button>
            <button title="Настройки">
              <Icon name="filter" size={11} />
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}

function Overlay({ onClose }: { onClose: () => void }) {
  return <button className="ui-overlay" onClick={onClose} aria-label="Закрыть" />;
}

function AddServerModal({ onClose, onSubmit }: { onClose: () => void; onSubmit: () => void }) {
  const [step, setStep] = useState(1);
  const [protocol, setProtocol] = useState("VLESS");
  return (
    <div className="modal-wrap">
      <Overlay onClose={onClose} />
      <div className="server-modal" role="dialog" aria-modal="true" aria-label="Добавить сервер">
        <div className="modal-head">
          <div>
            <span>НОВЫЙ УЗЕЛ</span>
            <h2>Добавить сервер</h2>
            <p>
              Шаг {step} из 2 · {step === 1 ? "Подключение" : "Конфигурация"}
            </p>
          </div>
          <button onClick={onClose}>×</button>
        </div>
        <div className="step-line">
          <i className="done" />
          <i className={step === 2 ? "done" : ""} />
        </div>
        {step === 1 ? (
          <div className="modal-body">
            <label>
              <span>Название сервера</span>
              <input defaultValue="DE-NEW-01" />
            </label>
            <div className="field-row">
              <label>
                <span>IP-адрес</span>
                <input placeholder="0.0.0.0" />
              </label>
              <label>
                <span>SSH-порт</span>
                <input defaultValue="22" />
              </label>
            </div>
            <label>
              <span>Регион</span>
              <select defaultValue="DE">
                <option value="DE">Германия · Frankfurt</option>
                <option value="NL">Нидерланды · Amsterdam</option>
                <option value="RU">Россия · Екатеринбург</option>
              </select>
            </label>
            <div className="connection-test">
              <span>
                <Icon name="pulse" size={16} />
              </span>
              <div>
                <strong>Проверка подключения</strong>
                <small>Убедимся, что сервер доступен по SSH</small>
              </div>
              <button>Проверить</button>
            </div>
          </div>
        ) : (
          <div className="modal-body">
            <span className="field-label">Основной протокол</span>
            <div className="protocol-select">
              {["VLESS", "Trojan", "Shadowsocks"].map((item) => (
                <button
                  key={item}
                  className={protocol === item ? "active" : ""}
                  onClick={() => setProtocol(item)}
                >
                  <span>
                    <Icon name="link" size={15} />
                  </span>
                  <strong>{item}</strong>
                  <small>{item === "VLESS" ? "Reality + XTLS" : "Стандартная схема"}</small>
                </button>
              ))}
            </div>
            <div className="field-row">
              <label>
                <span>Лимит клиентов</span>
                <input defaultValue="100" />
              </label>
              <label>
                <span>Лимит трафика</span>
                <input defaultValue="Без лимита" />
              </label>
            </div>
            <label className="toggle-line">
              <span>
                <strong>Установить AdGuard DNS</strong>
                <small>Автоматически настроить фильтрацию</small>
              </span>
              <input type="checkbox" defaultChecked />
            </label>
            <label className="toggle-line">
              <span>
                <strong>Включить мониторинг</strong>
                <small>CPU, RAM, диски и uptime</small>
              </span>
              <input type="checkbox" defaultChecked />
            </label>
          </div>
        )}
        <div className="modal-foot">
          <button className="ghost-button" onClick={step === 1 ? onClose : () => setStep(1)}>
            {step === 1 ? "Отмена" : "Назад"}
          </button>
          <button className="accent-button" onClick={step === 1 ? () => setStep(2) : onSubmit}>
            {step === 1 ? "Продолжить" : "Создать сервер"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ServerDrawer({
  server,
  onClose,
}: {
  server: (typeof servers)[number];
  onClose: () => void;
}) {
  const [tab, setTab] = useState("Обзор");
  return (
    <div className="drawer-wrap">
      <Overlay onClose={onClose} />
      <aside className="detail-drawer">
        <div className="drawer-head">
          <div>
            <span className="status">
              <i />
              ONLINE
            </span>
            <h2>{server.name}</h2>
            <p>{server.ip} · Frankfurt, DE</p>
          </div>
          <button onClick={onClose}>×</button>
        </div>
        <div className="drawer-actions">
          <button className="accent-button">Редактировать</button>
          <button className="ghost-button">Перезапустить</button>
          <button className="ghost-button">
            <Icon name="more" size={14} />
          </button>
        </div>
        <div className="drawer-tabs">
          {["Обзор", "Клиенты", "События"].map((item) => (
            <button
              key={item}
              className={tab === item ? "active" : ""}
              onClick={() => setTab(item)}
            >
              {item}
            </button>
          ))}
        </div>
        {tab === "Обзор" && (
          <div className="drawer-body">
            <div className="drawer-score">
              <div>
                <strong>99.98%</strong>
                <span>UPTIME</span>
              </div>
              <p>
                <strong>20д 11ч 42м</strong>
                <small>Последний рестарт 8 июня</small>
              </p>
            </div>
            <div className="drawer-metrics">
              {[
                ["CPU", `${server.load}%`, server.load],
                ["RAM", "4.9 / 8 GB", 62],
                ["Диск", "54 / 160 GB", 34],
                ["Сеть", "29.5 ms", 48],
              ].map((x) => (
                <div key={x[0]}>
                  <span>{x[0]}</span>
                  <strong>{x[1]}</strong>
                  <i>
                    <b style={{ width: `${x[2]}%` }} />
                  </i>
                </div>
              ))}
            </div>
            <div className="drawer-section">
              <div className="card-head">
                <div>
                  <span>ТРАФИК</span>
                  <h2>Последние 24 часа</h2>
                </div>
                <strong>{server.traffic}</strong>
              </div>
              <svg viewBox="0 0 400 100" preserveAspectRatio="none">
                <path
                  d="M0 85 C35 82 50 55 85 68 S140 34 175 48 S230 25 265 42 S330 9 400 22 V100 H0Z"
                  fill="color-mix(in srgb,var(--accent) 15%,transparent)"
                />
                <path
                  d="M0 85 C35 82 50 55 85 68 S140 34 175 48 S230 25 265 42 S330 9 400 22"
                  fill="none"
                  stroke="var(--accent)"
                  strokeWidth="2"
                />
              </svg>
            </div>
            <div className="drawer-info">
              {[
                ["Провайдер", "Hetzner Cloud"],
                ["Версия ядра", "6.8.0-31"],
                ["Inbound", "4 активных"],
                ["Клиентов", String(server.users)],
              ].map((x) => (
                <div key={x[0]}>
                  <span>{x[0]}</span>
                  <strong>{x[1]}</strong>
                </div>
              ))}
            </div>
          </div>
        )}
        {tab === "Клиенты" && (
          <div className="drawer-body drawer-client-list">
            {clients.slice(0, 5).map((c) => (
              <div key={c[0]}>
                <span className="client-cell">
                  <i>{c[0][0]}</i>
                  <strong>{c[0]}</strong>
                </span>
                <span className="status">
                  <i />
                  online
                </span>
                <strong>{c[3]}</strong>
              </div>
            ))}
          </div>
        )}
        {tab === "События" && (
          <div className="drawer-body timeline">
            {[
              "Конфигурация синхронизирована",
              "Пиковая нагрузка CPU: 81%",
              "Клиент ALEXANDRA подключён",
              "Резервная копия создана",
            ].map((x, i) => (
              <div key={x}>
                <i />
                <span>
                  <strong>{x}</strong>
                  <small>{i * 3 + 2} ч назад · system</small>
                </span>
              </div>
            ))}
          </div>
        )}
      </aside>
    </div>
  );
}

const clients = [
  ["mashka_a", "RU-5-EKT", "Активен", "8.46 GB", "Без лимита", "1 мин"],
  ["ALEXANDRA", "NL-104-F1", "Активен", "9.91 GB", "Без лимита", "3 мин"],
  ["ALEXANDER", "DE-65-F3", "Активен", "4.18 GB", "Без лимита", "8 мин"],
  ["ALDIK2", "UK-138-LT", "Истекает", "17.97 GB", "30 июня", "12 мин"],
  ["ANDREYVP", "RU-5-EKT", "Активен", "6.32 GB", "Без лимита", "18 мин"],
  ["andrey-bekezov", "US-89-LT", "Активен", "12.70 GB", "Без лимита", "24 мин"],
  ["ANNA", "NL-104-F1", "Пауза", "2.14 GB", "12 июля", "1 час"],
  ["ANNAMARTEZOO", "DE-65-F3", "Активен", "7.08 GB", "Без лимита", "2 часа"],
];

const fleetNodes = [
  ["EE 5-EST", "3.8.5", "https://ebola.shrinkface.dev/6g8fr0oz7fi"],
  ["FI 164-FI", "3.11.0", "https://depression.shrinkface.dev/RHhAXm2QNU"],
  ["FI 45-FI", "3.8.5", "https://asthma.shrinkface.dev/AUGCEDvRQ3"],
  ["LT 185-LT", "3.8.5", "https://migraine.shrinkface.dev/Za7LJpEDMQ"],
  ["LT 80-LT", "3.11.0", "https://anxiety.shrinkface.dev/J304Kuo4Li"],
  ["NL 146-AM-E", "3.8.5", "https://mers-cov.shrinkface.dev/Zl0CKMp1L"],
  ["NL 195-AM", "3.8.5", "https://h1n1.shrinkface.dev/9CdoeHqtAX"],
  ["PL 91-PL", "3.8.5", "https://nipax.shrinkface.dev/MokuKzvaA7"],
  ["RU 185-RF-E", "3.8.5", "https://cholera.shrinkface.dev/x7LaB1Loh2"],
  ["RU 45-RF", "3.11.0", "https://first.shrinkface.dev/tzC2b6pfqu"],
  ["RU 88-RF", "3.8.5", "https://anaemia.kleva.ru"],
  ["RU 94-RF", "3.8.5", "https://dev.kleva.ru"],
  ["TR 5-TR", "3.11.0", "https://probe.shrinkface.dev/e0hd3dztzi"],
];

function FleetPanel({ onClose, onOpen }: { onClose: () => void; onOpen: (index: number) => void }) {
  const [query, setQuery] = useState("");
  const [checking, setChecking] = useState(false);
  const filtered = fleetNodes.filter((node) => node[0].toLowerCase().includes(query.toLowerCase()));
  return (
    <div className="fleet-wrap">
      <button className="fleet-screen" onClick={onClose} aria-label="Закрыть парк" />
      <aside className="fleet-panel">
        <button className="fleet-close-handle" onClick={onClose} aria-label="Закрыть парк">
          <span>→</span>
        </button>
        <div className="fleet-top">
          <div>
            <span>ЗАРЕГИСТРИРОВАННЫЙ ПАРК</span>
            <div>
              <em>Online: 13</em>
              <em>Error: 0</em>
              <em>Offline: 0</em>
            </div>
          </div>
          <button
            className={checking ? "checking" : ""}
            onClick={() => {
              setChecking(true);
              window.setTimeout(() => setChecking(false), 1300);
            }}
          >
            {checking ? "Проверяем…" : "Проверить все"}
          </button>
        </div>
        <p className="fleet-description">
          Изменяйте параметры подключения узлов или удаляйте устаревшие записи панели.
        </p>
        <label className="fleet-search">
          <Icon name="search" size={14} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Найти узел…"
          />
          <kbd>{filtered.length}</kbd>
        </label>
        <div className="fleet-list">
          {filtered.map((node, index) => (
            <article className="fleet-node" key={node[0]}>
              <div className="fleet-node-head">
                <i />
                <strong>{node[0]}</strong>
                <small>{node[1]}</small>
                <button onClick={() => onOpen(index)}>
                  <Icon name="more" size={14} />
                </button>
              </div>
              <a href={node[2]} onClick={(e) => e.preventDefault()}>
                {node[2]}
              </a>
              <div className="fleet-tags">
                <span>online</span>
                <em>XUI</em>
                <em>RW</em>
              </div>
              <div className="fleet-actions">
                <button title="Открыть">
                  <Icon name="arrow" size={12} />
                </button>
                <button title="Клиенты">
                  <Icon name="users" size={12} />
                </button>
                <button title="Статистика">
                  <Icon name="chart" size={12} />
                </button>
                <button title="Настройки">
                  <Icon name="filter" size={12} />
                </button>
                <button title="Копировать">
                  <Icon name="link" size={12} />
                </button>
                <span>TG</span>
              </div>
            </article>
          ))}
        </div>
        <footer>
          <span>
            <i /> {filtered.length} узлов онлайн
          </span>
          <button onClick={onClose}>Закрыть панель</button>
        </footer>
      </aside>
    </div>
  );
}

function PageTitle(_: {
  eyebrow: string;
  title: string;
  text: string;
  action?: string;
  onAction?: () => void;
}) {
  return null;
}

function CreateEntityModal({
  kind,
  onClose,
}: {
  kind: "inbound" | "client" | "subscription";
  onClose: () => void;
}) {
  const config = {
    inbound: {
      eyebrow: "НОВАЯ КОНФИГУРАЦИЯ",
      title: "Добавить inbound",
      fields: ["Тег конфигурации", "Порт", "SNI / Server Name"],
    },
    client: {
      eyebrow: "НОВЫЙ ПОЛЬЗОВАТЕЛЬ",
      title: "Добавить клиента",
      fields: ["Имя клиента", "Telegram username", "Лимит трафика"],
    },
    subscription: {
      eyebrow: "НОВАЯ ССЫЛКА",
      title: "Создать подписку",
      fields: ["Название", "Срок действия", "Лимит устройств"],
    },
  }[kind];
  const [server, setServer] = useState(servers[0].name);
  const [advanced, setAdvanced] = useState(false);
  return (
    <div className="modal-wrap">
      <Overlay onClose={onClose} />
      <div className="entity-modal">
        <div className="modal-head">
          <div>
            <span>{config.eyebrow}</span>
            <h2>{config.title}</h2>
            <p>Заполните основные параметры</p>
          </div>
          <button onClick={onClose}>×</button>
        </div>
        <div className="modal-body entity-form">
          <label>
            <span>{config.fields[0]}</span>
            <input placeholder={kind === "client" ? "Например, alexander" : "Введите значение"} />
          </label>
          <div className="field-row">
            <label>
              <span>{config.fields[1]}</span>
              <input placeholder={kind === "inbound" ? "443" : "Необязательно"} />
            </label>
            <label>
              <span>{config.fields[2]}</span>
              <input placeholder="Без лимита" />
            </label>
          </div>
          <label>
            <span>Сервер</span>
            <select value={server} onChange={(e) => setServer(e.target.value)}>
              {servers.map((item) => (
                <option key={item.name}>{item.name}</option>
              ))}
            </select>
          </label>
          <div className="select-cards">
            {(kind === "inbound"
              ? ["VLESS", "Trojan", "Shadowsocks"]
              : kind === "client"
                ? ["Стандарт", "Команда", "Безлимит"]
                : ["30 дней", "90 дней", "Без срока"]
            ).map((item, i) => (
              <button key={item} className={i === 0 ? "active" : ""}>
                <i>{i + 1}</i>
                <span>
                  <strong>{item}</strong>
                  <small>{i === 0 ? "Рекомендуется" : "Дополнительный вариант"}</small>
                </span>
              </button>
            ))}
          </div>
          <button className="advanced-toggle" onClick={() => setAdvanced(!advanced)}>
            <span>Расширенные настройки</span>
            <strong>{advanced ? "−" : "+"}</strong>
          </button>
          {advanced && (
            <div className="advanced-panel">
              <label className="toggle-line">
                <span>
                  <strong>Автоматическое продление</strong>
                  <small>Продлевать при завершении срока</small>
                </span>
                <input type="checkbox" defaultChecked />
              </label>
              <label className="toggle-line">
                <span>
                  <strong>Уведомления</strong>
                  <small>Отправлять события в Telegram</small>
                </span>
                <input type="checkbox" defaultChecked />
              </label>
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button className="ghost-button" onClick={onClose}>
            Отмена
          </button>
          <button className="accent-button" onClick={onClose}>
            Создать
          </button>
        </div>
      </div>
    </div>
  );
}

function ClientDrawer({ client, onClose }: { client: string[]; onClose: () => void }) {
  const [tab, setTab] = useState("Профиль");
  return (
    <div className="drawer-wrap">
      <Overlay onClose={onClose} />
      <aside className="detail-drawer client-drawer">
        <div className="drawer-head">
          <div className="client-hero">
            <span>{client[0][0]}</span>
            <div>
              <span className="status">
                <i />
                ONLINE
              </span>
              <h2>{client[0]}</h2>
              <p>UUID · 842a…7f91</p>
            </div>
          </div>
          <button onClick={onClose}>×</button>
        </div>
        <div className="drawer-actions">
          <button className="accent-button">Продлить</button>
          <button className="ghost-button">Редактировать</button>
          <button className="ghost-button">
            <Icon name="more" size={14} />
          </button>
        </div>
        <div className="drawer-tabs">
          {["Профиль", "Трафик", "Сессии"].map((item) => (
            <button
              key={item}
              className={tab === item ? "active" : ""}
              onClick={() => setTab(item)}
            >
              {item}
            </button>
          ))}
        </div>
        {tab === "Профиль" && (
          <div className="drawer-body">
            <div className="client-plan">
              <span>ТЕКУЩИЙ ПЛАН</span>
              <div>
                <strong>Безлимитный доступ</strong>
                <em>Активен</em>
              </div>
              <p>Действует до 12 июля 2025</p>
              <i>
                <b style={{ width: "68%" }} />
              </i>
              <small>Осталось 20 дней</small>
            </div>
            <div className="drawer-info">
              {[
                ["Сервер", client[1]],
                ["Inbound", "vless-reality"],
                ["Трафик", client[3]],
                ["Telegram", "@" + client[0].toLowerCase()],
                ["Создан", "14 мая 2025"],
                ["Последняя активность", client[5] + " назад"],
              ].map((x) => (
                <div key={x[0]}>
                  <span>{x[0]}</span>
                  <strong>{x[1]}</strong>
                </div>
              ))}
            </div>
            <div className="qr-placeholder">
              <div>
                <i />
                <i />
                <i />
                <i />
                <i />
                <i />
                <i />
                <i />
                <i />
              </div>
              <span>
                <strong>Ссылка подписки</strong>
                <small>Отсканируйте QR-код или скопируйте URL</small>
                <button>Копировать ссылку</button>
              </span>
            </div>
          </div>
        )}
        {tab === "Трафик" && (
          <div className="drawer-body">
            <div className="client-traffic-total">
              <span>ИСПОЛЬЗОВАНО</span>
              <strong>{client[3]}</strong>
              <small>за последние 30 дней</small>
            </div>
            <div className="drawer-section">
              <svg viewBox="0 0 400 140" preserveAspectRatio="none">
                <path
                  d="M0 120 C45 110 65 70 105 88 S170 55 210 72 S275 25 320 49 S365 20 400 30 V140 H0Z"
                  fill="color-mix(in srgb,var(--accent) 15%,transparent)"
                />
                <path
                  d="M0 120 C45 110 65 70 105 88 S170 55 210 72 S275 25 320 49 S365 20 400 30"
                  fill="none"
                  stroke="var(--accent)"
                  strokeWidth="2"
                />
              </svg>
            </div>
          </div>
        )}
        {tab === "Сессии" && (
          <div className="drawer-body session-list">
            {[
              ["iPhone 15 Pro", "192.0.2.16", "Сейчас"],
              ["MacBook Pro", "192.0.2.16", "12 мин"],
              ["Windows PC", "192.0.2.17", "2 дня"],
            ].map((x) => (
              <div key={x[0]}>
                <span>
                  <Icon name="pulse" size={15} />
                </span>
                <p>
                  <strong>{x[0]}</strong>
                  <small>{x[1]}</small>
                </p>
                <em>{x[2]}</em>
                <button>×</button>
              </div>
            ))}
          </div>
        )}
      </aside>
    </div>
  );
}

function FilterStrip({ tags }: { tags: string[] }) {
  const [selected, setSelected] = useState(tags[0]);
  return (
    <div className="filter-strip">
      <label>
        <Icon name="search" size={14} />
        <input placeholder="Поиск по разделу..." />
      </label>
      <div className="filter-tags">
        {tags.map((tag) => (
          <button
            key={tag}
            className={selected === tag ? "active" : ""}
            onClick={() => setSelected(tag)}
          >
            {tag}
          </button>
        ))}
      </div>
      <button className="ghost-button">
        <Icon name="filter" size={13} />
        Ещё фильтры
      </button>
    </div>
  );
}

function InboundPage() {
  const [createOpen, setCreateOpen] = useState(false);
  return (
    <>
      <PageTitle
        eyebrow="УПРАВЛЕНИЕ INBOUND"
        title="Входящие подключения"
        text="Маршруты, протоколы и параметры подключений на всех серверах"
        action="Добавить inbound"
        onAction={() => setCreateOpen(true)}
      />
      <div className="snapshot-stamp">СНИМОК ПОЛУЧЕН · 11:45:21 PM</div>
      <section className="dash-card inbound-summary">
        <div>
          <span>ВСЕГО</span>
          <strong>51</strong>
        </div>
        <div>
          <span>ВКЛЮЧЕНО</span>
          <strong className="positive">14</strong>
        </div>
        <div>
          <span>ОТКЛЮЧЕНО</span>
          <strong className="negative">37</strong>
        </div>
        <div className="summary-pills">
          <span>ПРОТОКОЛ</span>
          <p>
            <em>
              vless <b>39</b>
            </em>
            <em>
              trojan <b>11</b>
            </em>
            <em>
              http <b>1</b>
            </em>
          </p>
        </div>
        <div className="summary-pills">
          <span>БЕЗОПАСНОСТЬ</span>
          <p>
            <em>
              reality <b>13</b>
            </em>
            <em>
              none <b>38</b>
            </em>
          </p>
        </div>
      </section>
      <section className="dash-card control-card">
        <div className="card-head">
          <div>
            <span>ФИЛЬТР</span>
            <h2>Протоколы, безопасность и узлы</h2>
          </div>
        </div>
        <FilterStrip tags={["Все протоколы", "VLESS", "TROJAN", "HTTP"]} />
        <div className="inbound-filter-row">
          <div>
            <button className="active">Вся безопасность</button>
            <button>reality</button>
            <button>none</button>
          </div>
          <label>
            <input type="checkbox" /> Только пустые
          </label>
        </div>
        <div className="protocol-row">
          <span>Узлы:</span>
          <button className="active">Все узлы</button>
          {servers.map((server) => (
            <button key={server.name}>{server.name}</button>
          ))}
        </div>
        <div className="inbound-filter-row">
          <div>
            <button>Все</button>
            <button className="active">Активные</button>
            <button>Отключено</button>
          </div>
          <button>Дублировать</button>
          <button className="reset-control">Сбросить фильтры</button>
        </div>
      </section>
      <section className="dash-card inbound-actions">
        <div className="selected-count">
          <span>ВЫБРАНО: 0</span>
          <button>Выбрать все</button>
        </div>
        <div>
          <span>ДЕЙСТВИЯ</span>
          <p>
            <button className="success-action" onClick={() => setCreateOpen(true)}>
              + Добавить inbound
            </button>
            <button className="primary-action">Обновить</button>
          </p>
        </div>
        <label>
          <span>ОБЩИЙ REMARK</span>
          <input placeholder="Опционально · новый remark" />
          <i />
        </label>
        <div>
          <span>РЕЖИМ ENABLE</span>
          <p>
            <button>Массово включить</button>
            <button>Массово отключить</button>
            <button className="danger-action">Массовое удаление</button>
          </p>
        </div>
        <footer>
          <button>Сбросить выбранные</button>
          <button className="danger-action">Сбросить весь трафик</button>
          <button>Импорт JSON</button>
          <button>Экспорт JSON</button>
          <button>CSV</button>
        </footer>
      </section>
      <section className="dash-card data-section">
        <div className="card-head">
          <div>
            <span>51 ЗАПИСЬ</span>
            <h2>Inbound-конфигурации</h2>
          </div>
          <button className="ghost-button">Колонки</button>
        </div>
        <div className="ops-table inbound-table">
          <div className="ops-row ops-labels">
            <span>
              <input type="checkbox" />
            </span>
            <span>ТЕГ</span>
            <span>СЕРВЕР</span>
            <span>ПОРТ</span>
            <span>ПРОТОКОЛ</span>
            <span>ТРАНСПОРТ</span>
            <span>БЕЗОПАСНОСТЬ</span>
            <span>СТАТУС</span>
            <span />
          </div>
          {servers.concat(servers.slice(0, 3)).map((server, i) => (
            <div className="ops-row" key={`${server.name}-${i}`}>
              <span>
                <input type="checkbox" />
              </span>
              <strong>{i % 2 ? "vless-reality" : "mobile-main"}</strong>
              <span>{server.name}</span>
              <span className="mono">{443 + i * 10}</span>
              <span>
                <em className="data-badge">VLESS</em>
              </span>
              <span>{i % 2 ? "tcp" : "grpc"}</span>
              <span>
                <em className="success-badge">Reality</em>
              </span>
              <span className="status">
                <i />
                Активен
              </span>
              <div className="row-actions">
                <button title="Редактировать">
                  <Icon name="filter" size={12} />
                </button>
                <button title="Клиенты">
                  <Icon name="users" size={12} />
                </button>
                <button title="Статистика">
                  <Icon name="chart" size={12} />
                </button>
                <button title="Копировать">
                  <Icon name="link" size={12} />
                </button>
                <button title="Отключить">
                  <Icon name="pulse" size={12} />
                </button>
                <button title="Ещё">
                  <Icon name="more" size={12} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>
      {createOpen && <CreateEntityModal kind="inbound" onClose={() => setCreateOpen(false)} />}
    </>
  );
}

function ClientsPage() {
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedClient, setSelectedClient] = useState<string[] | null>(null);
  const [checked, setChecked] = useState<string[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const toggleClient = (name: string) =>
    setChecked((current) =>
      current.includes(name) ? current.filter((item) => item !== name) : [...current, name],
    );
  return (
    <>
      <PageTitle
        eyebrow="УПРАВЛЕНИЕ КЛИЕНТАМИ"
        title="Клиенты"
        text="Пользователи, лимиты, подписки и привязанные inbound-конфигурации"
        action="Добавить клиента"
        onAction={() => setCreateOpen(true)}
      />
      <div className="snapshot-stamp">СНИМОК ПОЛУЧЕН · 11:43:29 PM</div>
      <section className="client-statline">
        {[
          ["TOTAL", "609"],
          ["ACTIVE", "605 (99%)"],
          ["ONLINE", "43 (7%)"],
          ["EXPIRED", "0"],
          ["DELETED", "0"],
          ["DISABLED", "1"],
        ].map((item, i) => (
          <div key={item[0]}>
            <span>{item[0]}</span>
            <strong className={i === 1 ? "positive" : i > 2 ? "negative" : ""}>{item[1]}</strong>
          </div>
        ))}
      </section>
      <section className="dash-card client-actions-top">
        <span>ДЕЙСТВИЯ</span>
        <p>
          <button className="primary-action" onClick={() => setCreateOpen(true)}>
            + Добавить
          </button>
          <button>Массовое добавление</button>
          <button>Импорт CSV</button>
          <button
            className={refreshing ? "refreshing" : ""}
            onClick={() => {
              setRefreshing(true);
              window.setTimeout(() => setRefreshing(false), 900);
            }}
          >
            {refreshing ? "Обновляем…" : "Обновить"}
          </button>
          <button
            className={autoRefresh ? "active" : ""}
            onClick={() => setAutoRefresh(!autoRefresh)}
          >
            Авто
          </button>
        </p>
      </section>
      <section className="client-control-grid">
        <div className="dash-card control-card">
          <div className="card-head">
            <div>
              <span>ФИЛЬТР</span>
              <h2>Поиск и сегментация</h2>
            </div>
          </div>
          <FilterStrip tags={["Все статусы", "ACTIVE", "EXPIRED", "ONLINE", "OFFLINE"]} />
          <div className="client-node-filters">
            <span>Узлы:</span>
            {servers.map((server, i) => (
              <button className={i === 0 ? "active" : ""} key={server.name}>
                {server.name}
              </button>
            ))}
          </div>
          <div className="client-extra-filters">
            <button>Все протоколы</button>
            <button>VLESS</button>
            <select>
              <option>Все inbound</option>
              <option>vless-reality</option>
            </select>
            <button>Expiring 7d</button>
            <button>Сначала онлайн</button>
            <button>Дубликаты</button>
          </div>
        </div>
        <div className="dash-card cleanup-card">
          <div className="card-head">
            <div>
              <span>МАССОВАЯ ОЧИСТКА</span>
              <h2>Выбор и операции</h2>
            </div>
          </div>
          <div className="cleanup-groups">
            <span>ВЫБРАТЬ:</span>
            <p>
              <button className="danger-action">Все истёкшие</button>
              <button>Все непродлённые</button>
              <button>Все отключённые</button>
              <button>Очистить выбор</button>
            </p>
          </div>
          <div className="cleanup-groups">
            <span>ОПЕРАЦИИ:</span>
            <p>
              <button>Удалить истёкшие</button>
              <button>Удалить непродлённые</button>
              <button className="primary-action">Сбросить весь трафик</button>
              <button>Сбросить непродлённые</button>
              <button className="primary-action">Продлить на месяц</button>
              <button>Продлить отключённые</button>
            </p>
          </div>
          <div className="cleanup-groups compact">
            <span>ЕЩЁ:</span>
            <p>
              <button>Groups</button>
              <button>Demo</button>
              <button>Поиск по IP</button>
              <button>Копировать email</button>
              <button>JSON</button>
              <button>CSV</button>
            </p>
          </div>
        </div>
      </section>
      <section className="dash-card data-section">
        <div className="card-head">
          <div>
            <span>96 КЛИЕНТОВ</span>
            <h2>Список пользователей</h2>
          </div>
          <button className="ghost-button">Экспорт CSV</button>
        </div>
        <div className="ops-table clients-table">
          <div className="ops-row ops-labels">
            <span>
              <input type="checkbox" />
            </span>
            <span>КЛИЕНТ</span>
            <span>СЕРВЕР</span>
            <span>СТАТУС</span>
            <span>ТРАФИК</span>
            <span>ПОДПИСКА</span>
            <span>АКТИВНОСТЬ</span>
            <span />
          </div>
          {clients.map((client, i) => (
            <div className="ops-row" key={client[0]}>
              <span>
                <input
                  type="checkbox"
                  checked={checked.includes(client[0])}
                  onChange={() => toggleClient(client[0])}
                />
              </span>
              <span className="client-cell">
                <i>{client[0][0]}</i>
                <span>
                  <strong>{client[0]}</strong>
                  <small>
                    UUID · {String(i + 19).padStart(3, "0")}a…f{i}
                  </small>
                </span>
              </span>
              <span>{client[1]}</span>
              <span>
                <em className={client[2] === "Активен" ? "success-badge" : "warning-badge"}>
                  {client[2]}
                </em>
              </span>
              <strong>{client[3]}</strong>
              <span>{client[4]}</span>
              <span>{client[5]}</span>
              <div className="row-actions client-row-actions">
                <button title="Открыть" onClick={() => setSelectedClient(client)}>
                  <Icon name="arrow" size={12} />
                </button>
                <button title="Редактировать">
                  <Icon name="filter" size={12} />
                </button>
                <button title="Ссылка">
                  <Icon name="link" size={12} />
                </button>
                <button title="Статистика">
                  <Icon name="chart" size={12} />
                </button>
                <button title="Сбросить трафик">
                  <Icon name="pulse" size={12} />
                </button>
                <button title="Отключить">
                  <Icon name="check" size={12} />
                </button>
                <button title="Удалить" className="danger-item">
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>
      {checked.length > 0 && (
        <div className="selection-bar">
          <span>
            <strong>{checked.length}</strong> выбрано
          </span>
          <button>Продлить</button>
          <button>Перенести</button>
          <button>Сбросить трафик</button>
          <button className="danger-item">Отключить</button>
          <button onClick={() => setChecked([])}>×</button>
        </div>
      )}
      {createOpen && <CreateEntityModal kind="client" onClose={() => setCreateOpen(false)} />}
      {selectedClient && (
        <ClientDrawer client={selectedClient} onClose={() => setSelectedClient(null)} />
      )}
    </>
  );
}

function StatisticsPage() {
  const bars = [78, 64, 57, 55, 48, 42, 39, 36, 33, 29];
  return (
    <>
      <PageTitle
        eyebrow="СТАТИСТИКА"
        title="Использование трафика"
        text="Детальная аналитика серверов и клиентов за выбранный период"
      />
      <FilterStrip tags={["Сегодня", "7 дней", "30 дней", "3 месяца"]} />
      <section className="stats-triplet">
        {[
          ["Входящий", "2.49 TB", 66],
          ["Исходящий", "35.64 TB", 91],
          ["Всего", "38.13 TB", 84],
        ].map((item) => (
          <article className="dash-card capacity-card" key={item[0]}>
            <span>{item[0]}</span>
            <strong>{item[1]}</strong>
            <i>
              <b style={{ width: `${item[2]}%` }} />
            </i>
            <small>{item[2]}% от прогноза</small>
          </article>
        ))}
      </section>
      <section className="dash-card bars-card">
        <div className="card-head">
          <div>
            <span>TOP 10</span>
            <h2>Клиенты по трафику</h2>
          </div>
          <button className="ghost-button">Выгрузить отчёт</button>
        </div>
        <div className="big-bars">
          {bars.map((bar, i) => (
            <div key={i}>
              <i style={{ height: `${bar}%` }} />
              <span>{clients[i % clients.length][0]}</span>
              <small>{(bar / 10).toFixed(1)} TB</small>
            </div>
          ))}
        </div>
      </section>
      <section className="stats-columns">
        <article className="dash-card rank-list">
          <div className="card-head">
            <div>
              <span>КЛИЕНТЫ</span>
              <h2>Самые активные</h2>
            </div>
          </div>
          {clients.slice(0, 6).map((c, i) => (
            <div key={c[0]}>
              <em>{i + 1}</em>
              <strong>{c[0]}</strong>
              <span>{c[3]}</span>
            </div>
          ))}
        </article>
        <article className="dash-card rank-list">
          <div className="card-head">
            <div>
              <span>СЕРВЕРЫ</span>
              <h2>Распределение нагрузки</h2>
            </div>
          </div>
          {servers.map((s, i) => (
            <div key={s.name}>
              <em>{i + 1}</em>
              <strong>{s.name}</strong>
              <span>{s.traffic}</span>
            </div>
          ))}
        </article>
      </section>
    </>
  );
}

function MonitoringPage() {
  return (
    <>
      <PageTitle
        eyebrow="МОНИТОРИНГ"
        title="Состояние системы"
        text="Метрики инфраструктуры и AdGuard DNS в реальном времени"
        action="Снять снимок"
      />
      <section className="monitor-grid">
        {[
          ["CPU", "42.8%", 43, "Норма"],
          ["RAM", "4.9 GB", 62, "из 8 GB"],
          ["Диски", "10.8%", 11, "452 GB свободно"],
          ["Uptime", "20д 11ч", 92, "99.98%"],
        ].map((item) => (
          <article className="dash-card monitor-card" key={item[0]}>
            <span>{item[0]}</span>
            <strong>{item[1]}</strong>
            <small>{item[3]}</small>
            <i>
              <b style={{ width: `${item[2]}%` }} />
            </i>
          </article>
        ))}
      </section>
      <section className="dash-card adguard-card">
        <div className="card-head">
          <div>
            <span>ADGUARD DNS</span>
            <h2>Защита и фильтрация</h2>
          </div>
          <span className="live-pill">
            <i />
            LIVE
          </span>
        </div>
        <div className="adguard-stats">
          {[
            ["Запросов", "308,338"],
            ["Заблокировано", "17.31%"],
            ["Обработано", "99.9%"],
            ["Среднее время", "29.5 ms"],
            ["Ошибок", "0.00%"],
          ].map((x) => (
            <div key={x[0]}>
              <span>{x[0]}</span>
              <strong>{x[1]}</strong>
            </div>
          ))}
        </div>
      </section>
      <section className="monitor-charts">
        <article className="dash-card waveform">
          <div className="card-head">
            <div>
              <span>ЗАПРОСЫ</span>
              <h2>Активность за 24 часа</h2>
            </div>
          </div>
          <svg viewBox="0 0 800 140" preserveAspectRatio="none">
            <path
              d="M0 110 L20 42 40 85 60 25 80 94 110 63 140 102 180 41 215 82 250 55 300 108 340 48 380 72 410 31 450 104 490 61 530 85 570 39 610 112 650 54 700 89 750 45 800 73"
              fill="none"
              stroke="var(--accent)"
              strokeWidth="2"
            />
            <path
              d="M0 120 C90 100 140 125 210 91 S350 110 430 76 S600 92 800 55"
              fill="none"
              stroke="var(--accent-2)"
              strokeWidth="1.5"
            />
          </svg>
        </article>
        <article className="dash-card latency">
          <div className="card-head">
            <div>
              <span>ЗАДЕРЖКА</span>
              <h2>Latency, ms</h2>
            </div>
          </div>
          <div className="latency-value">
            <strong>29.5</strong>
            <span>ms average</span>
          </div>
          <div className="latency-line" />
        </article>
      </section>
      <section className="stats-columns">
        <article className="dash-card rank-list">
          <div className="card-head">
            <div>
              <span>БЛОКИРОВКИ</span>
              <h2>Топ доменов</h2>
            </div>
          </div>
          {[
            "events.statsigapi.net",
            "errors.figma.com",
            "graph.instagram.com",
            "api.segment.io",
          ].map((x, i) => (
            <div key={x}>
              <em>{i + 1}</em>
              <strong>{x}</strong>
              <span>{38 - i * 7}%</span>
            </div>
          ))}
        </article>
        <article className="dash-card rank-list">
          <div className="card-head">
            <div>
              <span>КЛИЕНТЫ</span>
              <h2>Топ источников</h2>
            </div>
          </div>
          {clients.slice(0, 4).map((x, i) => (
            <div key={x[0]}>
              <em>{i + 1}</em>
              <strong>{x[0]}</strong>
              <span>{84 - i * 11}k</span>
            </div>
          ))}
        </article>
      </section>
    </>
  );
}

function SubscriptionsPage() {
  const [createOpen, setCreateOpen] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  return (
    <>
      <PageTitle
        eyebrow="ПОДПИСКИ"
        title="Управление подписками"
        text="Персональные ссылки, сроки действия и параметры доступа"
        action="Создать подписку"
        onAction={() => setCreateOpen(true)}
      />
      <section className="subscription-summary">
        {[
          ["Всего", "96"],
          ["Активные", "68"],
          ["Истекают", "7"],
          ["Отключены", "21"],
        ].map((x, i) => (
          <article className="dash-card" key={x[0]}>
            <span className={`summary-icon s${i}`}>
              <Icon
                name={i === 0 ? "link" : i === 1 ? "check" : i === 2 ? "bell" : "pulse"}
                size={16}
              />
            </span>
            <span>{x[0]}</span>
            <strong>{x[1]}</strong>
          </article>
        ))}
      </section>
      <section className="dash-card data-section">
        <div className="card-head">
          <div>
            <span>ИНДИВИДУАЛЬНЫЕ ПОДПИСКИ</span>
            <h2>Ссылки клиентов</h2>
          </div>
          <div className="server-actions">
            <button className="accent-button" onClick={() => setCreateOpen(true)}>
              + Создать
            </button>
            <label>
              <Icon name="search" size={14} />
              <input placeholder="Поиск" />
            </label>
            <button className="ghost-button">Копировать всё</button>
          </div>
        </div>
        <div className="subscription-list">
          {clients.map((client, i) => (
            <div key={client[0]}>
              <span className="client-cell">
                <i>{client[0][0]}</i>
                <strong>{client[0]}</strong>
              </span>
              <em>{Math.round(100 + i * 17)}</em>
              <code>
                https://sub.manager.local/api/v1/{client[0].toLowerCase()}/a8f{i}…
              </code>
              <span>{client[4]}</span>
              <div>
                <button
                  onClick={() => {
                    setCopied(client[0]);
                    window.setTimeout(() => setCopied(null), 1400);
                  }}
                >
                  {copied === client[0] ? "Скопировано" : "Копировать"}
                </button>
                <button>
                  <Icon name="more" size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>
      {createOpen && <CreateEntityModal kind="subscription" onClose={() => setCreateOpen(false)} />}
    </>
  );
}

function TelegramPage() {
  return (
    <>
      <PageTitle
        eyebrow="TELEGRAM"
        title="Пользователи и обращения"
        text="Связанные Telegram-аккаунты, заявки и уведомления бота"
        action="Обновить данные"
      />
      <section className="telegram-metrics">
        {[
          ["Пользователи", "86", "users"],
          ["Заявки", "6", "requests"],
          ["Уведомления", "14", "alerts"],
          ["Заблокированы", "2", "blocked"],
        ].map((x) => (
          <article className="dash-card" key={x[0]}>
            <span>{x[0]}</span>
            <strong>{x[1]}</strong>
            <small>{x[2]}</small>
          </article>
        ))}
      </section>
      <div className="section-tabs">
        <button className="active">Пользователи и обращения</button>
        <button>Операции с каналами</button>
        <button>Бот и настройки</button>
      </div>
      <section className="dash-card data-section">
        <div className="card-head">
          <div>
            <span>ПОЛЬЗОВАТЕЛИ</span>
            <h2>Telegram-аккаунты</h2>
          </div>
          <div className="server-actions">
            <label>
              <Icon name="search" size={14} />
              <input placeholder="Имя или ID" />
            </label>
            <button className="ghost-button">Все статусы</button>
          </div>
        </div>
        <div className="telegram-table">
          <div className="tg-row tg-labels">
            <span>ПОЛЬЗОВАТЕЛЬ</span>
            <span>TELEGRAM IDENTITY</span>
            <span>УЗЛЫ</span>
            <span>ТРАФИК</span>
            <span>СОСТОЯНИЕ</span>
          </div>
          {clients.map((client, i) => (
            <div className="tg-row" key={client[0]}>
              <span className="client-cell">
                <i>{client[0][0]}</i>
                <strong>@{client[0].toLowerCase()}</strong>
              </span>
              <span>
                <strong>{87900012 + i * 3471}</strong>
                <small>{i % 2 ? "Имя не указано" : "Alex " + client[0]}</small>
              </span>
              <span className="node-dots">
                <i />
                <i />
                <i />
              </span>
              <strong>{client[3]}</strong>
              <span className="status">
                <i />
                Связан
              </span>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

function UtilityPage({ page }: { page: string }) {
  const content: Record<string, [string, string, string]> = {
    "Резервные копии": [
      "РЕЗЕРВНОЕ КОПИРОВАНИЕ",
      "Снимки конфигурации",
      "Автоматические и ручные копии серверов, клиентов и системных настроек",
    ],
    Настройки: [
      "СИСТЕМНЫЕ НАСТРОЙКИ",
      "Конфигурация панели",
      "Безопасность, уведомления, внешний вид и параметры интеграций",
    ],
    "Журнал системы": [
      "АУДИТ",
      "Журнал системы",
      "Действия администраторов, события API и изменения конфигурации",
    ],
  };
  const current = content[page] ?? content["Журнал системы"];
  return (
    <>
      <PageTitle
        eyebrow={current[0]}
        title={current[1]}
        text={current[2]}
        action={page === "Резервные копии" ? "Создать копию" : undefined}
      />
      <section className="mini-metrics">
        {[
          ["События сегодня", "148", "+12%"],
          ["Успешно", "139", "93.9%"],
          ["Предупреждения", "8", "требуют проверки"],
          ["Ошибки", "1", "за 24 часа"],
        ].map((item) => (
          <article className="dash-card" key={item[0]}>
            <span>{item[0]}</span>
            <strong>{item[1]}</strong>
            <small>{item[2]}</small>
          </article>
        ))}
      </section>
      <section className="dash-card data-section">
        <div className="card-head">
          <div>
            <span>ПОСЛЕДНИЕ ОПЕРАЦИИ</span>
            <h2>История активности</h2>
          </div>
          <button className="ghost-button">Экспорт</button>
        </div>
        <div className="utility-list">
          {[
            "Конфигурация сервера обновлена",
            "Резервная копия создана",
            "Клиент перенесён на новый узел",
            "AdGuard DNS синхронизирован",
            "Выполнен вход администратора",
            "Токен подписки перевыпущен",
          ].map((item, i) => (
            <div key={item}>
              <span className={`event-icon e${i % 3}`}>
                <Icon name={i % 2 ? "check" : "pulse"} size={14} />
              </span>
              <p>
                <strong>{item}</strong>
                <small>
                  root · {2 + i * 7} минут назад · 185.21.44.{20 + i}
                </small>
              </p>
              <em>{i % 3 === 0 ? "Изменение" : i % 3 === 1 ? "Система" : "Безопасность"}</em>
              <button>
                <Icon name="more" size={14} />
              </button>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

function OperationsPage({ page }: { page: string }) {
  if (page === "Inbound") return <InboundPage />;
  if (page === "Клиенты") return <ClientsPage />;
  if (page === "Статистика") return <StatisticsPage />;
  if (page === "Мониторинг") return <MonitoringPage />;
  if (page === "Подписки") return <SubscriptionsPage />;
  if (page === "Telegram") return <TelegramPage />;
  return <UtilityPage page={page} />;
}

function CommandPalette({
  onClose,
  onNavigate,
  onAddServer,
}: {
  onClose: () => void;
  onNavigate: (page: string) => void;
  onAddServer: () => void;
}) {
  const [query, setQuery] = useState("");
  const commands = [
    ...nav.map(([icon, label]) => ({
      icon,
      label,
      group: "Разделы",
      action: () => onNavigate(label),
    })),
    {
      icon: "server" as const,
      label: "Добавить новый сервер",
      group: "Быстрые действия",
      action: onAddServer,
    },
    {
      icon: "users" as const,
      label: "Создать клиента",
      group: "Быстрые действия",
      action: () => onNavigate("Клиенты"),
    },
    {
      icon: "pulse" as const,
      label: "Открыть мониторинг",
      group: "Быстрые действия",
      action: () => onNavigate("Мониторинг"),
    },
  ].filter((item) => item.label.toLowerCase().includes(query.toLowerCase()));
  return (
    <div className="modal-wrap command-wrap">
      <Overlay onClose={onClose} />
      <div className="command-palette">
        <label>
          <Icon name="search" size={18} />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Найти раздел, сервер или действие…"
          />
          <kbd>ESC</kbd>
        </label>
        <div className="command-results">
          {commands.length ? (
            commands.map((item, i) => (
              <button
                key={`${item.label}-${i}`}
                onClick={() => {
                  item.action();
                  onClose();
                }}
              >
                <span>
                  <Icon name={item.icon} size={15} />
                </span>
                <strong>{item.label}</strong>
                <small>{item.group}</small>
                <em>↵</em>
              </button>
            ))
          ) : (
            <div className="empty-command">
              <Icon name="search" size={22} />
              <strong>Ничего не найдено</strong>
              <span>Попробуйте изменить запрос</span>
            </div>
          )}
        </div>
        <footer>
          <span>↑↓ навигация</span>
          <span>↵ открыть</span>
          <span>esc закрыть</span>
        </footer>
      </div>
    </div>
  );
}

function Dashboard({ theme }: { theme: Theme }) {
  const [collapsed, setCollapsed] = useState(false);
  const [activePage, setActivePage] = useState("Панель управления");
  const [toast, setToast] = useState(false);
  const [notifications, setNotifications] = useState(false);
  const [profileMenu, setProfileMenu] = useState(false);
  const [filterMenu, setFilterMenu] = useState(false);
  const [addModal, setAddModal] = useState(false);
  const [viewMode, setViewMode] = useState<"cards" | "table">("cards");
  const [selectedServer, setSelectedServer] = useState<(typeof servers)[number] | null>(null);
  const [commandOpen, setCommandOpen] = useState(false);
  const [fleetOpen, setFleetOpen] = useState(false);
  const showToast = () => {
    setToast(true);
    window.setTimeout(() => setToast(false), 2200);
  };

  return (
    <div className={`admin-ui theme-${theme.slug}`}>
      <MainNav
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        active={activePage}
        onSelect={setActivePage}
      />
      <main className="admin-main">
        <header className="admin-topbar">
          <div className="topbar-section-title">
            <span>
              <Icon name={getPageIcon(activePage)} size={17} />
            </span>
            <strong>{activePage}</strong>
          </div>
          <div className="admin-actions">
            <label className="admin-search" onClick={() => setCommandOpen(true)}>
              <Icon name="search" size={15} />
              <input placeholder="Поиск..." readOnly />
            </label>
            <button onClick={() => setNotifications(!notifications)} aria-label="Уведомления">
              <Icon name="bell" size={16} />
              <i />
            </button>
            <button className="avatar-button" onClick={() => setProfileMenu(!profileMenu)}>
              <span className="top-avatar">AK</span>
            </button>
            {profileMenu && (
              <div className="profile-dropdown">
                <div>
                  <span className="top-avatar">AK</span>
                  <p>
                    <strong>Алексей Ковалёв</strong>
                    <small>root · администратор</small>
                  </p>
                </div>
                <button>Профиль и безопасность</button>
                <button>Настройки интерфейса</button>
                <button>Журнал действий</button>
                <button className="danger-item">Выйти из системы</button>
              </div>
            )}
          </div>
        </header>

        <div className="admin-page">
          {activePage !== "Панель управления" ? (
            <OperationsPage page={activePage} />
          ) : (
            <>
              {theme.slug === "vision" && (
                <section className="vision-hero">
                  <div>
                    <span>СИСТЕМА РАБОТАЕТ СТАБИЛЬНО</span>
                    <h2>
                      Все сервисы
                      <br />
                      под контролем.
                    </h2>
                  </div>
                  <div className="uptime-ring">
                    <strong>99.98%</strong>
                    <span>UPTIME</span>
                  </div>
                </section>
              )}

              <section className="metric-grid">
                {stats.map((item, index) => (
                  <article className="metric-card" key={item.label}>
                    <div className="metric-icon">
                      <Icon
                        name={
                          index === 0
                            ? "server"
                            : index === 1
                              ? "users"
                              : index === 2
                                ? "pulse"
                                : "chart"
                        }
                        size={17}
                      />
                    </div>
                    <div className="metric-copy">
                      <span>{item.label}</span>
                      <strong>{item.value}</strong>
                      <small>{item.sub}</small>
                    </div>
                    <em>{item.trend}</em>
                  </article>
                ))}
              </section>

              <section className="content-grid">
                <TrafficAnalytics />
                <UserTrafficRanking />
              </section>

              <section className="dash-card servers-card">
                <div className="card-head">
                  <div>
                    <span>ИНФРАСТРУКТУРА</span>
                    <h2>Серверы</h2>
                    <p>13 серверов · все узлы доступны</p>
                  </div>
                  <div className="server-actions">
                    <div className="filter-anchor">
                      <button className="ghost-button" onClick={() => setFilterMenu(!filterMenu)}>
                        <Icon name="filter" size={14} /> Фильтры
                      </button>
                      {filterMenu && (
                        <div className="filter-dropdown">
                          <strong>Показывать серверы</strong>
                          {[
                            "Все серверы",
                            "Только онлайн",
                            "Высокая нагрузка",
                            "Требуют внимания",
                          ].map((x, i) => (
                            <label key={x}>
                              <input type="radio" name="server-filter" defaultChecked={i === 0} />
                              <span>{x}</span>
                              <em>{[13, 13, 2, 1][i]}</em>
                            </label>
                          ))}
                          <hr />
                          <strong>Регион</strong>
                          <div>
                            <button className="active">Все</button>
                            <button>EU</button>
                            <button>RU</button>
                            <button>US</button>
                          </div>
                        </div>
                      )}
                    </div>
                    <button className="accent-button" onClick={() => setAddModal(true)}>
                      + Сервер
                    </button>
                    <label>
                      <Icon name="search" size={14} />
                      <input placeholder="Найти сервер" />
                    </label>
                    <button className="ghost-button">Все регионы</button>
                    <div className="view-switch">
                      <button
                        className={viewMode === "cards" ? "active" : ""}
                        onClick={() => setViewMode("cards")}
                      >
                        <Icon name="grid" size={13} />
                      </button>
                      <button
                        className={viewMode === "table" ? "active" : ""}
                        onClick={() => setViewMode("table")}
                      >
                        <Icon name="menu" size={13} />
                      </button>
                    </div>
                  </div>
                </div>
                <ServerStatusToolbar />
                {viewMode === "cards" ? (
                  <ServerCards onOpen={setSelectedServer} />
                ) : (
                  <ServerTable onOpen={setSelectedServer} />
                )}
              </section>
            </>
          )}
        </div>
      </main>
      <div className={`action-toast ${toast ? "show" : ""}`}>
        <span>
          <Icon name="check" size={15} />
        </span>
        <div>
          <strong>Сервер добавлен в очередь</strong>
          <small>Откроем форму конфигурации</small>
        </div>
      </div>
      {notifications && (
        <div className="drawer-wrap compact-drawer">
          <Overlay onClose={() => setNotifications(false)} />
          <aside className="notification-drawer">
            <div className="notification-head">
              <div>
                <span>ЦЕНТР СОБЫТИЙ</span>
                <h2>Уведомления</h2>
              </div>
              <button onClick={() => setNotifications(false)}>×</button>
            </div>
            <div className="notice-tabs">
              <button className="active">
                Все <em>8</em>
              </button>
              <button>Система</button>
              <button>Клиенты</button>
            </div>
            <div className="notice-list">
              {[
                [
                  "warning",
                  "Высокая нагрузка на DE-65-F3",
                  "CPU держится выше 80% последние 12 минут",
                  "2 мин",
                ],
                [
                  "success",
                  "Резервная копия завершена",
                  "Конфигурации 13 серверов сохранены",
                  "18 мин",
                ],
                ["info", "Новый клиент подключён", "@mashka_a · RU-5-EKT", "34 мин"],
                ["danger", "Подписка скоро истечёт", "У 7 клиентов осталось менее 3 дней", "1 ч"],
                ["success", "AdGuard обновлён", "Списки фильтрации синхронизированы", "3 ч"],
              ].map((n) => (
                <button className="notice-item" key={n[1]}>
                  <i className={n[0]} />
                  <span>
                    <strong>{n[1]}</strong>
                    <small>{n[2]}</small>
                  </span>
                  <em>{n[3]}</em>
                </button>
              ))}
            </div>
            <button className="notice-all">Открыть журнал событий</button>
          </aside>
        </div>
      )}
      {addModal && (
        <AddServerModal
          onClose={() => setAddModal(false)}
          onSubmit={() => {
            setAddModal(false);
            showToast();
          }}
        />
      )}
      {selectedServer && (
        <ServerDrawer server={selectedServer} onClose={() => setSelectedServer(null)} />
      )}
      {commandOpen && (
        <CommandPalette
          onClose={() => setCommandOpen(false)}
          onNavigate={setActivePage}
          onAddServer={() => setAddModal(true)}
        />
      )}
      {!fleetOpen && (
        <button
          className="fleet-edge-toggle"
          onClick={() => setFleetOpen(true)}
          aria-label="Открыть зарегистрированный парк"
          title="Зарегистрированный парк"
        >
          <span>←</span>
          <em>13</em>
        </button>
      )}
      {fleetOpen && (
        <FleetPanel
          onClose={() => setFleetOpen(false)}
          onOpen={(index) => {
            setFleetOpen(false);
            setSelectedServer(servers[index % servers.length]);
          }}
        />
      )}
    </div>
  );
}

export default function App() {
  const [activeTheme, setActiveTheme] = useState(3);
  const theme = themes.find((item) => item.id === activeTheme) ?? themes[0];
  return (
    <div className="showcase">
      <ThemeRail active={activeTheme} onChange={setActiveTheme} />
      <section className="preview-area">
        <header className="preview-head">
          <div>
            <span>РАСШИРЕННЫЙ ФИНАЛИСТ · КОНЦЕПЦИЯ {String(theme.id).padStart(2, "0")}</span>
            <h1>{theme.name}</h1>
            <p>{theme.note}</p>
          </div>
          <div className="preview-meta">
            <span>Основа</span>
            <strong>{theme.source}</strong>
          </div>
        </header>
        <div className="browser-frame">
          <div className="browser-bar">
            <span />
            <span />
            <span />
            <p>admin.sub-manager.local / dashboard</p>
            <em>1440 × 960</em>
          </div>
          <Dashboard theme={theme} />
        </div>
      </section>
    </div>
  );
}
