import re
import subprocess
import unittest
from urllib.parse import unquote
from harness import ROOT

MODULES = [
    "00-azure-basics.md", "01-prerequisites.md", "02-network-foundation.md",
    "03-avnm-connectivity.md", "04-connectivity-nsg.md", "05-firewall.md",
    "06-routing-validation.md", "07-cleanup-production.md",
]


class DocsTests(unittest.TestCase):
    def test_module_navigation_reaches_firewall_routing_and_cleanup_in_order(self):
        readme = (ROOT / "README.md").read_text()
        entries = re.findall(r"^\| (\d{2}) \| \[[^\]]+\]\(docs/([^)]+)\)", readme, re.M)
        self.assertEqual(entries, [(f"{index:02}", name) for index, name in enumerate(MODULES)])
        for index, name in enumerate(MODULES):
            text = (ROOT / "docs" / name).read_text()
            navigation = text.split("## 다음 단계\n")[-1]
            if index < len(MODULES) - 1:
                self.assertIn(f"]({MODULES[index + 1]})", navigation)
            if index:
                self.assertIn(f"]({MODULES[index - 1]})", navigation)

    def test_entry_and_all_modules_exist(self):
        for relative in ["README.md", "docs/maintainer-validation.md"] + ["docs/" + p for p in MODULES]:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_shell_examples_parse(self):
        for path in [ROOT / "README.md", *(ROOT / "docs" / name for name in MODULES)]:
            if not path.exists():
                self.fail(f"Missing participant document: {path}")
            for block in re.findall(r"```bash\n(.*?)\n```", path.read_text(), re.S):
                result = subprocess.run(["bash", "-n"], input=block, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, f"{path}: {result.stderr}")

    def test_local_navigation_resolves_files_and_anchors(self):
        paths = [ROOT / "README.md", *(ROOT / "docs" / name for name in MODULES)]
        paths.append(ROOT / "docs/maintainer-validation.md")
        for path in paths:
            self.assertTrue(path.is_file(), path)
            text = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
                if "://" in target or target.startswith("mailto:"):
                    continue
                filename, _, fragment = target.partition("#")
                destination = (path.parent / unquote(filename)).resolve() if filename else path
                self.assertTrue(destination.is_file(), f"{path}: broken link {target}")
                if fragment:
                    content = destination.read_text()
                    anchors = set(re.findall(r'<a id="([^"]+)"', content))
                    for heading in re.findall(r"^#+ (.+)$", content, re.M):
                        slug = re.sub(r"[^\w\s-]", "", heading.lower()).replace(" ", "-")
                        anchors.add(slug)
                    self.assertIn(unquote(fragment), anchors, f"{path}: broken anchor {target}")

    def test_active_workshop_never_creates_manual_peerings(self):
        paths = [ROOT / "README.md", *(ROOT / "docs" / name for name in MODULES)]
        for path in paths:
            self.assertNotIn("az network vnet peering create", path.read_text(), path)

    def test_avnm_has_three_scopes_and_staged_firewall_routing_security_order(self):
        manager = (ROOT / "docs/03-avnm-connectivity.md").read_text()
        self.assertIn('networkManagerScopeAccesses:["Connectivity","SecurityAdmin","Routing"]', manager)
        module04 = (ROOT / "docs/04-connectivity-nsg.md").read_text()
        module05 = (ROOT / "docs/05-firewall.md").read_text()
        self.assertIn("routing-config", module04)
        self.assertIn("firewall", module04.lower())
        self.assertNotIn("vm-lzbegin-spokea", module04)
        self.assertIn("security-admin-config", module05)
        self.assertIn("lab-support.bicep", module05)
        self.assertIn("assert_avnm_routes_ready", module04)
        self.assertIn("assert_no_spoke_nat", module05)
        text = "\n".join((ROOT / relative).read_text() for relative in
                         ("README.md", "docs/01-prerequisites.md", "docs/03-avnm-connectivity.md"))
        self.assertNotIn("--connect-capabilities", text)
        self.assertNotIn("peeringEnforcement", text)
        self.assertNotIn("peering-enforcement", text)

    def test_peering_enforcement_is_staged_after_forwarding_in_module_04(self):
        module03 = (ROOT / "docs/03-avnm-connectivity.md").read_text()
        module04 = (ROOT / "docs/04-connectivity-nsg.md").read_text()
        self.assertNotIn("peeringEnforcement=Enforced", module03)
        positions = [module04.index(f"<!-- exec:forward-{local}-to-{remote} -->")
                     for local, remote in (("hub", "spokea"), ("spokea", "hub"),
                                           ("hub", "spokeb"), ("spokeb", "hub"))]
        enforcement = module04.index("<!-- exec:enforce-peering -->")
        commit = module04.index("<!-- exec:commit-enforced-connectivity -->")
        inspect = module04.index("<!-- exec:inspect-enforced-connectivity -->")
        routing = module04.index("<!-- exec:routing-config-create -->")
        self.assertEqual(positions, sorted(positions))
        self.assertLess(max(positions), enforcement)
        self.assertLess(enforcement, commit)
        self.assertLess(commit, inspect)
        self.assertLess(inspect, routing)

    def test_prerequisites_clone_the_standalone_workshop_repository(self):
        text = (ROOT / "docs/01-prerequisites.md").read_text()
        self.assertIn(
            'git clone https://github.com/jungwoonlee_microsoft/ms-landing-zone-02.git \\',
            text,
        )
        self.assertIn('cd "$HOME/ms-landing-zone-02"', text)
        self.assertNotIn("ms-security-landingzone-workshop01", text)
        self.assertNotIn("git clone https://github.com/jungwoonlee_microsoft/ms-landing-zone-01.git", text)
        self.assertNotIn("cd ms-landing-zone-01", text)
