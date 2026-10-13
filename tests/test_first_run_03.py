import json
import unittest

from harness import run
from test_network_docs import (
    DOCS, avnm_cases, avnm_name, az, blocks, network_group_name,
    preparation_calls, rg, static_member,
)


CREATION_STEPS = (
    "network-group-create",
    "member-spokea",
    "member-spokeb",
    "route-group-spokea-create",
    "route-group-spokeb-create",
    "route-member-spokea",
    "route-member-spokeb",
    "connectivity-config-create",
)


class Module03FirstRunTests(unittest.TestCase):
    def execute(self, steps, calls):
        script = 'export STATE_FILE=state.json\n' + " || exit 1\n".join(
            blocks(DOCS[3])[step] for step in steps
        )
        return run(script, [*preparation_calls(3), *calls])

    def test_first_run_creates_each_resource_without_name_or_membership_inventory(self):
        cases = avnm_cases()
        for step in CREATION_STEPS:
            with self.subTest(step=step):
                create = cases[step][-1]
                self.assertIn("create", create["argv"])
                result = self.execute(("prepare-03", step), [create])
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_creation_errors_fail_without_continuing_to_another_write(self):
        cases = avnm_cases()
        for step in CREATION_STEPS:
            with self.subTest(step=step):
                create = dict(cases[step][-1], returncode=1, stderr="already exists")
                result = self.execute(("prepare-03", step, "connectivity-commit"), [create])
                self.assertNotEqual(result.returncode, 0)

    def test_manager_readiness_gates_first_group_creation(self):
        cases = avnm_cases()
        steps = ("prepare-03", "avnm-ready", "network-group-create")
        good = self.execute(steps, [*cases["avnm-ready"], cases["network-group-create"][-1]])
        self.assertEqual(good.returncode, 0, good.stderr)
        manager = cases["avnm-ready"][0]
        not_ready = dict(manager, stdout=json.dumps({
            **json.loads(manager["stdout"]), "provisioningState": "Updating",
        }))
        failed = self.execute(steps, [not_ready])
        self.assertNotEqual(failed.returncode, 0)

    def test_required_member_check_still_gates_configuration_creation(self):
        cases = avnm_cases()
        members = az([
            "network", "manager", "group", "static-member", "list",
            "--network-group", network_group_name(),
            "--network-manager", avnm_name(),
            "--resource-group", rg("hub"), "-o", "json",
        ], [static_member("spokea", "spokea"), static_member("spokeb", "spokeb")])
        steps = ("prepare-03", "inspect-static-members", "connectivity-config-create")
        good = self.execute(steps, [members, cases["connectivity-config-create"][-1]])
        self.assertEqual(good.returncode, 0, good.stderr)
        bad_members = dict(members, stdout=json.dumps([static_member("hub", "hub")]))
        failed = self.execute(steps, [bad_members])
        self.assertNotEqual(failed.returncode, 0)

if __name__ == "__main__":
    unittest.main()
