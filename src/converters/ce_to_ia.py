import os
import re

from .base import BaseConverter
from src.migrators.ce_to_ia import CEToIAMigrator


class CEToIAConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.ia_config = {
            "info": {"namespace": self.namespace},
            "items": {},
            "equipments": {},
            "categories": {},
            "recipes": {},
            "loots": {}
        }
        self.ce_resourcepack_roots = []
        self.ia_resourcepack_root = None
        self._ce_data = {}

    def set_resource_paths(self, ce_roots, ia_root):
        self.ce_resourcepack_roots = []
        if isinstance(ce_roots, (list, tuple)):
            for path in ce_roots:
                if isinstance(path, str) and path.strip():
                    normalized = os.path.normpath(path)
                    if normalized not in self.ce_resourcepack_roots:
                        self.ce_resourcepack_roots.append(normalized)
        elif isinstance(ce_roots, str) and ce_roots.strip():
            self.ce_resourcepack_roots.append(os.path.normpath(ce_roots))
        self.ia_resourcepack_root = ia_root

    def convert(self, ce_data, namespace=None):
        if namespace:
            self.namespace = namespace

        self.ia_config = {
            "info": {"namespace": self.namespace},
            "items": {},
            "equipments": {},
            "categories": {},
            "recipes": {},
            "loots": {}
        }
        self._ce_data = ce_data if isinstance(ce_data, dict) else {}

        self._convert_equipments(self._ce_data.get("equipments", {}))
        self._convert_items(self._ce_data.get("items", {}))
        self._convert_categories(self._ce_data.get("categories", {}))
        self._convert_recipes(self._ce_data.get("recipes", {}))

        if not self.ia_config["categories"] and self.ia_config["items"]:
            self._generate_default_category()

        return self.ia_config

    def save_config(self, output_dir):
        os.makedirs(output_dir, exist_ok=True)

        armor_items = {}
        normal_items = {}
        for item_id, item_data in self.ia_config["items"].items():
            if isinstance(item_data, dict) and isinstance(item_data.get("equipment"), dict):
                armor_items[item_id] = item_data
            else:
                normal_items[item_id] = item_data

        if normal_items:
            self._write_yaml_with_footer(
                {"info": self.ia_config["info"], "items": normal_items},
                os.path.join(output_dir, f"{self.namespace}.yml")
            )

        if armor_items or self.ia_config["equipments"]:
            self._write_yaml_with_footer(
                {
                    "info": self.ia_config["info"],
                    "equipments": self.ia_config["equipments"],
                    "items": armor_items
                },
                os.path.join(output_dir, f"{self.namespace}_armor.yml")
            )

        if self.ia_config["categories"]:
            self._write_yaml_with_footer(
                {"info": self.ia_config["info"], "categories": self.ia_config["categories"]},
                os.path.join(output_dir, f"{self.namespace}_category.yml")
            )

        if self.ia_config["recipes"]:
            self._write_yaml_with_footer(
                {"info": self.ia_config["info"], "recipes": self.ia_config["recipes"]},
                os.path.join(output_dir, f"{self.namespace}_recipes.yml")
            )

        if self.ia_config["loots"]:
            self._write_yaml_with_footer(
                {"info": self.ia_config["info"], "loots": self.ia_config["loots"]},
                os.path.join(output_dir, f"{self.namespace}_loots.yml")
            )

        if self.ce_resourcepack_roots and self.ia_resourcepack_root:
            CEToIAMigrator(
                self.ce_resourcepack_roots,
                self.ia_resourcepack_root,
                self.namespace
            ).migrate()

    def _convert_items(self, items):
        if not isinstance(items, dict):
            return
        furniture_map = self._ce_data.get("furniture", {})
        if not isinstance(furniture_map, dict):
            furniture_map = {}
        block_map = self._ce_data.get("blocks", {})
        if not isinstance(block_map, dict):
            block_map = {}

        for raw_id, item_data in items.items():
            if not isinstance(item_data, dict):
                continue
            item_id = self._local_id(raw_id)
            ia_item = {}

            name = self._get_item_name(item_data, item_id)
            if name:
                ia_item["name"] = name

            lore = self._get_dict_value(self._get_dict_value(item_data, "data", default={}), "lore")
            if lore is not None:
                normalized_lore = self._normalize_lore(lore)
                if normalized_lore:
                    ia_item["lore"] = normalized_lore

            self._apply_resource(ia_item, item_data)
            self._apply_block(ia_item, item_data, raw_id, block_map)
            self._apply_equipment(ia_item, item_data)
            self._apply_furniture(ia_item, item_data, raw_id, furniture_map)

            if ia_item:
                self.ia_config["items"][item_id] = ia_item

    def _apply_resource(self, ia_item, item_data):
        material = self._get_dict_value(item_data, "material", default="PAPER")
        resource = {"material": str(material).upper()}

        custom_model_data = self._get_dict_value(item_data, "custom_model_data", "custom-model-data")
        if custom_model_data is not None:
            resource["model_id"] = custom_model_data

        texture = self._get_dict_value(item_data, "texture")
        textures = self._get_dict_value(item_data, "textures")
        model = self._get_dict_value(item_data, "model")
        models = self._get_dict_value(item_data, "models")

        texture_values = self._extract_texture_values(texture, textures)
        model_path = self._extract_model_path(model)
        if not model_path:
            model_path = self._extract_model_path(models)
        if not model_path:
            model_path = self._normalize_resource_path(
                self._get_dict_value(item_data, "item_model", "client_bound_model")
            )

        if texture_values:
            resource["generate"] = True
            resource["textures"] = texture_values
        elif model_path:
            resource["generate"] = False
            resource["model_path"] = model_path
        else:
            resource["generate"] = False

        ia_item["resource"] = resource

    def _apply_block(self, ia_item, item_data, raw_item_id, block_map):
        behavior = self._get_dict_value(item_data, "behavior", default={})
        if not isinstance(behavior, dict):
            return
        if self._get_dict_value(behavior, "type") != "block_item":
            return

        block_ref = self._get_dict_value(behavior, "block", default=raw_item_id)
        block_data = self._resolve_block_data(block_ref, raw_item_id, block_map)
        block_props = {
            "placed_model": {
                "type": self._ia_block_placed_model_type(block_data)
            }
        }

        settings = self._get_dict_value(block_data, "settings", default={})
        if isinstance(settings, dict):
            hardness = self._get_dict_value(settings, "hardness")
            if hardness is not None:
                block_props["hardness"] = hardness
            resistance = self._get_dict_value(settings, "resistance", "blast_resistance")
            if resistance is not None:
                block_props["blast_resistance"] = resistance
            luminance = self._get_dict_value(settings, "luminance", "light_level")
            if luminance is not None:
                block_props["light_level"] = luminance
            sounds = self._ce_sounds_to_ia(self._get_dict_value(settings, "sounds", default={}))
            if sounds:
                block_props["sound"] = sounds
            tools = self._ce_tags_to_ia_tools(self._get_dict_value(settings, "tags", default=[]))
            if tools:
                block_props["break_tools_whitelist"] = tools

        wrote_custom_loot = self._apply_block_loot(block_ref, raw_item_id, block_data)
        if wrote_custom_loot:
            block_props["cancel_drop"] = True
        else:
            block_props["drop_when_mined"] = True

        ia_item.setdefault("specific_properties", {})["block"] = block_props
        self._apply_block_resource(ia_item, block_data)

    def _resolve_block_data(self, block_ref, raw_item_id, block_map):
        if not isinstance(block_map, dict):
            return {}
        for candidate in (block_ref, raw_item_id):
            if isinstance(candidate, str) and candidate in block_map:
                data = block_map[candidate]
                return data if isinstance(data, dict) else {}
        wanted = self._local_id(block_ref or raw_item_id)
        for key, data in block_map.items():
            if self._local_id(key) == wanted:
                return data if isinstance(data, dict) else {}
        return {}

    def _ia_block_placed_model_type(self, block_data):
        state = self._get_dict_value(block_data, "state", default={})
        auto_state = ""
        if isinstance(state, dict):
            auto_state = str(self._get_dict_value(state, "auto_state", "auto-state", default="")).lower()
            if not auto_state:
                raw_state = str(self._get_dict_value(state, "state", default="")).lower()
                if "note_block" in raw_state or "note-block" in raw_state:
                    auto_state = "note_block"
                elif "mushroom" in raw_state:
                    auto_state = "mushroom"
                elif "chorus" in raw_state:
                    auto_state = "chorus"
                elif "tripwire" in raw_state:
                    auto_state = "tripwire"
        mapping = {
            "note_block": "REAL_NOTE",
            "note-block": "REAL_NOTE",
            "solid": "REAL",
            "mushroom": "REAL",
            "chorus": "REAL_TRANSPARENT",
            "tripwire": "REAL_WIRE"
        }
        return mapping.get(auto_state, "REAL_NOTE")

    def _ce_sounds_to_ia(self, sounds):
        result = {}
        if not isinstance(sounds, dict):
            return result
        for key in ("break", "place", "hit", "step", "fall"):
            value = self._get_dict_value(sounds, key)
            if isinstance(value, dict):
                sound = self._get_dict_value(value, "name", "sound", "id")
            else:
                sound = value
            if sound:
                result[key] = {"name": str(sound)}
        return result

    def _ce_tags_to_ia_tools(self, tags):
        if isinstance(tags, str):
            tags = [tags]
        if not isinstance(tags, list):
            return []
        joined = " ".join(str(tag).lower() for tag in tags)
        tools = []
        for token, tool in (
            ("mineable/pickaxe", "PICKAXE"),
            ("mineable/axe", "AXE"),
            ("mineable/shovel", "SHOVEL"),
            ("mineable/hoe", "HOE")
        ):
            if token in joined and tool not in tools:
                tools.append(tool)
        return tools

    def _apply_block_resource(self, ia_item, block_data):
        state = self._get_dict_value(block_data, "state", default={})
        if not isinstance(state, dict):
            return
        model_data = self._get_dict_value(state, "model", default={})
        if not isinstance(model_data, dict):
            return

        generation = self._get_dict_value(model_data, "generation", default={})
        textures = self._get_dict_value(generation, "textures", default={}) if isinstance(generation, dict) else {}
        texture_path = None
        if isinstance(textures, dict):
            for key in ("all", "side", "top", "bottom", "north", "south", "west", "east"):
                value = self._get_dict_value(textures, key)
                if value:
                    texture_path = self._normalize_ia_block_resource_path(value, suffix=".png")
                    break

        resource = ia_item.setdefault("resource", {})
        if texture_path:
            resource["generate"] = True
            resource["textures"] = [texture_path]
            resource.pop("model_path", None)
            return

        model_path = self._extract_model_path(model_data)
        if model_path:
            resource["generate"] = False
            resource["model_path"] = self._normalize_ia_block_resource_path(model_path)

    def _normalize_ia_block_resource_path(self, value, suffix=""):
        path = self._normalize_resource_path(value)
        if not path:
            return path
        for prefix in ("block/", "item/"):
            if path.startswith(prefix):
                path = path[len(prefix):]
        if suffix and not path.endswith(suffix):
            path = f"{path}{suffix}"
        return path

    def _apply_block_loot(self, block_ref, raw_item_id, block_data):
        loot = self._get_dict_value(block_data, "loot", default={})
        if not isinstance(loot, dict):
            return False
        pools = self._get_dict_value(loot, "pools", default=[])
        if not isinstance(pools, list):
            return False

        drops = []
        for pool in pools:
            if not isinstance(pool, dict):
                continue
            entries = self._get_dict_value(pool, "entries", default=[])
            drops.extend(self._extract_ia_loot_entries(entries))

        if not drops:
            return False

        block_item_ref = self._normalize_item_ref(block_ref or raw_item_id, keep_namespace=True)
        self_only = all(
            drop["item"] == block_item_ref and drop.get("min_amount", 1) == 1 and drop.get("max_amount", 1) == 1 and drop.get("chance", 100) == 100
            for drop in drops
        )
        if self_only:
            return False

        loot_key = self._local_id(block_ref or raw_item_id)
        loot_items = {}
        for drop in drops:
            item_key = self._local_id(drop["item"])
            loot_items[item_key] = drop

        self.ia_config.setdefault("loots", {}).setdefault("blocks", {})[loot_key] = {
            "type": block_item_ref,
            "items": loot_items
        }
        return True

    def _extract_ia_loot_entries(self, entries):
        result = []
        if not isinstance(entries, list):
            return result
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_type = str(self._get_dict_value(entry, "type", default="item")).lower()
            if entry_type in {"alternatives", "sequence", "group"}:
                children = self._get_dict_value(entry, "children", "entries", default=[])
                result.extend(self._extract_ia_loot_entries(children))
                continue
            if entry_type != "item":
                continue
            item = self._get_dict_value(entry, "item", "name", "id")
            if not item:
                continue
            drop = {
                "item": self._normalize_item_ref(item, keep_namespace=True),
                "min_amount": 1,
                "max_amount": 1,
                "chance": self._extract_entry_chance(entry)
            }
            min_amount, max_amount = self._extract_entry_count(entry)
            if min_amount is not None:
                drop["min_amount"] = min_amount
                drop["max_amount"] = max_amount
            result.append(drop)
        return result

    def _extract_entry_chance(self, entry):
        conditions = self._get_dict_value(entry, "conditions", default=[])
        if not isinstance(conditions, list):
            return 100
        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            condition_type = str(self._get_dict_value(condition, "type", default="")).lower()
            if condition_type == "random_chance":
                chance = self._get_dict_value(condition, "chance", "probability", default=1)
                try:
                    return int(round(float(chance) * 100))
                except (TypeError, ValueError):
                    return 100
        return 100

    def _extract_entry_count(self, entry):
        count = self._get_dict_value(entry, "count")
        if count is None:
            functions = self._get_dict_value(entry, "functions", default=[])
            if isinstance(functions, list):
                for function in functions:
                    if not isinstance(function, dict):
                        continue
                    if str(self._get_dict_value(function, "type", default="")).lower() == "set_count":
                        count = self._get_dict_value(function, "count")
                        break
        if count is None:
            return None, None
        if isinstance(count, str) and "~" in count:
            left, right = count.split("~", 1)
            try:
                return int(float(left)), int(float(right))
            except ValueError:
                return None, None
        try:
            amount = int(float(count))
            return amount, amount
        except (TypeError, ValueError):
            return None, None

    def _apply_equipment(self, ia_item, item_data):
        settings = self._get_dict_value(item_data, "settings", default={})
        if not isinstance(settings, dict):
            return
        equipment = self._get_dict_value(settings, "equipment", default={})
        if not isinstance(equipment, dict):
            return

        asset_id = self._get_dict_value(equipment, "asset_id", "asset-id")
        if not asset_id:
            return
        slot = self._normalize_slot(self._get_dict_value(equipment, "slot", default="head"))
        ia_item["equipment"] = {
            "id": self._normalize_item_ref(asset_id, keep_namespace=True),
            "slot": slot.upper()
        }

    def _apply_furniture(self, ia_item, item_data, raw_item_id, furniture_map):
        behavior = self._get_dict_value(item_data, "behavior", default={})
        if not isinstance(behavior, dict):
            return
        if self._get_dict_value(behavior, "type") != "furniture_item":
            return

        furniture_ref = self._get_dict_value(behavior, "furniture")
        furniture_data = {}
        if isinstance(furniture_ref, dict):
            furniture_data = furniture_ref
        elif isinstance(furniture_ref, str):
            furniture_data = furniture_map.get(furniture_ref, {})
        if not isinstance(furniture_data, dict):
            furniture_data = {}

        variants = self._get_dict_value(furniture_data, "variants", default={})
        if not isinstance(variants, dict):
            variants = {}

        ia_furniture = {
            "entity": "item_display",
            "placeable_on": {
                "floor": "ground" in variants or not variants,
                "walls": "wall" in variants,
                "ceiling": "ceiling" in variants
            }
        }

        hitbox = self._extract_furniture_hitbox(variants)
        if hitbox:
            ia_furniture["solid"] = hitbox.get("blocks_building", hitbox.get("blocks-building", True))
            ia_furniture["hitbox"] = {
                "width": hitbox.get("width", 1),
                "height": hitbox.get("height", 1),
                "length": hitbox.get("length", hitbox.get("width", 1)),
                "width_offset": 0,
                "height_offset": 0,
                "length_offset": 0
            }
            seats = hitbox.get("seats")
            if isinstance(seats, list) and seats:
                ia_item.setdefault("behaviours", {})["furniture_sit"] = {
                    "sit_height": self._infer_ia_sit_height(seats[0])
                }

        ia_item.setdefault("behaviours", {})["furniture"] = ia_furniture

        if not self._extract_model_path(self._get_dict_value(item_data, "model")):
            model_from_variant = self._extract_model_from_furniture(raw_item_id, variants)
            if model_from_variant:
                ia_item.setdefault("resource", {})["generate"] = False
                ia_item["resource"]["model_path"] = model_from_variant

    def _convert_equipments(self, equipments):
        if not isinstance(equipments, dict):
            return
        for raw_id, equipment_data in equipments.items():
            if not isinstance(equipment_data, dict):
                continue
            equipment_id = self._local_id(raw_id)
            layer_1 = self._normalize_equipment_layer(
                self._get_dict_value(equipment_data, "humanoid")
            )
            layer_2 = self._normalize_equipment_layer(
                self._get_dict_value(equipment_data, "humanoid_leggings", "humanoid-leggings")
            )
            entry = {}
            if layer_1:
                entry["layer_1"] = layer_1
            if layer_2:
                entry["layer_2"] = layer_2
            if entry:
                self.ia_config["equipments"][equipment_id] = entry

    def _convert_categories(self, categories):
        if not isinstance(categories, dict):
            return
        for raw_id, category_data in categories.items():
            if not isinstance(category_data, dict):
                continue
            category_id = self._local_id(raw_id)
            items = []
            raw_list = self._get_dict_value(category_data, "list", default=[])
            if isinstance(raw_list, list):
                for value in raw_list:
                    if isinstance(value, str) and not value.startswith("#"):
                        items.append(self._normalize_item_ref(value, keep_namespace=True))
            icon = self._normalize_item_ref(
                self._get_dict_value(category_data, "icon", default=items[0] if items else ""),
                keep_namespace=True
            )
            permission = self._extract_permission(category_data)
            entry = {
                "enabled": not bool(self._get_dict_value(category_data, "hidden", default=False)),
                "name": self._to_plain_text(str(self._get_dict_value(category_data, "name", default=category_id))),
                "icon": icon,
                "items": items
            }
            if permission:
                entry["permission"] = permission
            self.ia_config["categories"][category_id] = entry

    def _convert_recipes(self, recipes):
        if not isinstance(recipes, dict):
            return
        result = {}
        for raw_id, recipe_data in recipes.items():
            if not isinstance(recipe_data, dict):
                continue
            recipe_id = self._local_id(raw_id)
            recipe_type = str(self._get_dict_value(recipe_data, "type", default="shaped")).lower()
            if recipe_type in {"shaped", "shapeless"}:
                result.setdefault("crafting_table", {})[recipe_id] = self._convert_crafting_recipe(recipe_type, recipe_data)
            elif recipe_type in {"smelting", "blasting", "smoking", "campfire_cooking"}:
                result.setdefault("cooking", {})[recipe_id] = self._convert_cooking_recipe(recipe_type, recipe_data)
            elif recipe_type == "smithing_transform":
                result.setdefault("smithing", {})[recipe_id] = self._convert_smithing_recipe(recipe_data)
            elif recipe_type == "stonecutting":
                result.setdefault("stonecutting", {})[recipe_id] = self._convert_stonecutting_recipe(recipe_data)
            elif recipe_type == "brewing":
                result.setdefault("brewing", {})[recipe_id] = self._convert_brewing_recipe(recipe_data)
        self.ia_config["recipes"] = result

    def _convert_crafting_recipe(self, recipe_type, recipe_data):
        entry = {"enabled": True}
        if recipe_type == "shapeless":
            entry["shapeless"] = True
            ingredients = self._get_dict_value(recipe_data, "ingredients", default=[])
            if isinstance(ingredients, dict):
                entry["ingredients"] = [self._normalize_recipe_item(v) for v in ingredients.values()]
            elif isinstance(ingredients, list):
                entry["ingredients"] = [self._normalize_recipe_item(v) for v in ingredients]
        else:
            pattern = self._get_dict_value(recipe_data, "pattern", default=[])
            if pattern:
                entry["pattern"] = pattern
            ingredients = self._get_dict_value(recipe_data, "ingredients", default={})
            if isinstance(ingredients, dict):
                entry["ingredients"] = {k: self._normalize_recipe_item(v) for k, v in ingredients.items()}
        result = self._convert_recipe_result(self._get_dict_value(recipe_data, "result"))
        if result:
            entry["result"] = result
        return entry

    def _convert_cooking_recipe(self, recipe_type, recipe_data):
        machine_map = {
            "smelting": "furnace",
            "blasting": "blast_furnace",
            "smoking": "smoker",
            "campfire_cooking": "campfire"
        }
        entry = {
            "enabled": True,
            "machines": [machine_map.get(recipe_type, "furnace")]
        }
        ingredient = self._get_dict_value(recipe_data, "ingredient", "ingredients")
        if isinstance(ingredient, list):
            ingredient = ingredient[0] if ingredient else None
        if ingredient is not None:
            entry["ingredient"] = self._normalize_recipe_item(ingredient)
        result = self._convert_recipe_result(self._get_dict_value(recipe_data, "result"))
        if result:
            entry["result"] = result
        experience = self._get_dict_value(recipe_data, "experience")
        if experience is not None:
            entry["exp"] = experience
        time_value = self._get_dict_value(recipe_data, "time")
        if time_value is not None:
            entry["cook_time"] = time_value
        return entry

    def _convert_smithing_recipe(self, recipe_data):
        entry = {"enabled": True}
        for ce_key, ia_key in (("template", "template"), ("template-type", "template"), ("base", "base"), ("addition", "addition")):
            value = self._get_dict_value(recipe_data, ce_key)
            if value is not None and ia_key not in entry:
                entry[ia_key] = self._normalize_recipe_item(value)
        result = self._convert_recipe_result(self._get_dict_value(recipe_data, "result"))
        if result:
            entry["result"] = result
        return entry

    def _convert_stonecutting_recipe(self, recipe_data):
        entry = {"enabled": True}
        ingredient = self._get_dict_value(recipe_data, "ingredient", "ingredients")
        if isinstance(ingredient, list):
            ingredient = ingredient[0] if ingredient else None
        if ingredient is not None:
            entry["ingredient"] = self._normalize_recipe_item(ingredient)
        result = self._convert_recipe_result(self._get_dict_value(recipe_data, "result"))
        if result:
            entry["result"] = result
        return entry

    def _convert_brewing_recipe(self, recipe_data):
        entry = {"enabled": True}
        ingredient = self._get_dict_value(recipe_data, "ingredient")
        if ingredient is not None:
            entry["ingredient"] = self._normalize_recipe_item(ingredient)
        container = self._get_dict_value(recipe_data, "container")
        if container is not None:
            entry["container"] = self._normalize_recipe_item(container)
        result = self._convert_recipe_result(self._get_dict_value(recipe_data, "result"))
        if result:
            entry["result"] = result
        return entry

    def _convert_recipe_result(self, result):
        if result is None:
            return None
        if isinstance(result, dict):
            item_id = self._get_dict_value(result, "id", "item")
            amount = self._get_dict_value(result, "count", "amount", default=1)
        else:
            item_id = result
            amount = 1
        if item_id is None:
            return None
        return {
            "item": self._normalize_recipe_item(item_id),
            "amount": amount
        }

    def _extract_texture_values(self, texture, textures):
        values = []
        if isinstance(texture, str):
            values.append(texture)
        elif isinstance(texture, dict):
            values.extend(v for v in texture.values() if isinstance(v, str))
        if isinstance(textures, str):
            values.append(textures)
        elif isinstance(textures, list):
            values.extend(v for v in textures if isinstance(v, str))
        elif isinstance(textures, dict):
            for value in textures.values():
                if isinstance(value, str):
                    values.append(value)
                elif isinstance(value, dict):
                    values.extend(v for v in value.values() if isinstance(v, str))

        normalized = []
        seen = set()
        for value in values:
            path = self._normalize_texture_path(value)
            if path and path not in seen:
                seen.add(path)
                normalized.append(path)
        return normalized

    def _extract_model_path(self, model_value):
        if isinstance(model_value, str):
            return self._normalize_model_path(model_value)
        if isinstance(model_value, dict):
            path = self._get_dict_value(model_value, "path")
            if path:
                return self._normalize_model_path(path)
            for key in ("normal", "default", "model"):
                value = self._get_dict_value(model_value, key)
                if value:
                    return self._extract_model_path(value)
            for value in model_value.values():
                found = self._extract_model_path(value)
                if found:
                    return found
        return None

    def _extract_model_from_furniture(self, raw_item_id, variants):
        if not isinstance(variants, dict):
            return None
        for variant in variants.values():
            if not isinstance(variant, dict):
                continue
            elements = self._get_dict_value(variant, "elements", default=[])
            if not isinstance(elements, list):
                continue
            for element in elements:
                if not isinstance(element, dict):
                    continue
                if self._get_dict_value(element, "item") == raw_item_id:
                    return self._local_id(raw_item_id)
        return None

    def _extract_furniture_hitbox(self, variants):
        if not isinstance(variants, dict):
            return None
        for key in ("ground", "wall", "ceiling"):
            variant = variants.get(key)
            if not isinstance(variant, dict):
                continue
            hitboxes = self._get_dict_value(variant, "hitboxes", default=[])
            if isinstance(hitboxes, list) and hitboxes:
                for hitbox in hitboxes:
                    if isinstance(hitbox, dict):
                        return hitbox
        return None

    def _infer_ia_sit_height(self, seat):
        if not isinstance(seat, str):
            return 0.5
        try:
            parts = seat.split()[0].split(",")
            if len(parts) >= 2:
                return float(parts[1]) + 0.85
        except Exception:
            return 0.5
        return 0.5

    def _generate_default_category(self):
        item_ids = list(self.ia_config["items"].keys())
        if not item_ids:
            return
        namespaced_items = [f"{self.namespace}:{item_id}" for item_id in item_ids]
        self.ia_config["categories"][self.namespace] = {
            "enabled": True,
            "name": self.namespace,
            "icon": namespaced_items[0],
            "permission": f"ia.menu.{self.namespace}",
            "items": namespaced_items
        }

    def _get_item_name(self, item_data, fallback):
        data = self._get_dict_value(item_data, "data", default={})
        if not isinstance(data, dict):
            data = {}
        name = self._get_dict_value(data, "item_name", "item-name", "custom_name", "custom-name")
        if isinstance(name, str) and name.strip():
            return self._to_plain_text(name)
        return fallback

    def _extract_permission(self, category_data):
        conditions = self._get_dict_value(category_data, "conditions", default=[])
        if not isinstance(conditions, list):
            return None
        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            if self._get_dict_value(condition, "type") == "permission":
                permission = self._get_dict_value(condition, "permission")
                if permission:
                    return permission
        return None

    def _normalize_recipe_item(self, value):
        if isinstance(value, dict):
            item_id = self._get_dict_value(value, "id", "item")
            return self._normalize_recipe_item(item_id)
        if not isinstance(value, str):
            return value
        item = value.strip()
        if not item:
            return item
        if item.startswith("#"):
            return item
        if item.startswith("minecraft:"):
            return item
        return self._normalize_item_ref(item, keep_namespace=True)

    def _normalize_item_ref(self, value, keep_namespace=False):
        if not isinstance(value, str) or not value.strip():
            return value
        ref = value.strip()
        if ref.startswith("#"):
            return ref
        if ":" in ref:
            ns, key = ref.split(":", 1)
            if ns == "minecraft":
                return ref
            if keep_namespace:
                return f"{self.namespace}:{key}"
            return key
        return f"{self.namespace}:{ref}" if keep_namespace else ref

    def _normalize_texture_path(self, value):
        path = self._normalize_resource_path(value)
        if not path:
            return None
        if path.startswith("textures/"):
            path = path[len("textures/"):]
        return path

    def _normalize_model_path(self, value):
        path = self._normalize_resource_path(value)
        if not path:
            return None
        if path.startswith("models/"):
            path = path[len("models/"):]
        return path

    def _normalize_resource_path(self, value):
        if not isinstance(value, str) or not value.strip():
            return None
        path = value.strip().replace("\\", "/")
        if ":" in path:
            ns, rel = path.split(":", 1)
            path = rel if ns != "minecraft" else path
        path = path.strip("/")
        for suffix in (".json", ".png"):
            if path.endswith(suffix):
                path = path[:-len(suffix)]
        if path.startswith(f"{self.namespace}/"):
            path = path[len(self.namespace) + 1:]
        return path

    def _normalize_equipment_layer(self, value):
        path = self._normalize_texture_path(value)
        if not path:
            return None
        return path

    def _normalize_lore(self, value):
        if isinstance(value, list):
            return [self._to_plain_text(str(line)) for line in value]
        if isinstance(value, str):
            return [self._to_plain_text(value)]
        return None

    def _normalize_slot(self, value):
        slot = str(value).strip().lower()
        slot_map = {
            "helmet": "head",
            "head": "head",
            "chestplate": "chest",
            "chest": "chest",
            "leggings": "legs",
            "legs": "legs",
            "boots": "feet",
            "feet": "feet"
        }
        return slot_map.get(slot, slot or "head")

    def _local_id(self, raw_id):
        if not isinstance(raw_id, str):
            return str(raw_id)
        if ":" in raw_id:
            return raw_id.split(":", 1)[1]
        return raw_id

    def _to_plain_text(self, value):
        plain = re.sub(r"<[^>]+>", "", str(value))
        return plain.strip()

    def _get_dict_value(self, data, *keys, default=None):
        if not isinstance(data, dict):
            return default
        for key in keys:
            if key in data:
                return data[key]
        lowered = {}
        normalized = {}
        for key, value in data.items():
            if isinstance(key, str):
                lowered[key.lower()] = value
                normalized[key.lower().replace("-", "_")] = value
        for key in keys:
            if not isinstance(key, str):
                continue
            lowered_key = key.lower()
            if lowered_key in lowered:
                return lowered[lowered_key]
            normalized_key = lowered_key.replace("-", "_")
            if normalized_key in normalized:
                return normalized[normalized_key]
        return default
