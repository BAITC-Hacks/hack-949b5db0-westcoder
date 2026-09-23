"""Optional browser check: pip install playwright; uses installed Chrome."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".tools"))
from playwright.sync_api import sync_playwright, expect


def run(base_url="http://127.0.0.1:8000"):
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width":1440,"height":1050},device_scale_factor=1)
        page.on("pageerror", lambda error: errors.append(str(error)))
        with page.expect_response('**/api/recommend') as initial_response:
            page.goto(base_url,wait_until="networkidle")
        page.wait_for_selector(".candidate-card")
        assert page.locator(".candidate-card").count() == 3
        assert "4" in page.locator(".result-subtitle").inner_text()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(artifacts / "desktop.png"),full_page=True)
        page.locator("[data-detail='0']").click()
        assert page.locator("dialog").is_visible()
        breakdown = initial_response.value.json()['recommendations'][0]['score_breakdown']
        assert page.locator("dialog table tbody tr").count() == len(breakdown)
        page.keyboard.press("Escape")
        # Cards must display the backend explanation, including date and duration.
        initial = page.request.get(base_url + '/api/meta').json()
        expected = page.request.post(base_url + '/api/recommend',data=initial['demos'][0]['request']).json()
        for index,candidate in enumerate(expected['recommendations']):
            expect(page.locator('.explanation-box p').nth(index)).to_have_text(candidate['explanation'])
        page.locator("[data-demo='1']").click()
        expect(page.locator('#results')).to_have_attribute('aria-busy', 'false')
        assert page.locator(".candidate-card").count() == 2
        assert "Флорист" in page.locator(".query-chips").inner_text()
        page.locator("[data-demo='2']").click()
        page.wait_for_selector(".empty-state")
        assert "совпадений нет" in page.locator(".empty-state").inner_text()
        assert page.locator(".suggestion").count() > 0
        page.locator("[data-suggestion='0']").click()
        page.wait_for_selector(".candidate-card")
        assert page.locator(".candidate-card").count() > 0
        page.locator("[data-demo='3']").click()
        page.wait_for_selector(".empty-state")
        assert "категории пока нет" in page.locator(".empty-state").inner_text()
        page.locator("[data-demo='0']").click()
        page.wait_for_selector(".candidate-card")
        page.locator("#budget_kzt").fill("650000")
        assert page.locator("#dirty-notice").is_visible()
        page.locator("#submit-button").click()
        expect(page.locator('#results')).to_have_attribute('aria-busy', 'false')
        assert not page.locator("#dirty-notice").is_visible()
        # Fractional inputs accepted by the API must also be accepted by the form.
        page.locator('#budget_kzt').fill('650123.45')
        page.locator('#duration_hours').fill('0.25')
        with page.expect_response('**/api/recommend') as response:
            page.locator('#submit-button').click()
        assert response.value.status == 200
        assert response.value.json()['request']['budget_kzt'] == 650123.45
        assert response.value.json()['request']['duration_hours'] == 0.25
        expect(page.locator('#results')).to_have_attribute('aria-busy', 'false')
        page.locator('#duration_hours').fill('0')
        assert not page.locator('#duration_hours').evaluate('(input) => input.checkValidity()')
        page.locator('#duration_hours').fill('6')
        # Network failures and malformed responses must leave a working retry path.
        for response_type in ('offline', 'invalid_json'):
            def fail_request(route):
                if response_type == 'offline':
                    route.abort()
                else:
                    route.fulfill(status=502, content_type='text/html', body='<h1>Bad gateway</h1>')
            page.route('**/api/recommend', fail_request)
            page.locator('#submit-button').click()
            expect(page.locator('#retry-search')).to_be_visible()
            expect(page.locator('#submit-button')).to_be_enabled()
            expect(page.locator('#city')).to_be_enabled()
            page.unroute('**/api/recommend')
            page.locator('#retry-search').click()
            expect(page.locator('.candidate-card')).to_have_count(3)
            expect(page.locator('#results')).to_have_attribute('aria-busy', 'false')
        page.set_viewport_size({"width":390,"height":844})
        page.screenshot(path=str(artifacts / "mobile.png"),full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile horizontal overflow"
        page.locator("[data-detail='0']").click()
        assert page.locator("dialog").is_visible()
        page.locator("#close-dialog").click()
        startup = browser.new_page()
        startup.on('pageerror', lambda error: errors.append(str(error)))
        startup.route('**/api/meta', lambda route: route.abort())
        startup.goto(base_url)
        expect(startup.locator('#retry-init')).to_be_visible()
        startup.unroute('**/api/meta')
        startup.locator('#retry-init').click()
        expect(startup.locator('.candidate-card')).to_have_count(3)
        startup.close()
        # UI wiring for an explicit retry. Provider recovery is covered by backend tests.
        retried = []
        def transient_semantics(route):
            response = route.fetch()
            data = response.json()
            is_retry = route.request.post_data_json.get('refresh_semantic',False)
            retried.append(is_retry)
            if not is_retry:
                data['semantic_mode'] = 'unavailable'
                data['semantic_retry_allowed'] = True
            route.fulfill(response=response,json=data)
        page.route('**/api/recommend',transient_semantics)
        page.locator('#submit-button').click()
        expect(page.locator('#retry-semantic')).to_be_visible()
        page.locator('#retry-semantic').click()
        expect(page.locator('#retry-semantic')).to_have_count(0)
        expect(page.locator('#results')).to_have_attribute('aria-busy','false')
        assert retried == [False,True]
        page.unroute('**/api/recommend')
        assert not errors, errors
        browser.close()
    print(json.dumps({"browser":"Chrome","scenarios":4,"network_recovery":True,"fractional_inputs":True,"desktop":"1440x1050","mobile":"390x844","js_errors":errors,"status":"passed"}))


if __name__ == "__main__":
    run()
