from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from engineering_council import council


class CouncilTests(unittest.TestCase):
    def packet(self, **kwargs: object) -> dict:
        return council.make_packet("change", "Keep the observable behavior", "small diff", 10, **kwargs)

    def report(self, packet: dict, agent: str, **changes: object) -> dict:
        finding = {
            "target": "worker.py:20",
            "severity": "major",
            "category": "simplicity",
            "action": "remove",
            "problem": "Duplicate retry loop",
            "evidence": "The caller already retries this operation.",
            "recommendation": "Remove the inner retry loop.",
            "without_change": "Nested retries multiply latency.",
            "effort_minutes": 5,
        }
        return {
            "request_id": packet["request_id"],
            "agent": agent,
            "findings": [{**finding, **changes}],
        }

    def reports(self, packet: dict) -> list[dict]:
        return [{"request_id": packet["request_id"], "agent": agent, "findings": []} for agent in packet["roles"]]

    def test_nontrivial_work_runs_all_seven_in_requested_order(self) -> None:
        expected = ["Ponytail", "Architect", "Hamilton", "Lambda", "Feynman", "Delivery", "Finisher"]
        for kind in ("change", "pr", "plan", "architecture"):
            packet = council.make_packet(kind, "brief", "context", 10)
            self.assertEqual(packet["roles"], expected)
            self.assertEqual(packet["budget_seconds"], 150)

    def test_feynman_challenges_do_not_overrule_or_trigger_another_round(self) -> None:
        packet = self.packet()
        reports = self.reports(packet)
        reports[0] = self.report(packet, "Ponytail")
        reports[4] = self.report(packet, "Feynman", severity="blocker", action="keep")
        decision = council.decide(packet, reports)
        self.assertEqual(decision["status"], "recommend")
        self.assertFalse(decision["disagreements"])
        self.assertEqual(decision["findings"][-1]["agent"], "Feynman")

    def test_finisher_termination_recommends_implementation_without_bypassing_safety(self) -> None:
        packet = self.packet()
        reports = self.reports(packet)
        reports[6] = self.report(
            packet,
            "Finisher",
            category="completion",
            recommendation="STOP DISCUSSING. IMPLEMENT THE SIMPLEST WORKING VERSION.",
        )
        decision = council.decide(packet, reports)
        self.assertIn("STOP DISCUSSING", decision["next_action"])
        reports[2] = self.report(packet, "Hamilton", severity="blocker", category="safety", action="keep")
        decision = council.decide(packet, reports)
        self.assertEqual(decision["status"], "needs-human")
        self.assertIn("human", decision["next_action"].lower())

    def test_conflict_recommendations_follow_requested_authority_order(self) -> None:
        packet = self.packet()
        reports = [
            self.report(packet, agent, category="assumptions", recommendation=f"{agent} recommendation")
            for agent in packet["roles"]
        ]
        decision = council.decide(packet, reports)
        self.assertEqual(
            [finding["agent"] for finding in decision["findings"]],
            ["Hamilton", "Ponytail", "Delivery", "Finisher", "Architect", "Lambda", "Feynman"],
        )

    def test_high_risk_keeps_safety_and_cannot_silently_skip_reviewers(self) -> None:
        packet = council.make_packet("plan", "brief", "plan", 10, risk="high")
        self.assertIn("Hamilton", packet["roles"])
        full = self.packet(full=True)
        self.assertEqual(len(full["roles"]), 7)
        with self.assertRaisesRegex(ValueError, "max_calls"):
            self.packet(config=replace(council.Config(), max_calls=3))

    def test_review_budget_never_exceeds_implementation_fraction(self) -> None:
        packet = council.make_packet("change", "brief", "diff", 1)
        self.assertEqual(packet["budget_seconds"], 15)

    def test_rejects_oversized_input_and_invalid_config(self) -> None:
        with self.assertRaisesRegex(ValueError, "input"):
            council.make_packet("change", "brief", "x" * 30_000, 10)
        for changes in ({"max_calls": True}, {"max_calls": 8}, {"review_fraction": 0}, {"max_seconds": float("nan")}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(council.Config(), **changes)

    def test_safety_blocker_cannot_be_outvoted_by_deletion(self) -> None:
        packet = self.packet()
        reports = self.reports(packet)
        reports[2] = self.report(packet, "Hamilton", severity="blocker", category="safety", action="keep")
        reports[0] = self.report(packet, "Ponytail")
        decision = council.decide(packet, reports)
        self.assertEqual(decision["status"], "needs-human")
        self.assertEqual(decision["findings"][0]["agent"], "Hamilton")
        self.assertTrue(decision["disagreements"])

    def test_missing_reviews_are_not_a_clean_review(self) -> None:
        packet = self.packet()
        decision = council.decide(packet, self.reports(packet)[:1])
        self.assertEqual(decision["status"], "incomplete")
        self.assertEqual(decision["missing"], ["Architect", "Hamilton", "Lambda", "Feynman", "Delivery", "Finisher"])
        self.assertIn("smallest", decision["next_action"])

    def test_duplicate_wrong_order_and_unbound_reports_are_rejected(self) -> None:
        packet = self.packet()
        reports = self.reports(packet)
        for invalid in ([reports[0], reports[0]], list(reversed(reports)), [{**reports[0], "request_id": "stale"}]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                council.decide(packet, invalid)

    def test_findings_require_evidence_and_strict_fields(self) -> None:
        packet = self.packet()
        for changes in ({"evidence": ""}, {"severity": "critical"}, {"effort_minutes": -1}, {"extra": "ignored"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                council.decide(packet, [self.report(packet, "Ponytail", **changes)])

    def test_ranking_preserves_role_priority_and_deduplicates(self) -> None:
        packet = self.packet()
        reports = self.reports(packet)
        reports[2] = self.report(packet, "Hamilton", category="state", target="state.py:2", effort_minutes=1)
        reports[0] = self.report(packet, "Ponytail")
        reports[5] = self.report(packet, "Delivery")
        decision = council.decide(packet, reports)
        self.assertEqual(len(decision["findings"]), 2)
        self.assertEqual(decision["findings"][0]["agent"], "Hamilton")
        self.assertEqual(decision["status"], "recommend")
        self.assertIn("human", decision["next_action"].lower())

    def test_packet_tampering_is_rejected(self) -> None:
        packet = self.packet()
        with self.assertRaisesRegex(ValueError, "packet"):
            council.decide({**packet, "content": "different diff"}, [])

    def test_malformed_native_shapes_do_not_pass_validation(self) -> None:
        packet = self.packet()
        for altered in ({**packet, "version": True}, {**packet, "full": "yes"}, {**packet, "brief": 10}):
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                council.decide(altered, [])
        with self.assertRaisesRegex(ValueError, "array"):
            council.decide(packet, {})

    def test_adapter_stops_at_a_blocker_and_retains_the_finding(self) -> None:
        packet = self.packet()
        report = self.report(packet, "Hamilton", severity="blocker", category="safety")
        code = (
            "import json,sys; p=json.load(sys.stdin); "
            f"r={report!r}; r['agent']=p['agent']; "
            "r['findings']=r['findings'] if p['agent']=='Hamilton' else []; print(json.dumps(r))"
        )
        decision = council.run(packet, [sys.executable, "-c", code])
        self.assertEqual(decision["status"], "incomplete")
        self.assertEqual(decision["completed"], ["Ponytail", "Architect", "Hamilton"])
        self.assertEqual(decision["findings"][0]["severity"], "blocker")
        self.assertEqual(decision["missing"], ["Lambda", "Feynman", "Delivery", "Finisher"])

    def test_duplicate_adapter_keys_cannot_hide_blocker_findings(self) -> None:
        packet = self.packet()
        findings = self.report(packet, "Hamilton", severity="blocker")["findings"]
        code = (
            "import json,sys; p=json.load(sys.stdin); "
            f"r={{'request_id':p['packet']['request_id'],'agent':p['agent'],'findings':{findings!r}}}; "
            "print(json.dumps(r)[:-1]+',\"findings\":[]}')"
        )
        decision = council.run(packet, [sys.executable, "-c", code])
        self.assertEqual(decision["status"], "incomplete")
        self.assertEqual(decision["completed"], [])
        self.assertIn("duplicate", decision["errors"][0])

    def test_duplicate_native_report_keys_are_rejected_before_decision(self) -> None:
        packet = self.packet()
        report = self.report(packet, "Hamilton", severity="blocker")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet_path, reports_path, output = (root / name for name in ("packet", "reports", "decision"))
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            reports_path.write_text("[" + json.dumps(report)[:-1] + ',"findings":[]}]', encoding="utf-8")
            result = council.main(
                [
                    "decide",
                    "--packet",
                    str(packet_path),
                    "--reports",
                    str(reports_path),
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())

    def test_adapter_runs_sequentially_once_and_receives_no_prior_reviews(self) -> None:
        packet = self.packet()
        code = (
            "import json,sys; p=json.load(sys.stdin); "
            "assert 'reports' not in p; "
            "print(json.dumps({'request_id':p['packet']['request_id'],'agent':p['agent'],'findings':[]}))"
        )
        decision = council.run(packet, [sys.executable, "-c", code])
        self.assertEqual(decision["status"], "recommend")
        self.assertEqual(decision["completed"], packet["roles"])

    def test_adapter_errors_stop_pipeline_without_success(self) -> None:
        packet = self.packet()
        for code in ("raise SystemExit(9)", "print('not JSON')", "print('x'*20000)"):
            with self.subTest(code=code):
                decision = council.run(packet, [sys.executable, "-c", code])
                self.assertEqual(decision["status"], "incomplete")
                self.assertEqual(decision["completed"], [])
                self.assertTrue(decision["errors"])

    def test_timeout_and_simultaneous_stream_flood_are_bounded(self) -> None:
        config = replace(council.Config(), max_seconds=1)
        packet = self.packet(config=config)
        for code in (
            "import time; time.sleep(5)",
            "import sys; sys.stderr.write('x'*20000); sys.stdout.write('x'*20000)",
        ):
            with self.subTest(code=code):
                decision = council.run(packet, [sys.executable, "-c", code])
                self.assertEqual(decision["status"], "incomplete")
                self.assertLess(decision["elapsed_seconds"], 3)

    @unittest.skipUnless(sys.platform == "linux", "POSIX process-group isolation")
    def test_descendant_cannot_keep_review_running_after_parent_exits(self) -> None:
        packet = self.packet(config=replace(council.Config(), max_seconds=1))
        code = "import os,time; pid=os.fork(); time.sleep(5) if pid == 0 else None"
        decision = council.run(packet, [sys.executable, "-c", code])
        self.assertEqual(decision["status"], "incomplete")
        self.assertLess(decision["elapsed_seconds"], 3)

    def test_native_reports_and_cli_decision_work_without_an_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, packet_path, reports_path, output = (
                root / name for name in ("diff", "packet", "reports", "decision")
            )
            source.write_text("diff", encoding="utf-8")
            self.assertEqual(
                council.main(
                    [
                        "packet",
                        "--input",
                        str(source),
                        "--brief",
                        "Preserve behavior",
                        "--implementation-minutes",
                        "10",
                        "--output",
                        str(packet_path),
                    ]
                ),
                0,
            )
            packet = json.loads(packet_path.read_text())
            reports_path.write_text(json.dumps(self.reports(packet)), encoding="utf-8")
            self.assertEqual(
                council.main(
                    [
                        "decide",
                        "--packet",
                        str(packet_path),
                        "--reports",
                        str(reports_path),
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
            self.assertEqual(json.loads(output.read_text())["status"], "recommend")
            self.assertEqual(
                council.main(
                    [
                        "decide",
                        "--packet",
                        str(packet_path),
                        "--reports",
                        str(reports_path),
                        "--output",
                        str(output),
                    ]
                ),
                1,
            )

    def test_agent_installation_preserves_existing_files_until_explicit_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            agents = repo / ".github" / "agents"
            agents.mkdir(parents=True)
            old = agents / "code-review-critic.agent.md"
            old.write_text("old", encoding="utf-8")
            council.install_agents(repo)
            self.assertTrue(old.exists())
            self.assertTrue((agents / "council.agent.md").exists())
            council.install_agents(repo, replace_old=True)
            self.assertFalse(old.exists())
            self.assertTrue((agents / "finisher.agent.md").exists())
            self.assertTrue((agents / "feynman.agent.md").exists())
            self.assertEqual(len(list(agents.glob("*.agent.md"))), 8)

    def test_installation_rejects_symlink_destinations_before_any_changes(self) -> None:
        for relative in (".github", ".github/agents", ".github/agents/hamilton.agent.md"):
            with self.subTest(destination=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo, outside = root / "repo", root / "outside"
                repo.mkdir()
                outside.mkdir()
                link = repo / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                target = outside / "escaped.agent.md" if relative.endswith(".md") else outside
                link.symlink_to(target, target_is_directory=not relative.endswith(".md"))
                agents = repo / ".github" / "agents"
                agents.mkdir(parents=True, exist_ok=True)
                legacy = agents / "code-review-critic.agent.md"
                legacy.write_text("preserve legacy", encoding="utf-8")
                before = sorted(path.relative_to(outside) for path in outside.rglob("*"))
                with self.assertRaisesRegex(ValueError, "symlink"):
                    council.install_agents(repo, replace_old=True)
                self.assertTrue(link.is_symlink())
                self.assertEqual(legacy.read_text(encoding="utf-8"), "preserve legacy")
                self.assertEqual(sorted(path.relative_to(outside) for path in outside.rglob("*")), before)
                self.assertFalse((agents / "architect.agent.md").exists())

    def test_feynman_advisory_blocker_does_not_skip_delivery_or_finisher(self) -> None:
        packet = self.packet()
        finding = self.report(packet, "Feynman", severity="blocker", category="assumptions")["findings"]
        code = (
            "import json,sys; p=json.load(sys.stdin); "
            f"f={finding!r} if p['agent']=='Feynman' else []; "
            "print(json.dumps({'request_id':p['packet']['request_id'],'agent':p['agent'],'findings':f}))"
        )
        decision = council.run(packet, [sys.executable, "-c", code])
        self.assertEqual(decision["status"], "recommend")
        self.assertEqual(decision["completed"][-2:], ["Delivery", "Finisher"])


if __name__ == "__main__":
    unittest.main()
