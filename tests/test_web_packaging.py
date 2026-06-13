import tempfile
import unittest
import zipfile
import json
from pathlib import Path

from web.app import (
    app,
    _build_output_filename,
    _convert_ia_to_ce,
    _convert_ia_to_nexo,
    _convert_ia_to_oraxen,
    _load_itemsadder_packages,
    _next_available_output_path,
)


class WebPackagingTests(unittest.TestCase):
    def _write_itemsadder_content(self, root, namespace):
        content_root = Path(root) / "ItemsAdder" / "contents" / namespace
        configs_dir = content_root / "configs"
        model_dir = content_root / "resourcepack" / "assets" / namespace / "models" / "item"
        texture_dir = content_root / "resourcepack" / "assets" / namespace / "textures" / "item"
        configs_dir.mkdir(parents=True)
        model_dir.mkdir(parents=True)
        texture_dir.mkdir(parents=True)

        item_id = f"{namespace}_gem"
        (configs_dir / "items.yml").write_text(
            f"""
info:
  namespace: {namespace}
items:
  {item_id}:
    display_name: {namespace.title()} Gem
    resource:
      material: PAPER
      model_path: item/{item_id}
recipes:
  crafting_table:
    {item_id}:
      enabled: true
      pattern:
        - " A "
      ingredients:
        A: STONE
      result:
        item: {namespace}:{item_id}
        amount: 1
""".lstrip(),
            encoding="utf-8",
        )
        (model_dir / f"{item_id}.json").write_text(
            (
                '{"parent":"minecraft:item/generated",'
                f'"textures":{{"layer0":"{namespace}:item/{item_id}"}}}}'
            ),
            encoding="utf-8",
        )
        (texture_dir / f"{item_id}.png").write_bytes(b"png")

    def _run_itemsadder_conversion(self, converter, target_format, form_data=None):
        original_output_folder = app.config["OUTPUT_FOLDER"]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            extract_dir = tmp_path / "extracted"
            upload_dir = tmp_path / "upload"
            session_output_dir = tmp_path / "session_output"
            download_dir = tmp_path / "downloads"
            upload_dir.mkdir()
            session_output_dir.mkdir()
            download_dir.mkdir()
            (upload_dir / "bundle.zip").touch()
            self._write_itemsadder_content(extract_dir, "alpha")
            self._write_itemsadder_content(extract_dir, "beta")

            try:
                app.config["OUTPUT_FOLDER"] = str(download_dir)
                with app.test_request_context("/api/convert", method="POST", data=form_data or {}):
                    response = converter(
                        str(extract_dir),
                        str(session_output_dir),
                        str(upload_dir),
                        target_format,
                    )
                data = response.get_json()
                output_name = data["download_url"].rsplit("/", 1)[-1]
                with zipfile.ZipFile(download_dir / output_name) as zip_file:
                    names = set(zip_file.namelist())
                    contents = {
                        name: zip_file.read(name).decode("utf-8", errors="ignore")
                        for name in names
                        if name.endswith((".yml", ".yaml"))
                    }
                return names, contents
            finally:
                app.config["OUTPUT_FOLDER"] = original_output_folder

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

    def test_itemsadder_loader_groups_contents_by_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_itemsadder_content(tmp, "alpha")
            self._write_itemsadder_content(tmp, "beta")

            packages = _load_itemsadder_packages(tmp)

            self.assertEqual([package["namespace"] for package in packages], ["alpha", "beta"])
            self.assertTrue(all(package["item_configs"] for package in packages))
            self.assertTrue(all(package["resourcepack_path"] for package in packages))

    def test_analyze_reports_itemsadder_batch_packages(self):
        original_upload_folder = app.config["UPLOAD_FOLDER"]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_dir = tmp_path / "source"
            upload_dir = tmp_path / "uploads"
            upload_dir.mkdir()
            self._write_itemsadder_content(source_dir, "alpha")
            self._write_itemsadder_content(source_dir, "beta")

            archive_path = tmp_path / "bundle.zip"
            with zipfile.ZipFile(archive_path, "w") as zip_file:
                for file_path in source_dir.rglob("*"):
                    if file_path.is_file():
                        zip_file.write(file_path, file_path.relative_to(source_dir))

            try:
                app.config["UPLOAD_FOLDER"] = str(upload_dir)
                with archive_path.open("rb") as f:
                    response = app.test_client().post(
                        "/api/analyze",
                        data={"file": (f, "bundle.zip")},
                        content_type="multipart/form-data",
                    )
                self.assertEqual(response.status_code, 200)
                report = response.get_json()["report"]
                self.assertTrue(report["batch_mode"])
                self.assertEqual(
                    [item["source_namespace"] for item in report["itemsadder_packages"]],
                    ["alpha", "beta"],
                )
            finally:
                app.config["UPLOAD_FOLDER"] = original_upload_folder

    def test_itemsadder_batch_to_craftengine_outputs_each_namespace(self):
        names, _ = self._run_itemsadder_conversion(_convert_ia_to_ce, "CraftEngine")

        self.assertIn(
            "CraftEngine/resources/alpha/configuration/items.yml",
            names,
        )
        self.assertIn(
            "CraftEngine/resources/beta/configuration/items.yml",
            names,
        )
        self.assertNotIn("CraftEngine/resources/alpha/configuration/items/", names)

    def test_itemsadder_batch_to_craftengine_uses_per_package_namespace_overrides(self):
        names, _ = self._run_itemsadder_conversion(
            _convert_ia_to_ce,
            "CraftEngine",
            form_data={
                "namespace_overrides": json.dumps(
                    {
                        "alpha": "alpha_custom",
                        "beta": "beta_custom",
                    }
                )
            },
        )

        self.assertIn(
            "CraftEngine/resources/alpha_custom/configuration/items.yml",
            names,
        )
        self.assertIn(
            "CraftEngine/resources/beta_custom/configuration/items.yml",
            names,
        )
        self.assertNotIn(
            "CraftEngine/resources/alpha/configuration/items.yml",
            names,
        )

    def test_itemsadder_batch_to_nexo_outputs_each_namespace(self):
        names, _ = self._run_itemsadder_conversion(_convert_ia_to_nexo, "Nexo")

        self.assertIn("Nexo/items/alpha.yml", names)
        self.assertIn("Nexo/items/beta.yml", names)
        self.assertIn("Nexo/pack/assets/alpha/models/item/alpha_gem.json", names)
        self.assertIn("Nexo/pack/assets/beta/models/item/beta_gem.json", names)

    def test_itemsadder_batch_to_oraxen_keeps_recipes_from_each_namespace(self):
        names, contents = self._run_itemsadder_conversion(_convert_ia_to_oraxen, "Oraxen")

        self.assertIn("Oraxen/items/alpha.yml", names)
        self.assertIn("Oraxen/items/beta.yml", names)
        shaped = contents["Oraxen/recipes/shaped.yml"]
        self.assertIn("alpha_gem", shaped)
        self.assertIn("beta_gem", shaped)


if __name__ == "__main__":
    unittest.main()
