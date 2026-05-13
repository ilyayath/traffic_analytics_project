# Дашборд аналітики веб-трафіку

Django-застосунок для аналізу access-логів веб-серверів (Apache/Nginx Combined Log Format) з інтерактивними графіками на Chart.js.

## Реалізовані патерни проєктування

| Патерн | Де реалізовано | Призначення |
|---|---|---|
| **MVT** | вся структура Django | Models / Views / Templates замість MVC |
| **Facade** | `analytics/facades.py` — `TrafficAnalyticsFacade` | Єдина точка входу для парсингу, агрегації, побудови звіту, експорту |
| **Observer** | `analytics/signals.py` | Email-сповіщення + детектор аномалій через Django signals |
| **Composite** | `analytics/composite.py` + `ReportSection` модель + `templates/components/section.html` | Ієрархічні звіти (групи → графіки/таблиці) |

## Шари аналітики

Проект демонструє два **взаємодоповнюючих** підходи, які ховаються за одним фасадом:

| Шар | Технологія | Призначення |
|---|---|---|
| Швидкі агрегації для дашборда | Django ORM (`_AggregationService`) | `Count`, `Sum`, `Avg`, `TruncHour` — оптимальні для UI |
| Розширена аналітика | pandas (`PandasAnalyticsService`) | Resample, rolling-window анoмалії, pivot, Excel-експорт |

Це класичний приклад того, навіщо потрібен **Facade**: views не знають, що під капотом — ORM чи pandas. Можна додати ще третій бекенд (Polars, ClickHouse) без зміни views.

## Швидкий старт

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py generate_sample_log --lines 2000
python manage.py runserver
```

Відкрийте http://127.0.0.1:8000/ — завантажте `sample_data/access.log` і згенеруйте звіт.

## Тести

```bash
python manage.py test analytics
# або з покриттям:
coverage run --source='analytics' manage.py test analytics
coverage report -m
```

## Структура проекту

```
traffic_analytics/
├── config/                    # Налаштування Django
├── analytics/
│   ├── models.py              # LogFile, LogEntry, Report, ReportSection, Notification
│   ├── facades.py             # ★ Facade Pattern
│   ├── signals.py             # ★ Observer Pattern
│   ├── composite.py           # ★ Composite Pattern (GoF)
│   ├── parsers.py             # Парсер логів
│   ├── views.py               # Тонкі views, делегують фасаду
│   ├── urls.py
│   ├── tests.py               # 20 тестів
│   └── management/commands/
│       └── generate_sample_log.py
├── templates/
│   ├── base.html              # Bootstrap + Chart.js
│   ├── analytics/             # Сторінки
│   └── components/section.html # ★ Composite в шаблоні (рекурсивний include)
└── .github/workflows/tests.yml # CI
```

## Архітектурні рішення

### Facade
`TrafficAnalyticsFacade` приховує три внутрішні сервіси:
- `_LogIngestionService` — парсинг і збереження
- `_AggregationService` — підрахунок статистики
- `_ReportBuilderService` — побудова дерева звіту

Views викликають тільки публічні методи фасаду:
```python
# Базова аналітика (Django ORM)
facade.upload_and_process(file, name)
facade.get_overview(log_file)
facade.get_chart_data(log_file, "status")
facade.build_report(log_file)

# Розширена аналітика (pandas)
facade.resample_traffic(log_file, freq="1h")          # time-series resample
facade.rolling_anomalies(log_file, window="10min")    # ковзне вікно
facade.export_excel(log_file)                         # Excel-звіт із 4 вкладок
```

### Observer
Власний сигнал `log_file_processed` має двох підписників:
1. `notify_admin_email` — email-сповіщення 
2. `detect_traffic_anomalies` — окремий незалежний обсерватор

### Composite
Реалізовано **на трьох рівнях**:
1. **Модель** — `ReportSection` має `parent → children` (self-referential FK)
2. **GoF-клас** — `CompositeSection` / `LeafSection` у `composite.py`
3. **Шаблон** — `section.html` рекурсивно включає сам себе для рендера дерева
