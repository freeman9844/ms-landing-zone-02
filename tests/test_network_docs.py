import copy
import json
import re
import unittest
from harness import ROOT, run, account, call, group, STATE, SUB


def blocks(path):
    pairs = re.findall(r"<!-- exec:([a-z0-9-]+) -->\s*```bash\n(.*?)\n```", path.read_text(), re.S)
    if len(dict(pairs)) != len(pairs):
        raise AssertionError("Duplicate executable block IDs")
    return dict(pairs)


DOCS = {int(path.name[:2]): path for path in (ROOT / "docs").glob("0[2-7]-*.md")}
TAGS = ["--tags", "workshop=lz-beginner", "environment=lab", "runId=demo123", "managedBy=workshop"]
OWNED = {"runId": "demo123", "workshop": "lz-beginner", "environment": "lab", "managedBy": "workshop"}


def rg(zone):
    return STATE["resourceGroups"][zone]


def rid(zone, kind, name):
    return f"/subscriptions/{SUB}/resourceGroups/{rg(zone)}/providers/{kind}/{name}"


def netid(zone, kind, name):
    return rid(zone, "Microsoft.Network/" + kind, name)


def az(args, value="", code=0):
    return call([*args, "--subscription", SUB], value, code)


def vnet(zone):
    return f"vnet-lzbegin-{zone}-demo123"


def subnet_args(zone):
    return ["-g", rg(zone), "--vnet-name", vnet(zone), "-n",
            "snet-management" if zone == "hub" else "snet-workload"]


def nic(zone, ip):
    return az(["network", "nic", "show", "-g", rg(zone), "-n", f"nic-lzbegin-{zone}-demo123",
               "--query", "ipConfigurations[0].privateIPAddress", "-o", "tsv"], ip)


def foundation_cases():
    cases = {}
    for zone, prefix, subnet_prefix in (
        ("hub", "10.0.0.0/16", "10.0.1.0/24"),
        ("spokea", "10.10.0.0/16", "10.10.1.0/24"),
        ("spokeb", "10.20.0.0/16", "10.20.1.0/24"),
    ):
        nsg = f"nsg-lzbegin-{zone}-demo123"
        for kind, args in (
            ("vnet", ["network", "vnet", "create", "--resource-group", rg(zone), "--name", vnet(zone),
                      "--location", "koreacentral", "--address-prefixes", prefix, *TAGS, "-o", "json"]),
            ("nsg", ["network", "nsg", "create", "--resource-group", rg(zone), "--name", nsg,
                     "--location", "koreacentral", *TAGS, "-o", "json"]),
            ("subnet", ["network", "vnet", "subnet", "create", "--resource-group", rg(zone),
                        "--vnet-name", vnet(zone), "--name",
                        "snet-management" if zone == "hub" else "snet-workload",
                        "--address-prefixes", subnet_prefix, "--network-security-group", nsg,
                        "--default-outbound-access", "false", "-o", "json"]),
            ("deny", ["network", "nsg", "rule", "create", "--resource-group", rg(zone), "--nsg-name", nsg,
                      "--name", "deny-other-vnet-inbound", "--priority", "4000", "--direction", "Inbound",
                      "--access", "Deny", "--protocol", "*", "--source-address-prefixes", "VirtualNetwork",
                      "--source-port-ranges", "*", "--destination-address-prefixes", "*",
                      "--destination-port-ranges", "*", "-o", "json"]),
        ):
            cases[f"foundation-{zone}-{kind}"] = [az(args)]
        cases[f"foundation-{zone}-rg"] = [
            az(["group", "exists", "--name", rg(zone), "-o", "tsv"], "false"),
            az(["group", "create", "--name", rg(zone), "--location", "koreacentral", *TAGS, "-o", "json"])]
        cases[f"inspect-foundation-{zone}"] = [
            az(["network", "vnet", "show", "-g", rg(zone), "-n", vnet(zone), "--query",
                            "{VNet:name,Address:addressSpace.addressPrefixes,Subnets:subnets[].{Name:name,Prefix:addressPrefix,DefaultOutbound:defaultOutboundAccess},Tags:tags}",
                            "-o", "json"])]
    cases["foundation-firewall-subnet"] = [
        az(["network", "vnet", "subnet", "create", "--resource-group", rg("hub"),
                          "--vnet-name", vnet("hub"), "--name", "AzureFirewallSubnet",
                          "--address-prefixes", "10.0.2.0/26", "-o", "json"])]
    return cases


def peering_cases():
    cases = {}
    for local, remote in (("hub", "spokea"), ("spokea", "hub"), ("hub", "spokeb"), ("spokeb", "hub")):
        remote_id = netid(remote, "virtualNetworks", vnet(remote))
        cases[f"peering-{local}-to-{remote}"] = [
            az(["network", "vnet", "show", "-g", rg(remote), "-n", vnet(remote),
                "--query", "id", "-o", "tsv"], remote_id),
            az(["network", "vnet", "peering", "create", "-g", rg(local), "--vnet-name", vnet(local),
                "-n", f"{local}-to-{remote}", "--remote-vnet", remote_id, "--allow-vnet-access", "true",
                "--allow-forwarded-traffic", "false", "--allow-gateway-transit", "false", "-o", "json"])]
    for zone in ("hub", "spokea", "spokeb"):
        cases[f"inspect-peering-{zone}"] = [
            az(["network", "vnet", "peering", "list", "-g", rg(zone), "--vnet-name", vnet(zone),
                            "--query", "[].{Name:name,State:peeringState,Remote:remoteVirtualNetwork.id}", "-o", "table"])]
    return cases


def recase_ids(calls, transform):
    """Vary Azure ID casing without changing tags, names, or CLI option names."""
    def convert(value):
        if isinstance(value, str):
            return transform(value) if value.lower().startswith("/subscriptions/") else value
        if isinstance(value, list):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        return value

    result = copy.deepcopy(calls)
    for item in result:
        try:
            payload = json.loads(item["stdout"])
        except json.JSONDecodeError:
            item["stdout"] = convert(item["stdout"])
        else:
            item["stdout"] = json.dumps(convert(payload))
        item["argv"] = convert(item["argv"])
    return result


def foreign_ids(resource_id):
    parts = resource_id.split("/")
    # Subscription, RG, provider namespace, resource type and name must all match.
    for index in (2, 4, 6, 7, 8):
        changed = parts.copy()
        changed[index] += "-foreign"
        yield "/".join(changed)
    yield "/unexpected-prefix" + resource_id
    yield resource_id + "/unexpected-child"


def preparation_calls(module):
    calls = [account()]
    if module in (3, 4, 5, 6):
        calls.extend(group(zone) for zone in ("hub", "spokea", "spokeb"))
    return calls


class NetworkDocsTests(unittest.TestCase):
    def execute(self, module, name, calls=(), input_text=None, files=None, prefix=""):
        steps = blocks(DOCS[module])
        self.assertIn(f"prepare-{module:02}", steps, "Module needs one common preparation block")
        self.assertIn(name, steps, "Missing separate teaching action")
        script = 'export STATE_FILE=state.json\n' + steps[f"prepare-{module:02}"] + "\n"
        script += 'prepared=$?\nif [[ "$prepared" == 0 ]]; then\n' + prefix + steps[name] + '\nelse\nfalse\nfi\n'
        script += 'status=$?\nprintf "SHELL_ALIVE\\n"\nexit "$status"'
        result = run(script, [*preparation_calls(module), *calls], input_text=input_text, files=files)
        self.assertIn("SHELL_ALIVE", result.stdout, result.stderr)
        return result

    def test_every_module_preparation_rejects_wrong_subscription_without_exiting(self):
        for module, path in DOCS.items():
            with self.subTest(module=module):
                steps = blocks(path)
                self.assertIn(f"prepare-{module:02}", steps)
                result = run('export STATE_FILE=state.json\n' + steps[f"prepare-{module:02}"] +
                             '\nstatus=$?\nprintf "ALIVE\\n"\nexit "$status"',
                             [call(["account", "show", "--query", "id", "-o", "tsv"], "wrong")])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ALIVE", result.stdout)
                self.assertIn("Subscription mismatch", result.stderr)

    def test_every_module_preparation_rejects_invalid_state(self):
        for module, path in DOCS.items():
            with self.subTest(module=module):
                steps = blocks(path)
                self.assertIn(f"prepare-{module:02}", steps)
                result = run('export STATE_FILE=state.json\n' + steps[f"prepare-{module:02}"],
                             files={"state.json": '{"schemaVersion":999}'})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid or unreadable", result.stderr)

    def test_each_preparation_prompts_for_existing_state_only_when_path_is_unset(self):
        for module, path in DOCS.items():
            with self.subTest(module=module):
                prepare = blocks(path)[f"prepare-{module:02}"]
                result = run(prepare + '\nprintf "TARGET=%s:%s\\n" "$STATE_FILE" "$RUN_ID"\n',
                             preparation_calls(module),
                             files={".workshop-state/demo123.json": json.dumps(STATE)},
                             input_text=".workshop-state/demo123.json\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("TARGET=.workshop-state/demo123.json:demo123", result.stdout)
                result = run('export STATE_FILE=state.json\n' + prepare +
                             '\nprintf "TARGET=%s:%s\\n" "$STATE_FILE" "$RUN_ID"\n',
                             preparation_calls(module))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("TARGET=state.json:demo123", result.stdout)

    def test_preparation_rejects_wrong_path_and_cancelled_input_without_stale_targets(self):
        for module, path in DOCS.items():
            for input_text in ("./workshop-state/demo123.json\n", "\n", ""):
                with self.subTest(module=module, input=input_text):
                    prepare = blocks(path)[f"prepare-{module:02}"]
                    script = 'source scripts/workshop-common.sh\nload_run state.json && zone_context hub\n'
                    script += 'unset STATE_FILE\n' + prepare + '''
status=$?
printf 'PREPARE_STATUS=%s\\n' "$status"
for name in RUN_ID SUBSCRIPTION_ID LOCATION RG_HUB RG_SPOKEA RG_SPOKEB \
AVNM NETWORK_GROUP CONNECTIVITY_CONFIG AVNM_ID NETWORK_GROUP_ID CONNECTIVITY_CONFIG_ID \
RG VNET VM NSG; do
  [[ ! -v "$name" ]] || { printf 'STALE:%s\\n' "$name"; exit 91; }
done
printf 'SHELL_ALIVE\\n'
'''
                    result = run(script, input_text=input_text)
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                    self.assertIn("PREPARE_STATUS=1\nSHELL_ALIVE", result.stdout)
                    self.assertIn("ERROR:", result.stderr)

    def test_failed_preparation_does_not_leave_a_previous_workshop_target(self):
        for module, path in DOCS.items():
            with self.subTest(module=module):
                script = 'source scripts/workshop-common.sh\nload_run state.json\nzone_context hub\n'
                script += 'export STATE_FILE=missing.json\n' + blocks(path)[f"prepare-{module:02}"]
                script += '''
status=$?
printf 'PREPARE_STATUS=%s\\n' "$status"
for name in RUN_ID SUBSCRIPTION_ID LOCATION RG_HUB RG_SPOKEA RG_SPOKEB \
AVNM NETWORK_GROUP CONNECTIVITY_CONFIG AVNM_ID NETWORK_GROUP_ID CONNECTIVITY_CONFIG_ID \
RG VNET VM NSG; do
  [[ ! -v "$name" ]] || { printf 'STALE:%s\\n' "$name"; exit 91; }
done
printf 'SHELL_ALIVE\\n'
'''
                result = run(script)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertIn("PREPARE_STATUS=1\nSHELL_ALIVE", result.stdout)

    def test_foundation_and_peering_actions_are_independent_and_subscription_scoped(self):
        for module, cases in ((2, foundation_cases()), (3, peering_cases())):
            for name, calls in cases.items():
                with self.subTest(module=module, step=name):
                    result = self.execute(module, name, calls)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_foundation_and_peering_actions_stop_on_each_failed_lookup(self):
        for module, cases in ((2, foundation_cases()), (3, peering_cases())):
            for name, calls in cases.items():
                for index in range(len(calls) - 1):
                    with self.subTest(step=name, failure=index):
                        failed = copy.deepcopy(calls[:index + 1])
                        failed[-1].update(returncode=1, stdout="")
                        result = self.execute(module, name, failed)
                        self.assertNotEqual(result.returncode, 0)

    def test_rg_collision_never_retags_existing_group(self):
        for zone in ("hub", "spokea", "spokeb"):
            for owned in (True, False):
                with self.subTest(zone=zone, owned=owned):
                    ownership = group(zone)
                    if not owned:
                        ownership["stdout"] = json.dumps({"id": "foreign", "tags": {}})
                    result = self.execute(2, f"foundation-{zone}-rg", [
                        az(["group", "exists", "--name", rg(zone), "-o", "tsv"], "true"), ownership])
                    self.assertEqual(result.returncode == 0, owned, result.stderr)

    def test_foundation_rechecks_reused_group_once_before_resuming_resource_creation(self):
        steps = blocks(DOCS[2])
        cases = foundation_cases()
        for zone in ("hub", "spokea", "spokeb"):
            with self.subTest(zone=zone):
                names = [f"foundation-{zone}-{kind}" for kind in ("rg", "vnet", "nsg")]
                script = 'export STATE_FILE=state.json\n'
                script += " &&\n".join([steps["prepare-02"], *(steps[name] for name in names)])
                calls = [account(), az(["group", "exists", "--name", rg(zone), "-o", "tsv"], "true"), group(zone)]
                for name in names[1:]:
                    calls.extend(cases[name])
                result = run(script, calls)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_preparation_and_state_changing_safety_boundaries_keep_assertions(self):
        for module, path in DOCS.items():
            for name, script in blocks(path).items():
                with self.subTest(module=module, step=name):
                    assertions = re.findall(r"\bassert_\w+", script)
                    if name.startswith("prepare-"):
                        expected = ["assert_subscription"]
                        if module in (3, 4, 5, 6):
                            expected.extend(["assert_owned_rg"] * 3)
                    elif module == 2 and name.endswith("-rg"):
                        expected = ["assert_owned_rg"]
                    elif module == 6 and name.startswith("attach-routes-"):
                        expected = ["assert_route_tables_ready"]
                    elif module == 6 and name.startswith("remove-"):
                        expected = ["assert_spoke_nat_removal"]
                    else:
                        expected = []
                    self.assertEqual(assertions, expected)
        for module in (3, 5):
            self.assertNotIn("source scripts/workshop-safety.sh", DOCS[module].read_text())

    def test_peering_accepts_id_casing_and_preserves_discovered_remote_id(self):
        for name, calls in peering_cases().items():
            if not name.startswith("peering-"):
                continue
            for transform in (str.lower, str.swapcase):
                with self.subTest(step=name, casing=transform.__name__):
                    result = self.execute(3, name, recase_ids(calls, transform))
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_foundation_and_peering_propagate_final_cli_errors(self):
        for module, cases in ((2, foundation_cases()), (3, peering_cases())):
            for name, calls in cases.items():
                with self.subTest(module=module, step=name):
                    failed = copy.deepcopy(calls)
                    failed[-1].update(returncode=1, stdout="", stderr="Azure request failed")
                    result = self.execute(module, name, failed)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Azure request failed", result.stderr)
