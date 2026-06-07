import tempfile
import unittest
from pathlib import Path

from web.app import app, _build_output_filename, _next_available_output_path


class WebPackagingTests(unittest.TestCase):
    def test_output_filename_uses_original_archive_name_and_mcc_marker(self):
        output_name = _build_output_filename(
            "Exile Studio - Ore Pack vol.1 v1.1",
            "CraftEngine",
        )

        self.assertEqual(
            output_name,
            "Exile_Studio_-_Ore_Pack_vol.1_v1.1_CraftEngine_by_MCC.zip",
        )
        self.assertNotIn("ca0cafe8", output_name)

    def test_duplicate_output_filename_gets_numeric_suffix(self):
        original_output_folder = app.config["OUTPUT_FOLDER"]
        with tempfile.TemporaryDirectory() as tmp:
            try:
                app.config["OUTPUT_FOLDER"] = tmp
                existing_name = "Ore_Pack_CraftEngine_by_MCC.zip"
                (Path(tmp) / existing_name).touch()

                output_name, output_path = _next_available_output_path(existing_name)

                self.assertEqual(output_name, "Ore_Pack_CraftEngine_by_MCC_2.zip")
                self.assertEqual(Path(output_path).name, output_name)
            finally:
                app.config["OUTPUT_FOLDER"] = original_output_folder


if __name__ == "__main__":
    unittest.main()
