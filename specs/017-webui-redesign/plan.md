# Implementation Plan: Веб-интерфейс инженера «Дом» (редизайн с нуля)

**Branch**: `017-webui-redesign` | **Date**: 2026-10-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/017-webui-redesign/spec.md`

## Summary

Полная замена текущего серверного Jinja+HTMX интерфейса (`src/webui/templates`, 4 экрана)
на отдельное одностраничное приложение на Next.js (App Router, TypeScript, Tailwind +
shadcn/ui), собираемое в статику (`output: 'export'`) и раздаваемое тем же процессом
FastAPI с того же origin. Пять разделов обслуживают пять работ инженера: «Дом» (состояние
и тревоги), «Автоматика» (устройства, решения, управление), «Журнал», «Настройка»,
«Система». Бэкенд остаётся источником истины и дополняется тремя вещами: агрегирующим
запросом для первого экрана, унифицированным каналом живых событий и раздачей статики.
Бизнес-логика автоматики (FSM, диспетчер, роутер) не меняется.

## Technical Context

**Language/Version**: TypeScript 5.x + React 19 + Next.js 15 (App Router) для фронтенда;
Python 3.12+ (существующий) для бэкенда.

**Primary Dependencies**:
- Frontend: `next`, `react`, `tailwindcss`, `shadcn/ui` (Radix), `@tanstack/react-query`,
  `@tanstack/react-virtual`, `zod`, `lucide-react`, `recharts`, `mermaid`.
- Backend (дополнения): существующие `fastapi`, `uvicorn`, `pydantic`; новых рантайм-
  зависимостей Python не требуется (`StaticFiles` — часть Starlette).

**Storage**: существующие хранилища без изменений (манифест YAML, `EventStore`,
`PersistenceManager`, состояние движка). Фронтенд хранит только пользовательские
предпочтения (тема, свёрнутые блоки) в `localStorage`.

**Testing**:
- Frontend: Vitest + React Testing Library + MSW (компоненты и клиенты), Playwright (E2E).
- Backend: pytest (существующий) + контрактные тесты новых endpoint'ов; mypy --strict.

**Target Platform**: локальная сеть (LAN), браузеры настольных машин и телефонов; раздача
из контейнера платформы (порт 8125 в проде, 8000 в dev), без выхода в интернет.

**Project Type**: web application (существующий backend + новый frontend).

**Performance Goals**: первый содержательный экран < 2 с на LAN; отклик на нажатие < 100 мс
(оптимистично); журнал с 1000+ записей без длинных задач (> 50 мс) при прокрутке и приходе
событий; ноль блокирующих запросов к внешней сети.

**Constraints**: работа без доступа в интернет (все ресурсы локальны, ноль внешних CDN);
раздача с того же origin, что API; модель доступа не меняется (LAN + существующие заголовки
`X-User-ID`/`X-Is-Admin`); один контейнер в проде; старый интерфейс удаляется целиком.

**Scale/Scope**: один дом; ~1500 сущностей Home Assistant; единицы локаций и десятки
устройств; 5 разделов + страницы-сущности (локация, устройство).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Принцип | Оценка | Обоснование |
|---|---|---|
| I. Event-Driven FSM (NON-NEGOTIABLE) | PASS | Логика FSM, диспетчер, роутер не затрагиваются; фронтенд только читает состояния и отправляет существующие команды. |
| II. AI-first, TDD/SDD (NON-NEGOTIABLE) | PASS | Спека готова до кода; тесты фронтенда (Vitest/Playwright) и контрактные тесты бэкенда пишутся до реализации; покрытие нового кода ≥ 80%. Для фронтенда вводится зеркальная система качества (eslint, tsc, vitest). |
| III. Контроль за пользователем | PASS | Веб-интерфейс остаётся источником управления; никаких автоматических изменений состояния без действия человека. |
| IV. Многоуровневая архитектура (NON-NEGOTIABLE) | PASS | Фронтенд — слой выше API, общается только по HTTP/WS; `core` не знает о фронтенде. |
| V. Манифест — единственный источник конфигурации | PASS | Фронтенд не хранит списков устройств/локаций: всё приходит из манифеста через API; никаких хардкодов. |
| VI. Двухрежимное развёртывание (Standalone/HA) | PASS | Фронтенд одинаков в обоих режимах; HA-специфика остаётся в адаптере. |
| VII. Многоуровневый интерфейс | PASS | Роль Web UI в конституции («конфигурация манифеста, статус, история, отладка») сохраняется; интерфейс не подменяет HA Dashboard. |
| ADR-001…005 | PASS | Не затрагиваются. |

**Вывод**: гейт пройден. Отклонение (второй тулчейн — Node/TypeScript) зафиксировано в
Complexity Tracking и обосновано ниже.

**Повторная проверка после Phase 1 (design)**: PASS. Спроектированные артефакты не нарушают
принципов: фронтенд общается только по HTTP/WS (IV); конфигурация приходит из манифеста
через API (V); логика FSM не затрагивается (I); тестовая стратегия задана для обеих сторон
(II); модель доступа и роль Web UI сохранены (III, VII). Новых нарушений не появилось.

## Project Structure

### Documentation (this feature)

```text
specs/017-webui-redesign/
├── plan.md              # Этот файл
├── research.md          # Phase 0: решения и альтернативы
├── data-model.md        # Phase 1: сущности интерфейса
├── quickstart.md        # Phase 1: сценарии проверки
├── contracts/           # Phase 1: контракты HTTP/WS/маршрутов UI
│   ├── http-api.md
│   ├── ws-events.md
│   └── ui-routes.md
└── tasks.md             # Phase 2 (создаёт /speckit-tasks)
```

### Source Code (repository root)

```text
frontend/                          # НОВЫЙ проект (статика, раздаётся платформой)
├── app/                           # Маршруты App Router
│   ├── layout.tsx                 # Оболочка: навигация, тема, провайдеры
│   ├── page.tsx                   # Раздел «Дом»
│   ├── devices/page.tsx           # «Автоматика»
│   ├── devices/[id]/page.tsx      # Устройство
│   ├── locations/[id]/page.tsx    # Локация
│   ├── journal/page.tsx           # «Журнал»
│   ├── settings/…                 # «Настройка» (источники, устройства, поведения, локации, манифест)
│   └── system/page.tsx            # «Система»
├── src/
│   ├── components/ui/             # shadcn/ui (локальные, без CDN)
│   ├── features/                  # home, devices, journal, settings, system
│   ├── lib/                       # api-клиент, ws-клиент, identity, query-client, формат
│   ├── hooks/
│   └── styles/
├── public/
├── tests/unit/                    # Vitest + RTL + MSW
├── tests/e2e/                     # Playwright (заменяют старые)
├── next.config.ts                 # output: 'export'
├── package.json / pnpm-lock.yaml
└── tsconfig.json

src/webui/                         # Бэкенд (существующий, дополняется)
├── app.py                         # + раздача frontend/out (SPA-fallback), API-маршруты регистрируются раньше
├── routes/
│   ├── overview.py                # НОВОЕ: GET /api/v1/overview (агрегат для «Дома»)
│   ├── events.py                  # НОВОЕ: GET /api/v1/events (журнал с фильтрами)
│   ├── session.py                 # НОВОЕ: GET /api/v1/session (идентичность/права)
│   ├── devices/websocket.py       # + унифицированный /api/v1/ws/events
│   └── …                          # существующие devices/locations/readiness
└── templates/                     # УДАЛЯЕТСЯ вместе со старым UI

tests/
├── unit/webui/                    # существующие тесты маршрутов (адаптируются)
└── test_webui_playwright.py       # ЗАМЕНЯЕТСЯ на frontend/tests/e2e

deploy/docker/Dockerfile           # multi-stage: сборка фронта (node) → рантайм (python)
Makefile                           # + frontend-install, frontend-build, frontend-test, dev
```

**Structure Decision**: вариант «Web application» — к существующему `src/` добавляется
`frontend/`. Фронтенд собирается в статику и кладётся в образ; в рантайме Node не нужен.
Один контейнер сохраняет текущую топологию `docker-compose.prod.yml` (правки минимальны:
build-стадия), поэтому отдельный сервис не вводится.

## Complexity Tracking

| Отклонение | Почему нужно | Почему простая альтернатива отклонена |
|---|---|---|
| Второй тулчейн (Node/TypeScript) рядом с Python | «Редизайн с нуля» + требование современного вида и надёжных диалогов; серверный HTMX не даёт нужной интерактивности и уже хрупок (модалки не открываются) | Остаться на Jinja+HTMX: не решает исходные жалобы (внешний вид, тормоза, хрупкость), накопленный 1400-строчный шаблон и CDN-зависимости; починка выходит дороже нового проекта |
| Стадия сборки фронтенда в Dockerfile | В проде не нужен Node-рантайм; статика кладётся в образ | Запускать `next` как отдельный сервис: лишний контейнер, CORS, обход модели LAN-доступа |
| Локальные ресурсы вместо CDN | Требование работы без интернета (FR-005) | CDN: интерфейс не работает при недоступности внешней сети, что противоречит развёртыванию в LAN |
