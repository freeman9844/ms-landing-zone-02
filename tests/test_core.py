import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from harness import ROOT, run, call, account, group, STATE
from test_run_vm import invoke


class RouteTests(unittest.TestCase):
    def check_route(self, routes, destination, hop, address=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.json"
            path.write_text(json.dumps({"value": routes}))
            return subprocess.run(["python3", str(ROOT / "scripts/assert-route.py"),
                                   str(path), destination, hop] + ([address] if address else []),
                                  text=True, capture_output=True)

    def test_longer_blackhole_wins_over_default_internet(self):
        routes = [
            {"state": "Active", "addressPrefix": ["0.0.0.0/0"], "nextHopType": "Internet", "nextHopIpAddress": []},
            {"state": "Active", "addressPrefix": ["10.0.0.0/8"], "nextHopType": "None", "nextHopIpAddress": []},
        ]
        result = self.check_route(routes, "10.20.1.4", "None")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.check_route(routes, "10.20.1.4", "Internet").returncode, 0)

    def test_firewall_route_requires_correct_ip_and_active_state(self):
        routes = [{"state": "Active", "addressPrefix": ["10.20.0.0/16"],
                   "nextHopType": "VirtualAppliance", "nextHopIpAddress": ["10.0.2.4"]}]
        self.assertEqual(self.check_route(routes, "10.20.1.4", "VirtualAppliance", "10.0.2.4").returncode, 0)
        self.assertNotEqual(self.check_route(routes, "10.20.1.4", "VirtualAppliance", "10.0.2.5").returncode, 0)
        routes[0]["state"] = "Invalid"
        self.assertNotEqual(self.check_route(routes, "10.20.1.4", "VirtualAppliance", "10.0.2.4").returncode, 0)

    def test_missing_routes_are_not_success(self):
        self.assertNotEqual(self.check_route([], "10.20.1.4", "None").returncode, 0)


class HttpProofTests(unittest.TestCase):
    def probe(self, code, body, expected):
        response = invoke("")
        response["run_guest"] = True
        return run('source "$WORKSHOP_ROOT/scripts/verify-common.sh"; load_run state.json; '
                   f'http_proof state.json spokea 10.20.1.4 {expected}',
                   [account(), group("spokea"), response],
                   files={"bin/curl": f"#!/bin/sh\nprintf '%s\\n' '{body}'\nexit {code}\n"})

    def test_real_guest_checks_successful_body(self):
        self.assertEqual(self.probe(0, "spokeb", "spokeb").returncode, 0)
        self.assertNotEqual(self.probe(0, "wrong-server", "spokeb").returncode, 0)

    def test_http_error_is_not_network_deny(self):
        self.assertNotEqual(self.probe(22, "", "blocked").returncode, 0)
        self.assertNotEqual(self.probe(6, "", "blocked").returncode, 0)
        self.assertEqual(self.probe(28, "", "blocked").returncode, 0)

    def test_unexpected_success_is_not_deny(self):
        self.assertNotEqual(self.probe(0, "spokeb", "blocked").returncode, 0)


class CoreGateTests(unittest.TestCase):
    def test_unrelated_nsg_deny_is_not_the_lab_rule(self):
        result = run('source "$WORKSHOP_ROOT/scripts/verify-common.sh"; load_run state.json; '
                     'nsg_proof spokea 10.10.1.4 10.0.1.4 Deny', [
            call(["network", "watcher", "test-ip-flow", "-g", STATE["resourceGroups"]["spokea"],
                  "--vm", "vm-lzbegin-spokea-demo123", "--direction", "Inbound", "--protocol", "TCP",
                  "--local", "10.10.1.4:8080", "--remote", "10.0.1.4:50000", "-o", "json"],
                 {"access": "Deny", "ruleName": "defaultSecurityRules/DenyAllInBound"}),
        ])
        self.assertNotEqual(result.returncode, 0)

    def test_wrong_peering_count_stops_before_http(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
            account(), group("hub"),
            call(["network", "vnet", "peering", "list", "-g", STATE["resourceGroups"]["hub"],
                  "--vnet-name", "vnet-lzbegin-hub-demo123", "-o", "json"],
                 [{"peeringState": "Connected"}]),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("peerings", result.stderr)
