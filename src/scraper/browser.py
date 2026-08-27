from playwright.async_api import async_playwright, Page
from ..utils import random_user_agent


class Browser:
    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright = None
        self._browser = None

    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def is_alive(self) -> bool:
        try:
            return self._browser is not None and self._browser.is_connected()
        except Exception:
            return False

    async def restart(self):
        try:
            await self.stop()
        except Exception:
            pass
        await self.start()

    async def new_page(self) -> Page:
        context = await self._browser.new_context(user_agent=random_user_agent())
        return await context.new_page()