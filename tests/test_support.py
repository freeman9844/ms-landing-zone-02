import json
import subprocess
import unittest
from harness import ROOT


def resources(template):
    for resource in template.get("resources", []):
        yield resource
        nested = resource.get("properties", {}).get("template")
        if nested:
            yield from resources(nested)


class SupportTests(unittest.TestCase):
    def test_compiled_template_has_private_vms_and_does_not_modify_subnets(self):
        entry = ROOT / "infra/lab-support.bicep"
        self.assertTrue(entry.exists(), "Support template missing")
        result = subprocess.run(
            ["az", "bicep", "build", "--file", str(entry), "--stdout"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        template = json.loads(result.stdout)
        for deployment in template["resources"]:
            subnet = deployment.get("properties", {}).get("parameters", {}).get("subnetId")
            if subnet:
                self.assertTrue(
                    subnet["value"].startswith("[resourceId(subscription().subscriptionId, "),
                    "Subscription-scope subnet IDs must specify subscription before resource group",
                )
        all_resources = list(resources(template))
        self.assertIn("support", template["outputs"])
        types = [r["type"].lower() for r in all_resources]
        self.assertIn("microsoft.network/natgateways", types)
        self.assertNotIn("microsoft.network/virtualnetworks", types)
        self.assertNotIn("microsoft.network/virtualnetworks/subnets", types)
        for r in all_resources:
            if r["type"].lower() == "microsoft.network/networkinterfaces":
                for config in r["properties"]["ipConfigurations"]:
                    self.assertNotIn("publicIPAddress", config["properties"])
            if r["type"].lower() == "microsoft.compute/virtualmachines":
                props = r["properties"]
                self.assertEqual(props["hardwareProfile"]["vmSize"], "Standard_B2als_v2")
                self.assertTrue(props["osProfile"]["linuxConfiguration"]["disablePasswordAuthentication"])
                self.assertTrue(props["securityProfile"]["uefiSettings"]["secureBootEnabled"])
                self.assertEqual(props["storageProfile"]["imageReference"]["offer"], "ubuntu-24_04-lts")
