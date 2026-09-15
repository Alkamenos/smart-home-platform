# LLM / NLP Adapter

**Приоритет:** LOW (Future)
**Оценка:** 3-5 дней
**Категория:** Advanced Features

## Цель

Управление платформой на естественном языке.

## Проблема

Сейчас управление только через YAML манифесты и Python.

## Предлагаемое решение

Фраза *"Сделай в гостиной уютно"* парсится через LLM и превращается в `CommandIntent`:

```json
{
  "device_id": "light.living_room",
  "domain": "light",
  "service": "turn_on",
  "data": {"brightness": 80, "color_temp": 370},
  "priority": 20,
  "source": "nlp_user_command"
}
```

## План реализации

1. `adapters/nlp_adapter.py` — адаптер для LLM
2. `core/nlp_parser.py` — парсинг ответа в `CommandIntent`
3. Интеграция с:
   - Локальными моделями через Ollama (llama3, mistral)
   - Облачными API (OpenAI, Anthropic) — опционально
4. Контекст: текущие комнаты, устройства, состояния
5. Тесты с фиксированными промптами

## Файлы

- `adapters/nlp_adapter.py`
- `core/nlp_parser.py`
- `tests/test_nlp_adapter.py`

## Критерии успеха

- [ ] Понимание команд на русском и английском
- [ ] Контекст (комната, устройства) учитывается
- [ ] Подтверждение опасных команд перед выполнением
- [ ] Покрытие тестами >= 70%

## Зависимости

- `ollama` или `openai` Python клиент
- Для локального запуска: установленный Ollama с моделью
