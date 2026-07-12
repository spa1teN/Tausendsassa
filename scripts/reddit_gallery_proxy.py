"""Reddit Gallery Proxy — runs on Raspberry Pi (residential IP).

HTTP service that accepts Reddit post URLs and returns all gallery images.
Uses Playwright to visit the page and extract image URLs from the DOM.

Setup on Pi:
  pip install playwright fastapi uvicorn
  playwright install chromium
  python reddit_gallery_proxy.py

Usage:
  POST /gallery  {"url": "https://www.reddit.com/r/sub/comments/id/title/"}
  → {"images": ["https://i.redd.it/abc.jpg", "https://i.redd.it/def.jpg"]}

The bot calls this service. On failure (Pi offline), falls back to RSS thumbnail.
"""
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import asyncio

app = FastAPI(title="Reddit Gallery Proxy")


class GalleryRequest(BaseModel):
    url: str


class GalleryResponse(BaseModel):
    images: list[str] = []
    error: Optional[str] = None


async def _extract_images(url: str) -> list[str]:
    """Use Playwright to extract Reddit gallery image URLs."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Block unnecessary resources for speed
        await page.route("**/*", lambda route: (
            route.abort()
            if route.request.resource_type in ("font", "media", "websocket")
            else route.continue_()
        ))

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            # Wait for gallery container or image elements
            await page.wait_for_selector(
                'img[src*="preview.redd.it"], img[src*="i.redd.it"], '
                'div[data-testid="gallery-viewer"], gallery-carousel',
                timeout=5000)
        except Exception:
            pass  # Page may have loaded enough

        # Extract all Reddit image URLs
        images = await page.evaluate("""() => {
            const urls = new Set();
            // Gallery images (high-res)
            document.querySelectorAll(
                'img[src*="preview.redd.it"], img[src*="i.redd.it"]'
            ).forEach(img => {
                let src = img.src || img.getAttribute('data-src') || '';
                if (src) urls.add(src);
            });
            // Fallback: faceplate images (gallery thumbnails)
            document.querySelectorAll(
                'faceplate-img[src*="preview.redd.it"], faceplate-img[src*="i.redd.it"]'
            ).forEach(el => {
                let src = el.getAttribute('src') || '';
                if (src) urls.add(src);
            });
            return [...urls];
        }""")

        await browser.close()
        return images


@app.post("/gallery", response_model=GalleryResponse)
async def get_gallery(req: GalleryRequest):
    try:
        images = await _extract_images(req.url)
        if not images:
            return GalleryResponse(images=[], error="no images found")
        return GalleryResponse(images=images)
    except Exception as e:
        return GalleryResponse(images=[], error=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)
