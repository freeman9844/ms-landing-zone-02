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


def workshop_state(run_id="demo123", subscription=SUB):
    return {
        "schemaVersion": 2,
        "topology": "avnm-hub-spoke",
        "runId": run_id,
        "subscriptionId": subscription,
        "location": "koreacentral",
        "resourceGroups": {
            "hub": f"rg-lzbegin-hub-{run_id}",
            "spokea": f"rg-lzbegin-spokea-{run_id}",
            "spokeb": f"rg-lzbegin-spokeb-{run_id}",
        },
    }


def rg(zone, state=STATE):
    return state["resourceGroups"][zone]


def rid(zone, kind, name, state=STATE):
    return f"/subscriptions/{SUB}/resourceGroups/{rg(zone, state)}/providers/{kind}/{name}"


def netid(zone, kind, name, state=STATE):
    return rid(zone, "Microsoft.Network/" + kind, name, state)


def az(args, value="", code=0):
    return call([*args, "--subscription", SUB], value, code)


def vnet(zone, state=STATE):
    return f"vnet-lzbegin-{zone}-{state['runId']}"


def avnm_name(state=STATE):
    return f"avnm-lzbegin-{state['runId']}"


def network_group_name(state=STATE):
    return f"ng-lzbegin-spokes-{state['runId']}"

def routing_group_name(zone, state=STATE):
    return f"ng-lzbegin-route-{zone}-{state['runId']}"

def routing_group_id(zone, state=STATE):
    return avnm_id(state) + "/networkGroups/" + routing_group_name(zone, state)


def connectivity_config_name(state=STATE):
    return f"cc-lzbegin-hub-spoke-{state['runId']}"


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


def avnm_id(state=STATE):
    return netid("hub", "networkManagers", avnm_name(state), state)


def network_group_id(state=STATE):
    return avnm_id(state) + f"/networkGroups/{network_group_name(state)}"


def connectivity_config_id(state=STATE):
    return avnm_id(state) + f"/connectivityConfigurations/{connectivity_config_name(state)}"


def static_member(name, zone, state=STATE):
    return {
        "name": name,
        "id": network_group_id(state) + f"/staticMembers/{name}",
        "resourceId": netid(zone, "virtualNetworks", vnet(zone, state), state),
        "provisioningState": "Succeeded",
    }


def connectivity_config(state=STATE):
    return {
        "name": connectivity_config_name(state),
        "id": connectivity_config_id(state),
        "connectivityTopology": "HubAndSpoke",
        "deleteExistingPeering": "False",
        "isGlobal": "False",
        "provisioningState": "Succeeded",
        "hubs": [{
            "resourceId": netid("hub", "virtualNetworks", vnet("hub", state), state),
            "resourceType": "Microsoft.Network/virtualNetworks",
        }],
        "appliesToGroups": [{
            "networkGroupId": network_group_id(state),
            "groupConnectivity": "None",
            "isGlobal": "False",
            "useHubGateway": "False",
        }],
    }


def effective_configuration(zone, state=STATE):
    return {"value": [dict(connectivity_config(state), targetVirtualNetwork={
        "id": netid(zone, "virtualNetworks", vnet(zone, state), state),
    })]}


def avnm_peerings(zone, state=STATE):
    peerings = {
        "hub": [
            {"name": "avnm-hub-a", "peeringState": "Connected",
             "remoteVirtualNetwork": {"id": netid("spokea", "virtualNetworks", vnet("spokea", state), state)}},
            {"name": "avnm-hub-b", "peeringState": "Connected",
             "remoteVirtualNetwork": {"id": netid("spokeb", "virtualNetworks", vnet("spokeb", state), state)}},
        ],
        "spokea": [
            {"name": "avnm-a-hub", "peeringState": "Connected",
             "remoteVirtualNetwork": {"id": netid("hub", "virtualNetworks", vnet("hub", state), state)}},
        ],
        "spokeb": [
            {"name": "avnm-b-hub", "peeringState": "Connected",
             "remoteVirtualNetwork": {"id": netid("hub", "virtualNetworks", vnet("hub", state), state)}},
        ],
    }
    return peerings[zone]


def owned_group_call(zone, state=STATE):
    name = rg(zone, state)
    return call(["group", "show", "--name", name, "-o", "json"], {
        "name": name,
        "id": f"/subscriptions/{SUB}/resourceGroups/{name}",
        "tags": {
            "workshop": "lz-beginner",
            "environment": "lab",
            "runId": state["runId"],
            "managedBy": "workshop",
        },
    })


def avnm_cases():
    hub = netid("hub", "virtualNetworks", vnet("hub"))
    spokea = netid("spokea", "virtualNetworks", vnet("spokea"))
    spokeb = netid("spokeb", "virtualNetworks", vnet("spokeb"))
    manager = avnm_id()
    manager_body = {
        "location": "koreacentral",
        "properties": {
            "description": "Beginner Hub and Spoke connectivity",
            "networkManagerScopes": {"subscriptions": [f"/subscriptions/{SUB}"]},
            "networkManagerScopeAccesses": ["Connectivity", "SecurityAdmin", "Routing"],
        },
    }
    hubs = json.dumps([{
        "resourceId": hub,
        "resourceType": "Microsoft.Network/virtualNetworks",
    }], separators=(",", ":"))
    groups = json.dumps([{
        "networkGroupId": network_group_id(),
        "groupConnectivity": "None",
        "isGlobal": False,
        "useHubGateway": False,
    }], separators=(",", ":"))
    initial_group = {"name": network_group_name(), "id": network_group_id(),
                     "provisioningState": "Succeeded"}
    route_a_group = {"name": routing_group_name("spokea"), "id": routing_group_id("spokea"),
                     "provisioningState": "Succeeded"}
    return {
        "avnm-create": [
            az(["network", "manager", "list", "--resource-group", rg("hub"), "-o", "json"], []),
            az([
                "rest", "--method", "put",
                "--url", f"{manager}?api-version=2025-01-01",
                "--body", json.dumps(manager_body, separators=(",", ":")),
                "-o", "json",
            ], {"id": manager, "properties": {
                **manager_body["properties"], "provisioningState": "Succeeded"}}),
        ],
        "avnm-ready": [
            az(["network", "manager", "show", "--name", avnm_name(),
                "--resource-group", rg("hub"), "-o", "json"],
               {"id": manager, "properties": {
                   **manager_body["properties"], "provisioningState": "Succeeded"}}),
        ],
        "network-group-create": [
            az([
                "network", "manager", "group", "list",
                "--network-manager-name", "avnm-lzbegin-demo123",
                "--resource-group", rg("hub"),
                "-o", "json",
            ], []),
            az([
                "network", "manager", "group", "create",
                "--name", "ng-lzbegin-spokes-demo123",
                "--network-manager-name", "avnm-lzbegin-demo123",
                "--resource-group", rg("hub"),
                "--description", "Workshop spoke virtual networks",
                "-o", "json",
            ]),
        ],
        "member-spokea": [
            az([
                "network", "manager", "group", "static-member", "list",
                "--network-group", "ng-lzbegin-spokes-demo123",
                "--network-manager", "avnm-lzbegin-demo123",
                "--resource-group", rg("hub"),
                "-o", "json",
            ], []),
            az([
                "network", "manager", "group", "static-member", "create",
                "--name", "spokea",
                "--network-group", "ng-lzbegin-spokes-demo123",
                "--network-manager", "avnm-lzbegin-demo123",
                "--resource-group", rg("hub"),
                "--resource-id", spokea,
                "-o", "json",
            ]),
        ],
        "member-spokeb": [
            az([
                "network", "manager", "group", "static-member", "list",
                "--network-group", "ng-lzbegin-spokes-demo123",
                "--network-manager", "avnm-lzbegin-demo123",
                "--resource-group", rg("hub"),
                "-o", "json",
            ], [static_member("spokea", "spokea")]),
            az([
                "network", "manager", "group", "static-member", "create",
                "--name", "spokeb",
                "--network-group", "ng-lzbegin-spokes-demo123",
                "--network-manager", "avnm-lzbegin-demo123",
                "--resource-group", rg("hub"),
                "--resource-id", spokeb,
                "-o", "json",
            ]),
        ],
        "route-group-spokea-create": [
            az(["network", "manager", "group", "list", "--network-manager-name", avnm_name(),
                "--resource-group", rg("hub"), "-o", "json"], [initial_group]),
            az(["network", "manager", "group", "create",
                "--name", routing_group_name("spokea"),
                "--network-manager-name", avnm_name(), "--resource-group", rg("hub"),
                "--description", "Spoke A routing scope", "-o", "json"]),
        ],
        "route-group-spokeb-create": [
            az(["network", "manager", "group", "list", "--network-manager-name", avnm_name(),
                "--resource-group", rg("hub"), "-o", "json"], [initial_group, route_a_group]),
            az(["network", "manager", "group", "create",
                "--name", routing_group_name("spokeb"),
                "--network-manager-name", avnm_name(), "--resource-group", rg("hub"),
                "--description", "Spoke B routing scope", "-o", "json"]),
        ],
        "route-member-spokea": [
            az(["network", "manager", "group", "static-member", "list",
                "--network-group", routing_group_name("spokea"), "--network-manager", avnm_name(),
                "--resource-group", rg("hub"), "-o", "json"], []),
            az(["network", "manager", "group", "static-member", "create",
                "--name", "spokea", "--network-group", routing_group_name("spokea"),
                "--network-manager", avnm_name(), "--resource-group", rg("hub"),
                "--resource-id", spokea, "-o", "json"]),
        ],
        "route-member-spokeb": [
            az(["network", "manager", "group", "static-member", "list",
                "--network-group", routing_group_name("spokeb"), "--network-manager", avnm_name(),
                "--resource-group", rg("hub"), "-o", "json"], []),
            az(["network", "manager", "group", "static-member", "create",
                "--name", "spokeb", "--network-group", routing_group_name("spokeb"),
                "--network-manager", avnm_name(), "--resource-group", rg("hub"),
                "--resource-id", spokeb, "-o", "json"]),
        ],
        "connectivity-config-create": [
            az([
                "network", "manager", "connect-config", "list",
                "--network-manager-name", "avnm-lzbegin-demo123",
                "--resource-group", rg("hub"),
                "-o", "json",
            ], []),
            az([
                "network", "manager", "connect-config", "create",
                "--configuration-name", "cc-lzbegin-hub-spoke-demo123",
                "--description", "AVNM managed beginner hub and spoke",
                "--applies-to-groups", groups,
                "--hubs", hubs,
                "--connectivity-topology", "HubAndSpoke",
                "--delete-existing-peering", "False",
                "--is-global", "False",
                "--network-manager-name", "avnm-lzbegin-demo123",
                "--resource-group", rg("hub"),
                "-o", "json",
            ]),
        ],
        "connectivity-commit": [az([
            "network", "manager", "post-commit",
            "--network-manager-name", "avnm-lzbegin-demo123",
            "--commit-type", "Connectivity",
            "--configuration-ids", connectivity_config_id(),
            "--target-locations", "koreacentral",
            "--resource-group", rg("hub"),
            "-o", "json",
        ])],
        "effective-hub": [az([
            "network", "manager", "list-effective-connectivity-config",
            "--resource-group", rg("hub"),
            "--virtual-network-name", vnet("hub"),
            "-o", "json",
        ], {"value": []})],
        "effective-spokea": [az([
            "network", "manager", "list-effective-connectivity-config",
            "--resource-group", rg("spokea"),
            "--virtual-network-name", vnet("spokea"),
            "-o", "json",
        ], effective_configuration("spokea"))],
        "effective-spokeb": [az([
            "network", "manager", "list-effective-connectivity-config",
            "--resource-group", rg("spokeb"),
            "--virtual-network-name", vnet("spokeb"),
            "-o", "json",
        ], effective_configuration("spokeb"))],
        "inspect-avnm-peerings-hub": [az([
            "network", "vnet", "peering", "list",
            "-g", rg("hub"),
            "--vnet-name", vnet("hub"),
            "-o", "json",
        ], avnm_peerings("hub"))],
        "inspect-avnm-peerings-spokea": [az([
            "network", "vnet", "peering", "list",
            "-g", rg("spokea"),
            "--vnet-name", vnet("spokea"),
            "-o", "json",
        ], avnm_peerings("spokea"))],
        "inspect-avnm-peerings-spokeb": [az([
            "network", "vnet", "peering", "list",
            "-g", rg("spokeb"),
            "--vnet-name", vnet("spokeb"),
            "-o", "json",
        ], avnm_peerings("spokeb"))],
    }


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


def preparation_calls(module, state=STATE):
    calls = [account()]
    if module in (3, 4, 5, 6):
        calls.extend(owned_group_call(zone, state) for zone in ("hub", "spokea", "spokeb"))
    return calls


class NetworkDocsTests(unittest.TestCase):
    def test_module_03_execution_blocks_do_not_chain_with_and(self):
        for name, script in blocks(DOCS[3]).items():
            with self.subTest(step=name):
                self.assertNotIn("&&", script)

    def test_configuration_waits_for_both_static_members_before_create(self):
        calls = [az([
            "network", "manager", "group", "static-member", "list",
            "--network-group", network_group_name(),
            "--network-manager", avnm_name(),
            "--resource-group", rg("hub"), "-o", "json",
        ], [static_member("spokea", "spokea"), static_member("spokeb", "spokeb")])]
        result = self.execute(3, "inspect-static-members", [
            dict(calls[0], stdout=json.dumps([static_member("spokea", "spokea")])),
            calls[0],
        ])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_configuration_preflight_checks_hub_separately_and_create_uses_verified_ids(self):
        hub_call = az(["network", "vnet", "show", "-g", rg("hub"), "-n", vnet("hub"),
                       "--query", "id", "-o", "tsv"], netid("hub", "virtualNetworks", vnet("hub")))
        result = self.execute(3, "inspect-avnm-hub", [hub_call])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(netid("hub", "virtualNetworks", vnet("hub")), result.stdout)
        result = self.execute(3, "inspect-avnm-hub", [dict(hub_call, stdout="unexpected")])
        self.assertNotEqual(result.returncode, 0)
        script = blocks(DOCS[3])["connectivity-config-create"]
        self.assertNotIn("static-member list", script)
        self.assertNotIn("network vnet show", script)
        self.assertNotIn("&&", script)

    def test_configuration_creation_follows_member_and_hub_checks(self):
        steps = blocks(DOCS[3])
        members = az([
            "network", "manager", "group", "static-member", "list",
            "--network-group", network_group_name(), "--network-manager", avnm_name(),
            "--resource-group", rg("hub"), "-o", "json",
        ], [static_member("spokea", "spokea"), static_member("spokeb", "spokeb")])
        hub = az(["network", "vnet", "show", "-g", rg("hub"), "-n", vnet("hub"),
                  "--query", "id", "-o", "tsv"], netid("hub", "virtualNetworks", vnet("hub")))
        actions = ["prepare-03", "inspect-static-members", "inspect-avnm-hub", "connectivity-config-create"]
        script = 'export STATE_FILE=state.json\n' + " || exit 1\n".join(steps[action] for action in actions)
        result = run(script, [*preparation_calls(3), members, hub,
                              *avnm_cases()["connectivity-config-create"]])
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run(script, [*preparation_calls(3),
                              dict(members, stdout=json.dumps([static_member("hub", "hub")]))])
        self.assertNotEqual(result.returncode, 0)

    def execute(self, module, name, calls=(), input_text=None, files=None, prefix="", state=STATE):
        steps = blocks(DOCS[module])
        self.assertIn(f"prepare-{module:02}", steps, "Module needs one common preparation block")
        self.assertIn(name, steps, "Missing separate teaching action")
        script = 'export STATE_FILE=state.json\n' + steps[f"prepare-{module:02}"] + "\n"
        script += 'prepared=$?\nif [[ "$prepared" == 0 ]]; then\n' + prefix + steps[name] + '\nelse\nfalse\nfi\n'
        script += 'status=$?\nprintf "SHELL_ALIVE\\n"\nexit "$status"'
        result = run(script, [*preparation_calls(module, state), *calls], input_text=input_text, files=files)
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

    def test_foundation_and_avnm_actions_are_independent_and_subscription_scoped(self):
        for module, cases in ((2, foundation_cases()), (3, avnm_cases())):
            for name, calls in cases.items():
                with self.subTest(module=module, step=name):
                    result = self.execute(module, name, calls)
                    self.assertEqual(result.returncode, 0, result.stderr)
        config_calls = avnm_cases()["connectivity-config-create"]
        for name, calls in (
            ("inspect-static-members", [az([
                "network", "manager", "group", "static-member", "list",
                "--network-group", network_group_name(), "--network-manager", avnm_name(),
                "--resource-group", rg("hub"), "-o", "json",
            ], [static_member("spokea", "spokea"), static_member("spokeb", "spokeb")])]),
            ("inspect-avnm-hub", [az(["network", "vnet", "show", "-g", rg("hub"), "-n", vnet("hub"),
                                      "--query", "id", "-o", "tsv"],
                                     netid("hub", "virtualNetworks", vnet("hub")))]),
        ):
            with self.subTest(step=name):
                result = self.execute(3, name, calls)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_avnm_inspection_blocks_are_read_only_and_show_cli_output(self):
        steps = blocks(DOCS[3])
        for name, calls in (
            ("inspect-avnm", avnm_cases()["avnm-create"][:1]),
            ("inspect-network-groups", avnm_cases()["network-group-create"][:1]),
            ("inspect-members-before-spokea", avnm_cases()["member-spokea"][:1]),
            ("inspect-members-before-spokeb", avnm_cases()["member-spokeb"][:1]),
        ):
            with self.subTest(step=name):
                self.assertNotIn(" create ", steps[name])
                result = self.execute(3, name, calls)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(calls[0]["stdout"], result.stdout)

    def test_hub_effective_configuration_accepts_only_empty_or_approved_configuration(self):
        expected_call = avnm_cases()["effective-hub"][0]
        for value, accepted in (
            ({"value": []}, True),
            (effective_configuration("hub"), True),
            ({"value": [connectivity_config()]}, True),
            ({"value": [dict(connectivity_config(), id="unexpected")]}, False),
            ({"value": [dict(connectivity_config(), targetVirtualNetwork={"id": "unexpected"})]}, False),
            ({"value": [connectivity_config(), connectivity_config()]}, False),
            ({"value": {}}, False),
        ):
            with self.subTest(value=value):
                result = self.execute(3, "effective-hub", [dict(expected_call, stdout=json.dumps(value))])
                self.assertEqual(result.returncode == 0, accepted, result.stderr)

    def test_spoke_effective_checks_preserve_exact_ids_and_status(self):
        for zone in ("spokea", "spokeb"):
            expected_call = avnm_cases()[f"effective-{zone}"][0]
            valid = effective_configuration(zone)
            variants = [
                (valid, True),
                ({"value": [dict(valid["value"][0], deleteExistingPeering=False, isGlobal=False)]}, True),
                ({"value": []}, False),
                ({"value": {}}, False),
                ({"value": [dict(valid["value"][0], id="unexpected")]}, False),
                ({"value": [dict(valid["value"][0], provisioningState="Updating")]}, False),
                ({"value": [dict(valid["value"][0], hubs=[{"resourceId": "unexpected"}])]}, False),
                ({"value": [dict(valid["value"][0], appliesToGroups=[{"networkGroupId": "unexpected"}])]}, False),
            ]
            for response, accepted in variants:
                with self.subTest(zone=zone, response=response):
                    result = self.execute(3, f"effective-{zone}",
                                          [dict(expected_call, stdout=json.dumps(response))])
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)

    def test_foundation_and_avnm_actions_stop_on_each_failed_lookup(self):
        for module, cases in ((2, foundation_cases()), (3, avnm_cases())):
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

    def test_first_creation_rejects_any_existing_resource_without_writing(self):
        cases = avnm_cases()
        for name, payload in (
            ("avnm-create", [{"name": "unrelated-avnm"}]),
            ("network-group-create", [{"name": "unrelated-group"}]),
            ("member-spokea", [static_member("hub", "hub")]),
            ("member-spokeb", [static_member("spokea", "spokea"),
                               static_member("spokeb", "spokeb")]),
            ("connectivity-config-create", [{"name": "unrelated-config"}]),
        ):
            with self.subTest(step=name):
                calls = copy.deepcopy(cases[name])
                calls[0]["stdout"] = json.dumps(payload)
                result = self.execute(3, name, calls[:1])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR:", result.stderr)

    def test_avnm_first_creation_rejects_malformed_discovery(self):
        for name in ("avnm-create", "network-group-create", "member-spokea",
                     "member-spokeb", "connectivity-config-create"):
            with self.subTest(step=name):
                calls = copy.deepcopy(avnm_cases()[name])
                calls[0]["stdout"] = '{"unexpected":true}'
                result = self.execute(3, name, calls[:1])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR:", result.stderr)

    def test_avnm_creation_rejects_wrong_scope_and_foreign_resource_id(self):
        calls = avnm_cases()["avnm-create"]
        original = json.loads(calls[-1]["stdout"])
        for changed in (
            dict(original, id="unexpected"),
            dict(original, properties=dict(original["properties"],
                networkManagerScopeAccesses=["Connectivity", "SecurityAdmin"])),
            dict(original, properties=dict(original["properties"],
                networkManagerScopes={"subscriptions": ["/subscriptions/00000000-0000-0000-0000-000000000000"]})),
        ):
            with self.subTest(response=changed):
                result = self.execute(3, "avnm-create",
                                      [calls[0], dict(calls[-1], stdout=json.dumps(changed))])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR:", result.stderr)

    def test_avnm_creation_accepts_scope_resource_id_case_variants(self):
        calls = avnm_cases()["avnm-create"]
        response = json.loads(calls[-1]["stdout"])
        response["properties"]["networkManagerScopes"]["subscriptions"][0] = (
            response["properties"]["networkManagerScopes"]["subscriptions"][0].upper())
        result = self.execute(3, "avnm-create",
                              [calls[0], dict(calls[-1], stdout=json.dumps(response))])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_state_restores_distinct_spoke_routing_group_ids(self):
        script = ('source scripts/workshop-common.sh\nload_run state.json\n'
                  'printf "%s\\n%s\\n" "$ROUTE_GROUP_A_ID" "$ROUTE_GROUP_B_ID"\n')
        result = run(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         [routing_group_id("spokea"), routing_group_id("spokeb")])

    def test_member_lists_reject_unapproved_topology_membership(self):
        valid = [static_member("spokea", "spokea"), static_member("spokeb", "spokeb")]
        scenarios = (
            ("hub-present", [*valid, static_member("hub", "hub")]),
            ("missing-spokea", [static_member("spokeb", "spokeb")]),
            ("missing-spokeb", [static_member("spokea", "spokea")]),
            ("foreign-subscription", [dict(static_member("spokea", "spokea"),
                                           resourceId=netid("spokea", "virtualNetworks", vnet("spokea")).replace(
                                               SUB, "99999999-9999-9999-9999-999999999999")),
                                     static_member("spokeb", "spokeb")]),
            ("foreign-rg", [dict(static_member("spokea", "spokea"),
                                 resourceId=netid("spokea", "virtualNetworks", vnet("spokea")).replace(
                                     rg("spokea"), rg("spokea") + "-foreign")),
                            static_member("spokeb", "spokeb")]),
        )
        for label, members in scenarios:
            with self.subTest(case=label):
                calls = [az([
                    "network", "manager", "group", "static-member", "list",
                    "--network-group", "ng-lzbegin-spokes-demo123",
                    "--network-manager", "avnm-lzbegin-demo123",
                    "--resource-group", rg("hub"),
                    "-o", "json",
                ], members)]
                result = self.execute(3, "inspect-static-members", calls * 12 if label.startswith("missing-") else calls)
                self.assertNotEqual(result.returncode, 0)

    def test_foundation_and_avnm_propagate_final_cli_errors(self):
        for module, cases in ((2, foundation_cases()), (3, avnm_cases())):
            for name, calls in cases.items():
                with self.subTest(module=module, step=name):
                    failed = copy.deepcopy(calls)
                    failed[-1].update(returncode=1, stdout="", stderr="Azure request failed")
                    result = self.execute(module, name, failed)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Azure request failed", result.stderr)
