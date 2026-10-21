# Тонкая обёртка аддона: сама платформа уже собрана в образе (frontend, зависимости),
# здесь только точка входа, которая читает опции аддона и переводит их в переменные
# окружения. Так аддон не дублирует сборку и не тянет репозиторий в контекст.
ARG BUILD_VERSION=latest
FROM ghcr.io/alkamenos/smart-home-platform:${BUILD_VERSION}

COPY run.sh /run.sh
RUN chmod +x /run.sh

ENTRYPOINT ["/run.sh"]
CMD ["python", "-m", "src.main"]
