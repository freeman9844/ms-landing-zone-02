import json
import re
import unittest
from harness import ROOT, STATE, SUB, account, call, run


def recovery_block():
    text = (ROOT / "docs/01-prerequisites.md").read_text()
    section = text.split("## 세션 재연결 시 변수 복구\n", 1)[1]
    return re.search(r"```bash\n(.*?)\n```", section, re.S).group(1)


class RecoveryDocsTests(unittest.TestCase):
    def test_recovery_lists_available_state_file_before_path_input(self):
        script = '''
mkdir -p home
ln -s "$PWD" home/ms-landing-zone-02
export HOME="$PWD/home"
read() { printf 'PROMPT=%s\\n' "$2"; builtin read "$@"; }
'''
        result = run(script + recovery_block() + '\nprintf "TARGET=%s\\n" "$STATE_FILE"\n',
                     [call(["account", "set", "--subscription", SUB]), account()],
                     files={".workshop-state/demo123.json": json.dumps(STATE)},
                     input_text=".workshop-state/demo123.json\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("demo123.json\n"), result.stdout)
        self.assertIn("PROMPT=저장된 상태 파일 경로 (예: .workshop-state/demo123.json): ", result.stdout)
        self.assertIn("TARGET=.workshop-state/demo123.json", result.stdout)

    def test_failed_directory_change_stops_recovery_without_account_changes(self):
        script = '''
mkdir -p empty-home .workshop-state
export HOME="$PWD/empty-home"
'''
        script += recovery_block()
        script += '\nstatus=$?\nprintf "RECOVERY_STATUS=%s\\nSHELL_ALIVE\\n" "$status"\n'
        result = run(script, input_text="state.json\n")
        self.assertIn("RECOVERY_STATUS=1\nSHELL_ALIVE", result.stdout)
        self.assertIn("No such file or directory", result.stderr)

    def test_successful_recovery_accepts_uploaded_json_without_state_directory(self):
        script = '''
mkdir -p home
ln -s "$PWD" home/ms-landing-zone-02
export HOME="$PWD/home"
read() { printf 'PROMPT=%s\\n' "$2"; builtin read "$@"; }
'''
        script += recovery_block()
        script += '\nstatus=$?\nprintf "RECOVERY_STATUS=%s\\nTARGET=%s:%s\\n" "$status" "$RUN_ID" "$RG_HUB"\n'
        result = run(script, [
            call(["account", "set", "--subscription", SUB]), account(),
        ], input_text="state.json\n")
        self.assertIn("RECOVERY_STATUS=0\nTARGET=demo123:rg-lzbegin-hub-demo123", result.stdout)
        self.assertIn("PROMPT=저장된 상태 파일 경로 (예: .workshop-state/<실행 ID>.json): ", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_cancelled_input_stops_before_loading_or_selecting_a_subscription(self):
        script = '''
mkdir -p home .workshop-state
mkdir -p home
ln -s "$PWD" home/ms-landing-zone-02
export HOME="$PWD/home"
'''
        script += recovery_block()
        script += '\nstatus=$?\nprintf "RECOVERY_STATUS=%s\\nSHELL_ALIVE\\n" "$status"\n'
        result = run(script, input_text="state.json")
        self.assertIn("RECOVERY_STATUS=1\nSHELL_ALIVE", result.stdout)

    def test_failed_load_clears_old_targets_without_selecting_a_subscription(self):
        script = '''
source scripts/workshop-common.sh
load_run state.json && export SPOKEA_VNET_CIDR=172.20.16.0/20 && zone_context spokea || exit 90
mkdir -p home .workshop-state
mkdir -p home
ln -s "$PWD" home/ms-landing-zone-02
export HOME="$PWD/home"
'''
        script += recovery_block()
        script += '''
status=$?
printf 'RECOVERY_STATUS=%s\\n' "$status"
for name in RUN_ID SUBSCRIPTION_ID LOCATION RG_HUB RG_SPOKEA RG_SPOKEB \
AVNM NETWORK_GROUP CONNECTIVITY_CONFIG AVNM_ID NETWORK_GROUP_ID CONNECTIVITY_CONFIG_ID \
RG VNET VM NSG SPOKEA_VNET_CIDR; do
  [[ ! -v "$name" ]] || { printf 'STALE:%s\\n' "$name"; exit 91; }
done
printf 'SHELL_ALIVE\\n'
'''
        result = run(script, input_text="missing.json\n")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("RECOVERY_STATUS=1\nSHELL_ALIVE", result.stdout)
        self.assertIn("Invalid or unreadable state file", result.stderr)

    def test_missing_common_script_stops_before_reading_or_selecting_subscription(self):
        script = '''
source scripts/workshop-common.sh
load_run state.json || exit 90
mkdir -p home/ms-landing-zone-02
export HOME="$PWD/home"
'''
        script += recovery_block()
        script += '\nstatus=$?\nprintf "RECOVERY_STATUS=%s\\nSHELL_ALIVE\\n" "$status"\n'
        result = run(script, input_text="state.json\n")
        self.assertIn("RECOVERY_STATUS=1\nSHELL_ALIVE", result.stdout)
        self.assertIn("scripts/workshop-common.sh: No such file or directory", result.stderr)
        self.assertNotIn("Invalid or unreadable state file", result.stderr)

    def test_failed_subscription_selection_is_not_hidden_by_account_check(self):
        script = '''
mkdir -p home
ln -s "$PWD" home/ms-landing-zone-02
export HOME="$PWD/home"
'''
        script += recovery_block()
        script += '\nstatus=$?\nprintf "RECOVERY_STATUS=%s\\nSHELL_ALIVE\\n" "$status"\n'
        result = run(script, [
            call(["account", "set", "--subscription", SUB], code=1, stderr="Subscription unavailable"),
        ], input_text="state.json\n")
        self.assertIn("RECOVERY_STATUS=1\nSHELL_ALIVE", result.stdout)
        self.assertIn("Subscription unavailable", result.stderr)
