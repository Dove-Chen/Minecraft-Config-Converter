import os
import re
from .base import BaseConverter, RecipeDumper
from src.migrators.oraxen_to_ia import OraxenToIAMigrator


class OraxenToIAConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.ia_config = {
            "info": {"namespace": self.namespace},
            "items": {},
            "categories": {},
            "equipments": {},
            "recipes": {}
        }
        self.oraxen_resourcepack_root = None
        self.ia_resourcepack_root = None
        self._armor_candidates = []

    def set_resource_paths(self, oraxen_root, ia_root):
        self.oraxen_resourcepack_root = oraxen_root
        self.ia_resourcepack_root = ia_root

    def convert(self, oraxen_data, namespace=None):
        if namespace:
            self.namespace = namespace

        self.ia_config["info"] = {"namespace": self.namespace}
        self.ia_config["items"] = {}
        self.ia_config["categories"] = {}
        self.ia_config["equipments"] = {}
        self.ia_config["recipes"] = {}
        self._armor_candidates = []

        if isinstance(oraxen_data, dict):
            items_data = oraxen_data.get("items")
            if isinstance(items_data, dict):
                for key, value in items_data.items():
                    if isinstance(value, dict):
                        self._convert_item(key, value)
            else:
                for key, value in oraxen_data.items():
                    if key in {"categories", "recipes"}:
                        continue
                    if isinstance(value, dict):
                        self._convert_item(key, value)
            self._convert_categories(oraxen_data.get("categories", {}))
            self._convert_recipes(oraxen_data.get("recipes", {}))

        self._finalize_armors()
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

        if self.oraxen_resourcepack_root and self.ia_resourcepack_root:
            migrator = OraxenToIAMigrator(
                self.oraxen_resourcepack_root,
                self.ia_resourcepack_root,
                self.namespace
            )
            migrator.migrate()

    def _convert_item(self, key, data):
        ia_item = {}

        display_name = data.get("displayname")
        if isinstance(display_name, str) and display_name.strip():
            ia_item["display_name"] = self._to_plain_text(display_name)

        permission = data.get("permission")
        if isinstance(permission, str) and permission.strip():
            ia_item["permission"] = permission

        self._apply_durability(ia_item, data)
        self._apply_attribute_modifiers(ia_item, data)
        self._apply_behaviours(ia_item, data)
        self._apply_resource(key, ia_item, data)

        if ia_item:
            self.ia_config["items"][key] = ia_item

    def _apply_durability(self, ia_item, data):
        mechanics = data.get("Mechanics", {})
        if not isinstance(mechanics, dict):
            return
        durability = mechanics.get("durability", {})
        if not isinstance(durability, dict):
            return
        value = durability.get("value")
        if isinstance(value, (int, float)):
            ia_item["durability"] = {"max_custom_durability": int(value)}

    def _apply_attribute_modifiers(self, ia_item, data):
        modifiers = data.get("AttributeModifiers")
        if not isinstance(modifiers, list):
            return

        result = {}
        for modifier in modifiers:
            if not isinstance(modifier, dict):
                continue
            slot = str(modifier.get("slot", "")).strip().lower()
            amount = modifier.get("amount")
            attribute = str(modifier.get("attribute", "")).strip().lower()
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
        mechanics = data.get("Mechanics", {})
        if not isinstance(mechanics, dict):
            mechanics = {}

        components = data.get("Components", data.get("components", {}))
        if not isinstance(components, dict):
            components = {}
        equippable = components.get("equippable", {})
        if not isinstance(equippable, dict):
            equippable = {}

        behaviours = {}

        slot = str(equippable.get("slot", "")).strip().lower()
        if slot == "head":
            behaviours["hat"] = True

        hat = mechanics.get("hat", {})
        if isinstance(hat, dict) and hat.get("enabled"):
            behaviours["hat"] = True

        furniture = mechanics.get("furniture", {})
        if isinstance(furniture, dict) and furniture:
            ia_furniture = {}
            entity_type = str(furniture.get("type", "ITEM_FRAME")).lower()
            if "item_frame" in entity_type:
                ia_furniture["entity"] = "item_frame"
            elif "armor_stand" in entity_type:
                ia_furniture["entity"] = "armor_stand"
            else:
                ia_furniture["entity"] = "item_display"

            if furniture.get("barrier") is True:
                ia_furniture["solid"] = True
                ia_furniture["hitbox"] = {
                    "width": 1,
                    "height": 1,
                    "length": 1,
                    "width_offset": 0,
                    "height_offset": 0,
                    "length_offset": 0
                }

            restricted_rotation = str(furniture.get("restricted_rotation", "")).upper()
            if restricted_rotation and restricted_rotation != "NONE":
                ia_furniture["fixed_rotation"] = True

            limited = furniture.get("limited_placing", {})
            if isinstance(limited, dict):
                ia_furniture["placeable_on"] = {
                    "floor": bool(limited.get("floor", True)),
                    "ceiling": bool(limited.get("roof", False)),
                    "walls": bool(limited.get("wall", limited.get("walls", False)))
                }

            behaviours["furniture"] = ia_furniture

        if behaviours:
            ia_item["behaviours"] = behaviours

    def _apply_resource(self, item_id, ia_item, data):
        material = data.get("material", "PAPER")
        pack = data.get("Pack", {})
        if not isinstance(pack, dict):
            pack = {}
        armor_slot = self._infer_armor_slot(data, material)

        if armor_slot:
            material = self._resolve_armor_material(armor_slot)
        resource = {"material": material}
        generate_model = pack.get("generate_model")
        if isinstance(generate_model, bool):
            resource["generate"] = generate_model
        else:
            resource["generate"] = False

        model_id = data.get("model")
        if model_id is None:
            model_id = data.get("custom_model_data", data.get("custom-model-data"))
        if isinstance(model_id, (int, float)):
            resource["model_id"] = int(model_id)

        model_path = self._normalize_model_path(pack.get("model"))
        if model_path:
            resource["model_path"] = model_path

        texture_values = []
        texture = pack.get("texture")
        if isinstance(texture, str):
            texture_values.append(texture)
        textures = pack.get("textures")
        if isinstance(textures, list):
            texture_values.extend([x for x in textures if isinstance(x, str)])
        elif isinstance(textures, dict):
            texture_values.extend([x for x in textures.values() if isinstance(x, str)])
        if texture_values:
            normalized = [self._normalize_texture_path(x) for x in texture_values if isinstance(x, str)]
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

        custom_armor = pack.get("CustomArmor", pack.get("custom_armor", pack.get("customArmor", {})))
        if not isinstance(custom_armor, dict):
            custom_armor = {}
        equipment_id = self._normalize_equipment_id(custom_armor.get("id") or custom_armor.get("asset_id"))
        layer_1 = self._normalize_texture_path(custom_armor.get("layer1") or custom_armor.get("layer_1"))
        layer_2 = self._normalize_texture_path(custom_armor.get("layer2") or custom_armor.get("layer_2"))

        if armor_slot:
            self._armor_candidates.append({
                "item_id": item_id,
                "slot": armor_slot,
                "equipment_id": equipment_id,
                "layer_1": layer_1,
                "layer_2": layer_2,
                "color": data.get("color"),
                "textures": pack.get("textures")
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
            if layer_pair and layer_pair[0] and layer_pair[1]:
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
        if not self.oraxen_resourcepack_root:
            return None, None

        for root in self._collect_texture_roots():
            if not os.path.isdir(root):
                continue
            layer_1 = None
            layer_2 = None
            for current_root, _, files in os.walk(root):
                for file_name in files:
                    lower_name = file_name.lower()
                    if not lower_name.endswith(".png"):
                        continue
                    rel_path = os.path.relpath(os.path.join(current_root, file_name), root).replace("\\", "/")
                    rel_path = rel_path[:-4]
                    if lower_name.endswith("_armor_layer_1.png") or lower_name.endswith("armor_layer_1.png"):
                        layer_1 = self._normalize_equipment_layer_path(rel_path)
                    elif lower_name.endswith("_armor_layer_2.png") or lower_name.endswith("armor_layer_2.png"):
                        layer_2 = self._normalize_equipment_layer_path(rel_path)
            if layer_1 and layer_2:
                return layer_1, layer_2
        return None, None

    def _collect_texture_roots(self):
        roots = []
        base = self.oraxen_resourcepack_root
        candidates = [
            os.path.join(base, "textures", self.namespace),
            os.path.join(base, "assets", self.namespace, "textures"),
            os.path.join(base, "textures"),
            os.path.join(base, "assets")
        ]
        for path in candidates:
            if os.path.isdir(path):
                normalized = os.path.normpath(path)
                if normalized not in roots:
                    roots.append(normalized)

        assets_root = os.path.join(base, "assets")
        if os.path.isdir(assets_root):
            for ns in os.listdir(assets_root):
                ns_textures = os.path.join(assets_root, ns, "textures")
                if os.path.isdir(ns_textures):
                    normalized = os.path.normpath(ns_textures)
                    if normalized not in roots:
                        roots.append(normalized)
        return roots

    def _get_primary_armor_color(self):
        for item in self._armor_candidates:
            value = item.get("color")
            if isinstance(value, str) and "," in value:
                parts = [x.strip() for x in value.split(",")]
                if len(parts) == 3 and all(p.isdigit() for p in parts):
                    r, g, b = [int(p) for p in parts]
                    return f"#{r:02x}{g:02x}{b:02x}"
        return None

    def _infer_armor_slot(self, data, material):
        components = data.get("Components", data.get("components", {}))
        if isinstance(components, dict):
            equippable = components.get("equippable", {})
            if isinstance(equippable, dict):
                slot = str(equippable.get("slot", "")).strip().lower()
                if slot in {"head", "chest", "legs", "feet"}:
                    return slot

        material_upper = str(material).upper()
        armor_by_material = {
            "LEATHER_HELMET": "head",
            "LEATHER_CHESTPLATE": "chest",
            "LEATHER_LEGGINGS": "legs",
            "LEATHER_BOOTS": "feet",
            "NETHERITE_HELMET": "head",
            "NETHERITE_CHESTPLATE": "chest",
            "NETHERITE_LEGGINGS": "legs",
            "NETHERITE_BOOTS": "feet",
            "DIAMOND_HELMET": "head",
            "DIAMOND_CHESTPLATE": "chest",
            "DIAMOND_LEGGINGS": "legs",
            "DIAMOND_BOOTS": "feet"
        }
        if material_upper in armor_by_material:
            return armor_by_material[material_upper]
        return None

    def _resolve_armor_material(self, slot):
        slot_map = {
            "head": "DIAMOND_HELMET",
            "chest": "DIAMOND_CHESTPLATE",
            "legs": "DIAMOND_LEGGINGS",
            "feet": "DIAMOND_BOOTS"
        }
        return slot_map.get(slot, "DIAMOND_HELMET")

    def _normalize_equipment_layer_path(self, rel_path):
        path = rel_path.replace("\\", "/").strip("/")
        if path.startswith(f"{self.namespace}/"):
            path = path[len(self.namespace) + 1:]
        return path

    def _generate_default_category(self):
        if self.ia_config["categories"]:
            return
        item_ids = list(self.ia_config["items"].keys())
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

    def _convert_categories(self, categories):
        if not isinstance(categories, dict):
            return
        for raw_id, category_data in categories.items():
            if not isinstance(category_data, dict):
                continue
            category_id = self._local_id(raw_id)
            raw_items = category_data.get("items", category_data.get("list", []))
            items = []
            if isinstance(raw_items, list):
                for value in raw_items:
                    if isinstance(value, str) and not value.startswith("#"):
                        normalized = self._normalize_item_ref(value, keep_namespace=True)
                        if normalized not in items:
                            items.append(normalized)
            icon = self._normalize_item_ref(category_data.get("icon", items[0] if items else ""), keep_namespace=True)
            entry = {
                "enabled": bool(category_data.get("enabled", True)),
                "name": self._to_plain_text(str(category_data.get("name", category_id))),
                "icon": icon,
                "items": items,
            }
            permission = category_data.get("permission")
            if isinstance(permission, str) and permission.strip():
                entry["permission"] = permission
            self.ia_config["categories"][category_id] = entry

    def _convert_recipes(self, recipes):
        if not isinstance(recipes, dict):
            return
        result = {}
        for group_key, group_data in recipes.items():
            if not isinstance(group_data, dict):
                continue
            group = str(group_key).lower()
            if self._looks_like_recipe_entry(group_data):
                recipe_id = self._local_id(group_key)
                recipe_type = str(group_data.get("type", "shaped")).lower()
                self._add_recipe_entry(result, recipe_type, recipe_id, group_data)
                continue
            for raw_id, recipe_data in group_data.items():
                if not isinstance(recipe_data, dict):
                    continue
                recipe_id = self._local_id(raw_id)
                recipe_type = str(recipe_data.get("type", group)).lower()
                self._add_recipe_entry(result, recipe_type, recipe_id, recipe_data)
        self.ia_config["recipes"] = result

    def _add_recipe_entry(self, result, recipe_type, recipe_id, recipe_data):
        recipe_type = {
            "crafting": "shaped",
            "furnace": "smelting",
            "blast_furnace": "blasting",
            "smoker": "smoking",
            "campfire": "campfire_cooking",
        }.get(recipe_type, recipe_type)

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

    def _convert_crafting_recipe(self, recipe_type, recipe_data):
        entry = {"enabled": True}
        if recipe_type == "shapeless":
            entry["shapeless"] = True
        pattern = recipe_data.get("pattern", recipe_data.get("shape"))
        if pattern and recipe_type == "shaped":
            entry["pattern"] = pattern
        ingredients = recipe_data.get("ingredients")
        if ingredients is not None:
            entry["ingredients"] = self._normalize_recipe_value(ingredients)
        result = self._convert_recipe_result(recipe_data.get("result"))
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
        ingredient = recipe_data.get("ingredient", recipe_data.get("ingredients"))
        if isinstance(ingredient, list):
            ingredient = ingredient[0] if ingredient else None
        if ingredient is not None:
            entry["ingredient"] = self._normalize_recipe_value(ingredient)
        result = self._convert_recipe_result(recipe_data.get("result"))
        if result:
            entry["result"] = result
        experience = recipe_data.get("experience", recipe_data.get("exp"))
        if experience is not None:
            entry["exp"] = experience
        cook_time = recipe_data.get("time", recipe_data.get("cook_time", recipe_data.get("cookingTime")))
        if cook_time is not None:
            entry["cook_time"] = cook_time
        return entry

    def _convert_smithing_recipe(self, recipe_data):
        entry = {"enabled": True}
        for oraxen_key, ia_key in (("template-type", "template"), ("template", "template"), ("base", "base"), ("addition", "addition")):
            value = recipe_data.get(oraxen_key)
            if value is not None and ia_key not in entry:
                entry[ia_key] = self._normalize_recipe_value(value)
        result = self._convert_recipe_result(recipe_data.get("result"))
        if result:
            entry["result"] = result
        return entry

    def _convert_stonecutting_recipe(self, recipe_data):
        entry = {"enabled": True}
        ingredient = recipe_data.get("ingredient", recipe_data.get("ingredients"))
        if ingredient is not None:
            entry["ingredient"] = self._normalize_recipe_value(ingredient)
        result = self._convert_recipe_result(recipe_data.get("result"))
        if result:
            entry["result"] = result
        return entry

    def _convert_brewing_recipe(self, recipe_data):
        entry = {"enabled": True}
        for key in ("ingredient", "container"):
            value = recipe_data.get(key)
            if value is not None:
                entry[key] = self._normalize_recipe_value(value)
        result = self._convert_recipe_result(recipe_data.get("result"))
        if result:
            entry["result"] = result
        return entry

    def _convert_recipe_result(self, result):
        if result is None:
            return None
        if isinstance(result, dict):
            item_id = result.get("item", result.get("id"))
            amount = result.get("amount", result.get("count", 1))
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
            return self._normalize_recipe_item_ref(value)
        return value

    def _normalize_recipe_item_ref(self, value):
        if not isinstance(value, str) or not value.strip():
            return value
        ref = value.strip()
        if ref.startswith("#"):
            return ref
        if re.match(r"^[A-Z0-9_]+$", ref):
            return ref
        if ":" in ref:
            namespace, item_id = ref.split(":", 1)
            if namespace == "minecraft":
                return f"minecraft:{item_id.lower()}"
            return f"{self.namespace}:{item_id}"
        return f"{self.namespace}:{ref}"

    def _looks_like_recipe_entry(self, value):
        if not isinstance(value, dict):
            return False
        return any(key in value for key in ("result", "ingredients", "ingredient", "shape", "pattern"))

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

    def _local_id(self, raw_id):
        if not isinstance(raw_id, str):
            return str(raw_id)
        if ":" in raw_id:
            return raw_id.split(":", 1)[1]
        return raw_id

    def _normalize_equipment_id(self, value):
        if not isinstance(value, str) or not value.strip():
            return None
        ref = value.strip()
        if ":" in ref:
            _, ref = ref.split(":", 1)
        return ref

    def _normalize_model_path(self, value):
        if not isinstance(value, str) or not value.strip():
            return None
        path = value.strip()
        if ":" in path:
            _, path = path.split(":", 1)
            path = path.strip()
        path = path.replace("\\", "/").strip("/")
        if path.startswith(f"{self.namespace}/"):
            path = path[len(self.namespace) + 1:]
        return path

    def _normalize_texture_path(self, value):
        if not isinstance(value, str):
            return value
        path = value.strip()
        if ":" in path:
            path = path.split(":", 1)[1]
        path = path.replace("\\", "/").strip("/")
        if path.startswith(f"{self.namespace}/"):
            path = path[len(self.namespace) + 1:]
        return path

    def _to_plain_text(self, value):
        plain = re.sub(r"<[^>]+>", "", value)
        return plain.strip()
