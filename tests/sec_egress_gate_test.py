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
        cls.legacy_workflow_path = Path(".github/workflows/data-refresh.yml")
        cls.workflow_path = Path(".github/workflows/sec-egress-smoke.yml")
        cls.workflow = cls.workflow_path.read_text(encoding="utf-8")
        cls.probe = Path("scripts/probe_providers.py").read_text(encoding="utf-8")

    def job(self, name):
        match = re.search(
            rf"(?ms)^  {re.escape(name)}:\n.*?(?=^  [A-Za-z0-9_-]+:\n|\Z)",
            self.workflow,
        )
        self.assertIsNotNone(match)
        return match.group(0)

    def test_legacy_refresh_is_removed_and_trigger_is_manual_only(self):
        self.assertFalse(self.legacy_workflow_path.exists())
        self.assertTrue(self.workflow_path.exists())
        self.assertRegex(
            self.workflow,
            r"(?m)^name: SEC egress smoke\n\non:\n  workflow_dispatch:\n\npermissions:",
        )
        for forbidden_trigger in (
            "inputs:",
            "schedule:",
            "cron:",
            "push:",
            "pull_request:",
        ):
            self.assertNotIn(forbidden_trigger, self.workflow)

    def test_smoke_job_is_read_only_and_does_not_publish(self):
        smoke = self.job("sec-egress-smoke")
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertIn("permissions:\n      contents: read", smoke)
        self.assertEqual(2, self.workflow.count("contents: read"))
        self.assertIn("runs-on: ubuntu-latest", smoke)
        self.assertIn("timeout-minutes: 10", smoke)
        self.assertIn(
            "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7",
            smoke,
        )
        self.assertIn(
            "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405 # v6",
            smoke,
        )
        self.assertIn("persist-credentials: false", smoke)
        self.assertIn("python-version: '3.12'", smoke)
        self.assertIn("SEC_USER_AGENT: ${{ vars.SEC_USER_AGENT }}", smoke)
        self.assertEqual(
            1,
            smoke.count("python scripts/probe_providers.py --sec-strict-gate"),
        )
        self.assertIn("if: always()", smoke)
        self.assertEqual(
            2,
            smoke.count("git status --porcelain --untracked-files=all -- docs/data"),
        )
        self.assertRegex(
            smoke,
            r"(?s)- name: Verify docs/data remains unchanged\n"
            r"        if: always\(\)\n"
            r"        run: test -z .*?docs/data",
        )
        for forbidden in (
            "contents: write",
            "secrets.SEC_USER_AGENT",
            "${{ github.token }}",
            "GITHUB_TOKEN",
            "SEC_USER_AGENT_CONFIGURED",
            "--sec-user-agent-from-repository-variable",
            "SEC_USER_AGENT_VALUE",
            "::add-mask::",
            "token:",
            "git add",
            "git commit",
            "git push",
            "scripts/update_data.py",
            "scripts/check_data_freshness.py",
            "scripts/verify_publication_freshness.py",
            "build-derived.mjs",
            "upload-artifact",
            "actions/cache",
        ):
            self.assertNotIn(forbidden, smoke)
        for removed_probe_path in (
            "fetch_github_repository_variable",
            "--sec-user-agent-from-repository-variable",
            "SEC_USER_AGENT_CONFIGURED",
            "GITHUB_TOKEN",
            "/actions/variables/",
        ):
            self.assertNotIn(removed_probe_path, self.probe)

    def test_smoke_is_the_only_job_and_has_no_refresh_mode(self):
        jobs = self.workflow.split("\njobs:\n", 1)[1]
        job_names = re.findall(r"(?m)^  ([A-Za-z0-9_-]+):\n", jobs)
        self.assertEqual(["sec-egress-smoke"], job_names)
        self.assertNotRegex(self.workflow, r"(?m)^  refresh:\s*$")
        self.assertNotIn("inputs.mode", self.workflow)
        self.assertNotIn("mode:", self.workflow)


if __name__ == "__main__":
    unittest.main()
