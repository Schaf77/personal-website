"""Exercise actual GPG exports without touching the user's keyring or site data."""

import importlib.util
import html
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/publish-key.py"
SPEC = importlib.util.spec_from_file_location("publish_key", SCRIPT)
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


@unittest.skipUnless(shutil.which("gpg"), "GnuPG is required")
class PublishKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="site-key-tests-")
        cls.home = str(Path(cls.temp.name) / "gnupg")
        Path(cls.home).mkdir(mode=0o700)
        cls.gpg("--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key",
                "Template Test <hello@example.org>", "ed25519", "sign", "1d")
        records = cls.gpg("--with-colons", "--list-keys").decode().splitlines()
        cls.fingerprint = next(line.split(":")[9] for line in records if line.startswith("fpr:"))
        cls.gpg("--quick-add-uid", cls.fingerprint, "Another Identity <other@example.org>")
        cls.gpg("--pinentry-mode", "loopback", "--passphrase", "", "--quick-add-key",
                cls.fingerprint, "cv25519", "encr", "1d")
        cls.public = Path(cls.temp.name) / "public.asc"
        cls.public.write_bytes(cls.gpg("--armor", "--export", cls.fingerprint))

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--homedir", cls.home, "--kill", "all"], capture_output=True)
        cls.temp.cleanup()

    @classmethod
    def gpg(cls, *args):
        return publisher.run_gpg(cls.home, *args)

    def setUp(self):
        self.site = tempfile.TemporaryDirectory(prefix="site-output-tests-")
        self.addCleanup(self.site.cleanup)
        self.root = Path(self.site.name)
        (self.root / "data").mkdir()
        (self.root / "data/pgp.json").write_text('{"keys": []}\n')

    def test_hash_matches_gnupg(self):
        self.assertEqual(publisher.wkd_hash("HELLO"), "im4cc8qhazwkfsi65a8us1bc5gzk1o4p")
        if shutil.which("gpg-wks-client"):
            actual = subprocess.check_output(["gpg-wks-client", "--print-wkd-hash", "hello@example.org"]).decode().split()[0]
            self.assertEqual(publisher.wkd_hash("hello"), actual)

    def test_download_wkd_and_metadata(self):
        entry = publisher.prepare("HELLO@example.org", self.public, self.root)
        self.assertEqual(entry["fingerprint"], self.fingerprint)
        download = self.root / "static" / entry["download"].lstrip("/")
        self.assertTrue(download.read_bytes().startswith(b"-----BEGIN PGP PUBLIC KEY BLOCK-----"))
        wkd = self.root / ".wellknowndir/.well-known/openpgpkey"
        self.assertEqual((wkd / "policy").read_bytes(), b"")
        binary_file = wkd / "hu" / entry["hash"]
        self.assertFalse(binary_file.read_bytes().startswith(b"-----BEGIN"))
        listing = self.gpg("--with-colons", "--show-keys", str(binary_file)).decode()
        self.assertIn(self.fingerprint, listing)
        self.assertIn("hello@example.org", listing)
        self.assertNotIn("other@example.org", listing)
        self.assertIn("sub:", listing)  # The encryption subkey must survive filtering.
        self.assertFalse(any(line.startswith(("sec:", "ssb:")) for line in listing.splitlines()))
        self.assertEqual(json.loads((self.root / "data/pgp.json").read_text())["keys"], [entry])

    def test_add_mailbox_and_update_without_duplicate(self):
        publisher.prepare("hello@example.org", self.public, self.root)
        publisher.prepare("other@example.org", self.public, self.root)
        publisher.prepare("hello@example.org", self.public, self.root)
        entries = json.loads((self.root / "data/pgp.json").read_text())["keys"]
        self.assertEqual([item["email"] for item in entries], ["hello@example.org", "other@example.org"])

    def test_missing_identity_leaves_site_untouched(self):
        with self.assertRaises(ValueError):
            publisher.prepare("missing@example.org", self.public, self.root)
        self.assertEqual(json.loads((self.root / "data/pgp.json").read_text()), {"keys": []})
        self.assertFalse((self.root / "static").exists())
        self.assertFalse((self.root / ".wellknowndir").exists())

    def test_rejects_secret_key(self):
        secret = self.root / "secret.asc"
        secret.write_bytes(self.gpg("--pinentry-mode", "loopback", "--passphrase", "", "--armor", "--export-secret-keys", self.fingerprint))
        with self.assertRaisesRegex(ValueError, "PUBLIC key"):
            publisher.prepare("hello@example.org", secret, self.root)

    def test_rejects_second_domain_before_publication(self):
        publisher.prepare("hello@example.org", self.public, self.root)
        before = (self.root / "data/pgp.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "one email domain"):
            publisher.prepare("hello@example.net", self.public, self.root)
        self.assertEqual((self.root / "data/pgp.json").read_bytes(), before)

    def test_rejects_invalid_mailbox(self):
        for email in ["../hello@example.org", "hello", "hello@example.org && revoked=0", "hello@../", "hello@..org", "..hello@example.org"]:
            with self.subTest(email=email), self.assertRaises(ValueError):
                publisher.prepare(email, self.public, self.root)

    @unittest.skipUnless(shutil.which("hugo"), "Hugo is required")
    def test_hugo_publishes_download_key_page_and_hidden_wkd(self):
        source = SCRIPT.parents[1]
        for name in ["layouts", "assets", "content", "static", "data"]:
            if (source / name).is_dir():
                shutil.copytree(source / name, self.root / name, dirs_exist_ok=True)
        shutil.copy2(source / "hugo.toml", self.root / "hugo.toml")
        # Keep the fixture independent of the owner's published email domain.
        (self.root / "data/pgp.json").write_text('{"keys": []}\n')
        entry = publisher.prepare("hello@example.org", self.public, self.root)
        build = subprocess.run(
            ["hugo", "--source", str(self.root), "--themesDir", str(source / "themes"), "--panicOnWarning", "--minify"],
            capture_output=True, text=True,
        )
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        output = self.root / "public"
        self.assertEqual((output / ".well-known/openpgpkey/policy").read_bytes(), b"")
        self.assertGreater((output / ".well-known/openpgpkey/hu" / entry["hash"]).stat().st_size, 0)
        self.assertTrue((output / entry["download"].lstrip("/")).is_file())
        page = (output / "keys/index.html").read_text()
        self.assertIn(f'href="{entry["download"]}"', page)
        self.assertIn('download rel="pgpkey">', page)
        self.assertNotIn("hello@example.org", page)
        self.assertIn("hello@example.org", html.unescape(page))
        self.assertIn(" ".join(self.fingerprint[i:i+4] for i in range(0, len(self.fingerprint), 4)), page)
        self.assertNotIn("No public keys published yet", page)
        home = (output / "index.html").read_text()
        for css in ["vars", "syntax", "main", "nav"]:
            self.assertIn(f'href="/css/{css}.css"', home)
            self.assertIn(f'href="/css/{css}.css"', page)
        self.assertNotIn('class="hero"', home)
        for path in ["index.xml", "tags", "categories"]:
            self.assertFalse((output / path).exists())


if __name__ == "__main__":
    unittest.main()
