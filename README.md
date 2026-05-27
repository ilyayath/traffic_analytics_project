# Дашборд аналітики веб-трафіку

Django-застосунок для аналізу access-логів веб-серверів (Apache/Nginx Combined Log Format) з інтерактивними графіками на Chart.js, автентифікацією користувачів, AI-аналізом та Docker-деплойментом.

## Можливості

- Реєстрація та автентифікація користувачів (кожен бачить тільки свої файли)
- Завантаження та парсинг лог-файлів Combined Log Format
- Агрегація метрик: запити, унікальні відвідувачі, помилки, трафік
- 8 типів інтерактивних графіків на Chart.js з AJAX-фільтрацією
- Ресемплінг часових рядів, ковзне вікно для аномалій (pandas)
- Ієрархічні звіти (Composite pattern) з експортом у Excel
- AI-аналіз логів: Ollama → Anthropic Claude API → rule-based fallback
- Сповіщення на сайті через Observer pattern (Django signals)
- Docker-деплоймент: PostgreSQL + Gunicorn + Nginx

## Патерни проєктування

| Патерн | Де реалізовано | Призначення |
|---|---|---|
| **MVT** | Вся структура Django | Models / Views / Templates |
| **Facade** | `analytics/facades.py` | Єдина точка входу для парсингу, агрегації, звітів, Excel, AI |
| **Observer** | `analytics/signals.py` | Сповіщення + детектор аномалій через Django signals |
| **Composite** | `analytics/composite.py` + модель `ReportSection` + `section.html` | Ієрархічні звіти довільної глибини |

### Facade

`TrafficAnalyticsFacade` приховує 4 внутрішні сервіси за єдиним API:

```python
facade = TrafficAnalyticsFacade()

# Базова аналітика (Django ORM)
facade.upload_and_process(file, name)
facade.get_overview(log_file)
facade.get_chart_data(log_file, "status")
facade.build_report(log_file)

# Розширена аналітика (pandas)
facade.resample_traffic(log_file, freq="1h")
facade.rolling_anomalies(log_file, window="10min")
facade.export_excel(log_file)

# AI-аналіз
facade.ai_analyze(log_file)
```

Views викликають тільки публічні методи фасаду — не знають ні про парсер, ні про pandas, ні про AI.

### Observer

Власний сигнал `log_file_processed` з двома підписниками:
1. `notify_upload_done` — створює Notification "Файл оброблено" + email
2. `detect_traffic_anomalies` — якщо >5% помилок 5xx → Notification "Аномалія"

### Composite

Реалізовано на трьох рівнях:
1. **Модель** — `ReportSection.parent = ForeignKey("self")` (дерево в БД)
2. **GoF-клас** — `CompositeSection` / `LeafSection` у `composite.py`
3. **Шаблон** — `section.html` рекурсивно включає сам себе

## Технологічний стек

| Компонент | Технологія |
|---|---|
| Backend | Django 5, Python 3.11+ |
| База даних | PostgreSQL 16 (SQLite для dev) |
| Аналітика | pandas, openpyxl |
| Графіки | Chart.js 4 |
| AI | Anthropic Claude API, Ollama |
| Конфігурація | django-environ (.env) |
| WSGI | Gunicorn |
| Reverse-proxy | Nginx |
| Контейнеризація | Docker, docker-compose |
| CI/CD | GitHub Actions |
| Тестування | Django TestCase, coverage |

## Швидкий старт

### Локальна розробка

```bash
git clone https://github.com/your-repo/traffic-analytics-dashboard.git
cd traffic-analytics-dashboard
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py generate_sample_log --lines 2000
python manage.py runserver
```

Відкрийте http://127.0.0.1:8000/ → зареєструйтесь → завантажте `sample_data/access.log`.

### Docker (production)

```bash
cp .env.example .env  # заповнити реальними значеннями
docker compose up -d
# Доступно на http://localhost:80
```

## Тести

```bash
# Запуск 38 тестів
python manage.py test analytics

# З покриттям
coverage run --source='analytics' manage.py test analytics
coverage report -m
```

Категорії тестів: ModelsTest (2), ParserTest (2), FacadeTest (5), CompositeTest (4), ObserverTest (3), ViewsTest (4), PandasServiceTest (18).

## Структура проєкту

```
├── config/                       # Конфігурація Django
│   ├── settings.py               # Налаштування (environ, security)
│   ├── urls.py                   # Кореневий маршрутизатор
│   └── wsgi.py                   # WSGI-точка входу
├── analytics/                    # Основний додаток
│   ├── models.py                 # LogFile, LogEntry, Report, ReportSection, Notification
│   ├── facades.py                # ★ Facade Pattern
│   ├── signals.py                # ★ Observer Pattern
│   ├── composite.py              # ★ Composite Pattern (GoF)
│   ├── parsers.py                # Парсер Combined Log Format
│   ├── pandas_service.py         # pandas: resample, rolling, heatmap, Excel
│   ├── ai_service.py             # AI: Ollama → Anthropic → rule-based
│   ├── views.py                  # Views з @login_required, делегують фасаду
│   ├── urls.py                   # 17 URL-маршрутів
│   ├── tests.py                  # 38 юніт-тестів
│   └── management/commands/
│       └── generate_sample_log.py
├── accounts/                     # Автентифікація
│   ├── views.py                  # register (login/logout — стандартні Django)
│   ├── forms.py                  # RegisterForm (UserCreationForm + email)
│   └── urls.py                   # register, login, logout
├── templates/
│   ├── base.html                 # Базовий layout + Chart.js
│   ├── analytics/                # Дашборд, деталі, звіти, сповіщення
│   ├── accounts/                 # Логін, реєстрація
│   └── components/section.html   # ★ Composite: рекурсивний шаблон
├── static/                       # CSS, JS
├── Dockerfile                    # python:3.12-slim + gunicorn
├── docker-compose.yml            # db + web + nginx
├── nginx/default.conf            # Reverse-proxy конфігурація
├── requirements.txt              # Python-залежності
├── .env.example                  # Шаблон змінних середовища
└── .github/workflows/tests.yml   # CI: тести на Python 3.11/3.12
```

## Змінні середовища

| Змінна | Призначення | За замовчуванням |
|---|---|---|
| `SECRET_KEY` | Ключ Django | `django-insecure-change-me` |
| `DEBUG` | Режим розробки | `True` |
| `ALLOWED_HOSTS` | Дозволені домени | `*` |
| `DATABASE_URL` | DSN бази даних | `sqlite:///db.sqlite3` |
| `EMAIL_BACKEND` | Бекенд email | `console` |
| `ANTHROPIC_API_KEY` | Ключ Anthropic Claude API | (порожній) |

## Безпека

- CSRF-захист через `CsrfViewMiddleware` + `{% csrf_token %}`
- SQL-ін'єкції: тільки ORM, жодного raw SQL
- IDOR: `get_object_or_404(LogFile, pk=pk, user=request.user)` у кожному view
- Секрети у `.env` (у `.gitignore`), `.env.example` з плейсхолдерами
- При `DEBUG=False`: HTTPS redirect, secure cookies, `X_FRAME_OPTIONS=DENY`

