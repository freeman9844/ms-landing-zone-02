import json
import unittest
from harness import run, call, account, group, STATE, SUB


def inventory(absent=False):
    calls = [account()]
    for zone, name in STATE["resourceGroups"].items():
        calls.append(call(["group", "exists", "--name", name, "-o", "tsv"], "false" if absent else "true"))
        if not absent:
            calls.append(group(zone))
    return calls


def avnm_cleanup(manager=False):
    calls = [call(["network", "vnet", "list", "-g", STATE["resourceGroups"][zone],
                   "-o", "json", "--subscription", SUB], [])
             for zone in ("spokea", "spokeb")]
    calls += [call(["network", "manager", "list", "-g", STATE["resourceGroups"]["hub"],
                   "-o", "json", "--subscription", SUB],
                  [{"id": f"/subscriptions/{SUB}/resourceGroups/{STATE['resourceGroups']['hub']}"
                          "/providers/Microsoft.Network/networkManagers/avnm-lzbegin-demo123"}] if manager else [])]
    if manager:
        for command in ("routing-config", "security-admin-config", "connect-config"):
            calls.append(call(["network", "manager", command, "list", "-g", STATE["resourceGroups"]["hub"],
                               "--network-manager-name" if command == "connect-config" else "--manager-name",
                               "avnm-lzbegin-demo123", "-o", "json",
                               "--subscription", SUB], []))
        for kind in ("Routing", "SecurityAdmin", "Connectivity"):
            calls.append(call(["network", "manager", "post-commit", "-g", STATE["resourceGroups"]["hub"],
                               "-n", "avnm-lzbegin-demo123", "--commit-type", kind,
                               "--configuration-ids", "[]", "--target-locations", "koreacentral",
                               "-o", "none", "--subscription", SUB]))
            status_args = (["rest", "--method", "post", "--url",
                            f"/subscriptions/{SUB}/resourceGroups/{STATE['resourceGroups']['hub']}"
                            "/providers/Microsoft.Network/networkManagers/avnm-lzbegin-demo123"
                            "/listDeploymentStatus?api-version=2025-05-01",
                            "--body", '{"deploymentTypes":["Routing"],"regions":["koreacentral"]}',
                            "-o", "json", "--subscription", SUB]
                           if kind == "Routing" else
                           ["network", "manager", "list-deploy-status", "-g", STATE["resourceGroups"]["hub"],
                            "-n", "avnm-lzbegin-demo123", "--deployment-types", kind,
                            "--regions", "koreacentral", "-o", "json", "--subscription", SUB])
            calls.append(call(status_args, [{"deploymentType": kind, "region": "koreacentral",
                                             "commitTime": "2026-09-26T10:00:00Z",
                                             "deploymentStatus": "Deployed", "configurationIds": []}]))
    for zone in ("spokea", "spokeb"):
        calls.append(call(["network", "vnet", "list", "-g", STATE["resourceGroups"][zone],
                           "-o", "json", "--subscription", SUB], []))
    return calls


class CleanupTests(unittest.TestCase):
    def test_wrong_confirmation_never_deletes(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', inventory(), input_text="no\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cancelled", result.stderr)

    def test_all_absent_is_explicit_success_without_prompt(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', inventory(True))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already absent", result.stdout)

    def test_lookup_error_is_not_treated_as_absent(self):
        calls = [account(), call(["group", "exists", "--name", STATE["resourceGroups"]["hub"], "-o", "tsv"],
                                 "", code=1, stderr="Forbidden")]
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls)
        self.assertNotEqual(result.returncode, 0)

    def test_valid_confirmation_checks_actual_deletion(self):
        calls = inventory() + [account()] + [group(zone) for zone in STATE["resourceGroups"]]
        calls += avnm_cleanup(manager=True)
        for item in calls:
            if item["argv"][:3] == ["network", "manager", "list-deploy-status"]:
                item["stdout"] = json.dumps({"skipToken": "", "value": json.loads(item["stdout"])})
        for name in STATE["resourceGroups"].values():
            calls.append(call(["group", "delete", "--name", name, "--yes", "--no-wait"]))
        for name in STATE["resourceGroups"].values():
            calls.append(call(["group", "exists", "--name", name, "-o", "tsv"], "false"))
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls,
                     input_text=f"DELETE demo123 FROM {STATE['subscriptionId']}\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("deletion complete", result.stdout)

    def test_foreign_manager_stops_before_any_undeployment_or_deletion(self):
        calls = inventory() + [account()] + [group(zone) for zone in STATE["resourceGroups"]]
        calls += avnm_cleanup(manager=False)[:2]
        calls += [call(["network", "manager", "list", "-g", STATE["resourceGroups"]["hub"],
                        "-o", "json", "--subscription", SUB],
                       [{"id": f"/subscriptions/{SUB}/resourceGroups/{STATE['resourceGroups']['hub']}"
                               "/providers/Microsoft.Network/networkManagers/another-manager"}])]
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls,
                     input_text=f"DELETE demo123 FROM {SUB}\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected AVNM", result.stderr)

    def test_foreign_configuration_stops_before_any_commit(self):
        calls = inventory() + [account()] + [group(zone) for zone in STATE["resourceGroups"]]
        calls += avnm_cleanup(manager=True)[:5]
        calls[-1]["stdout"] = json.dumps([{
            "id": f"/subscriptions/{SUB}/resourceGroups/{STATE['resourceGroups']['hub']}/providers/"
                  "Microsoft.Network/networkManagers/avnm-lzbegin-demo123/"
                  "securityAdminConfigurations/foreign"
        }])
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls,
                     input_text=f"DELETE demo123 FROM {SUB}\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected SecurityAdmin", result.stderr)

    def test_duplicate_manager_listing_does_not_skip_undeployment(self):
        calls = inventory() + [account()] + [group(zone) for zone in STATE["resourceGroups"]]
        calls += avnm_cleanup(manager=True)[:3]
        managers = json.loads(calls[-1]["stdout"])
        calls[-1]["stdout"] = json.dumps(managers * 2)
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls,
                     input_text=f"DELETE demo123 FROM {SUB}\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected AVNM", result.stderr)

    def test_none_commit_waits_until_latest_deployment_is_applied(self):
        calls = inventory() + [account()] + [group(zone) for zone in STATE["resourceGroups"]]
        calls += avnm_cleanup(manager=True)
        index = next(i for i, item in enumerate(calls)
                     if item["argv"][:3] == ["rest", "--method", "post"])
        pending = dict(calls[index])
        pending["stdout"] = json.dumps([{
            "deploymentType": "Routing", "region": "koreacentral",
            "commitTime": "2026-09-26T10:00:00Z",
            "deploymentStatus": "Deploying", "configurationIds": [],
        }])
        calls.insert(index, pending)
        for name in STATE["resourceGroups"].values():
            calls.append(call(["group", "delete", "--name", name, "--yes", "--no-wait"]))
        for name in STATE["resourceGroups"].values():
            calls.append(call(["group", "exists", "--name", name, "-o", "tsv"], "false"))
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls,
                     input_text=f"DELETE demo123 FROM {SUB}\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_residual_managed_table_is_not_silently_deleted_or_ignored(self):
        rg = STATE["resourceGroups"]["spokea"]
        table = f"/subscriptions/{SUB}/resourceGroups/NetworkManagerRG/providers/Microsoft.Network/routeTables/managed"
        calls = inventory() + [account()] + [group(zone) for zone in STATE["resourceGroups"]]
        calls += [
            call(["network", "vnet", "list", "-g", rg, "-o", "json", "--subscription", SUB],
                 [{"name": "vnet-lzbegin-spokea-demo123"}]),
            call(["network", "vnet", "subnet", "list", "-g", rg, "--vnet-name",
                  "vnet-lzbegin-spokea-demo123", "-o", "json", "--subscription", SUB],
                 [{"name": "snet-workload", "routeTable": {"id": table}}]),
            call(["network", "vnet", "list", "-g", STATE["resourceGroups"]["spokeb"],
                  "-o", "json", "--subscription", SUB], []),
            call(["network", "manager", "list", "-g", STATE["resourceGroups"]["hub"],
                  "-o", "json", "--subscription", SUB], []),
            call(["network", "vnet", "list", "-g", rg, "-o", "json", "--subscription", SUB],
                 [{"name": "vnet-lzbegin-spokea-demo123"}]),
            call(["network", "vnet", "subnet", "list", "-g", rg, "--vnet-name",
                  "vnet-lzbegin-spokea-demo123", "-o", "json", "--subscription", SUB],
                 [{"name": "snet-workload", "routeTable": None}]),
            call(["network", "vnet", "list", "-g", STATE["resourceGroups"]["spokeb"],
                  "-o", "json", "--subscription", SUB], []),
        ]
        calls.extend(call(["resource", "list", "--resource-type", "Microsoft.Network/routeTables",
                           "-o", "json", "--subscription", SUB], [{"id": table}])
                     for _ in range(40))
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls,
                     input_text=f"DELETE demo123 FROM {SUB}\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("still exist", result.stderr)

    def test_delayed_subnet_and_managed_table_removal_is_rechecked(self):
        rg = STATE["resourceGroups"]["spokea"]
        spokeb = STATE["resourceGroups"]["spokeb"]
        table = f"/subscriptions/{SUB}/resourceGroups/NetworkManagerRG/providers/Microsoft.Network/routeTables/managed"
        vnet = "vnet-lzbegin-spokea-demo123"
        def vnets(zone, value):
            return call(["network", "vnet", "list", "-g", zone, "-o", "json",
                         "--subscription", SUB], value)
        def subnets(value):
            return call(["network", "vnet", "subnet", "list", "-g", rg, "--vnet-name", vnet,
                         "-o", "json", "--subscription", SUB], value)
        def tables(value):
            return call(["resource", "list", "--resource-type", "Microsoft.Network/routeTables",
                         "-o", "json", "--subscription", SUB], value)
        calls = inventory() + [account()] + [group(zone) for zone in STATE["resourceGroups"]]
        calls += [
            vnets(rg, [{"name": vnet}]), subnets([{"name": "snet-workload", "routeTable": {"id": table}}]),
            vnets(spokeb, []),
            call(["network", "manager", "list", "-g", STATE["resourceGroups"]["hub"],
                  "-o", "json", "--subscription", SUB], []),
            vnets(rg, [{"name": vnet}]), subnets([{"name": "snet-workload", "routeTable": {"id": table}}]),
            vnets(spokeb, []),
            vnets(rg, [{"name": vnet}]), subnets([{"name": "snet-workload", "routeTable": None}]),
            vnets(spokeb, []),
            tables([{"id": table}]), tables([]),
        ]
        for name in STATE["resourceGroups"].values():
            calls.append(call(["group", "delete", "--name", name, "--yes", "--no-wait"]))
        for name in STATE["resourceGroups"].values():
            calls.append(call(["group", "exists", "--name", name, "-o", "tsv"], "false"))
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls,
                     input_text=f"DELETE demo123 FROM {SUB}\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_partially_created_spoke_vnet_without_subnet_can_be_cleaned(self):
        rg = STATE["resourceGroups"]["spokea"]
        calls = inventory() + [account()] + [group(zone) for zone in STATE["resourceGroups"]]
        calls += avnm_cleanup(manager=False)
        for index in (0, 3):
            calls[len(inventory()) + 4 + index]["stdout"] = json.dumps(
                [{"name": "vnet-lzbegin-spokea-demo123"}])
        subnet_list = call(["network", "vnet", "subnet", "list", "-g", rg, "--vnet-name",
                            "vnet-lzbegin-spokea-demo123", "-o", "json", "--subscription", SUB], [])
        before = len(inventory()) + 4
        calls.insert(before + 1, subnet_list)
        calls.insert(before + 5, subnet_list.copy())
        for name in STATE["resourceGroups"].values():
            calls.append(call(["group", "delete", "--name", name, "--yes", "--no-wait"]))
        for name in STATE["resourceGroups"].values():
            calls.append(call(["group", "exists", "--name", name, "-o", "tsv"], "false"))
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls,
                     input_text=f"DELETE demo123 FROM {SUB}\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_mismatched_owner_prevents_all_deletion(self):
        calls = inventory()[:3]
        data = json.loads(calls[-1]["stdout"])
        data["tags"]["managedBy"] = "production"
        calls[-1]["stdout"] = json.dumps(data)
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls)
        self.assertNotEqual(result.returncode, 0)
