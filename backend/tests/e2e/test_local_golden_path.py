#!/usr/bin/env python3
"""AdaptaAI LOCAL E2E golden-path — nightly autonomous run (2026-05-28).

Scenario:
  Scene 1  — HR login (demo button → Войти)
  Scene 2  — RAG upload demo_ru.pdf → "Проиндексировано N chunks" toast, N>0
  Scene 3  — Invite creation → token returned
  Scene 4  — Migrant open invite → accept → hub with "Раджу"
  Scene 5  — AI chat: "Во сколько начинается смена?" → streamed answer + Cyrillic citation
  Scene 6  — HR worker sync: "Раджу Шарма" in workers table
  Scene 7  — Workers table: country flag shown, object shown, relative time shown
  Scene 8  — Worker detail row click → detail page loads with real name (not placeholder)
  Scene 9  — PWA: manifest.json + sw.js respond with 200

Artifacts: backend/tests/e2e/artifacts/ (video + screenshots)
Exit 0 = all critical checks pass, 1 = bugs found.
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


def info(msg: str) -> None:
    print(f"  [info] {msg}")


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

        # HR context
        hr_ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(ART),
            locale="ru-RU",
        )
        hr = hr_ctx.new_page()
        wire_listeners(hr, "HR")

        # Migrant context
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
            hr.wait_for_selector("#demo-login-btn", timeout=10000)
            hr.click("#demo-login-btn")
            hr.click("#login-btn")
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
        # SCENE 2 — RAG upload
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 2: RAG upload ===")
        pdf = (Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "demo_ru.pdf")
        try:
            hr.goto(f"{BASE}/b2b/17-rag-upload.html", wait_until="networkidle")
            hr.wait_for_selector("#dropzone", timeout=10000)
            if not pdf.exists():
                bug("2 RAG upload", "fixture demo_ru.pdf exists", f"missing: {pdf}")
            else:
                file_input = hr.wait_for_selector("input[type=file]", state="attached", timeout=10000)
                file_input.set_input_files(str(pdf))
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
                    bug("2 RAG upload", "toast 'Проиндексировано N chunks' N>0", f"toast={indexed_text!r} N={n}", "02_upload_indexed.png")
        except Exception as e:  # noqa: BLE001
            bug("2 RAG upload", "indexed toast N>0", f"exception: {e}", shot(hr, "02_upload_FAIL.png"))

        # ════════════════════════════════════════════════════════════════════
        # SCENE 3 — Invite creation
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 3: Invite creation ===")
        token = None
        try:
            hr.goto(f"{BASE}/b2b/15-hr-dashboard.html", wait_until="networkidle")
            hr.wait_for_selector(".kpi-card__value", timeout=10000)
            hr.click(".btn.btn-primary.btn-sm")
            hr.wait_for_selector("#inv-email", timeout=8000)
            unique_suffix = str(int(time.time()))[-6:]
            hr.fill("#inv-email", f"raju.e2e.{unique_suffix}@example.com")
            hr.fill("#inv-first", "Раджу")
            hr.fill("#inv-last", "Шарма")
            hr.select_option("#inv-lang", "ru")
            hr.click("#invite-submit")
            hr.wait_for_selector("#invite-link-block", state="visible", timeout=15000)
            link_text = (hr.text_content("#invite-link-block") or "").strip()
            shot(hr, "03_invite_created.png")
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
        # SCENE 4 — Migrant accept → hub
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 4: Migrant accept -> hub ===")
        if not token:
            bug("4 Migrant accept", "valid token from scene 3", "no token, skipping")
        else:
            try:
                mig.goto(f"{BASE}/b2c/01-welcome.html?invite={token}", wait_until="networkidle")
                mig.wait_for_selector("#invite-banner", timeout=12000)
                banner_txt = (mig.text_content("#invite-banner") or "")
                shot(mig, "04a_welcome_invite.png")
                if "Раджу" not in banner_txt:
                    bug("4 Welcome banner", "banner shows 'Раджу'", f"banner={banner_txt!r}", "04a_welcome_invite.png")
                mig.wait_for_selector("#invite-accept-btn", timeout=8000)
                mig.click("#invite-accept-btn")
                mig.wait_for_url("**/04-hub.html", timeout=15000)
                mig.wait_for_selector("[data-user-name]", timeout=10000)
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
        # SCENE 5 — AI chat streamed answer + Cyrillic citation (ONE query)
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 5: AI chat streaming + citation Cyrillic ===")
        try:
            mig.goto(f"{BASE}/b2c/05-ai-chat.html", wait_until="networkidle")
            mig.wait_for_selector(".composer__input", timeout=10000)
            pre_agent = mig.query_selector_all(".bubble-row--agent")
            pre_n = len(pre_agent)
            mig.fill(".composer__input", "Во сколько начинается смена?")
            mig.press(".composer__input", "Enter")

            mig.wait_for_function(
                "(n) => document.querySelectorAll('.bubble-row--agent').length > n",
                arg=pre_n,
                timeout=20000,
            )
            new_bubble = mig.query_selector_all(".bubble-row--agent")[-1]
            stream_text = ""
            deadline = time.time() + 90
            while time.time() < deadline:
                el = new_bubble.query_selector(".bubble-agent__text-stream")
                stream_text = (el.text_content() or "").strip() if el else ""
                if len(stream_text) > 5:
                    break
                time.sleep(0.5)

            time.sleep(2.0)  # wait for citations to land
            shot(mig, "05_chat_answer.png")

            if stream_text and len(stream_text) > 5:
                ok(f"Streamed answer ({len(stream_text)} chars): {stream_text[:80]!r}")
                passed_scenes.add(5)
            else:
                bug("5 Chat stream", "streamed agent answer text", f"text={stream_text!r}", "05_chat_answer.png")

            # Citation Cyrillic guard
            chips = new_bubble.query_selector_all(".rag-citation")
            if not chips:
                deadline = time.time() + 15
                while time.time() < deadline and not chips:
                    time.sleep(1.0)
                    chips = new_bubble.query_selector_all(".rag-citation")
            shot(mig, "05b_chat_citation.png")
            if not chips:
                bug("5 Citation chip", "≥1 .rag-citation chip on new bubble", "no citation chips rendered", "05b_chat_citation.png")
                results["citation_cyrillic"] = "FAIL"
            else:
                cyr_found = False
                details = []
                for c in chips:
                    vis = (c.text_content() or "").strip()
                    title = (c.get_attribute("title") or "").strip()
                    details.append({"text": vis, "title": title})
                    blob = vis + " " + title
                    if "?????" in blob:
                        bug("5 Citation snippet", "Cyrillic snippet (not ?????)", f"chip={vis!r} title={title!r}", "05b_chat_citation.png")
                    if CYRILLIC.search(title) or CYRILLIC.search(vis):
                        cyr_found = True
                info(f"citation chips: {details}")
                if cyr_found:
                    ok("Citation chip contains Cyrillic — regression guard PASS")
                    results["citation_cyrillic"] = "PASS"
                else:
                    bug("5 Citation Cyrillic", "Cyrillic text in citation chip/snippet", f"chips={details}", "05b_chat_citation.png")
                    results["citation_cyrillic"] = "FAIL"
        except Exception as e:  # noqa: BLE001
            bug("5 Chat", "streamed answer + Cyrillic citation", f"exception: {e}", shot(mig, "05_chat_FAIL.png"))
            if results["citation_cyrillic"] is None:
                results["citation_cyrillic"] = "FAIL"

        # ════════════════════════════════════════════════════════════════════
        # SCENE 6 — HR worker sync (Раджу Шарма in table)
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 6: HR worker sync ===")
        try:
            hr.goto(f"{BASE}/b2b/15-hr-dashboard.html", wait_until="networkidle")
            hr.wait_for_selector(".workers-tbody tr", timeout=10000)
            found = False
            deadline = time.time() + 30
            while time.time() < deadline:
                body = hr.text_content(".workers-tbody") or ""
                # toast-container is created lazily by showToast(); use evaluate to avoid timeout
                toasts = hr.evaluate("() => { const el = document.getElementById('toast-container'); return el ? el.textContent : ''; }") or ""
                if "Раджу" in body or "Шарма" in body or "Раджу" in toasts:
                    found = True
                    break
                time.sleep(1.5)
            shot(hr, "06_hr_workers_sync.png")
            if found:
                ok("HR dashboard shows worker 'Раджу Шарма'")
                passed_scenes.add(6)
            else:
                bug("6 HR sync", "'Раджу Шарма' in workers table or notification toast", "not found within 30s", "06_hr_workers_sync.png")
        except Exception as e:  # noqa: BLE001
            bug("6 HR sync", "new worker visible", f"exception: {e}", shot(hr, "06_sync_FAIL.png"))

        # ════════════════════════════════════════════════════════════════════
        # SCENE 7 — Workers table: country flag, object (Метрополия), relative time
        # Sergey's specific checks from 2026-05-28 session
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 7: Workers table columns (flag / object / time) ===")
        try:
            hr.goto(f"{BASE}/b2b/15-hr-dashboard.html", wait_until="networkidle")
            hr.wait_for_selector(".workers-tbody tr", timeout=10000)
            time.sleep(2)  # let API fetch complete

            # Check country flag column
            flags = hr.query_selector_all(".country-flag")
            shot(hr, "07_workers_table.png")
            if flags:
                flag_texts = [(f.text_content() or "").strip() for f in flags]
                # At least one flag should be a real emoji flag or country symbol (not "—")
                non_empty = [t for t in flag_texts if t and t != "—"]
                if non_empty:
                    ok(f"Country flag column has values: {flag_texts[:3]}")
                    passed_scenes.add(7)
                else:
                    bug("7 Country flag", "flag emoji or code in .country-flag", f"all values: {flag_texts}", "07_workers_table.png")
            else:
                bug("7 Country flag", ".country-flag elements in workers table", "none found", "07_workers_table.png")

            # Check object column (Метрополия or any non-dash value)
            rows = hr.query_selector_all(".workers-tbody tr")
            obj_texts = []
            for row in rows:
                cells = row.query_selector_all("td")
                if len(cells) >= 3:
                    obj_texts.append((cells[2].text_content() or "").strip())
            info(f"Object column values: {obj_texts}")
            non_dash_objs = [t for t in obj_texts if t and t != "—"]
            if non_dash_objs:
                ok(f"Object column has values: {non_dash_objs}")
            else:
                bug("7 Object column", "site/object name in workers table col-3", f"all dash: {obj_texts}", "07_workers_table.png")

            # Check relative/formatted time column (last col before actions)
            time_texts = []
            for row in rows:
                cells = row.query_selector_all("td")
                if len(cells) >= 6:
                    time_texts.append((cells[5].text_content() or "").strip())
            info(f"Time column values: {time_texts}")
            non_dash_times = [t for t in time_texts if t and t != "—"]
            if non_dash_times:
                ok(f"Time column has values: {non_dash_times[:3]}")
            else:
                bug("7 Relative time", "time value in workers table", f"all dash: {time_texts}", "07_workers_table.png")

        except Exception as e:  # noqa: BLE001
            bug("7 Workers table columns", "flag/object/time visible", f"exception: {e}", shot(hr, "07_workers_FAIL.png"))

        # ════════════════════════════════════════════════════════════════════
        # SCENE 8 — Click worker row → detail page loads with real name
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 8: Worker detail row click ===")
        try:
            hr.goto(f"{BASE}/b2b/15-hr-dashboard.html", wait_until="networkidle")
            hr.wait_for_selector(".workers-tbody tr", timeout=10000)
            time.sleep(1.5)
            first_row = hr.query_selector(".workers-tbody tr")
            if not first_row:
                bug("8 Worker detail", "at least one worker row", "empty table", shot(hr, "08_detail_FAIL.png"))
            else:
                # Get expected name before clicking
                name_cell = first_row.query_selector(".name-cell")
                expected_name = (name_cell.text_content() or "").strip() if name_cell else ""
                info(f"Clicking worker row: {expected_name!r}")
                first_row.click()
                hr.wait_for_url("**/16-worker-detail.html", timeout=10000)
                hr.wait_for_selector("[data-worker-name]", timeout=8000)
                # Give inline script time to run
                time.sleep(1.0)
                detail_name = (hr.text_content("[data-worker-name]") or "").strip()
                shot(hr, "08_worker_detail.png")
                # The detail page replaces "Сотрудник" placeholder with real name
                is_placeholder = detail_name in ("Сотрудник", "Employee", "कर्मचारी")
                if expected_name and not is_placeholder and len(detail_name) > 3:
                    ok(f"Worker detail shows name: {detail_name!r} (expected from row: {expected_name!r})")
                    passed_scenes.add(8)
                elif is_placeholder:
                    bug("8 Worker detail", f"real name (e.g. {expected_name!r})", f"placeholder text: {detail_name!r}", "08_worker_detail.png")
                else:
                    bug("8 Worker detail", f"name text populated", f"got: {detail_name!r}", "08_worker_detail.png")
        except Exception as e:  # noqa: BLE001
            bug("8 Worker detail", "detail page with real name", f"exception: {e}", shot(hr, "08_detail_FAIL.png"))

        # ════════════════════════════════════════════════════════════════════
        # SCENE 9 — PWA manifest.json + sw.js reachable (with JWT)
        # ════════════════════════════════════════════════════════════════════
        print("\n=== SCENE 9: PWA manifest.json + sw.js ===")
        try:
            jwt = hr.evaluate("() => localStorage.getItem('adapta_jwt')")
            # Use fetch from browser context to get resources with auth cookie if needed
            manifest_status = mig.evaluate("""async (jwt) => {
                const r = await fetch('/b2c/manifest.json', { headers: jwt ? {'Authorization': 'Bearer ' + jwt} : {} });
                return r.status;
            }""", jwt)
            sw_status = mig.evaluate("""async (jwt) => {
                const r = await fetch('/b2c/sw.js', { headers: jwt ? {'Authorization': 'Bearer ' + jwt} : {} });
                return r.status;
            }""", jwt)
            info(f"manifest.json status: {manifest_status}, sw.js status: {sw_status}")
            if manifest_status == 200 and sw_status == 200:
                ok("PWA manifest.json and sw.js both return 200")
                passed_scenes.add(9)
            else:
                bug("9 PWA files", "manifest.json=200 sw.js=200", f"manifest={manifest_status} sw={sw_status}", "")
        except Exception as e:  # noqa: BLE001
            bug("9 PWA", "manifest + sw.js reachable", f"exception: {e}", "")

        # ── teardown ────────────────────────────────────────────────────────
        hr_ctx.close()
        mig_ctx.close()
        browser.close()

    # ════════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ════════════════════════════════════════════════════════════════════════
    total_scenes = 9
    print("\n" + "=" * 60)
    print("E2E RUN SUMMARY (LOCAL GOLDEN PATH — 2026-05-28)")
    print("=" * 60)
    print(f"Scenes passed: {len(passed_scenes)}/{total_scenes}  -> {sorted(passed_scenes)}")
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
