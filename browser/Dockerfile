# Browser sidecar: Playwright's Chromium image plus the matching playwright CLI, so it starts
# without downloading anything. Keep the version in step with backend/pyproject.toml.
ARG PLAYWRIGHT_VERSION=1.65.1
FROM mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble
ARG PLAYWRIGHT_VERSION
WORKDIR /opt/pw
RUN npm init -y >/dev/null && npm install --no-audit --no-fund playwright@${PLAYWRIGHT_VERSION} \
    && chown -R pwuser:pwuser /opt/pw
USER pwuser
EXPOSE 3000
CMD ["node", "/opt/pw/node_modules/playwright/cli.js", "run-server", "--port", "3000", "--host", "0.0.0.0"]
