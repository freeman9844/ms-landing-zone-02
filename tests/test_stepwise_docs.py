import copy
import json
import unittest
import test_network_docs
from harness import run, account, group, call, ROOT, SUB
from test_network_docs import blocks, DOCS, az, rg, netid, vnet, subnet_args, nic, TAGS, recase_ids, foreign_ids, preparation_calls
from test_workshop_safety import FW, LAW, FW_IP, ready_calls, tables_calls, removal_calls


def support_args(verb):
    return ["deployment", "sub", verb, "--name", "support-demo123", "--location", "koreacentral",
            "--template-file", "infra/lab-support.bicep", "--parameters", "runId=demo123",
            "location=koreacentral", "hubResourceGroup=" + rg("hub"),
            "spokeaResourceGroup=" + rg("spokea"), "spokebResourceGroup=" + rg("spokeb"),
            "sshPublicKey=fixture-public-key"]


def support_cases():
    cases = {
        "support-preview": [az(support_args("what-if"))],
        "support-deploy": [az([*support_args("create"), "-o", "json"])],
        "inspect-watcher": [az(["network", "watcher", "list", "--query",
                               "[?location=='koreacentral'].id", "-o", "json"], [])],
        "watcher-group": [az(["group", "exists", "--name", "NetworkWatcherRG", "-o", "tsv"], "false"),
                          az(["group", "create", "--name", "NetworkWatcherRG",
                              "--location", "koreacentral", "-o", "json"])],
        "watcher-enable": [az(["network", "watcher", "list", "--query",
                              "[?location=='koreacentral'].id", "-o", "json"], []),
                           az(["group", "exists", "--name", "NetworkWatcherRG", "-o", "tsv"], "true"),
                           az(["network", "watcher", "configure", "--locations", "koreacentral",
                               "--enabled", "true", "--resource-group", "NetworkWatcherRG", "-o", "json"])],
    }
    for zone in ("hub", "spokea", "spokeb"):
        nat = netid(zone, "natGateways", f"nat-lzbegin-{zone}-demo123")
        cases[f"attach-nat-{zone}"] = [az([
            "network", "vnet", "subnet", "update", *subnet_args(zone),
            "--nat-gateway", f"nat-lzbegin-{zone}-demo123", "-o", "json"])]
        cases[f"inspect-nat-{zone}"] = [az(
            ["network", "vnet", "subnet", "show", *subnet_args(zone), "--query",
             "{Subnet:name,NatGateway:natGateway.id,NSG:networkSecurityGroup.id,DefaultOutbound:defaultOutboundAccess}",
             "-o", "json"],
            {"Subnet": subnet_args(zone)[-1], "NatGateway": nat, "DefaultOutbound": False,
             "NSG": netid(zone, "networkSecurityGroups", f"nsg-lzbegin-{zone}-demo123")})]
    for name, source, destination, rule, priority, access, ip in (
        ("allow-hub-spokea", "hub", "spokea", "allow-hub-http", "200", "Allow", "10.0.1.4"),
        ("allow-hub-spokeb", "hub", "spokeb", "allow-hub-http", "200", "Allow", "10.0.1.4"),
        ("allow-spokea-spokeb", "spokea", "spokeb", "allow-spokea-http", "210", "Allow", "10.10.1.4"),
        ("deny-hub", "hub", "spokea", "test-deny-hub", "100", "Deny", "10.0.1.4"),
    ):
        cases[name] = [nic(source, ip),
                       az(["network", "nsg", "rule", "create", "-g", rg(destination),
                           "--nsg-name", f"nsg-lzbegin-{destination}-demo123", "-n", rule,
                           "--priority", priority, "--direction", "Inbound", "--access", access,
                           "--protocol", "Tcp", "--source-address-prefixes", ip + "/32",
                           "--source-port-ranges", "*", "--destination-address-prefixes", "*",
                           "--destination-port-ranges", "8080", "-o", "json"])]
    cases["restore-hub"] = [az(["network", "nsg", "rule", "delete", "-g", rg("spokea"),
                                              "--nsg-name", "nsg-lzbegin-spokea-demo123", "-n", "test-deny-hub"])]
    return cases


def diagnostic_ids():
    return [az(["network", "firewall", "show", "-g", rg("hub"), "-n", "fw-lzbegin-demo123",
                "--query", "id", "-o", "tsv"], FW),
            az(["monitor", "log-analytics", "workspace", "show", "-g", rg("hub"), "-n", "log-lzbegin-demo123",
                "--query", "id", "-o", "tsv"], LAW)]


def firewall_cases():
    base = ["network", "firewall", "policy", "rule-collection-group"]
    collection = [*base, "collection", "add-filter-collection", "-g", rg("hub"),
                  "--policy-name", "fwpol-lzbegin-demo123", "--rcg-name", "workshop"]
    cases = {
        "register-logs": [az(["provider", "register", "--namespace", "Microsoft.OperationalInsights", "--wait"])],
        "install-firewall-cli": [call(["extension", "add", "--name", "azure-firewall", "--version", "2.2.1",
                                     "--upgrade", "--yes"])],
        "install-logs-cli": [call(["extension", "add", "--name", "log-analytics", "--upgrade", "--yes"])],
        "firewall-workspace": [az(["monitor", "log-analytics", "workspace", "create", "-g", rg("hub"),
                                                "-n", "log-lzbegin-demo123", "-l", "koreacentral", "--sku", "PerGB2018",
                                                "--retention-time", "30", *TAGS, "-o", "json"])],
        "firewall-public-ip": [az(["network", "public-ip", "create", "-g", rg("hub"),
                                                "-n", "pip-lzbegin-fw-demo123", "-l", "koreacentral",
                                                "--sku", "Standard", "--allocation-method", "Static", "--version", "IPv4",
                                                *TAGS, "-o", "json"])],
        "firewall-policy": [az(["network", "firewall", "policy", "create", "-g", rg("hub"),
                                             "-n", "fwpol-lzbegin-demo123", "-l", "koreacentral", "--sku", "Standard",
                                             "--threat-intel-mode", "Alert", *TAGS, "-o", "json"])],
        "firewall-create": [az(["network", "firewall", "create", "-g", rg("hub"),
                                             "-n", "fw-lzbegin-demo123", "-l", "koreacentral", "--sku", "AZFW_VNet",
                                             "--tier", "Standard", "--firewall-policy", "fwpol-lzbegin-demo123",
                                             *TAGS, "-o", "json"])],
        "firewall-ip-config": [az(["network", "firewall", "ip-config", "create", "-g", rg("hub"),
                                                "--firewall-name", "fw-lzbegin-demo123", "-n", "primary",
                                                "--public-ip-address", "pip-lzbegin-fw-demo123",
                                                "--vnet-name", vnet("hub"), "-o", "json"])],
        "inspect-firewall": [az(["network", "firewall", "show", "-g", rg("hub"),
                                               "-n", "fw-lzbegin-demo123", "--query",
                                               "{State:provisioningState,PrivateIP:ipConfigurations[0].privateIPAddress}",
                                               "-o", "json"], {"State": "Succeeded", "PrivateIP": FW_IP})],
        "firewall-rule-group": [az([*base, "create", "-g", rg("hub"),
                                                  "--policy-name", "fwpol-lzbegin-demo123",
                                                  "-n", "workshop", "--priority", "200", "-o", "json"])],
        "firewall-management-rule": [az([*collection, "-n", "management", "--collection-priority", "100",
                                                       "--action", "Allow", "--rule-name", "azure-management",
                                                       "--rule-type", "NetworkRule", "--ip-protocols", "TCP",
                                                       "--source-addresses", "10.10.1.0/24", "10.20.1.0/24",
                                                       "--destination-addresses", "AzureCloud", "--destination-ports", "443",
                                                       "-o", "json"])],
        "firewall-http-rule": [nic("spokea", "10.10.1.4"), nic("spokeb", "10.20.1.4"),
                               az([*collection, "-n", "lab-http", "--collection-priority", "200", "--action", "Allow",
                                   "--rule-name", "spokea-to-spokeb", "--rule-type", "NetworkRule",
                                   "--ip-protocols", "TCP", "--source-addresses", "10.10.1.4",
                                   "--destination-addresses", "10.20.1.4", "--destination-ports", "8080", "-o", "json"])],
        "firewall-egress-rule": [az([*collection, "-n", "egress-check", "--collection-priority", "300",
                                                   "--action", "Allow", "--rule-name", "public-ip-check",
                                                   "--rule-type", "ApplicationRule", "--source-addresses",
                                                   "10.10.1.0/24", "10.20.1.0/24", "--protocols", "Https=443",
                                                   "--target-fqdns", "api.ipify.org", "-o", "json"])],
        "inspect-firewall-rules": [ready_calls()[-1]],
        "firewall-diagnostics": [
            *diagnostic_ids(),
            az(["monitor", "diagnostic-settings", "categories", "list", "--resource", FW, "-o", "json"],
               {"value": [{"name": "AZFWNetworkRule"}, {"name": "AZFWApplicationRule"}]}),
            az(["monitor", "diagnostic-settings", "create", "--name", "workshop", "--resource", FW,
                "--workspace", LAW, "--export-to-resource-specific", "true", "--logs",
                '[{"category":"AZFWNetworkRule","enabled":true},{"category":"AZFWApplicationRule","enabled":true}]',
                "-o", "json"])],
        "inspect-firewall-diagnostics": [*diagnostic_ids(), ready_calls()[3]],
    }
    return cases


def routing_cases():
    cases = {}
    for local, remote in (("hub", "spokea"), ("spokea", "hub"), ("hub", "spokeb"), ("spokeb", "hub")):
        remote_id = netid(remote, "virtualNetworks", vnet(remote))
        generated = f"avnm-{local}-{remote}"
        cases[f"forward-{local}-to-{remote}"] = [
            az(["network", "vnet", "show", "-g", rg(remote), "-n", vnet(remote), "--query", "id", "-o", "tsv"],
               remote_id),
            az(["network", "vnet", "peering", "list", "-g", rg(local), "--vnet-name", vnet(local), "-o", "json"], [{
                "name": generated,
                "remoteVirtualNetwork": {"id": remote_id},
            }]),
            az(["network", "vnet", "peering", "update", "-g", rg(local), "--vnet-name", vnet(local),
                "-n", generated, "--set", "allowForwardedTraffic=true", "-o", "json"])]
    for zone, remote in (("spokea", "10.20.0.0/16"), ("spokeb", "10.10.0.0/16")):
        table = f"rt-lzbegin-{zone}-demo123"
        cases[f"route-table-{zone}"] = [az(["network", "route-table", "create", "-g", rg(zone),
                                                       "-n", table, "-l", "koreacentral", *TAGS, "-o", "json"])]
        for kind, name, prefix in (("other", "to-other-spoke", remote), ("internet", "to-internet", "0.0.0.0/0")):
            cases[f"route-{zone}-{kind}"] = [*ready_calls(), az([
                "network", "route-table", "route", "create", "-g", rg(zone), "--route-table-name", table,
                "-n", name, "--address-prefix", prefix, "--next-hop-type", "VirtualAppliance",
                "--next-hop-ip-address", FW_IP, "-o", "json"])]
        cases[f"attach-routes-{zone}"] = [*ready_calls(), *tables_calls(), az([
            "network", "vnet", "subnet", "update", *subnet_args(zone), "--route-table", table, "-o", "json"])]
    for name, action in (("firewall-deny", "Deny"), ("firewall-restore", "Allow")):
        cases[name] = [az(["network", "firewall", "policy", "rule-collection-group", "show", "-g", rg("hub"),
                           "--policy-name", "fwpol-lzbegin-demo123", "-n", "workshop", "-o", "json"],
                          {"ruleCollections": [{"name": "egress-check"}, {"name": "management"}, {"name": "lab-http"}]}),
                       az(["network", "firewall", "policy", "rule-collection-group", "update", "-g", rg("hub"),
                           "--policy-name", "fwpol-lzbegin-demo123", "-n", "workshop",
                           "--set", f"ruleCollections[2].action.type={action}", "-o", "json"])]
    return cases


def verifier(script, args, code=0):
    expected = " ".join([script, "state.json", *args])
    return f'''bash() {{
  [[ "$*" == "{expected}" ]] || return 99
  printf 'VERIFY:{expected}\\n'
  return {code}
}}
'''


class StepwiseDocsTests(unittest.TestCase):
    execute = test_network_docs.NetworkDocsTests.execute
    keyfile = {".workshop-keys/demo123/id_ed25519.pub": "fixture-public-key"}

    def test_module_05_execution_blocks_do_not_chain_with_and(self):
        for name, script in blocks(DOCS[5]).items():
            with self.subTest(step=name):
                self.assertNotIn("&&", script)

    def test_ordinary_actions_check_ownership_once_for_a_prepared_session(self):
        cases = dict(self.cases())
        cases[3] = test_network_docs.avnm_cases()
        for module, names in (
            (3, ("avnm-create", "network-group-create", "member-spokea",
                 "member-spokeb", "connectivity-config-create",
                 "connectivity-commit", "effective-hub")),
            (4, ("support-preview", "attach-nat-hub", "allow-hub-spokea")),
            (5, ("inspect-firewall", "firewall-http-rule", "inspect-firewall-rules")),
            (6, ("forward-hub-to-spokea", "forward-spokea-to-hub", "route-table-spokea")),
        ):
            with self.subTest(module=module):
                steps = blocks(DOCS[module])
                script = 'export STATE_FILE=state.json\n'
                script += " &&\n".join([steps[f"prepare-{module:02}"], *(steps[name] for name in names)])
                calls = preparation_calls(module)
                for name in names:
                    calls.extend(cases[module][name])
                result = run(script, calls, files=self.keyfile)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_preparation_rejects_foreign_groups_and_lookup_failures(self):
        for module, action in ((3, "avnm-create"), (4, "support-deploy"),
                               (5, "firewall-workspace"), (6, "forward-hub-to-spokea")):
            steps = blocks(DOCS[module])
            for index in (1, 2, 3):
                for failure in ("foreign", "api-error"):
                    with self.subTest(module=module, group=index, failure=failure):
                        calls = preparation_calls(module)[:index + 1]
                        if failure == "foreign":
                            data = json.loads(calls[-1]["stdout"])
                            data["tags"]["runId"] = "another-run"
                            calls[-1]["stdout"] = json.dumps(data)
                        else:
                            calls[-1].update(returncode=1, stdout="", stderr="Forbidden")
                        script = 'export STATE_FILE=state.json\n'
                        script += steps[f"prepare-{module:02}"] + " &&\n" + steps[action]
                        script += '\nstatus=$?\nprintf "SHELL_ALIVE\\n"\nexit "$status"'
                        result = run(script, calls, files=self.keyfile, input_text="CREATE\nFIREWALL\n")
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("SHELL_ALIVE", result.stdout)
                        self.assertIn("Ownership mismatch" if failure == "foreign" else "Forbidden", result.stderr)

    def test_workspace_get_lowercase_response_does_not_block_diagnostics_creation(self):
        calls = firewall_cases()["firewall-diagnostics"]
        calls[1]["stdout"] = LAW.lower()
        workspace_index = calls[-1]["argv"].index("--workspace") + 1
        calls[-1]["argv"][workspace_index] = LAW.lower()
        result = self.execute(5, "firewall-diagnostics", calls)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_diagnostics_accepts_lowercase_workspace_discovery_and_mixedcase_reference(self):
        for name in ("firewall-diagnostics", "inspect-firewall-diagnostics"):
            for transform in (str.lower, str.swapcase):
                with self.subTest(step=name, casing=transform.__name__):
                    calls = recase_ids(firewall_cases()[name], transform)
                    if name.startswith("inspect-"):
                        setting = json.loads(calls[-1]["stdout"])
                        setting["workspaceId"] = LAW.swapcase() if transform == str.lower else LAW.lower()
                        calls[-1]["stdout"] = json.dumps(setting)
                    result = self.execute(5, name, calls)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_nat_inspections_display_ids_in_original_casing(self):
        for zone in ("hub", "spokea", "spokeb"):
            name = f"inspect-nat-{zone}"
            for transform in (str.lower, str.swapcase):
                with self.subTest(step=name, casing=transform.__name__):
                    result = self.execute(4, name, recase_ids(support_cases()[name], transform))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(transform(netid(zone, "natGateways", f"nat-lzbegin-{zone}-demo123")),
                                  result.stdout)

    def test_reference_mismatches_remain_errors_not_suffix_matches(self):
        for bad in foreign_ids(LAW):
            calls = firewall_cases()["inspect-firewall-diagnostics"]
            setting = json.loads(calls[-1]["stdout"])
            setting["workspaceId"] = bad.lower()
            calls[-1]["stdout"] = json.dumps(setting)
            result = self.execute(5, "inspect-firewall-diagnostics", calls)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ERROR:", result.stderr)

    def cases(self):
        return ((4, support_cases()), (5, firewall_cases()), (6, routing_cases()))

    def test_each_action_runs_after_only_preparation_with_explicit_targets(self):
        for module, cases in self.cases():
            for name, calls in cases.items():
                with self.subTest(module=module, step=name):
                    result = self.execute(module, name, calls, files=self.keyfile,
                                          input_text="CREATE\n" if name == "support-deploy" else "FIREWALL\n")
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_each_action_stops_after_any_failed_dependency_lookup(self):
        for module, cases in self.cases():
            for name, calls in cases.items():
                for index in range(len(calls) - 1):
                    with self.subTest(step=name, failure=index):
                        failed = copy.deepcopy(calls[:index + 1])
                        failed[-1].update(returncode=1, stdout="")
                        self.assertNotEqual(self.execute(module, name, failed, files=self.keyfile,
                                                         input_text="CREATE\nFIREWALL\n").returncode, 0)

    def test_final_cli_failure_is_not_hidden_and_does_not_exit_the_participant_shell(self):
        for module, cases in self.cases():
            for name, calls in cases.items():
                with self.subTest(step=name):
                    failed = copy.deepcopy(calls)
                    failed[-1].update(returncode=1, stdout="")
                    result = self.execute(module, name, failed, files=self.keyfile,
                                          input_text="CREATE\n" if name == "support-deploy" else "FIREWALL\n")
                    self.assertNotEqual(result.returncode, 0)

    def test_ownership_mismatch_never_reaches_mutations_or_other_resources(self):
        for module, cases in self.cases():
            for name, calls in cases.items():
                for index, item in enumerate(calls):
                    if item["argv"][:2] != ["group", "show"]:
                        continue
                    with self.subTest(step=name, group=index):
                        failed = copy.deepcopy(calls[:index + 1])
                        data = json.loads(failed[-1]["stdout"])
                        data["id"] = data["id"].replace(SUB, "99999999-9999-9999-9999-999999999999")
                        failed[-1]["stdout"] = json.dumps(data)
                        result = self.execute(module, name, failed, files=self.keyfile, input_text="CREATE\nFIREWALL\n")
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("Ownership mismatch", result.stderr)

    def test_firewall_creation_runs_without_repeated_cost_confirmation(self):
        names = ["firewall-workspace", "firewall-public-ip", "firewall-policy", "firewall-create", "firewall-ip-config"]
        for name in names:
            with self.subTest(step=name):
                result = self.execute(5, name, firewall_cases()[name], input_text="")
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.execute(4, "support-deploy",
                                        input_text="NO\n", files=self.keyfile).returncode, 0)

    def test_missing_key_stops_preview_and_deploy_without_cloud_mutation(self):
        for name in ("support-preview", "support-deploy"):
            with self.subTest(step=name):
                self.assertNotEqual(self.execute(4, name, input_text="CREATE\n").returncode, 0)

    def test_nat_inspection_shows_settings_for_manual_comparison_without_claiming_pass(self):
        for zone in ("hub", "spokea", "spokeb"):
            calls = copy.deepcopy(support_cases()[f"inspect-nat-{zone}"])
            data = json.loads(calls[-1]["stdout"])
            data["NSG"] = None
            data["DefaultOutbound"] = True
            calls[-1]["stdout"] = json.dumps(data)
            result = self.execute(4, f"inspect-nat-{zone}", calls)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"NSG": null', result.stdout)
            self.assertIn('"DefaultOutbound": true', result.stdout)
            self.assertNotIn("PASS", result.stdout)

    def test_shared_watcher_is_preserved_and_malformed_discovery_never_enables(self):
        result = self.execute(4, "watcher-group", [
            az(["group", "exists", "--name", "NetworkWatcherRG", "-o", "tsv"], "true")])
        self.assertEqual(result.returncode, 0, result.stderr)
        listing = support_cases()["watcher-enable"][0]
        for value, success in ((["/existing/watcher"], True), (None, False), ({}, False), ("malformed", False)):
            altered = copy.deepcopy(listing)
            altered["stdout"] = json.dumps(value)
            self.assertEqual(self.execute(4, "watcher-enable", [altered]).returncode == 0, success)

    def test_script_actions_remain_single_purpose_and_propagate_failures(self):
        cases = [
            (4, "service-spokea", "scripts/run-vm.sh", ["spokea", "scripts/guest-server.sh"]),
            (4, "service-spokeb", "scripts/run-vm.sh", ["spokeb", "scripts/guest-server.sh"]),
            (4, "verify-baseline", "scripts/verify-core.sh", ["baseline"]),
            (4, "verify-nsg-denied", "scripts/verify-core.sh", ["nsg-denied"]),
            (4, "verify-restored", "scripts/verify-core.sh", ["restored"]),
            (5, "extension-preflight", "scripts/preflight.sh", ["--extension"]),
            (6, "verify-allowed", "scripts/verify-extension.sh", ["allowed"]),
            (6, "verify-denied", "scripts/verify-extension.sh", ["denied"]),
            (6, "verify-restored", "scripts/verify-extension.sh", ["restored"]),
            (6, "verify-after-nat-removal", "scripts/verify-extension.sh", ["restored"]),
            (7, "cleanup", "scripts/cleanup.sh", []),
        ]
        for module, name, script, args in cases:
            for code in (0, 1):
                with self.subTest(step=name, code=code):
                    result = self.execute(module, name, prefix=verifier(script, args, code))
                    self.assertEqual(result.returncode, code, result.stderr)
                    self.assertEqual(result.stdout.count("VERIFY:"), 1)

    def test_each_nat_removal_requires_fresh_verification_and_new_confirmation(self):
        for zone in ("spokea", "spokeb"):
            for stage in ("detach", "nat", "pip"):
                name = f"remove-{zone}-{stage}"
                reads = removal_calls(zone, stage)
                if stage == "detach":
                    mutation = az(["network", "vnet", "subnet", "update", *subnet_args(zone),
                                   "--remove", "natGateway", "-o", "json"])
                else:
                    kind = ["nat", "gateway"] if stage == "nat" else ["public-ip"]
                    mutation = az(["network", *kind, "delete", "-g", rg(zone), "-n",
                                   f"{'nat' if stage == 'nat' else 'pip'}-lzbegin-{zone}-demo123"])
                with self.subTest(step=name):
                    result = self.execute(6, name, [*reads, mutation], input_text="REMOVE-SPOKE-NAT\n",
                                          prefix=verifier("scripts/verify-extension.sh", ["restored"]))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.count("VERIFY:"), 1)
                    self.assertNotEqual(self.execute(6, name, input_text="REMOVE-SPOKE-NAT\n",
                                                    prefix=verifier("scripts/verify-extension.sh", ["restored"], 1)).returncode, 0)
                    self.assertNotEqual(self.execute(6, name, reads, input_text="NO\n",
                                                    prefix=verifier("scripts/verify-extension.sh", ["restored"])).returncode, 0)
                    for index in range(len(reads)):
                        failed = copy.deepcopy(reads[:index + 1])
                        failed[-1].update(returncode=1, stdout="")
                        self.assertNotEqual(self.execute(6, name, failed, input_text="REMOVE-SPOKE-NAT\n",
                                                        prefix=verifier("scripts/verify-extension.sh", ["restored"])).returncode, 0)

    def test_http_rule_changes_reject_ambiguous_collections(self):
        for name in ("firewall-deny", "firewall-restore"):
            for collections in ([], [{"name": "lab-http"}, {"name": "lab-http"}], None,
                                {"not-an-array": {"name": "lab-http"}}):
                calls = routing_cases()[name][:1]
                calls[-1]["stdout"] = json.dumps({"ruleCollections": collections})
                self.assertNotEqual(self.execute(6, name, calls).returncode, 0)

    def test_diagnostics_reject_unsupported_categories_and_wrong_saved_workspace(self):
        for name in ("firewall-diagnostics", "inspect-firewall-diagnostics"):
            calls = firewall_cases()[name][:-1] if name == "firewall-diagnostics" else firewall_cases()[name]
            calls[-1]["stdout"] = '{"value":[]}' if name == "firewall-diagnostics" else '{"workspaceId":"foreign"}'
            self.assertNotEqual(self.execute(5, name, calls).returncode, 0)
        calls = firewall_cases()["firewall-diagnostics"][:-1]
        calls[-1]["stdout"] = '{"value":{"first":{"name":"AZFWNetworkRule"},"second":{"name":"AZFWApplicationRule"}}}'
        self.assertNotEqual(self.execute(5, "firewall-diagnostics", calls).returncode, 0)
        calls = firewall_cases()["inspect-firewall-diagnostics"]
        data = json.loads(calls[-1]["stdout"])
        data["logs"] = {"first": data["logs"][0], "second": data["logs"][1]}
        calls[-1]["stdout"] = json.dumps(data)
        self.assertNotEqual(self.execute(5, "inspect-firewall-diagnostics", calls).returncode, 0)

    def test_key_preparation_creates_or_reuses_a_private_directory_without_overwriting_partial_keys(self):
        stub = """#!/usr/bin/env python3
import pathlib, sys
assert sys.argv[1:] == ['-t', 'ed25519', '-N', '', '-f', '.workshop-keys/demo123/id_ed25519', '-C', 'lz-beginner-demo123']
key = pathlib.Path(sys.argv[sys.argv.index('-f') + 1])
assert key.parent.stat().st_mode & 0o777 == 0o700
key.write_text('fixture-private-key')
key.with_suffix('.pub').write_text('fixture-public-key')
"""
        result = self.execute(4, "support-key", files={"bin/ssh-keygen": stub})
        self.assertEqual(result.returncode, 0, result.stderr)
        both = dict(self.keyfile, **{".workshop-keys/demo123/id_ed25519": "fixture-private-key",
                                     "bin/ssh-keygen": "#!/bin/sh\nexit 99\n"})
        result = self.execute(4, "support-key", files=both)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.execute(4, "support-key", files=self.keyfile).returncode, 0)

    def test_cleanup_recovery_actions_are_separate_and_do_not_delete_anything(self):
        originals = ('ORIGINAL_RUN_ID=demo123\nORIGINAL_SUBSCRIPTION=' + SUB +
                     '\nORIGINAL_LOCATION=koreacentral\n')
        self.assertEqual(self.execute(7, "recovery-input", input_text=f"demo123\n{SUB}\nkoreacentral\n").returncode, 0)
        self.assertEqual(self.execute(7, "recovery-subscription",
                                     [call(["account", "set", "--subscription", SUB])], prefix=originals).returncode, 0)
        self.assertEqual(self.execute(7, "recovery-state", prefix=originals).returncode, 0)
        result = self.execute(7, "recovery-state", prefix=originals,
                              files={".workshop-state/demo123.json": "do-not-overwrite"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("State exists", result.stderr)

    def test_prepared_session_targets_state_subscription_even_after_active_subscription_switch(self):
        other = "99999999-9999-9999-9999-999999999999"
        cases = [
            (2, "foundation-hub-rg", test_network_docs.foundation_cases()["foundation-hub-rg"]),
            (2, "foundation-hub-vnet", test_network_docs.foundation_cases()["foundation-hub-vnet"]),
            (3, "avnm-create", test_network_docs.avnm_cases()["avnm-create"]),
            (4, "watcher-group", support_cases()["watcher-group"]),
            (4, "support-deploy", support_cases()["support-deploy"]),
            (4, "attach-nat-hub", support_cases()["attach-nat-hub"]),
            (4, "allow-hub-spokea", support_cases()["allow-hub-spokea"]),
            (5, "register-logs", firewall_cases()["register-logs"]),
            (5, "firewall-http-rule", firewall_cases()["firewall-http-rule"]),
            (5, "firewall-diagnostics", firewall_cases()["firewall-diagnostics"]),
            (6, "forward-hub-to-spokea", routing_cases()["forward-hub-to-spokea"]),
        ]
        for module, name, calls in cases:
            with self.subTest(step=name):
                result = self.execute(module, name,
                                      [call(["account", "set", "--subscription", other]), *calls],
                                      prefix=f'az account set --subscription {other}\n',
                                      input_text="CREATE\n", files=self.keyfile)
                self.assertEqual(result.returncode, 0, result.stderr)
