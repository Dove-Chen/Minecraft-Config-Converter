import os
import re
from .base import BaseConverter, RecipeDumper
from src.migrators.nexo_to_ia import NexoToIAMigrator


class NexoToIAConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.ia_config = {
            "info": {"namespace": self.namespace},
            "items": {},
            "categories": {},
            "equipments": {},
            "recipes": {}
        }
        self.nexo_resourcepack_root = None
        self.nexo_resourcepack_roots = []
        self.ia_resourcepack_root = None
        self._armor_candidates = []

    def set_resource_paths(self, nexo_root, ia_root, additional_nexo_roots=None):
        self.nexo_resourcepack_root = nexo_root
        self.nexo_resourcepack_roots = []
        if isinstance(nexo_root, str) and nexo_root.strip():
            self.nexo_resourcepack_roots.append(os.path.normpath(nexo_root))
        # 兼容 external_packs 等额外资源根
        if isinstance(additional_nexo_roots, (list, tuple)):
            for path in additional_nexo_roots:
                if isinstance(path, str) and path.strip():
                    normalized = os.path.normpath(path)
                    if normalized not in self.nexo_resourcepack_roots:
                        self.nexo_resourcepack_roots.append(normalized)
        self.ia_resourcepack_root = ia_root

    def convert(self, nexo_data, namespace=None):
        if namespace:
            self.namespace = namespace

        self.ia_config["info"] = {"namespace": self.namespace}
        self.ia_config["items"] = {}
        self.ia_config["categories"] = {}
        self.ia_config["equipments"] = {}
        self.ia_config["recipes"] = {}
        self._armor_candidates = []

        if isinstance(nexo_data, dict):
            items_data = nexo_data.get("items")
            if isinstance(items_data, dict):
                self._convert_items(items_data)
            else:
                self._convert_items(
                    {
                        key: value
                        for key, value in nexo_data.items()
                        if key not in {"categories", "recipes"} and isinstance(value, dict)
                    }
                )
            self._convert_categories(nexo_data.get("categories", {}))
            self._convert_recipes(nexo_data.get("recipes", {}))

        self._finalize_armors()
        self._generate_default_category()
        return self.ia_config

    def _convert_items(self, items_data):
        if not isinstance(items_data, dict):
            return
        for key, value in items_data.items():
            if isinstance(value, dict):
                self._convert_item(key, value)

    def save_config(self, output_dir):
        os.makedirs(output_dir, exist_ok=True)

        armor_items = {}
        normal_items = {}
        for item_id, item_data in self.ia_config["items"].items():
            if isinstance(item_data, dict) and isinstance(item_data.get("equipment"), dict):
                armor_items[item_id] = item_data
            else:
                normal_items[item_id] = item_data

        items_data = {
            "info": self.ia_config["info"],
            "items": normal_items
        }
        if normal_items:
            self._write_yaml_with_footer(items_data, os.path.join(output_dir, f"{self.namespace}.yml"))

        if armor_items or self.ia_config["equipments"]:
            armor_data = {
                "info": self.ia_config["info"],
                "equipments": self.ia_config["equipments"],
                "items": armor_items
            }
            self._write_yaml_with_footer(armor_data, os.path.join(output_dir, f"{self.namespace}_armor.yml"))

        if self.ia_config["categories"]:
            categories_data = {
                "info": self.ia_config["info"],
                "categories": self.ia_config["categories"]
            }
            self._write_yaml_with_footer(categories_data, os.path.join(output_dir, f"{self.namespace}_category.yml"))

        if self.ia_config["recipes"]:
            recipes_data = {
                "info": self.ia_config["info"],
                "recipes": self.ia_config["recipes"]
            }
            self._write_yaml_with_footer(
                recipes_data,
                os.path.join(output_dir, f"{self.namespace}_recipes.yml"),
                dumper=RecipeDumper
            )

        if self.nexo_resourcepack_root and self.ia_resourcepack_root:
            migrator = NexoToIAMigrator(
                self.nexo_resourcepack_roots or self.nexo_resourcepack_root,
                self.ia_resourcepack_root,
                self.namespace
            )
            migrator.migrate()

    def _convert_item(self, key, data):
        ia_item = {}

        enabled = self._get_dict_value(data, "enabled")
        if enabled is not None:
            ia_item["enabled"] = bool(enabled)

        display_name = self._get_dict_value(data, "itemname", "customname")
        if isinstance(display_name, str) and display_name.strip():
            ia_item["display_name"] = self._to_plain_text(display_name)

        permission = self._get_dict_value(data, "permission")
        if isinstance(permission, str) and permission.strip():
            ia_item["permission"] = permission

        enchants = self._get_dict_value(data, "enchants", "enchantments")
        if enchants:
            ia_item["enchants"] = enchants

        self._apply_durability(ia_item, data)
        self._apply_attribute_modifiers(ia_item, data)
        self._apply_behaviours(ia_item, data)
        self._apply_resource(key, ia_item, data)

        if ia_item:
            self.ia_config["items"][key] = ia_item

    def _apply_durability(self, ia_item, data):
        mechanics = self._get_dict_value(data, "Mechanics", "mechanics", default={})
        if not isinstance(mechanics, dict):
            return
        durability = self._get_dict_value(mechanics, "durability", default={})
        if not isinstance(durability, dict):
            return
        value = self._get_dict_value(durability, "value", "amount")
        if isinstance(value, (int, float)):
            ia_item["durability"] = {"max_custom_durability": int(value)}

    def _apply_attribute_modifiers(self, ia_item, data):
        modifiers = self._get_dict_value(data, "AttributeModifiers", "attribute_modifiers")
        if not isinstance(modifiers, list):
            return

        result = {}
        for modifier in modifiers:
            if not isinstance(modifier, dict):
                continue
            slot = str(self._get_dict_value(modifier, "slot", default="")).strip().lower()
            amount = self._get_dict_value(modifier, "amount", "value")
            attribute = str(self._get_dict_value(modifier, "attribute", default="")).strip().lower()
            if not slot or amount is None:
                continue

            if attribute.startswith("generic_"):
                attribute = attribute[len("generic_"):]
            if attribute == "attack_damage":
                attribute = "attack-damage"
            elif attribute == "attack_speed":
                attribute = "attack-speed"

            slot_map = {
                "head": "head",
                "chest": "chest",
                "legs": "legs",
                "feet": "feet",
                "hand": "mainhand",
                "mainhand": "mainhand",
                "offhand": "offhand"
            }
            slot_key = slot_map.get(slot, slot)
            if slot_key not in result:
                result[slot_key] = {}
            result[slot_key][attribute or "armor"] = amount

        if result:
            ia_item["attribute_modifiers"] = result

    def _apply_behaviours(self, ia_item, data):
        mechanics = self._get_dict_value(data, "Mechanics", "mechanics", default={})
        if not isinstance(mechanics, dict):
            mechanics = {}

        components = self._get_dict_value(data, "Components", "components", default={})
        if not isinstance(components, dict):
            components = {}
        equippable = self._get_dict_value(components, "equippable", default={})
        if not isinstance(equippable, dict):
            equippable = {}

        behaviours = {}

        slot = str(self._get_dict_value(equippable, "slot", default="")).strip().upper()
        if slot == "HEAD":
            behaviours["hat"] = True

        furniture = self._get_dict_value(mechanics, "furniture", "Furniture", default={})
        if isinstance(furniture, dict) and furniture:
            ia_furniture = {}
            furniture_type = str(self._get_dict_value(furniture, "type", default="ITEM_FRAME")).lower()
            if "item_frame" in furniture_type:
                ia_furniture["entity"] = "item_frame"
            elif "armor_stand" in furniture_type:
                ia_furniture["entity"] = "armor_stand"
            else:
                ia_furniture["entity"] = "item_display"

            hitbox = self._get_dict_value(furniture, "hitbox", default={})
            barriers = []
            ia_hitbox = {}
            if isinstance(hitbox, dict):
                raw_barriers = self._get_dict_value(hitbox, "barriers", default=[])
                if isinstance(raw_barriers, list):
                    barriers = raw_barriers
                for key in ("width", "height", "length"):
                    value = self._get_dict_value(hitbox, key)
                    if value is not None:
                        ia_hitbox[key] = value
                offsets = self._barriers_to_hitbox_offsets(barriers)
                if offsets:
                    ia_hitbox.update(offsets)
            if ia_hitbox or barriers:
                ia_furniture["solid"] = bool(self._get_dict_value(furniture, "solid", default=True))
                ia_hitbox.setdefault("width", 1)
                ia_hitbox.setdefault("height", 1)
                ia_hitbox.setdefault("length", 1)
                ia_hitbox.setdefault("width_offset", 0)
                ia_hitbox.setdefault("height_offset", 0)
                ia_hitbox.setdefault("length_offset", 0)
                ia_furniture["hitbox"] = ia_hitbox

            restricted_rotation = str(self._get_dict_value(furniture, "restricted_rotation", default="")).upper()
            tracking_rotation = str(
                self._get_dict_value(
                    self._get_dict_value(furniture, "properties", default={}) if isinstance(self._get_dict_value(furniture, "properties", default={}), dict) else {},
                    "tracking_rotation",
                    default=""
                )
            ).upper()
            if restricted_rotation and restricted_rotation != "NONE":
                ia_furniture["fixed_rotation"] = True
            elif tracking_rotation in {"FIXED", "NONE"}:
                ia_furniture["fixed_rotation"] = True

            limited = self._get_dict_value(furniture, "limited_placing", default={})
            if isinstance(limited, dict):
                ia_furniture["placeable_on"] = {
                    "floor": bool(self._get_dict_value(limited, "floor", default=True)),
                    "ceiling": bool(self._get_dict_value(limited, "roof", "ceiling", default=False)),
                    "walls": bool(self._get_dict_value(limited, "wall", "walls", default=False))
                }

            light_level = self._get_dict_value(furniture, "light_level", "light-level")
            if light_level is not None:
                ia_furniture["light_level"] = light_level
            small = self._get_dict_value(furniture, "small")
            if small is not None:
                ia_furniture["small"] = small
            solid = self._get_dict_value(furniture, "solid")
            if solid is not None:
                ia_furniture["solid"] = solid

            properties = self._get_dict_value(furniture, "properties", default={})
            if isinstance(properties, dict):
                display_transformation = self._get_dict_value(
                    properties,
                    "display_transformation",
                    "display-transform",
                    "display_transform",
                )
                if display_transformation is not None:
                    ia_furniture["display_transformation"] = display_transformation

            seats = self._get_dict_value(furniture, "seats", default=[])
            if isinstance(seats, list) and seats:
                behaviours["furniture_sit"] = {
                    "sit_height": self._infer_ia_sit_height(seats[0])
                }

            behaviours["furniture"] = ia_furniture

        if behaviours:
            ia_item["behaviours"] = behaviours

    def _apply_resource(self, item_id, ia_item, data):
        material = self._get_dict_value(data, "material", default="PAPER")
        pack = self._get_dict_value(data, "Pack", "pack", default={})
        if not isinstance(pack, dict):
            pack = {}

        armor_slot = self._infer_armor_slot(data, material)
        if armor_slot:
            material = self._resolve_armor_material(armor_slot)
        resource = {"material": material}

        model_id = self._get_dict_value(data, "model", "custom_model_data", "custom-model-data")
        if isinstance(model_id, (int, float)):
            resource["model_id"] = int(model_id)

        generate_model = self._get_dict_value(pack, "generate_model", "generate")
        if isinstance(generate_model, bool):
            resource["generate"] = generate_model
        else:
            resource["generate"] = False

        model_path = self._normalize_model_path(self._get_dict_value(pack, "model"))
        if model_path:
            resource["model_path"] = model_path
        else:
            fallback_model = self._first_pack_state_model(pack)
            if fallback_model:
                resource["model_path"] = fallback_model
                resource["generate"] = False

        texture_value = self._get_dict_value(pack, "texture")
        textures = self._get_dict_value(pack, "textures")
        all_textures = []
        if isinstance(texture_value, str) and texture_value.strip():
            all_textures.append(texture_value)
        if isinstance(textures, list):
            all_textures.extend([x for x in textures if isinstance(x, str)])
        normalized = [self._normalize_texture_path(x) for x in all_textures if isinstance(x, str)]
        normalized = [x for x in normalized if isinstance(x, str) and x]
        deduplicated = []
        seen = set()
        for value in normalized:
            if value in seen:
                continue
            seen.add(value)
            deduplicated.append(value)
        if deduplicated:
            resource["textures"] = deduplicated

        if resource:
            ia_item["resource"] = resource

        custom_armor = self._get_dict_value(pack, "CustomArmor", "custom_armor", "customArmor", default={})
        if not isinstance(custom_armor, dict):
            custom_armor = {}
        equipment_id = self._normalize_equipment_id(
            self._get_dict_value(custom_armor, "id", "asset_id", "asset-id")
        )
        layer_1 = self._normalize_texture_path(self._get_dict_value(custom_armor, "layer1", "layer_1"))
        layer_2 = self._normalize_texture_path(self._get_dict_value(custom_armor, "layer2", "layer_2"))
        if armor_slot:
            self._armor_candidates.append({
                "item_id": item_id,
                "slot": armor_slot,
                "equipment_id": equipment_id,
                "layer_1": layer_1,
                "layer_2": layer_2
            })

    def _finalize_armors(self):
        armor_items = {}
        armor_sets = {}
        fallback_layer_votes = {}

        for candidate in self._armor_candidates:
            item_id = candidate.get("item_id")
            slot = candidate.get("slot")
            if not item_id or not slot:
                continue
            if item_id not in self.ia_config["items"]:
                continue
            equipment_id = candidate.get("equipment_id") or f"{self.namespace.replace('_', '')}armor"
            armor_items[item_id] = (slot, equipment_id)
            layer_1 = candidate.get("layer_1")
            layer_2 = candidate.get("layer_2")
            if layer_1 or layer_2:
                armor_sets.setdefault(equipment_id, {})
                if layer_1:
                    armor_sets[equipment_id]["layer_1"] = layer_1
                if layer_2:
                    armor_sets[equipment_id]["layer_2"] = layer_2
            if not candidate.get("equipment_id") and layer_1 and layer_2:
                pair = (layer_1, layer_2)
                fallback_layer_votes[pair] = fallback_layer_votes.get(pair, 0) + 1

        if not armor_items:
            self.ia_config["equipments"] = {}
            return

        fallback_id = f"{self.namespace.replace('_', '')}armor"
        if fallback_id not in armor_sets:
            layer_pair = None
            if fallback_layer_votes:
                layer_pair = max(fallback_layer_votes.items(), key=lambda x: x[1])[0]
            else:
                layer_pair = self._detect_armor_layers()
            if layer_pair:
                armor_sets[fallback_id] = {
                    "layer_1": layer_pair[0],
                    "layer_2": layer_pair[1]
                }

        self.ia_config["equipments"] = {
            equipment_id: layers
            for equipment_id, layers in armor_sets.items()
            if layers
        }

        for item_id, (slot, equipment_id) in armor_items.items():
            self.ia_config["items"][item_id]["equipment"] = {
                "id": equipment_id,
                "slot": slot.upper()
            }

    def _detect_armor_layers(self):
        if not self.nexo_resourcepack_root:
            return None
        layer_1 = None
        layer_2 = None
        for root in self._collect_texture_roots():
            if not os.path.isdir(root):
                continue
            for current_root, _, files in os.walk(root):
                for file_name in files:
                    lower_name = file_name.lower()
                    if not lower_name.endswith(".png"):
                        continue
                    rel_path = os.path.relpath(os.path.join(current_root, file_name), root).replace("\\", "/")
                    rel_path = rel_path[:-4]
                    normalized = self._normalize_equipment_layer_path(rel_path)
                    if lower_name.endswith("_armor_layer_1.png") or lower_name.endswith("armor_layer_1.png"):
                        layer_1 = normalized
                    elif lower_name.endswith("_armor_layer_2.png") or lower_name.endswith("armor_layer_2.png"):
                        layer_2 = normalized
            if layer_1 and layer_2:
                return layer_1, layer_2
        return None

    def _collect_texture_roots(self):
        roots = []
        base_roots = self.nexo_resourcepack_roots or ([self.nexo_resourcepack_root] if self.nexo_resourcepack_root else [])
        for base in base_roots:
            candidates = [
                os.path.join(base, "assets", "minecraft", "textures"),
                os.path.join(base, "assets", self.namespace, "textures"),
                os.path.join(base, "textures", self.namespace),
                os.path.join(base, "textures")
            ]
            for path in candidates:
                if os.path.isdir(path):
                    normalized = os.path.normpath(path)
                    if normalized not in roots:
                        roots.append(normalized)
        return roots

    def _infer_armor_slot(self, data, material):
        components = self._get_dict_value(data, "Components", "components", default={})
        if isinstance(components, dict):
            equippable = self._get_dict_value(components, "equippable", default={})
            if isinstance(equippable, dict):
                slot = str(self._get_dict_value(equippable, "slot", default="")).strip().lower()
                if slot in {"head", "chest", "legs", "feet"}:
                    return slot

        material_upper = str(material).upper()
        armor_by_material = {
            "LEATHER_HELMET": "head",
            "LEATHER_CHESTPLATE": "chest",
            "LEATHER_LEGGINGS": "legs",
            "LEATHER_BOOTS": "feet",
            "CHAINMAIL_HELMET": "head",
            "CHAINMAIL_CHESTPLATE": "chest",
            "CHAINMAIL_LEGGINGS": "legs",
            "CHAINMAIL_BOOTS": "feet",
            "IRON_HELMET": "head",
            "IRON_CHESTPLATE": "chest",
            "IRON_LEGGINGS": "legs",
            "IRON_BOOTS": "feet",
            "GOLDEN_HELMET": "head",
            "GOLDEN_CHESTPLATE": "chest",
            "GOLDEN_LEGGINGS": "legs",
            "GOLDEN_BOOTS": "feet",
            "DIAMOND_HELMET": "head",
            "DIAMOND_CHESTPLATE": "chest",
            "DIAMOND_LEGGINGS": "legs",
            "DIAMOND_BOOTS": "feet",
            "NETHERITE_HELMET": "head",
            "NETHERITE_CHESTPLATE": "chest",
            "NETHERITE_LEGGINGS": "legs",
            "NETHERITE_BOOTS": "feet"
        }
        return armor_by_material.get(material_upper)

    def _resolve_armor_material(self, slot):
        slot_map = {
            "head": "DIAMOND_HELMET",
            "chest": "DIAMOND_CHESTPLATE",
            "legs": "DIAMOND_LEGGINGS",
            "feet": "DIAMOND_BOOTS"
        }
        return slot_map.get(slot, "DIAMOND_HELMET")

    def _normalize_model_path(self, value):
        if not isinstance(value, str) or not value.strip():
            return None
        path = value.strip()
        if ":" in path:
            _, path = path.split(":", 1)
            path = path.strip()
        path = path.replace("\\", "/").strip("/")
        if path.endswith(".json"):
            path = path[:-5]
        if path.startswith(f"{self.namespace}/"):
            path = path[len(self.namespace) + 1:]
        return path

    def _normalize_texture_path(self, value):
        if not isinstance(value, str) or not value.strip():
            return None
        path = value.strip()
        if ":" in path:
            _, path = path.split(":", 1)
        path = path.replace("\\", "/").strip("/")
        if path.endswith(".png"):
            path = path[:-4]
        if path.startswith(f"{self.namespace}/"):
            path = path[len(self.namespace) + 1:]
        return path

    def _normalize_equipment_layer_path(self, rel_path):
        path = rel_path.replace("\\", "/").strip("/")
        if path.startswith(f"{self.namespace}/"):
            path = path[len(self.namespace) + 1:]
        return path

    def _normalize_equipment_id(self, value):
        if not isinstance(value, str) or not value.strip():
            return None
        ref = value.strip()
        if ":" in ref:
            _, ref = ref.split(":", 1)
        return ref

    def _first_pack_state_model(self, pack):
        for key in ("normal_model", "blocking_model", "cast_model", "charged_model", "firework_model"):
            value = self._get_dict_value(pack, key)
            normalized = self._normalize_model_path(value)
            if normalized:
                return normalized
        pulling = self._get_dict_value(pack, "pulling_models", default=[])
        if isinstance(pulling, list):
            for value in pulling:
                normalized = self._normalize_model_path(value)
                if normalized:
                    return normalized
        return None

    def _barriers_to_hitbox_offsets(self, barriers):
        if not barriers:
            return {}
        first = barriers[0]
        if not isinstance(first, str):
            return {}
        try:
            width_offset, height_offset, length_offset = [float(part) for part in first.split(",", 2)]
        except (TypeError, ValueError):
            return {}
        return {
            "width_offset": width_offset,
            "height_offset": height_offset,
            "length_offset": length_offset,
        }

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

    def _convert_categories(self, categories):
        if not isinstance(categories, dict):
            return
        for raw_id, category_data in categories.items():
            if not isinstance(category_data, dict):
                continue
            category_id = self._local_id(raw_id)
            raw_items = self._get_dict_value(category_data, "items", "list", default=[])
            items = []
            if isinstance(raw_items, list):
                for value in raw_items:
                    if isinstance(value, str) and not value.startswith("#"):
                        normalized = self._normalize_item_ref(value, keep_namespace=True)
                        if normalized not in items:
                            items.append(normalized)
            icon = self._normalize_item_ref(
                self._get_dict_value(category_data, "icon", default=items[0] if items else ""),
                keep_namespace=True,
            )
            entry = {
                "enabled": not bool(self._get_dict_value(category_data, "hidden", default=False)),
                "name": self._to_plain_text(str(self._get_dict_value(category_data, "name", default=category_id))),
                "icon": icon,
                "items": items,
            }
            permission = self._get_dict_value(category_data, "permission")
            if isinstance(permission, str) and permission.strip():
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
        pattern = self._get_dict_value(recipe_data, "pattern")
        if pattern and recipe_type == "shaped":
            entry["pattern"] = pattern
        ingredients = self._get_dict_value(recipe_data, "ingredients")
        if ingredients is not None:
            entry["ingredients"] = self._normalize_recipe_value(ingredients)
        result = self._convert_recipe_result(self._get_dict_value(recipe_data, "result"))
        if result:
            entry["result"] = result
        return entry

    def _convert_cooking_recipe(self, recipe_type, recipe_data):
        machine_map = {
            "smelting": "furnace",
            "blasting": "blast_furnace",
            "smoking": "smoker",
            "campfire_cooking": "campfire",
        }
        entry = {
            "enabled": True,
            "machines": [machine_map.get(recipe_type, "furnace")],
        }
        ingredient = self._get_dict_value(recipe_data, "ingredient", "ingredients")
        if isinstance(ingredient, list):
            ingredient = ingredient[0] if ingredient else None
        if ingredient is not None:
            entry["ingredient"] = self._normalize_recipe_value(ingredient)
        result = self._convert_recipe_result(self._get_dict_value(recipe_data, "result"))
        if result:
            entry["result"] = result
        experience = self._get_dict_value(recipe_data, "experience", "exp")
        if experience is not None:
            entry["exp"] = experience
        cook_time = self._get_dict_value(recipe_data, "time", "cook_time", "cookingTime")
        if cook_time is not None:
            entry["cook_time"] = cook_time
        return entry

    def _convert_smithing_recipe(self, recipe_data):
        entry = {"enabled": True}
        for nexo_key, ia_key in (("template-type", "template"), ("template", "template"), ("base", "base"), ("addition", "addition")):
            value = self._get_dict_value(recipe_data, nexo_key)
            if value is not None and ia_key not in entry:
                entry[ia_key] = self._normalize_recipe_value(value)
        result = self._convert_recipe_result(self._get_dict_value(recipe_data, "result"))
        if result:
            entry["result"] = result
        return entry

    def _convert_stonecutting_recipe(self, recipe_data):
        entry = {"enabled": True}
        ingredient = self._get_dict_value(recipe_data, "ingredient", "ingredients")
        if ingredient is not None:
            entry["ingredient"] = self._normalize_recipe_value(ingredient)
        result = self._convert_recipe_result(self._get_dict_value(recipe_data, "result"))
        if result:
            entry["result"] = result
        return entry

    def _convert_brewing_recipe(self, recipe_data):
        entry = {"enabled": True}
        for key in ("ingredient", "container"):
            value = self._get_dict_value(recipe_data, key)
            if value is not None:
                entry[key] = self._normalize_recipe_value(value)
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
            "item": self._normalize_recipe_value(item_id),
            "amount": amount,
        }

    def _normalize_recipe_value(self, value):
        if isinstance(value, dict):
            return {key: self._normalize_recipe_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._normalize_recipe_value(item) for item in value]
        if isinstance(value, str):
            return self._normalize_item_ref(value, keep_namespace=True) if self._looks_like_custom_item(value) else value
        return value

    def _generate_default_category(self):
        item_ids = list(self.ia_config["items"].keys())
        if self.ia_config["categories"]:
            return
        if not item_ids:
            self.ia_config["categories"] = {}
            return

        category_id = self.namespace
        namespaced_items = [f"{self.namespace}:{item_id}" for item_id in item_ids]
        self.ia_config["categories"] = {
            category_id: {
                "enabled": True,
                "name": category_id,
                "icon": namespaced_items[0],
                "permission": f"ia.menu.{category_id}",
                "items": namespaced_items
            }
        }

    def _to_plain_text(self, value):
        plain = re.sub(r"<[^>]+>", "", value)
        return plain.strip()

    def _normalize_item_ref(self, value, keep_namespace=False):
        if not isinstance(value, str) or not value.strip():
            return value
        ref = value.strip()
        if ref.startswith("#") or ref.startswith("minecraft:"):
            return ref
        if ":" in ref:
            _, item_id = ref.split(":", 1)
            return f"{self.namespace}:{item_id}" if keep_namespace else item_id
        return f"{self.namespace}:{ref}" if keep_namespace else ref

    def _looks_like_custom_item(self, value):
        if not isinstance(value, str):
            return False
        if value.startswith("#") or value.startswith("minecraft:"):
            return False
        return ":" in value or re.match(r"^[0-9a-z_.-]+$", value) is not None

    def _local_id(self, raw_id):
        if not isinstance(raw_id, str):
            return str(raw_id)
        if ":" in raw_id:
            return raw_id.split(":", 1)[1]
        return raw_id

    def _get_dict_value(self, data, *keys, default=None):
        if not isinstance(data, dict):
            return default
        for key in keys:
            if key in data:
                return data[key]
        lowered = {}
        for k, v in data.items():
            if isinstance(k, str):
                lowered[k.lower()] = v
        for key in keys:
            if isinstance(key, str):
                value = lowered.get(key.lower())
                if value is not None:
                    return value
        return default
