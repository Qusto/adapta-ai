#!/usr/bin/env python3
"""AdaptaAI E2E golden-path demo-flow — real Chromium (Playwright sync).

Drives the full B2B2C demo through two browser contexts:
  HR (context 1):   login -> RAG upload -> create invite -> get token
  Migrant (ctx 2):  open invite -> accept -> hub -> AI chat (streamed answer)

Then cross-actor sync: HR notifications polling shows the new worker.

Runs against a live stack at http://localhost:8000 (FastAPI StaticFiles + API).
Collects ALL bugs in one run (does NOT stop at first failure): every assertion
is wrapped so a failure is recorded + screenshotted, then the run continues.

Artifacts (video + screenshots) -> backend/tests/e2e/artifacts/.

Usage:
    cd backend && uv run python tests/e2e/test_demo_flow.py
    # or with pytest:  uv run pytest tests/e2e/test_demo_flow.py -s

Exit code 0 = all critical asserts passed, 1 = bugs found.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "http://localhost:8000"
ART = Path(__file__).parent / "artifacts"
ART.mkdir(parents=True, exist_ok=True)

CYRILLIC = re.compile(r"[Ѐ-ӿ]")

# ── run-state collectors ────────────────────────────────────────────────────
bugs: list[dict] = []
passed_scenes: set[int] = set()
console_errors: list[str] = []
network_errors: list[str] = []
results: dict = {"citation_cyrillic": None, "invite_token": None}


def bug(scene: str, expected: str, actual: str, shot: str = "") -> None:
    entry = {"scene": scene, "expected": expected, "actual": actual, "screenshot": shot}
    bugs.append(entry)
    print(f"  [BUG] {scene}: expected={expected!r} actual={actual!r}")


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def shot(page: Page, name: str) -> str:
    path = ART / name
    try:
        page.screenshot(path=str(path), full_page=False)
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] screenshot {name} failed: {e}")
    return str(path)


def wire_listeners(page: Page, tag: str) -> None:
    def on_console(msg):
        if msg.type == "error":
            txt = f"[{tag}] {msg.text}"
            console_errors.append(txt)
            print(f"  [console.error] {txt}")

    def on_response(resp):
        if resp.status >= 400:
            txt = f"[{tag}] {resp.status} {resp.url}"
            network_errors.append(txt)
            print(f"  [net {resp.status}] {resp.url}")

    page.on("console", on_console)
    page.on("response", on_response)


def main() -> int:  # noqa: PLR0915, C901
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ── HR context (1) ──────────────────────────────────────────────────
        hr_ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(ART),
            locale="ru-RU",
        )
        hr = hr_ctx.new_page()
        wire_listeners(hr, "HR")

        # ── Migrant context (2) ─────────────────────────────────────────────
        mig_ctx = browser.new_context(
            viewport={"width": 414, "height": 896},
            record_video_dir=str(ART),
            locale="ru-RU",
        )
        mig = mig_ctx.new_page()
        wire_listeners(mig, "MIGRANT")

        # ════════════════════════════════════════════════════════════════════
        # SCENE 1 — HR login
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 1: HR login ===")
        try:
            hr.goto(f"{BASE}/b2b/15-hr-dashboard.html", wait_until="networkidle")
            # Demo button fills credentials, then click "Войти"
            hr.wait_for_selector("#demo-login-btn", timeout=10000)
            hr.click("#demo-login-btn")
            hr.click("#login-btn")
            # Dashboard ready when login overlay gone + KPI visible
            hr.wait_for_selector("#login-overlay", state="detached", timeout=15000)
            hr.wait_for_selector(".kpi-card__value", timeout=10000)
            shot(hr, "01_hr_login.png")
            jwt = hr.evaluate("() => localStorage.getItem('adapta_jwt')")
            if jwt:
                ok("HR logged in, JWT stored")
                passed_scenes.add(1)
            else:
                bug("1 HR login", "JWT in localStorage", "no JWT", "01_hr_login.png")
        except Exception as e:  # noqa: BLE001
            bug("1 HR login", "dashboard loads", f"exception: {e}", shot(hr, "01_hr_login_FAIL.png"))

        # ════════════════════════════════════════════════════════════════════
        # SCENE 2 — RAG upload (demo_ru.pdf) -> "Indexed N chunks" toast, N>0
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 2: RAG upload ===")
        pdf = (Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "demo_ru.pdf")
        try:
            hr.goto(f"{BASE}/b2b/17-rag-upload.html", wait_until="networkidle")
            hr.wait_for_selector("#dropzone", timeout=10000)
            if not pdf.exists():
                bug("2 RAG upload", "fixture demo_ru.pdf exists", f"missing: {pdf}")
            else:
                # The hidden file input is appended to <body> by wireDropzone().
                file_input = hr.wait_for_selector("input[type=file]", state="attached", timeout=10000)
                file_input.set_input_files(str(pdf))
                # Wait for success toast: "Проиндексировано N chunks: ..."
                toast = hr.wait_for_selector(
                    "#toast-container .toast", timeout=60000
                )
                # The first toast is "Загрузка ..."; poll until success/indexed toast appears.
                indexed_text = ""
                deadline = time.time() + 60
                while time.time() < deadline:
                    toasts = hr.query_selector_all("#toast-container .toast")
                    for t in toasts:
                        txt = (t.text_content() or "").strip()
                        if "роиндексировано" in txt or "Indexed" in txt:
                            indexed_text = txt
                            break
                    if indexed_text:
                        break
                    time.sleep(0.5)
                shot(hr, "02_upload_indexed.png")
                m = re.search(r"(\d+)", indexed_text)
                n = int(m.group(1)) if m else 0
                if indexed_text and n > 0:
                    ok(f"RAG indexed toast: {indexed_text!r} (N={n})")
                    passed_scenes.add(2)
                else:
                    bug(
                        "2 RAG upload",
                        "toast 'Проиндексировано N chunks' with N>0",
                        f"toast={indexed_text!r} N={n}",
                        "02_upload_indexed.png",
                    )
        except Exception as e:  # noqa: BLE001
            bug("2 RAG upload", "indexed toast N>0", f"exception: {e}", shot(hr, "02_upload_FAIL.png"))

        # ════════════════════════════════════════════════════════════════════
        # SCENE 3 — Invite modal -> create invite -> get token
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 3: Invite creation ===")
        token = None
        try:
            hr.goto(f"{BASE}/b2b/15-hr-dashboard.html", wait_until="networkidle")
            hr.wait_for_selector(".kpi-card__value", timeout=10000)
            # "Добавить сотрудника" button opens invite modal
            hr.click(".btn.btn-primary.btn-sm")
            hr.wait_for_selector("#inv-email", timeout=8000)
            hr.fill("#inv-email", "raju.e2e@example.com")
            hr.fill("#inv-first", "Раджу")
            hr.fill("#inv-last", "Шарма")
            hr.select_option("#inv-lang", "ru")
            hr.click("#invite-submit")
            # Link block becomes visible with API + '/i/' + token
            hr.wait_for_selector("#invite-link-block", state="visible", timeout=15000)
            link_text = (hr.text_content("#invite-link-block") or "").strip()
            shot(hr, "03_invite_created.png")
            # Extract token after /i/
            if "/i/" in link_text:
                token = link_text.split("/i/", 1)[1].strip()
            if token:
                results["invite_token"] = token[:24] + "…"
                ok(f"Invite token received (len={len(token)})")
                passed_scenes.add(3)
            else:
                bug("3 Invite", "token in link block", f"link={link_text!r}", "03_invite_created.png")
        except Exception as e:  # noqa: BLE001
            bug("3 Invite", "invite token created", f"exception: {e}", shot(hr, "03_invite_FAIL.png"))

        # ════════════════════════════════════════════════════════════════════
        # SCENE 4 — Migrant opens invite, accepts -> redirect to hub w/ "Раджу"
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 4: Migrant accept -> hub ===")
        if not token:
            bug("4 Migrant accept", "valid token from scene 3", "no token, skipping")
        else:
            try:
                mig.goto(f"{BASE}/b2c/01-welcome.html?invite={token}", wait_until="networkidle")
                # Invite banner with migrant name should appear
                mig.wait_for_selector("#invite-banner", timeout=12000)
                banner_txt = (mig.text_content("#invite-banner") or "")
                shot(mig, "04a_welcome_invite.png")
                if "Раджу" not in banner_txt:
                    bug(
                        "4 Welcome banner",
                        "banner shows 'Раджу'",
                        f"banner={banner_txt!r}",
                        "04a_welcome_invite.png",
                    )
                # Accept
                mig.wait_for_selector("#invite-accept-btn", timeout=8000)
                mig.click("#invite-accept-btn")
                # Redirect to hub
                mig.wait_for_url("**/04-hub.html", timeout=15000)
                mig.wait_for_selector("[data-user-name]", timeout=10000)
                # Allow the greeting render to run
                mig.wait_for_function(
                    "() => { const e = document.querySelector('[data-user-name]'); return e && e.textContent.trim().length > 0; }",
                    timeout=8000,
                )
                name_txt = (mig.text_content("[data-user-name]") or "").strip()
                shot(mig, "04b_hub.png")
                if "Раджу" in name_txt:
                    ok(f"Hub greets migrant: {name_txt!r}")
                    passed_scenes.add(4)
                else:
                    bug("4 Hub name", "greeting contains 'Раджу'", f"name={name_txt!r}", "04b_hub.png")
            except Exception as e:  # noqa: BLE001
                bug("4 Migrant accept", "hub with 'Раджу'", f"exception: {e}", shot(mig, "04_accept_FAIL.png"))

        # ════════════════════════════════════════════════════════════════════
        # SCENE 5 — AI chat: ask "Во сколько начинается смена?" -> streamed answer
        #           + citation chip with CYRILLIC snippet (regression guard)
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 5: AI chat streaming + citation Cyrillic ===")
        try:
            mig.goto(f"{BASE}/b2c/05-ai-chat.html", wait_until="networkidle")
            mig.wait_for_selector(".composer__input", timeout=10000)
            # Count pre-existing (mock) agent bubbles to target only the NEW one.
            pre_agent = mig.query_selector_all(".bubble-row--agent")
            pre_n = len(pre_agent)
            mig.fill(".composer__input", "Во сколько начинается смена?")
            mig.press(".composer__input", "Enter")

            # Wait for a NEW agent bubble to be created
            mig.wait_for_function(
                "(n) => document.querySelectorAll('.bubble-row--agent').length > n",
                arg=pre_n,
                timeout=20000,
            )
            new_bubble = mig.query_selector_all(".bubble-row--agent")[-1]
            # Wait for streamed text to accumulate inside this bubble
            stream_text = ""
            deadline = time.time() + 90
            while time.time() < deadline:
                el = new_bubble.query_selector(".bubble-agent__text-stream")
                stream_text = (el.text_content() or "").strip() if el else ""
                if len(stream_text) > 5:
                    break
                time.sleep(0.5)

            # Wait a bit more for citations to land after the answer completes
            time.sleep(2.0)
            shot(mig, "05_chat_answer.png")

            if stream_text and len(stream_text) > 5:
                ok(f"Streamed answer ({len(stream_text)} chars): {stream_text[:80]!r}")
                # Soft check: mentions shift/time
                if re.search(r"смен|8[:.]00|08[:.]00|восемь|07[:.]|начин", stream_text, re.I):
                    ok("Answer mentions shift/start time")
                else:
                    print(f"  [info] answer text (no explicit shift kw): {stream_text[:160]!r}")
                passed_scenes.add(5)
            else:
                bug(
                    "5 Chat stream",
                    "streamed agent answer text",
                    f"text={stream_text!r}",
                    "05_chat_answer.png",
                )

            # ── Citation Cyrillic guard ─────────────────────────────────────
            chips = new_bubble.query_selector_all(".rag-citation")
            if not chips:
                # citations may still be loading; poll a little more
                deadline = time.time() + 15
                while time.time() < deadline and not chips:
                    time.sleep(1.0)
                    chips = new_bubble.query_selector_all(".rag-citation")
            shot(mig, "05b_chat_citation.png")
            if not chips:
                bug(
                    "5 Citation chip",
                    "≥1 .rag-citation chip on new bubble",
                    "no citation chips rendered",
                    "05b_chat_citation.png",
                )
                results["citation_cyrillic"] = "FAIL"
            else:
                # Inspect chip visible text (document_name) and title (snippet)
                cyr_found = False
                details = []
                for c in chips:
                    vis = (c.text_content() or "").strip()
                    title = (c.get_attribute("title") or "").strip()
                    details.append({"text": vis, "title": title})
                    blob = vis + " " + title
                    if "?????" in blob:
                        bug(
                            "5 Citation snippet",
                            "Cyrillic snippet (not ?????)",
                            f"chip={vis!r} title={title!r}",
                            "05b_chat_citation.png",
                        )
                    if CYRILLIC.search(title) or CYRILLIC.search(vis):
                        cyr_found = True
                print(f"  [info] citation chips: {details}")
                if cyr_found:
                    ok("Citation chip contains Cyrillic (snippet/name) — regression guard PASS")
                    results["citation_cyrillic"] = "PASS"
                else:
                    bug(
                        "5 Citation Cyrillic",
                        "Cyrillic text in citation chip/snippet",
                        f"chips={details}",
                        "05b_chat_citation.png",
                    )
                    results["citation_cyrillic"] = "FAIL"
        except Exception as e:  # noqa: BLE001
            bug("5 Chat", "streamed answer + Cyrillic citation", f"exception: {e}", shot(mig, "05_chat_FAIL.png"))
            if results["citation_cyrillic"] is None:
                results["citation_cyrillic"] = "FAIL"

        # ════════════════════════════════════════════════════════════════════
        # SCENE 6 — HR worker sync: "Раджу Шарма" appears (notifications polling)
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 6: HR worker sync (polling) ===")
        try:
            # Reload HR dashboard so workers table re-fetches from API.
            hr.goto(f"{BASE}/b2b/15-hr-dashboard.html", wait_until="networkidle")
            hr.wait_for_selector(".workers-tbody tr", timeout=10000)
            found = False
            deadline = time.time() + 30
            while time.time() < deadline:
                body = hr.text_content(".workers-tbody") or ""
                # Toasts from notification polling also carry the name
                toasts = hr.text_content("#toast-container") or ""
                if "Раджу" in body or "Шарма" in body or "Раджу" in toasts:
                    found = True
                    break
                time.sleep(1.5)
            shot(hr, "06_hr_workers_sync.png")
            if found:
                ok("HR dashboard shows new worker 'Раджу Шарма'")
                passed_scenes.add(6)
            else:
                bug(
                    "6 HR sync",
                    "'Раджу Шарма' in workers table or notification toast",
                    "not found within 30s",
                    "06_hr_workers_sync.png",
                )
        except Exception as e:  # noqa: BLE001
            bug("6 HR sync", "new worker visible", f"exception: {e}", shot(hr, "06_sync_FAIL.png"))

        # ── teardown ────────────────────────────────────────────────────────
        hr_ctx.close()
        mig_ctx.close()
        browser.close()

    # ════════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("E2E RUN SUMMARY")
    print("=" * 60)
    print(f"Scenes passed: {len(passed_scenes)}/6  -> {sorted(passed_scenes)}")
    print(f"Citation Cyrillic check: {results['citation_cyrillic']}")
    print(f"Invite token: {results['invite_token']}")
    print(f"\nBugs ({len(bugs)}):")
    for b in bugs:
        print(f"  - [{b['scene']}] expected={b['expected']!r} actual={b['actual']!r} shot={b['screenshot']}")
    print(f"\nConsole errors ({len(console_errors)}):")
    for c in console_errors[:30]:
        print(f"  - {c}")
    print(f"\nNetwork errors ({len(network_errors)}):")
    for n in network_errors[:30]:
        print(f"  - {n}")
    print(f"\nArtifacts dir: {ART}")
    print("=" * 60)

    return 0 if not bugs else 1


if __name__ == "__main__":
    sys.exit(main())
