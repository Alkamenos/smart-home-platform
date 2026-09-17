# Правила коммита для ИИ-агента

## Перед коммитом ОБЯЗАТЕЛЬНО:

1. Убедись, что переменная окружения установлена:
   ```bash
   export AI_AGENT=1
   ```

2. **Pre-commit хук активирован:**
   ```bash
   git config core.hooksPath .githooks
   ```
   
   Это гарантирует, что `.githooks/pre-commit` будет запускаться автоматически перед КАЖДЫМ коммитом.
   
   Если хук не настроен, выполни:
   ```bash
   ./.ai/scripts/setup_hooks.sh
   ```

3. **Что проверяет pre-commit хук:**
   - ✅ Запускает `.ai/scripts/run_checks.sh` (тесты, mypy, ruff, interrogate)
   - ✅ Проверяет актуальность ROADMAP через `sync_roadmap.py`
   - ✅ Блокирует коммит при любой ошибке

4. **Если pre-commit не сработал:**
   - Проверь настройку: `git config core.hooksPath` (должно быть `.githooks`)
   - Убедись, что `.githooks/pre-commit` исполняемый: `chmod +x .githooks/pre-commit`
   - Запусти проверки вручную: `./.ai/scripts/run_checks.sh`

## Важные изменения

### Автоматическая синхронизация ROADMAP
Pre-commit хук теперь автоматически:
1. Проверяет, соответствует ли статус задач в ROADMAP наличию файлов кода
2. Если файлы задачи существуют, но статус `[ ]` — предлагает обновить ROADMAP
3. Требует добавить изменения ROADMAP в коммит

### Четкий статус "почти готово"
Если задача выполнена (файлы созданы), но ROADMAP не обновлен:
- Pre-commit покажет предупреждение
- Автоматически обновит `.ai/03_ROADMAP.md`
- Заблокирует коммит с сообщением добавить ROADMAP в staging

## Чек-лист быстрого старта

```
[ ] git config core.hooksPath = .githooks ✅
[ ] .githooks/pre-commit исполняемый ✅
[ ] .ai/scripts/run_checks.sh исполняемый ✅
[ ] .ai/scripts/sync_roadmap.py исполняемый ✅
```
