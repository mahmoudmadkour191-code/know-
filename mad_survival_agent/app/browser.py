from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, BrowserContext, Page


class BrowserAgent:
    def __init__(self, data_dir: str, on_event=None):
        self.profile_dir = Path(data_dir) / "browser_profile"
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.on_event = on_event
        self._pw = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def _log(self, message: str) -> None:
        if self.on_event:
            await self.on_event(message)

    async def ensure(self) -> Page:
        if self.page and not self.page.is_closed():
            return self.page
        if self._pw is None:
            self._pw = await async_playwright().start()
        if self.context is None:
            self.context = await self._pw.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                viewport={"width": 1365, "height": 900},
                locale="en-US",
            )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self.page.set_default_timeout(15000)
        return self.page

    async def open(self, url: str) -> dict[str, Any]:
        page = await self.ensure()
        await page.goto(url, wait_until="domcontentloaded")
        await self._log(f"Browser opened: {page.url}")
        return await self.snapshot()

    async def snapshot(self, max_chars: int = 7000) -> dict[str, Any]:
        page = await self.ensure()
        title = await page.title()
        text = (await page.locator("body").inner_text(timeout=5000))[:max_chars]
        links = []
        loc = page.locator("a")
        count = min(await loc.count(), 60)
        for i in range(count):
            link = loc.nth(i)
            try:
                label = (await link.inner_text()).strip()
                href = await link.get_attribute("href")
                if label or href:
                    links.append({"text": label[:160], "href": href})
            except Exception:
                continue
        return {"url": page.url, "title": title, "text": text, "links": links[:40]}

    async def click(self, target: str) -> dict[str, Any]:
        page = await self.ensure()
        locator = page.get_by_role("button", name=target, exact=False)
        if await locator.count() == 0:
            locator = page.get_by_text(target, exact=False)
        if await locator.count() == 0:
            locator = page.locator(target)
        if await locator.count() == 0:
            raise RuntimeError(f"Could not find clickable target: {target}")
        await locator.first.click()
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        return await self.snapshot()

    async def type_text(self, target: str, text: str, clear: bool = True) -> dict[str, Any]:
        page = await self.ensure()
        locator = page.locator(target)
        if await locator.count() == 0:
            locator = page.get_by_label(target, exact=False)
        if await locator.count() == 0:
            locator = page.get_by_placeholder(target, exact=False)
        if await locator.count() == 0:
            raise RuntimeError(f"Could not find input: {target}")
        if clear:
            await locator.first.fill(text)
        else:
            await locator.first.type(text)
        return {"ok": True, "target": target, "url": page.url}

    async def press(self, key: str) -> dict[str, Any]:
        page = await self.ensure()
        await page.keyboard.press(key)
        await page.wait_for_timeout(500)
        return await self.snapshot()

    async def wait(self, seconds: float = 2) -> dict[str, Any]:
        page = await self.ensure()
        await page.wait_for_timeout(max(0, min(float(seconds), 30)) * 1000)
        return await self.snapshot()

    async def back(self) -> dict[str, Any]:
        page = await self.ensure()
        await page.go_back(wait_until="domcontentloaded")
        return await self.snapshot()

    async def current(self) -> dict[str, Any]:
        page = await self.ensure()
        return {"url": page.url, "title": await page.title()}

    async def close(self) -> None:
        if self.context:
            await self.context.close()
        if self._pw:
            await self._pw.stop()
        self.context = None
        self.page = None
        self._pw = None
