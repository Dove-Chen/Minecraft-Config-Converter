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

    def test_craftengine_block_config_is_saved_under_blocks_directory(self):
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
            self.assertTrue(
                (package_root / "configuration" / "items" / "testores" / "items.yml").exists()
            )
            self.assertTrue(
                (package_root / "configuration" / "blocks" / "testores" / "blocks.yml").exists()
            )
            self.assertFalse(
                (package_root / "configuration" / "items" / "testores" / "blocks.yml").exists()
            )

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


if __name__ == "__main__":
    unittest.main()
