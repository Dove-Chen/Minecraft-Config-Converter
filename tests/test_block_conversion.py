import json
import tempfile
import unittest
from pathlib import Path

from src.converters.ce_to_ia import CEToIAConverter
from src.converters.ia_to_ce import IAConverter


class BlockConversionTests(unittest.TestCase):
    def _itemsadder_block_pack(self):
        return {
            "info": {"namespace": "testores"},
            "items": {
                "ruby_ore": {
                    "display_name": "Ruby Ore",
                    "resource": {
                        "material": "PAPER",
                        "generate": True,
                        "textures": ["ores/ruby/ruby_ore.png"],
                    },
                    "specific_properties": {
                        "block": {
                            "cancel_drop": True,
                            "hardness": 8,
                            "light_level": 3,
                            "placed_model": {
                                "type": "REAL_NOTE",
                                "break_particles": "ITEM",
                            },
                            "sound": {
                                "break": {"name": "minecraft:block.stone.break"},
                                "place": {"name": "minecraft:block.stone.place"},
                            },
                        }
                    },
                },
                "raw_ruby": {
                    "display_name": "Raw Ruby",
                    "resource": {
                        "material": "PAPER",
                        "generate": True,
                        "textures": ["ores/ruby/raw_ruby.png"],
                    },
                },
            },
            "loots": {
                "blocks": {
                    "ruby_ore": {
                        "type": "testores:ruby_ore",
                        "items": {
                            "raw_ruby": {
                                "item": "testores:raw_ruby",
                                "min_amount": 1,
                                "max_amount": 2,
                                "chance": 100,
                            }
                        },
                    }
                }
            },
        }

    def test_itemsadder_block_to_craftengine_block(self):
        ia_data = self._itemsadder_block_pack()

        converter = IAConverter()
        converted = converter.convert(ia_data)
        item = converted["items"]["testores:ruby_ore"]
        block = converted["blocks"]["testores:ruby_ore"]

        self.assertEqual(item["behavior"], {"type": "block_item", "block": "testores:ruby_ore"})
        self.assertEqual(
            converter.generated_models["item/ruby_ore.json"],
            {"parent": "testores:block/ruby_ore"},
        )
        self.assertEqual(
            converter.generated_models["block/ruby_ore.json"],
            {
                "parent": "minecraft:block/cube_all",
                "textures": {"all": "testores:block/ores/ruby/ruby_ore"},
            },
        )
        self.assertEqual(block["settings"]["hardness"], 8)
        self.assertEqual(block["settings"]["luminance"], 3)
        self.assertEqual(block["state"]["state"], "note_block:1000")
        self.assertNotIn("auto_state", block["state"])
        self.assertEqual(
            block["state"]["model"]["generation"]["textures"]["all"],
            "testores:block/ores/ruby/ruby_ore",
        )
        entry = block["loot"]["pools"][0]["entries"][0]
        self.assertEqual(entry["item"], "testores:raw_ruby")
        self.assertEqual(entry["functions"][0]["count"], "1~2")

    def test_craftengine_block_config_is_saved_directly_under_configuration(self):
        converter = IAConverter()
        converter.convert(self._itemsadder_block_pack())

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = (
                Path(tmp)
                / "CraftEngine"
                / "resources"
                / "testores"
                / "configuration"
                / "items"
                / "testores"
            )
            converter.save_config(str(output_dir))

            package_root = Path(tmp) / "CraftEngine" / "resources" / "testores"
            self.assertTrue((package_root / "pack.yml").exists())
            self.assertTrue((package_root / "configuration" / "items.yml").exists())
            self.assertTrue((package_root / "configuration" / "blocks.yml").exists())
            self.assertFalse((package_root / "configuration" / "items").exists())
            self.assertFalse((package_root / "configuration" / "blocks").exists())

    def test_craftengine_block_to_itemsadder_block(self):
        ce_data = {
            "items": {
                "testores:ruby_ore": {
                    "material": "paper",
                    "data": {"item_name": "<!i>Ruby Ore"},
                    "behavior": {
                        "type": "block_item",
                        "block": "testores:ruby_ore",
                    },
                }
            },
            "blocks": {
                "testores:ruby_ore": {
                    "settings": {
                        "item": "testores:ruby_ore",
                        "hardness": 8,
                        "luminance": 3,
                        "sounds": {
                            "break": "minecraft:block.stone.break",
                            "place": "minecraft:block.stone.place",
                        },
                    },
                    "state": {
                        "state": "note_block:1000",
                        "model": {
                            "path": "testores:block/ruby_ore",
                            "generation": {
                                "parent": "minecraft:block/cube_all",
                                "textures": {
                                    "all": "testores:block/ores/ruby/ruby_ore"
                                },
                            },
                        },
                    },
                    "loot": {
                        "pools": [
                            {
                                "rolls": 1,
                                "entries": [
                                    {
                                        "type": "item",
                                        "item": "testores:raw_ruby",
                                        "functions": [
                                            {"type": "set_count", "count": "1~2"}
                                        ],
                                    }
                                ],
                            }
                        ]
                    },
                }
            },
        }

        converted = CEToIAConverter().convert(ce_data, namespace="testores")
        item = converted["items"]["ruby_ore"]
        block = item["specific_properties"]["block"]

        self.assertEqual(block["placed_model"]["type"], "REAL_NOTE")
        self.assertEqual(block["hardness"], 8)
        self.assertEqual(block["light_level"], 3)
        self.assertTrue(block["cancel_drop"])
        self.assertEqual(item["resource"]["textures"], ["ores/ruby/ruby_ore.png"])
        loot = converted["loots"]["blocks"]["ruby_ore"]["items"]["raw_ruby"]
        self.assertEqual(loot["item"], "testores:raw_ruby")
        self.assertEqual(loot["min_amount"], 1)
        self.assertEqual(loot["max_amount"], 2)

    def test_itemsadder_font_images_to_craftengine_images(self):
        ia_data = {
            "info": {"namespace": "testpack"},
            "font_images": {
                "blank_menu": {
                    "path": "gui/blank_menu.png",
                    "scale_ratio": 256,
                    "y_position": 13,
                }
            },
            "items": {
                "menu_item": {
                    "display_name": ":offset_-16::blank_menu:Menu Item",
                    "lore": ["%img_offset_4%%img_blank_menu%Lore"],
                    "resource": {"material": "PAPER"},
                }
            },
            "categories": {
                "shop": {
                    "enabled": True,
                    "name": ":offset_-16::blank_menu:Shop",
                    "items": ["testpack:menu_item"],
                }
            },
        }

        converter = IAConverter()
        converted = converter.convert(ia_data)

        self.assertEqual(
            converted["images"]["testpack:blank_menu"],
            {
                "file": "testpack:gui/blank_menu.png",
                "height": 256,
                "ascent": 13,
                "font": "minecraft:default",
            },
        )
        self.assertEqual(converter.font_image_texture_keys, {"gui/blank_menu"})
        self.assertEqual(
            converted["items"]["testpack:menu_item"]["data"]["item_name"],
            "<!i><white><shift:-16><image:testpack:blank_menu>Menu Item",
        )
        self.assertEqual(
            converted["items"]["testpack:menu_item"]["data"]["lore"],
            ["<shift:4><image:testpack:blank_menu>Lore"],
        )
        self.assertEqual(
            converted["categories"]["testpack:shop"]["name"],
            "<!i><shift:-16><image:testpack:blank_menu>Shop",
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = (
                Path(tmp)
                / "CraftEngine"
                / "resources"
                / "testpack"
                / "configuration"
                / "items"
                / "testpack"
            )
            converter.save_config(str(output_dir))
            self.assertTrue(
                (
                    Path(tmp)
                    / "CraftEngine"
                    / "resources"
                    / "testpack"
                    / "configuration"
                    / "images.yml"
                ).exists()
            )

    def test_craftengine_images_to_itemsadder_font_images(self):
        ce_data = {
            "images": {
                "testpack:blank_menu": {
                    "file": "testpack:gui/blank_menu.png",
                    "height": 256,
                    "ascent": 13,
                }
            },
            "items": {
                "testpack:menu_item": {
                    "material": "paper",
                    "data": {
                        "item_name": "<!i><white><shift:-16><image:testpack:blank_menu>Menu Item",
                        "lore": ["<shift:4><image:testpack:blank_menu>Lore"],
                    },
                }
            },
            "categories": {
                "testpack:shop": {
                    "name": "<shift:-16><image:testpack:blank_menu>Shop",
                    "icon": "testpack:menu_item",
                    "list": ["testpack:menu_item"],
                }
            },
        }

        converter = CEToIAConverter()
        converted = converter.convert(ce_data, namespace="testpack")

        self.assertEqual(
            converted["font_images"]["blank_menu"],
            {
                "path": "gui/blank_menu.png",
                "scale_ratio": 256,
                "y_position": 13,
            },
        )
        self.assertEqual(
            converted["items"]["menu_item"]["name"],
            ":offset_-16::blank_menu:Menu Item",
        )
        self.assertEqual(
            converted["items"]["menu_item"]["lore"],
            [":offset_4::blank_menu:Lore"],
        )
        self.assertEqual(
            converted["categories"]["shop"]["name"],
            ":offset_-16::blank_menu:Shop",
        )

        with tempfile.TemporaryDirectory() as tmp:
            converter.save_config(tmp)
            self.assertTrue((Path(tmp) / "testpack_font_images.yml").exists())

    def test_itemsadder_to_craftengine_resource_migration_copies_sounds(self):
        converter = IAConverter()
        with tempfile.TemporaryDirectory() as tmp:
            ia_pack = Path(tmp) / "ItemsAdder" / "contents" / "testpack" / "resourcepack"
            sounds_dir = ia_pack / "assets" / "testpack" / "sounds" / "magic"
            sounds_dir.mkdir(parents=True)
            (sounds_dir / "chime.ogg").write_bytes(b"ogg")
            (ia_pack / "assets" / "testpack" / "sounds.json").write_text(
                json.dumps({"magic.chime": {"sounds": ["magic/chime"]}}),
                encoding="utf-8",
            )

            output_items = Path(tmp) / "CraftEngine" / "configuration"
            output_pack = Path(tmp) / "CraftEngine" / "resourcepack"
            converter.set_resource_paths(str(ia_pack), str(output_pack))
            converter.convert(
                {
                    "info": {"namespace": "testpack"},
                    "items": {"ruby": {"resource": {"material": "PAPER"}}},
                }
            )
            converter.save_config(str(output_items))

            self.assertTrue(
                (output_pack / "assets" / "testpack" / "sounds" / "magic" / "chime.ogg").exists()
            )
            self.assertTrue((output_pack / "assets" / "testpack" / "sounds.json").exists())

    def test_itemsadder_to_craftengine_prefers_internal_key_style(self):
        converter = IAConverter()
        converted = converter.convert(
            {
                "info": {"namespace": "testpack"},
                "equipments": {
                    "ruby_armor": {
                        "layer_1": "armor/ruby_layer_1.png",
                        "layer_2": "armor/ruby_layer_2.png",
                    }
                },
                "items": {
                    "ruby_leggings": {
                        "display_name": "Ruby Leggings",
                        "resource": {
                            "material": "LEATHER_LEGGINGS",
                            "model_id": 42,
                            "textures": ["armor/ruby_leggings.png"],
                        },
                        "equipment": {"id": "ruby_armor", "slot": "legs"},
                    }
                },
            }
        )

        item = converted["items"]["testpack:ruby_leggings"]
        self.assertEqual(item["material"], "DIAMOND_LEGGINGS")
        self.assertEqual(item["data"]["item_name"], "<!i><white>Ruby Leggings")
        self.assertNotIn("item-name", item["data"])
        self.assertEqual(item["custom_model_data"], 42)
        self.assertNotIn("custom-model-data", item)
        self.assertEqual(item["settings"]["equipment"]["asset_id"], "testpack:ruby_armor")
        self.assertEqual(item["settings"]["equipment"]["slot"], "legs")
        self.assertNotIn("asset-id", item["settings"]["equipment"])
        self.assertIn("humanoid_leggings", converted["equipments"]["testpack:ruby_armor"])
        self.assertNotIn("humanoid-leggings", converted["equipments"]["testpack:ruby_armor"])

    def test_itemsadder_to_craftengine_can_fix_illegal_model_rotations(self):
        with tempfile.TemporaryDirectory() as tmp:
            ia_pack = Path(tmp) / "ItemsAdder" / "contents" / "testpack" / "resourcepack"
            model_dir = ia_pack / "assets" / "testpack" / "models" / "item"
            model_dir.mkdir(parents=True)
            (model_dir / "helmet.json").write_text(
                json.dumps(
                    {
                        "textures": {"0": "testpack:item/helmet"},
                        "elements": [
                            {
                                "from": [0, 0, 0],
                                "to": [1, 1, 1],
                                "rotation": {"angle": 17.5, "axis": "z", "origin": [0, 0, 0]},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            fixed_output = Path(tmp) / "fixed" / "resourcepack"
            converter = IAConverter()
            converter.set_fix_illegal_model_rotations(True)
            converter.set_resource_paths(str(ia_pack), str(fixed_output))
            converter.convert({"info": {"namespace": "testpack"}, "items": {"helmet": {"resource": {"material": "PAPER"}}}})
            converter.save_config(str(Path(tmp) / "fixed" / "configuration"))
            fixed_model = json.loads(
                (fixed_output / "assets" / "testpack" / "models" / "item" / "helmet.json").read_text(encoding="utf-8")
            )
            self.assertEqual(fixed_model["elements"][0]["rotation"]["angle"], 22.5)

            raw_output = Path(tmp) / "raw" / "resourcepack"
            converter = IAConverter()
            converter.set_resource_paths(str(ia_pack), str(raw_output))
            converter.convert({"info": {"namespace": "testpack"}, "items": {"helmet": {"resource": {"material": "PAPER"}}}})
            converter.save_config(str(Path(tmp) / "raw" / "configuration"))
            raw_model = json.loads(
                (raw_output / "assets" / "testpack" / "models" / "item" / "helmet.json").read_text(encoding="utf-8")
            )
            self.assertEqual(raw_model["elements"][0]["rotation"]["angle"], 17.5)


if __name__ == "__main__":
    unittest.main()
