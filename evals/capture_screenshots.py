"""Screenshot the live app answering real questions (evidence for the README).

    pip install playwright==1.48.0
    python evals/capture_screenshots.py http://<alb-dns> docs/evidence

Uses the installed Microsoft Edge (channel="msedge"), so no browser download is needed on Windows.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SHOTS = [
    ("01-goa-budget-and-local-guide",
     "We are 4 friends with Rs 12,000 each. Can we do Goa for 3 nights in December? "
     "Ask the local guide what we should do there."),
    ("02-manali-monsoon-warning", "Is Manali a good idea in July for 4 friends, 3 nights?"),
    ("03-hampi-odd-group", "How much is Hampi per person for 5 friends, 2 nights?"),
]


def main(base_url: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        for name, question in SHOTS:
            page = browser.new_page(viewport={"width": 1100, "height": 900}, device_scale_factor=2)
            page.goto(base_url, wait_until="networkidle")
            page.fill("#q", question)
            page.click("#send")
            page.wait_for_selector(".msg .meta", timeout=120_000)   # chips appear when the answer is in
            page.wait_for_timeout(300)
            page.screenshot(path=str(out / f"{name}.png"), full_page=True)
            print(f"saved {name}.png")
            page.close()

        page = browser.new_page(viewport={"width": 900, "height": 300})
        page.goto(base_url.rstrip("/") + "/health/deep")
        page.screenshot(path=str(out / "04-health-deep.png"))
        print("saved 04-health-deep.png")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "docs/evidence")
