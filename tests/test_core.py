import json
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from harness import ROOT, run, call, account, group, STATE
from test_network_docs import (
    az,
    avnm_peerings,
    connectivity_config_id,
    effective_configuration,
    netid,
    network_group_id,
    rg,
    vnet,
)
from tests.test_run_vm import invoke


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
    def effective_call(self, zone, payload=None):
        return az([
            "network", "manager", "list-effective-connectivity-config",
            "--resource-group", rg(zone),
            "--virtual-network-name", vnet(zone),
            "-o", "json",
        ], effective_configuration(zone) if payload is None else payload)

    def peering_list_call(self, zone, peerings=None):
        return az([
            "network", "vnet", "peering", "list",
            "-g", rg(zone),
            "--vnet-name", vnet(zone),
            "-o", "json",
        ], avnm_peerings(zone) if peerings is None else peerings)

    def gate_calls(self):
        return [
            account(),
            group("hub"),
            self.effective_call("hub"),
            self.peering_list_call("hub"),
            group("spokea"),
            self.effective_call("spokea"),
            self.peering_list_call("spokea"),
            group("spokeb"),
            self.effective_call("spokeb"),
            self.peering_list_call("spokeb"),
        ]

    def test_unrelated_nsg_deny_is_not_the_lab_rule(self):
        result = run('source "$WORKSHOP_ROOT/scripts/verify-common.sh"; load_run state.json; '
                     'nsg_proof spokea 10.10.1.4 10.0.1.4 Deny', [
            call(["network", "watcher", "test-ip-flow", "-g", STATE["resourceGroups"]["spokea"],
                  "--vm", "vm-lzbegin-spokea-demo123", "--direction", "Inbound", "--protocol", "TCP",
                  "--local", "10.10.1.4:8080", "--remote", "10.0.1.4:50000", "-o", "json"],
                 {"access": "Deny", "ruleName": "defaultSecurityRules/DenyAllInBound"}),
        ])
        self.assertNotEqual(result.returncode, 0)

    def test_missing_effective_configuration_stops_before_http(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
            account(),
            group("hub"),
            self.effective_call("hub", {"value": []}),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("effective", result.stderr)

    def test_foreign_effective_configuration_id_stops_before_http(self):
        payload = copy.deepcopy(effective_configuration("hub"))
        payload["value"][0]["id"] = connectivity_config_id() + "-foreign"
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
            account(),
            group("hub"),
            self.effective_call("hub", payload),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("effective", result.stderr)

    def test_mesh_effective_configuration_stops_before_http(self):
        payload = copy.deepcopy(effective_configuration("hub"))
        payload["value"][0]["connectivityTopology"] = "Mesh"
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
            account(),
            group("hub"),
            self.effective_call("hub", payload),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("effective", result.stderr)

    def test_effective_configuration_requires_exact_hub_and_group_ids(self):
        cases = (
            ("hub", ["value", 0, "hubs", 0, "resourceId"],
             netid("hub", "virtualNetworks", vnet("hub")) + "/subnets/snet-management"),
            ("group", ["value", 0, "appliesToGroups", 0, "networkGroupId"],
             network_group_id() + "/staticMembers/spokea"),
        )
        for name, path, value in cases:
            with self.subTest(field=name):
                payload = copy.deepcopy(effective_configuration("hub"))
                cursor = payload
                for key in path[:-1]:
                    cursor = cursor[key]
                cursor[path[-1]] = value
                result = run('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
                    account(),
                    group("hub"),
                    self.effective_call("hub", payload),
                ])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("effective", result.stderr)

    def test_effective_configuration_accepts_false_booleans_before_peering_checks(self):
        payload = copy.deepcopy(effective_configuration("hub"))
        payload["value"][0]["deleteExistingPeering"] = False
        payload["value"][0]["isGlobal"] = False
        payload["value"][0]["appliesToGroups"][0]["isGlobal"] = False
        payload["value"][0]["appliesToGroups"][0]["useHubGateway"] = False
        peerings = copy.deepcopy(avnm_peerings("hub"))
        peerings[0]["peeringState"] = "Initiated"
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
            account(),
            group("hub"),
            self.effective_call("hub", payload),
            self.peering_list_call("hub", peerings),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("peerings", result.stderr)

    def test_extra_spoke_to_spoke_peering_stops_before_http(self):
        peerings = copy.deepcopy(avnm_peerings("spokea"))
        peerings.append({
            "name": "unexpected-a-to-b",
            "peeringState": "Connected",
            "remoteVirtualNetwork": {"id": netid("spokeb", "virtualNetworks", vnet("spokeb"))},
        })
        calls = self.gate_calls()[:7]
        calls[-1] = self.peering_list_call("spokea", peerings)
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("peerings", result.stderr)

    def test_missing_hub_spoke_direction_stops_before_http(self):
        calls = self.gate_calls()[:7]
        calls[-1] = self.peering_list_call("spokea", [])
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("peerings", result.stderr)

    def test_duplicate_remote_id_match_stops_before_http(self):
        spokea = netid("spokea", "virtualNetworks", vnet("spokea"))
        peerings = [
            {"name": "avnm-hub-a-1", "peeringState": "Connected",
             "remoteVirtualNetwork": {"id": spokea}},
            {"name": "avnm-hub-a-2", "peeringState": "Connected",
             "remoteVirtualNetwork": {"id": spokea.swapcase()}},
            {"name": "avnm-hub-b", "peeringState": "Connected",
             "remoteVirtualNetwork": {"id": netid("spokeb", "virtualNetworks", vnet("spokeb"))}},
        ]
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
            account(),
            group("hub"),
            self.effective_call("hub"),
            self.peering_list_call("hub", peerings),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("peerings", result.stderr)

    def test_initiated_peering_stops_before_http(self):
        peerings = copy.deepcopy(avnm_peerings("hub"))
        peerings[1]["peeringState"] = "Initiated"
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
            account(),
            group("hub"),
            self.effective_call("hub"),
            self.peering_list_call("hub", peerings),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("peerings", result.stderr)
