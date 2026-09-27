from pathlib import Path
import threading
import re
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler
from werkzeug.security import generate_password_hash
from hoanboy.app import create_app
from test_api import snapshot, measurement
from pypdf import PdfReader
from hoanboy.mapping import FIELDS


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def test_browser_login_sync_filing_report_offline_and_restore(tmp_path):
    state = {"offline": False}

    def reader():
        if state["offline"]:
            raise TimeoutError()
        base = measurement(
            age="30", height="170", gender="unknown", bhWHR="0.85", bhBodyScore="80"
        )
        for source, _, _, _ in FIELDS.values():
            base.setdefault(source, "10")
            base[source + "ListMin"] = "1"
            base[source + "ListMax"] = "100"
        return snapshot(
            *[
                dict(base, uid=str(i), time=f"2026-09-{20 + i:02} 10:00:00")
                for i in range(1, 6)
            ]
        )

    app = create_app(
        tmp_path,
        generate_password_hash("synthetic-password"),
        reader=reader,
        verified={
            "bhWeightKg": "synthetic fixture contract",
            "bhBodyFatRate": "synthetic fixture contract",
        },
    )
    server = make_server(
        "127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    artifacts = Path("test-results")
    artifacts.mkdir(exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1050})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if route.request.url.startswith(base)
                    else route.abort()
                ),
            )
            page.goto(base)
            page.get_by_label("操作帳號密碼").fill("synthetic-password")
            page.get_by_role("button", name="登入工作台").click()
            expect(page.get_by_role("heading", name="待歸檔量測")).to_be_visible()
            page.get_by_role("button", name="同步設備", exact=True).click()
            expect(page.get_by_role("link", name="核對歸檔").first).to_be_visible()
            page.screenshot(path=str(artifacts / "inbox.png"), full_page=True)
            page.get_by_role("link", name="02 病人與追蹤").click()
            page.get_by_label("病歷號", exact=True).fill("000123")
            page.get_by_label("姓名", exact=True).fill("虛構測試病人")
            page.get_by_label("手機（可共用）").fill("synthetic-source")
            page.get_by_role("button", name="建立病人", exact=True).click()
            expect(page.get_by_role("heading", name="虛構測試病人")).to_be_visible()
            page.get_by_role("link", name="01 待歸檔").click()
            page.get_by_role("link", name="核對歸檔").first.click()
            page.get_by_label("搜尋歸檔病人").fill("000123")
            page.get_by_role("button", name="搜尋", exact=True).click()
            page.get_by_label("選擇已確認病人").select_option(
                label="000123 · 虛構測試病人 · synthetic-source"
            )
            page.get_by_role("button", name="確認歸檔到所選病人").click()
            expect(
                page.get_by_role("button", name="保存／查看報告核對稿")
            ).to_be_visible()
            # Include five historical measurements in the print acceptance fixture.
            client = app.test_client()
            client.environ_base["HTTP_X_CSRF_TOKEN"] = client.post(
                "/api/login", json={"password": "synthetic-password"}
            ).json["csrf"]
            for mid in range(1, 5):
                assert (
                    client.post(
                        f"/api/measurements/{mid}/assignment", json={"patient_id": 1}
                    ).status_code
                    == 200
                )
            page.goto(base + "/#patient/1")
            expect(page.locator("#chart-weight circle")).to_have_count(5)
            tick = (
                page.locator("#chart-weight text")
                .filter(has_text=re.compile(r"^70\.0$"))
                .bounding_box()
            )
            point = page.locator("#chart-weight circle").first.bounding_box()
            assert (
                abs(tick["y"] + tick["height"] / 2 - point["y"] - point["height"] / 2)
                < 10
            )
            page.screenshot(path=str(artifacts / "timeline.png"), full_page=True)
            page.goto(base + "/#measurement/5")
            page.get_by_role("button", name="保存／查看報告核對稿").click()
            expect(
                page.get_by_role("heading", name="人體健康分析報告", exact=True)
            ).to_be_visible()
            assert page.locator("[data-section]").count() == 10
            expect(
                page.locator('[data-section="3"] tr').filter(has_text="bhWHR")
            ).to_contain_text("0.85 比值")
            report_url = page.url
            page.screenshot(path=str(artifacts / "report.png"), full_page=True)
            page.emulate_media(media="print")
            page.screenshot(path=str(artifacts / "report-print.png"), full_page=True)
            page.pdf(
                path=str(artifacts / "report.pdf"),
                prefer_css_page_size=True,
                print_background=True,
            )
            pdf = PdfReader(artifacts / "report.pdf")
            assert len(pdf.pages) == 1
            assert abs(float(pdf.pages[0].mediabox.width) - 595.28) < 2
            page.emulate_media(media="screen")
            state["offline"] = True
            page.goto(base)
            page.get_by_role("button", name="同步設備", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("設備離線")
            page.goto(report_url)
            expect(page.get_by_text("虛構測試病人", exact=True)).to_be_visible()
            page.goto(base + "/#backups")
            page.get_by_role("button", name="立即備份").click()
            expect(page.locator("#notice")).to_contain_text("手動備份已完成")
            page.get_by_role("button", name="隔離還原並驗證").first.click()
            expect(page.get_by_role("heading", name="隔離還原驗證通過")).to_be_visible()
            # Late search results cannot replace controls on a newer route.
            delayed = []
            page.route("**/api/patients?q=stale", lambda route: delayed.append(route))
            page.goto(base + "/#patients")
            expect(page.get_by_role("link", name="查看追蹤")).to_be_visible()
            page.get_by_label("搜尋病人").fill("stale")
            with page.expect_request("**/api/patients?q=stale"):
                page.get_by_role("button", name="搜尋", exact=True).click()
            page.get_by_role("link", name="01 待歸檔").click()
            page.get_by_role("link", name="02 病人與追蹤").click()
            expect(page.get_by_role("link", name="查看追蹤")).to_be_visible()
            delayed.pop().fulfill(
                json=[dict(id=999, mrn="old", name="STALE RESPONSE", phone="")]
            )
            expect(page.locator("#patient-list")).not_to_contain_text("STALE RESPONSE")

            # Successful mutations must not hide a failed automatic backup.
            (tmp_path / "backups").rename(tmp_path / "preserved-backups")
            (tmp_path / "backups").write_text("blocked destination")
            state["offline"] = False
            page.get_by_role("button", name="同步設備", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("同步完成")
            expect(page.locator("#backup-warning")).to_be_visible()
            page.reload()
            expect(page.locator("#backup-warning")).to_be_visible()
            page.goto(base + "/#measurement/5")
            page.get_by_role("button", name="保存／查看報告核對稿").click()
            expect(page.get_by_role("link", name="開啟報告核對稿")).to_be_visible()
            expect(page.locator("#backup-warning")).to_be_visible()
            (tmp_path / "backups").unlink()
            (tmp_path / "preserved-backups").rename(tmp_path / "backups")
            page.goto(base + "/#backups")
            page.get_by_role("button", name="立即備份").click()
            expect(page.locator("#backup-warning")).to_be_hidden()
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(base + "/#pending")
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            page.get_by_role("button", name="登出", exact=True).click()
            expect(page.get_by_label("操作帳號密碼")).to_be_visible()
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
