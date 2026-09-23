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

    def test_avnm_scope_stays_connectivity_only(self):
        text = "\n".join(
            (ROOT / relative).read_text()
            for relative in [
                "README.md",
                "docs/01-prerequisites.md",
                "docs/03-avnm-connectivity.md",
            ]
        )
        self.assertNotIn("--scope-accesses Connectivity SecurityAdmin", text)
        self.assertNotIn("routing-config create", text)
        self.assertNotIn("security-admin-config create", text)
        self.assertNotIn("--connect-capabilities", text)
        self.assertNotIn("peeringEnforcement", text)
        self.assertNotIn("peering-enforcement", text)

    def test_prerequisites_clone_the_workshop_repository_into_land2_path(self):
        text = (ROOT / "docs/01-prerequisites.md").read_text()
        self.assertIn(
            'git clone https://github.com/jungwoonlee_microsoft/ms-security-landingzone-workshop01.git \\',
            text,
        )
        self.assertIn('cd "$HOME/ms-security-landingzone-workshop01/land2"', text)
        self.assertNotIn("git clone https://github.com/jungwoonlee_microsoft/ms-landing-zone-01.git", text)
        self.assertNotIn("cd ms-landing-zone-01", text)
