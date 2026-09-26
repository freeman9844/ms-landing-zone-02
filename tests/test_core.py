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
    enforced_connectivity_calls,
    effective_configuration,
    netid,
    network_group_id,
    rg,
    vnet,
)
import test_avnm_redesign as redesign
from test_workshop_safety import ready_calls, admin_calls, CONFIG
from tests.test_run_vm import invoke


def admin_rule_id(zone, name):
    return f"{CONFIG}/ruleCollections/{zone}/rules/{name}"


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
    def run_core(self, script, calls, **kwargs):
        calls = list(calls)
        if calls and calls[0]["argv"] == account()["argv"]:
            calls[1:1] = enforced_connectivity_calls()
        return run(script, calls, **kwargs)

    def test_unenforced_connectivity_stops_before_vm_and_http_evidence(self):
        calls = enforced_connectivity_calls()[:2]
        config = json.loads(calls[-1]["stdout"])
        config["connectivityCapabilities"]["peeringEnforcement"] = "Unenforced"
        calls[-1]["stdout"] = json.dumps(config)
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline',
                     [account(), *calls])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unenforced Connectivity", result.stderr)

    def test_live_hub_outside_spoke_group_and_effective_without_target_reach_route_checks(self):
        spokea = copy.deepcopy(effective_configuration("spokea"))
        spokeb = copy.deepcopy(effective_configuration("spokeb"))
        del spokea["value"][0]["targetVirtualNetwork"]
        del spokeb["value"][0]["targetVirtualNetwork"]
        result = self.run_core('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
            account(),
            group("hub"),
            self.effective_call("hub", {"value": []}),
            self.peering_list_call("hub"),
            group("spokea"),
            self.effective_call("spokea", spokea),
            self.peering_list_call("spokea"),
            group("spokeb"),
            self.effective_call("spokeb", spokeb),
            self.peering_list_call("spokeb"),
            call(["network", "nic", "show", "-g", rg("hub"), "-n", "nic-lzbegin-hub-demo123",
                  "--query", "ipConfigurations[0].privateIPAddress", "-o", "tsv"], "invalid"),
        ])
        self.assertNotIn("Unexpected effective AVNM connectivity", result.stderr)
        self.assertIn("invalid VM IP", result.stderr)

    def effective_call(self, zone, payload=None):
        return az([
            "network", "manager", "list-effective-connectivity-config",
            "--resource-group", rg(zone),
            "--virtual-network-name", vnet(zone),
            "-o", "json",
        ], effective_configuration(zone, enforcement="Enforced") if payload is None else payload)

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

    def network_calls(self):
        return self.gate_calls() + [
            call(["network", "nic", "show", "-g", rg(zone),
                  "-n", f"nic-lzbegin-{zone}-demo123",
                  "--query", "ipConfigurations[0].privateIPAddress", "-o", "tsv"], ip)
            for zone, ip in (("hub", "10.0.1.4"), ("spokea", "10.10.1.4"),
                             ("spokeb", "10.20.1.4"))
        ] + ready_calls() + redesign.route_calls()

    def test_all_stages_reject_wrong_route_or_nat_before_http(self):
        routes = redesign.route_calls()
        routes[-1] = copy.deepcopy(routes[-1])
        table = json.loads(routes[-1]["stdout"])
        table["routes"][0]["nextHopIpAddress"] = "10.0.2.9"
        routes[-1]["stdout"] = json.dumps(table)
        prefix = self.network_calls()[:-len(redesign.route_calls())]
        for stage in ("baseline", "admin-denied", "restored"):
            with self.subTest(stage=stage, issue="route"):
                result = self.run_core(f'bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json {stage}',
                             prefix + routes)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Subnet routes", result.stderr)
            with self.subTest(stage=stage, issue="nat"):
                nat = redesign.SpokeNatAbsenceTests().calls(nat={"name": "unexpected"})
                result = self.run_core(f'bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json {stage}',
                             self.network_calls() + nat)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unexpected Spoke NAT", result.stderr)

    def test_stage_specific_admin_rule_is_checked_before_http(self):
        for stage, fixture_stage, rule_name in (
            ("baseline", "baseline", "hub-to-a"),
            ("admin-denied", "denied", "deny-hub-to-a"),
            ("restored", "restored", "a-to-b"),
        ):
            security = admin_calls(fixture_stage)
            index = next(i for i, entry in enumerate(security) if
                         "--rule-name" in entry["argv"] and
                         entry["argv"][entry["argv"].index("--rule-name") + 1] == rule_name)
            security = copy.deepcopy(security[:index + 1])
            bad = json.loads(security[-1]["stdout"])
            bad["priority"] = 999
            security[-1]["stdout"] = json.dumps(bad)
            with self.subTest(stage=stage):
                result = self.run_core(f'bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json {stage}',
                             self.network_calls() + redesign.SpokeNatAbsenceTests().calls() + security)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Security Admin rule", result.stderr)

    def test_admin_denied_requires_blocked_hub_a_but_keeps_hub_b_and_a_b_working(self):
        def route(zone, prefix, hop, next_ip=None):
            return call(["network", "nic", "show-effective-route-table", "-g", rg(zone),
                         "-n", f"nic-lzbegin-{zone}-demo123", "-o", "json"],
                        {"value": [{"state": "Active", "addressPrefix": [prefix],
                                    "nextHopType": hop, "nextHopIpAddress": [next_ip] if next_ip else []}]})

        def flow(zone, local, remote, access, rule):
            return call(["network", "watcher", "test-ip-flow", "-g", rg(zone),
                         "--vm", f"vm-lzbegin-{zone}-demo123", "--direction", "Inbound",
                         "--protocol", "TCP", "--local", f"{local}:8080",
                         "--remote", f"{remote}:50000", "-o", "json"],
                        {"access": access, "ruleName": admin_rule_id(zone, rule)})

        def guest(zone):
            response = call(["vm", "run-command", "invoke", "--resource-group", rg(zone),
                             "--name", f"vm-lzbegin-{zone}-demo123",
                             "--command-id", "RunShellScript",
                             "--scripts", {"regex": "@/.+/lzbegin-run\\.[A-Za-z0-9]+"}, "-o", "json"])
            response["run_guest"] = True
            return [account(), group(zone), response]

        calls = self.network_calls() + redesign.SpokeNatAbsenceTests().calls() + admin_calls("denied")
        calls += [
            route("hub", "10.10.0.0/16", "VNetPeering"),
            route("hub", "10.20.0.0/16", "VNetPeering"),
            route("spokea", "10.20.0.0/16", "VirtualAppliance", "10.0.2.4"),
            route("spokeb", "10.10.0.0/16", "VirtualAppliance", "10.0.2.4"),
            route("spokea", "0.0.0.0/0", "VirtualAppliance", "10.0.2.4"),
            route("spokeb", "0.0.0.0/0", "VirtualAppliance", "10.0.2.4"),
            *guest("spokea"),
            flow("spokea", "10.10.1.4", "10.0.1.4", "Deny", "deny-hub-to-a"),
            *guest("hub"),
            flow("spokeb", "10.20.1.4", "10.0.1.4", "Allow", "hub-to-b"),
            *guest("hub"),
            flow("spokeb", "10.20.1.4", "10.10.1.4", "Allow", "a-to-b"),
            *guest("spokea"),
        ]
        curl = """#!/bin/sh
case "$*" in
  *127.0.0.1:8080/*) printf 'spokea\\n' ;;
  *10.10.1.4:8080/*) exit 7 ;;
  *10.20.1.4:8080/*) printf 'spokeb\\n' ;;
  *) exit 99 ;;
esac
"""
        result = self.run_core('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json admin-denied',
                     calls, files={"bin/curl": curl})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS: core admin-denied evidence complete", result.stdout)

    def test_unrelated_nsg_deny_is_not_the_admin_rule(self):
        result = run('source "$WORKSHOP_ROOT/scripts/verify-common.sh"; load_run state.json; '
                     'admin_proof spokea 10.10.1.4 10.0.1.4 Deny deny-hub-to-a', [
            call(["network", "watcher", "test-ip-flow", "-g", STATE["resourceGroups"]["spokea"],
                  "--vm", "vm-lzbegin-spokea-demo123", "--direction", "Inbound", "--protocol", "TCP",
                  "--local", "10.10.1.4:8080", "--remote", "10.0.1.4:50000", "-o", "json"],
                 {"access": "Deny", "ruleName": "defaultSecurityRules/DenyAllInBound"}),
        ])
        self.assertNotEqual(result.returncode, 0)

    def test_matching_nsg_rule_name_is_not_avnm_admin_evidence(self):
        args = ["network", "watcher", "test-ip-flow", "-g", rg("spokea"),
                "--vm", "vm-lzbegin-spokea-demo123", "--direction", "Inbound",
                "--protocol", "TCP", "--local", "10.10.1.4:8080",
                "--remote", "10.0.1.4:50000", "-o", "json"]
        result = run('source "$WORKSHOP_ROOT/scripts/verify-common.sh"; load_run state.json; '
                     'admin_proof spokea 10.10.1.4 10.0.1.4 Allow hub-to-a',
                     [call(args, {"access": "Allow", "ruleName": "defaultSecurityRules/hub-to-a"})])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Admin rule evidence", result.stderr)

    def test_admin_proof_requires_matching_action_and_rule(self):
        args = ["network", "watcher", "test-ip-flow", "-g", rg("spokea"),
                "--vm", "vm-lzbegin-spokea-demo123", "--direction", "Inbound",
                "--protocol", "TCP", "--local", "10.10.1.4:8080",
                "--remote", "10.0.1.4:50000", "-o", "json"]
        for access, rule, valid in (
            ("Deny", "deny-hub-to-a", True),
            ("Deny", f"{admin_rule_id('spokea', 'deny-hub-to-a')}", True),
            ("Allow", "deny-hub-to-a", False),
            ("Deny", "hub-to-b", False),
            ("Deny", "defaultSecurityRules/deny-hub-to-a", False),
            ("Deny", "securityAdminRules/deny-hub-to-a", False),
            ("Deny", admin_rule_id("spokeb", "deny-hub-to-a"), False),
        ):
            with self.subTest(access=access, rule=rule):
                result = run('source "$WORKSHOP_ROOT/scripts/verify-common.sh"; load_run state.json; '
                             'admin_proof spokea 10.10.1.4 10.0.1.4 Deny deny-hub-to-a',
                             [call(args, {"access": access, "ruleName": rule})])
                self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_missing_effective_configuration_stops_before_http(self):
        result = self.run_core('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
            account(),
            group("hub"),
            self.effective_call("hub", {"value": []}),
            self.peering_list_call("hub"),
            group("spokea"),
            self.effective_call("spokea", {"value": []}),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("effective", result.stderr)

    def test_foreign_effective_configuration_id_stops_before_http(self):
        payload = copy.deepcopy(effective_configuration("hub"))
        payload["value"][0]["id"] = connectivity_config_id() + "-foreign"
        result = self.run_core('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
            account(),
            group("hub"),
            self.effective_call("hub", payload),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("effective", result.stderr)

    def test_mesh_effective_configuration_stops_before_http(self):
        payload = copy.deepcopy(effective_configuration("hub"))
        payload["value"][0]["connectivityTopology"] = "Mesh"
        result = self.run_core('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
            account(),
            group("hub"),
            self.effective_call("hub", payload),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("effective", result.stderr)

    def test_effective_configuration_requires_current_zone_target_vnet_id(self):
        payload = copy.deepcopy(effective_configuration("hub"))
        payload["value"][0]["targetVirtualNetwork"]["id"] = netid("spokea", "virtualNetworks", vnet("spokea"))
        result = self.run_core('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
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
                result = self.run_core('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
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
        payload["value"][0]["targetVirtualNetwork"]["id"] = payload["value"][0]["targetVirtualNetwork"]["id"].swapcase()
        payload["value"][0]["appliesToGroups"][0]["isGlobal"] = False
        payload["value"][0]["appliesToGroups"][0]["useHubGateway"] = False
        peerings = copy.deepcopy(avnm_peerings("hub"))
        peerings[0]["peeringState"] = "Initiated"
        result = self.run_core('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
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
        result = self.run_core('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("peerings", result.stderr)

    def test_missing_hub_spoke_direction_stops_before_http(self):
        calls = self.gate_calls()[:7]
        calls[-1] = self.peering_list_call("spokea", [])
        result = self.run_core('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', calls)
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
        result = self.run_core('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
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
        result = self.run_core('bash "$WORKSHOP_ROOT/scripts/verify-core.sh" state.json baseline', [
            account(),
            group("hub"),
            self.effective_call("hub"),
            self.peering_list_call("hub", peerings),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("peerings", result.stderr)
