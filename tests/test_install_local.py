import importlib.util
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install_local", BASE / "scripts" / "install_local.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class InstallLocalTest(unittest.TestCase):
    def test_preview_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / ".agents" / "skills" / mod.NAME
            result = mod.install_one(BASE, target, apply=False)
            self.assertIn("dry-run", result)
            self.assertFalse(target.exists())

    def test_upgrade_backs_up_and_preserves_private_data(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            data = home / ".roadside-stall" / "wiki" / "example.json"
            data.parent.mkdir(parents=True)
            data.write_text("DO NOT TOUCH", encoding="utf-8")
            target = home / ".agents" / "skills" / mod.NAME
            mod.install_one(BASE, target, apply=True)
            self.assertTrue((target / "SKILL.md").exists())
            (target / "old_marker").write_text("previous", encoding="utf-8")
            mod.install_one(BASE, target, apply=True)
            backups = list(target.parent.glob(mod.NAME + ".backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / "old_marker").exists())
            self.assertEqual(data.read_text(encoding="utf-8"), "DO NOT TOUCH")

    def test_refuse_symlink_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / mod.NAME
            target.symlink_to(BASE, target_is_directory=True)
            with self.assertRaises(ValueError):
                mod.install_one(BASE, target, apply=True)


if __name__ == "__main__":
    unittest.main()
