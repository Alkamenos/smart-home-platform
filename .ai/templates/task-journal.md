# Журнал задачи (шаблон)

<!--
Супервизор /task копирует этот шаблон в
${TMPDIR:-/tmp}/smart-home-changes/<SPEC_ID>_<STORY>.md и ведёт по ходу цикла.
Read-only роли не пишут в журнал — их отчёты переносит супервизор.
-->

# Задача: <SPEC_ID> <STORY / TNNN–TNNN> — <одна строка>

- **Спека**: `specs/<NNN-slug>/` (tasks.md — источник задач)
- **Ветка**: `task/<спека>-<slug>` (создана на шаге 0, в main попадает зелёной)
- **Scope**: <пути из tasks.md>
- **План коммитов**: `test` (red) → `feat` (green) → `docs`

## RESEARCH  [status]  ← researcher
<!-- Gate R: Затронутые файлы / Текущая логика / Существующие тесты / Риски -->
<отчёт researcher + ссылки на research.md спеки>

## TESTS  [status]  ← test-writer
<!-- Gate T: pytest по новым тестам ДОЛЖЕН падать — вставить вывод -->
- Тесты: `<paths>`
- Red доказан: `pytest ... -x` → N failed (вставить вывод)

## IMPLEMENT  [status]  ← implementer
<!-- Gate I: pytest зелёный + ruff check/format src + mypy src -->
- Изменённые файлы: ...
- Связь правок с тестами: ...

## REVIEW  [status]  ← reviewer
<!-- Gate V: APPROVE / REQUEST_CHANGES; critical/major — в доработку, minor — в BACKLOG -->
- Вердикт: ...
- Minor → BACKLOG: <да/нет, что записано>

## GATE  [status]  ← run_checks.sh
- `run_checks.sh` exit 0: <да/нет>

## COMMITS
- `test(tests): ... (спека NNN, TNNN)` → <hash>
- `feat(<scope>): ... (спека NNN, TNNN)` → <hash>
- `docs(<scope>): ... (спека NNN, TNNN)` → <hash>

## METRICS
- Круги: R<n> T<n> I<n> V<n>; время: <о>
<!-- Копится для квартального ревью конституции: где цикл спотыкается -->

## DoD (заполняет супервизор, показывает в финальном отчёте)

- [ ] Red доказан pytest'ом (не «тесты написаны», а «упали»)
- [ ] Green доказан: те же тесты + ruff + mypy
- [ ] Ревью APPROVE; critical/major закрыты; minor → BACKLOG
- [ ] `run_checks.sh` exit 0
- [ ] Отметки `- [x]` проставлены в tasks.md спеки
- [ ] `.ai/01_PROJECT_STATE.md` обновлён; ROADMAP синхронизирован
- [ ] Серия слита в main зелёной; ветка удалена
- [ ] Пush оставлен пользователю
