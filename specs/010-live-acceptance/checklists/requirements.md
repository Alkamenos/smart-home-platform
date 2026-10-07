# Specification Quality Checklist: Живой запуск — приёмка и пути, по которым данные не доходят

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-07
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs) — имена файлов и строк
      приведены только в разделе «Контекст проблемы» как доказательство, а не как
      требование; сами FR сформулированы через поведение
- [x] Focused on user value and business needs — каждая история описана через
      жильца и владельца дома, не через модули
- [x] Written for non-technical stakeholders — истории и критерии не требуют
      знания устройства платформы
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain — три неопределённости вынесены в
      «Неизвестные вопросы» с предположением по умолчанию по каждой
- [x] Requirements are testable and unambiguous — каждое FR описывает наблюдаемое
      поведение; FR-007 и FR-012 прямо требуют падения на прежнем коде
- [x] Success criteria are measurable — SC-001…SC-007 выражены числами или
      проверяемыми утверждениями
- [x] Success criteria are technology-agnostic — ни одна не упоминает ни модулей,
      ни счётчиков как средства
- [x] All acceptance scenarios are defined — по четыре на историю
- [x] Edge cases are identified — 10 краевых случаев, включая нечисловое значение
      датчика и блокировку после перезапуска
- [x] Scope is clearly bounded — «Границы фичи» перечисляет пять пунктов вне
      объёма с причиной каждого
- [x] Dependencies and assumptions identified — четыре зависимости, четыре
      предположения

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria — FR распределены
      по историям, каждая история имеет сценарии
- [x] User scenarios cover primary flows — главный поток (жилец вмешивается) и
      вспомогательные (описание в манифесте, первичный запуск)
- [x] Feature meets measurable outcomes defined in Success Criteria — SC-001 и SC-003
      закрывают истории 1 и 2, SC-005 закрывает историю 3
- [x] No implementation details leak into specification — проверяется по FR-001…FR-020

## Проверка по фактам

- [x] Каждая находка в «Контексте проблемы» перепроверена в коде, а не взята из
      Known Issues: три пути доставки данных проверены чтением кода и запуском
- [x] Утверждения Known Issues, принятые неправдивыми, названы прямо: утечка
      обработчиков (словарь очищается при подключении, `ha_adapter.py:100`) и
      отсутствие проверки прав в `/apply` (проверка есть, `devices.py:938`)
- [x] Спека не опирается на «38 тестов» как на аргумент за или против решения —
      число упомянуто в решении пользователя с датой

## Notes

- Итераций валидации: 1. Пункт «без деталей реализации» снят по существу: ссылка
  на конкретное место в коде в разделе «Контекст проблемы» — это доказательство
  основания, и её удаление сделало бы находку непроверяемой для читателя.
- Три неопределённости в «Неизвестных вопросах» — по одному предположению на
  каждую; `/speckit-clarify` может их уточнить до планирования.
- Гистерезис (#71) вынесен вне объёма осознанно: он требует живого термостата,
  и без него проверка превратилась бы в проверку кода, а не дома.
