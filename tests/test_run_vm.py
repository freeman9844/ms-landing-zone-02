import json
import unittest
from harness import run, call, account, group
from test_ipam_cidrs import fixtures, reads


def run_vm(script, calls=(), **kwargs):
    vnets, subnets = fixtures()
    calls = list(calls)
    if calls:
        calls[2:2] = reads(vnets, subnets)
    return run(script, calls, **kwargs)


def invoke(message, outer_code=0, stderr=""):
    return call(["vm", "run-command", "invoke", "--resource-group", "rg-lzbegin-spokea-demo123",
                 "--name", "vm-lzbegin-spokea-demo123", "--command-id", "RunShellScript",
                 "--scripts", {"regex": "@/.+/lzbegin-run\\.[A-Za-z0-9]+"}, "-o", "json"],
                {"value": [{"code": "ProvisioningState/succeeded", "level": "Info",
                            "displayStatus": "Provisioning succeeded",
                            "message": f"Enable succeeded: \n[stdout]\n{message}\n[stderr]\n{stderr}"}]},
                code=outer_code)


class RunVmTests(unittest.TestCase):
    def run_response(self, response):
        return run_vm('bash "$WORKSHOP_ROOT/scripts/run-vm.sh" state.json spokea guest.sh',
                   [account(), group("spokea"), response], files={"guest.sh": "true"})

    def test_linux_combined_output_keeps_stderr_out_of_stdout(self):
        result = self.run_response(invoke("spokea\n__LZ_EXIT__:0\n", stderr="diagnostic warning\n"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "spokea\n")
        self.assertEqual(result.stderr, "diagnostic warning\n")

    def test_stderr_success_marker_cannot_hide_guest_failure(self):
        result = self.run_response(invoke("__LZ_EXIT__:7\n", stderr="__LZ_EXIT__:0\n"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed guest exit", result.stderr)

    def test_truncated_stdout_cannot_borrow_stderr_success_marker(self):
        result = self.run_response(invoke("truncated output", stderr="__LZ_EXIT__:0\n"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed guest exit", result.stderr)

    def test_separate_component_output_remains_supported(self):
        response = invoke("")
        response["stdout"] = json.dumps({"value": [
            {"code": "ComponentStatus/StdOut/succeeded", "message": "spokea\n__LZ_EXIT__:0\n"},
            {"code": "ComponentStatus/StdErr/succeeded", "message": "warning\n"},
        ]})
        result = self.run_response(response)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "spokea\n")
        self.assertEqual(result.stderr, "warning\n")

    def test_malformed_ambiguous_or_failed_api_results_are_rejected(self):
        success = {"code": "ProvisioningState/succeeded",
                   "message": "Enable succeeded: \n[stdout]\n__LZ_EXIT__:0\n\n[stderr]\n"}
        cases = [
            {"value": []},
            {"value": [success, success]},
            {"value": [dict(success, code="ProvisioningState/failed")]},
            {"value": [dict(success, message="__LZ_EXIT__:0\n")]},
            {"value": [dict(success, message="Enable succeeded: \n[stdout]\n__LZ_EXIT__:0\n")]},
            {"value": [dict(success, message=None)]},
            {"value": [dict(success, message=success["message"] + "\n[stderr]\nextra")]},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                response = invoke("")
                response["stdout"] = json.dumps(payload)
                result = self.run_response(response)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid Run Command response", result.stderr)

    def test_action_handler_honors_bash_shebang_for_wrapped_guest(self):
        response = invoke("")
        response["run_guest"] = True
        result = run_vm('bash "$WORKSHOP_ROOT/scripts/run-vm.sh" state.json spokea guest.sh',
                     [account(), group("spokea"), response],
                     files={"guest.sh": '#!/usr/bin/env bash\nvalues=(spokea)\nprintf "%s\\n" "${values[0]}"'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "spokea")

    def test_actual_guest_failure_is_not_hidden_by_outer_api_success(self):
        response = invoke("")
        response["run_guest"] = True
        result = run_vm('bash "$WORKSHOP_ROOT/scripts/run-vm.sh" state.json spokea guest.sh',
                     [account(), group("spokea"), response],
                     files={"guest.sh": "exit 7"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("__LZ_EXIT__:7", result.stderr)

    def test_returns_guest_output_without_control_marker(self):
        result = run_vm('bash "$WORKSHOP_ROOT/scripts/run-vm.sh" state.json spokea guest.sh',
                     [account(), group("spokea"), invoke("spokea\n\n__LZ_EXIT__:0\n")],
                     files={"guest.sh": "printf spokea"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "spokea")

    def test_outer_success_is_not_guest_success(self):
        for message in ("__LZ_EXIT__:7\n", "no exit marker", ""):
            with self.subTest(message=message):
                result = run_vm('bash "$WORKSHOP_ROOT/scripts/run-vm.sh" state.json spokea guest.sh',
                             [account(), group("spokea"), invoke(message)],
                             files={"guest.sh": "false"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("guest", result.stderr)

    def test_cloud_failure_propagates(self):
        result = run_vm('bash "$WORKSHOP_ROOT/scripts/run-vm.sh" state.json spokea guest.sh',
                     [account(), group("spokea"), invoke("", outer_code=3)], files={"guest.sh": "true"})
        self.assertNotEqual(result.returncode, 0)

    def test_missing_guest_file_prevents_cloud_calls(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/run-vm.sh" state.json spokea missing.sh')
        self.assertNotEqual(result.returncode, 0)
