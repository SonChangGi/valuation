import importlib.util
import io
import json
import re
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path


MODULE_PATH = Path("scripts/probe_providers.py")
SPEC = importlib.util.spec_from_file_location("probe_providers", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def endpoint_for(url):
    if "/submissions/" in url:
        return "submissions"
    if "/companyfacts/" in url:
        return "companyfacts"
    return "archive"


def ticker_for(url):
    for ticker, metadata in PROBE.TARGETS.items():
        if metadata["cik"] in url or str(int(metadata["cik"])) in url:
            return ticker
    raise AssertionError(f"No target matched sanitized test URL: {url}")


def valid_submissions(ticker):
    metadata = PROBE.TARGETS[ticker]
    return {
        "cik": int(metadata["cik"]),
        "name": f"{ticker} issuer",
        "tickers": [ticker],
        "filings": {
            "recent": {
                "form": [metadata["filing"]["form"]],
                "accessionNumber": ["0000000000-00-000001"],
                "primaryDocument": [metadata["filing"]["document"]],
            }
        },
    }


def valid_companyfacts(ticker):
    return {
        "cik": int(PROBE.TARGETS[ticker]["cik"]),
        "entityName": f"{ticker} issuer",
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {"USD": [{"val": 1, "form": "10-K"}]}
                }
            }
        },
    }


def valid_archive(ticker, marker=""):
    metadata = PROBE.TARGETS[ticker]
    filing = metadata["filing"]
    visible_period = datetime.strptime(filing["period_end"], "%Y-%m-%d").strftime(
        "%B %d, %Y"
    ).replace(" 0", " ")
    return (
        "<html xmlns:ix='http://www.xbrl.org/2013/inlineXBRL'><body>"
        f"<ix:nonNumeric name='dei:EntityCentralIndexKey'>{metadata['cik']}</ix:nonNumeric>"
        f"<ix:nonNumeric name='dei:DocumentType'>{filing['form']}</ix:nonNumeric>"
        f"<ix:nonNumeric name='dei:DocumentPeriodEndDate'>{visible_period}</ix:nonNumeric>"
        f"{marker}</body></html>"
    ).encode()


def success_result(ticker, endpoint):
    if endpoint == "submissions":
        body = json.dumps(valid_submissions(ticker)).encode()
        content_type = "application/json"
    elif endpoint == "companyfacts":
        body = json.dumps(valid_companyfacts(ticker)).encode()
        content_type = "application/json"
    else:
        body = valid_archive(ticker)
        content_type = "text/html"
    return {
        "ok": True,
        "access_status": "ok",
        "http_status": 200,
        "content_type": content_type,
        "body": body,
    }


class FakeTransport:
    def __init__(self, overrides=None, clock=None):
        self.overrides = {key: list(value) for key, value in (overrides or {}).items()}
        self.clock = clock
        self.calls = []

    def __call__(self, url, **_kwargs):
        ticker = ticker_for(url)
        endpoint = endpoint_for(url)
        self.calls.append((ticker, endpoint, self.clock.monotonic() if self.clock else None))
        queue = self.overrides.get((ticker, endpoint))
        value = queue.pop(0) if queue else success_result(ticker, endpoint)
        if isinstance(value, BaseException):
            raise value
        return value


def failed_http(status):
    return {
        "ok": False,
        "access_status": f"http_{status}",
        "http_status": status,
        "content_type": "text/html",
    }


class SecStrictGateTest(unittest.TestCase):
    def run_gate(self, overrides=None, user_agent="valuation-gate test@example.com"):
        clock = FakeClock()
        transport = FakeTransport(overrides=overrides, clock=clock)
        records, gate_status, exit_code = PROBE.run_sec_strict_gate(
            user_agent=user_agent,
            timeout=1.0,
            transport=transport,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        return records, gate_status, exit_code, transport

    def test_all_targets_and_endpoints_must_pass(self):
        records, gate_status, exit_code, transport = self.run_gate()
        self.assertEqual(0, exit_code)
        self.assertEqual("passed", gate_status)
        self.assertEqual(9, len(records))
        self.assertTrue(all(record["gate_status"] == "passed" for record in records))
        starts = [call[2] for call in transport.calls]
        self.assertTrue(
            all(
                later - earlier >= PROBE.SEC_STRICT_MIN_INTERVAL_SECONDS - 1e-9
                for earlier, later in zip(starts, starts[1:])
            )
        )

    def test_partial_failure_blocks_entire_gate(self):
        bad_archive = success_result("MU", "archive")
        bad_archive["body"] = valid_archive("MSFT")
        records, gate_status, exit_code, _transport = self.run_gate(
            {("MU", "archive"): [bad_archive]}
        )
        self.assertEqual(1, exit_code)
        self.assertEqual("blocked", gate_status)
        mu_archive = next(
            record for record in records if record["ticker"] == "MU" and record["endpoint"] == "archive"
        )
        self.assertEqual("identity_mismatch", mu_archive["schema_status"])

    def test_403_opens_circuit_without_retry(self):
        records, gate_status, exit_code, transport = self.run_gate(
            {("MSFT", "submissions"): [failed_http(403)]}
        )
        self.assertEqual((1, "blocked"), (exit_code, gate_status))
        self.assertEqual([("MSFT", "submissions")], [call[:2] for call in transport.calls])
        self.assertEqual("not_checked_http_403", records[0]["schema_status"])
        self.assertTrue(
            all(
                record["schema_status"] == "not_checked_circuit_open"
                for record in records[1:]
            )
        )

    def test_429_exhausts_bounded_retries_and_blocks(self):
        records, gate_status, exit_code, transport = self.run_gate(
            {("MSFT", "submissions"): [failed_http(429)] * 3}
        )
        self.assertEqual((1, "blocked"), (exit_code, gate_status))
        calls = [call for call in transport.calls if call[:2] == ("MSFT", "submissions")]
        self.assertEqual(PROBE.SEC_STRICT_MAX_ATTEMPTS, len(calls))
        self.assertEqual("not_checked_http_429", records[0]["schema_status"])

    def test_timeout_exhausts_bounded_retries_and_blocks(self):
        records, _gate_status, exit_code, transport = self.run_gate(
            {("MSFT", "submissions"): [TimeoutError()] * 3}
        )
        self.assertEqual(1, exit_code)
        calls = [call for call in transport.calls if call[:2] == ("MSFT", "submissions")]
        self.assertEqual(PROBE.SEC_STRICT_MAX_ATTEMPTS, len(calls))
        self.assertEqual("not_checked_timeout", records[0]["schema_status"])

    def test_invalid_json_blocks(self):
        invalid = success_result("MSFT", "submissions")
        invalid["body"] = b"not-json RAW_BODY_MARKER"
        records, _gate_status, exit_code, _transport = self.run_gate(
            {("MSFT", "submissions"): [invalid]}
        )
        self.assertEqual(1, exit_code)
        self.assertEqual("invalid_json", records[0]["schema_status"])

    def test_invalid_content_type_blocks_before_parsing(self):
        invalid = success_result("MSFT", "submissions")
        invalid["content_type"] = "text/html"
        records, _gate_status, exit_code, _transport = self.run_gate(
            {("MSFT", "submissions"): [invalid]}
        )
        self.assertEqual(1, exit_code)
        self.assertEqual("invalid_content_type", records[0]["schema_status"])

    def test_missing_user_agent_makes_no_requests(self):
        records, gate_status, exit_code, transport = self.run_gate(user_agent="  ")
        self.assertEqual((2, "blocked"), (exit_code, gate_status))
        self.assertEqual([], transport.calls)
        self.assertEqual(9, len(records))
        self.assertTrue(all(record["schema_status"] == "missing_user_agent" for record in records))

    def test_submissions_ticker_mismatch_blocks(self):
        mismatch = success_result("MSFT", "submissions")
        payload = valid_submissions("MSFT")
        payload["tickers"] = ["OTHER"]
        mismatch["body"] = json.dumps(payload).encode()
        records, _gate_status, exit_code, _transport = self.run_gate(
            {("MSFT", "submissions"): [mismatch]}
        )
        self.assertEqual(1, exit_code)
        self.assertEqual("identity_mismatch", records[0]["schema_status"])

    def test_companyfacts_cik_mismatch_blocks(self):
        mismatch = success_result("MSFT", "companyfacts")
        payload = valid_companyfacts("MSFT")
        payload["cik"] = int(PROBE.TARGETS["NVDA"]["cik"])
        mismatch["body"] = json.dumps(payload).encode()
        records, _gate_status, exit_code, _transport = self.run_gate(
            {("MSFT", "companyfacts"): [mismatch]}
        )
        self.assertEqual(1, exit_code)
        companyfacts = next(
            record
            for record in records
            if record["ticker"] == "MSFT" and record["endpoint"] == "companyfacts"
        )
        self.assertEqual("identity_mismatch", companyfacts["schema_status"])

    def test_output_contains_no_body_or_user_agent(self):
        invalid = success_result("MSFT", "submissions")
        invalid["body"] = b"RAW_BODY_MARKER"
        records, gate_status, _exit_code, _transport = self.run_gate(
            {("MSFT", "submissions"): [invalid]},
            user_agent="SECRET_USER_AGENT_MARKER",
        )
        output = io.StringIO()
        with redirect_stdout(output):
            PROBE.print_sec_strict_gate(records, gate_status)
        rendered = output.getvalue()
        self.assertNotIn("RAW_BODY_MARKER", rendered)
        self.assertNotIn("SECRET_USER_AGENT_MARKER", rendered)
        self.assertNotIn("body", rendered)


class SecSmokeWorkflowContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = Path(".github/workflows/data-refresh.yml").read_text(encoding="utf-8")

    def job(self, name):
        match = re.search(
            rf"(?ms)^  {re.escape(name)}:\n.*?(?=^  [A-Za-z0-9_-]+:\n|\Z)",
            self.workflow,
        )
        self.assertIsNotNone(match)
        return match.group(0)

    def test_manual_mode_and_existing_schedule_are_preserved(self):
        self.assertRegex(
            self.workflow,
            r"(?s)mode:.*?default: 'refresh'.*?options:.*?- refresh.*?- sec-egress-smoke",
        )
        self.assertEqual(1, self.workflow.count('cron: "15 5 * * 2-6"'))
        self.assertEqual(1, self.workflow.count('cron: "15 7 * * 2-6"'))

    def test_smoke_job_is_read_only_and_does_not_publish(self):
        smoke = self.job("sec-egress-smoke")
        self.assertIn(
            "if: github.event_name == 'workflow_dispatch' && inputs.mode == 'sec-egress-smoke'",
            smoke,
        )
        self.assertIn("permissions:\n      contents: read", smoke)
        self.assertIn("persist-credentials: false", smoke)
        self.assertIn("GITHUB_TOKEN: ${{ github.token }}", smoke)
        self.assertIn("SEC_USER_AGENT_CONFIGURED: ${{ vars.SEC_USER_AGENT != '' }}", smoke)
        self.assertIn("python scripts/probe_providers.py --sec-strict-gate", smoke)
        self.assertIn("--sec-user-agent-from-repository-variable", smoke)
        self.assertIn("if: always()", smoke)
        self.assertGreaterEqual(smoke.count("git status --porcelain --untracked-files=all -- docs/data"), 2)
        for forbidden in (
            "contents: write",
            "secrets.SEC_USER_AGENT",
            "SEC_USER_AGENT_VALUE",
            "${{ vars.SEC_USER_AGENT }}",
            "::add-mask::",
            "git add",
            "git commit",
            "git push",
            "update_data.py",
            "build-derived.mjs",
            "upload-artifact",
            "actions/cache",
        ):
            self.assertNotIn(forbidden, smoke)

    def test_smoke_only_dispatch_cannot_run_refresh_job(self):
        refresh = self.job("refresh")
        self.assertIn(
            "if: github.event_name == 'schedule' || (github.event_name == 'workflow_dispatch' && inputs.mode == 'refresh')",
            refresh,
        )
        self.assertNotIn("sec-egress-smoke", refresh)
        self.assertIn("python scripts/update_data.py", refresh)
        self.assertIn("Commit data refresh", refresh)


if __name__ == "__main__":
    unittest.main()
