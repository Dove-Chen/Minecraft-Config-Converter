import os
import re

from .base import BaseConverter, RecipeDumper
from src.migrators.ia_to_nexo import IAToNexoMigrator


class IAToNexoConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.nexo_config = {
            "items": {},
            "categories": {},
            "recipes": {},
        }
        self.ia_resourcepack_root = None
        self.nexo_pack_root = None
        self._ia_data = {}

    def set_resource_paths(self, ia_root, nexo_pack_root):
        self.ia_resourcepack_root = ia_root
        self.nexo_pack_root = nexo_pack_root

    def convert(self, ia_data, namespace=None):
        if namespace:
            self.namespace = namespace
        elif isinstance(ia_data, dict):
            info = ia_data.get("info", {})
            if isinstance(info, dict) and info.get("namespace"):
                self.namespace = info["namespace"]

        self.nexo_config = {
            "items": {},
            "categories": {},
            "recipes": {},
        }
        self._ia_data = ia_data if isinstance(ia_data, dict) else {}

        self._convert_items(self._ia_data.get("items", {}))
        self._convert_categories(self._ia_data.get("categories", {}))
        self._convert_recipes(self._ia_data.get("recipes", {}))

        return self.nexo_config

    def save_config(self, output_dir):
        os.makedirs(output_dir, exist_ok=True)

        if self.nexo_config["items"]:
            self._write_yaml_with_footer(
                self.nexo_config["items"],
                os.path.join(output_dir, f"{self.namespace}.yml"),
            )

        if self.nexo_config["categories"]:
            self._write_yaml_with_footer(
                {"categories": self.nexo_config["categories"]},
                os.path.join(output_dir, f"{self.namespace}_categories.yml"),
            )

        if self.nexo_config["recipes"]:
            self._write_yaml_with_footer(
                {"recipes": self.nexo_config["recipes"]},
                os.path.join(output_dir, f"{self.namespace}_recipes.yml"),
                dumper=RecipeDumper,
            )

        if self.ia_resourcepack_root and self.nexo_pack_root:
            IAToNexoMigrator(
                self.ia_resourcepack_root,
                self.nexo_pack_root,
                self.namespace,
            ).migrate()

    def _convert_items(self, items):
        if not isinstance(items, dict):
            return
        for raw_id, item_data in items.items():
            if not isinstance(item_data, dict):
                continue
            item_id = self._local_id(raw_id)
            nexo_item = self._convert_item(item_id, item_data)
            if nexo_item:
                self.nexo_config["items"][item_id] = nexo_item

    def _convert_item(self, item_id, item_data):
        resource = self._build_resource_data(item_data)
        material = str(resource.get("material", "PAPER")).upper()
        slot = self._extract_equipment_slot(item_data, material)
        if slot and not self._is_armor_material(material):
            material = self._armor_material_for_slot(slot)

        nexo_item = {"material": material}

        enabled = self._get_dict_value(item_data, "enabled")
        if enabled is not None:
            nexo_item["enabled"] = bool(enabled)

        name = self._get_item_name(item_data)
        if name:
            nexo_item["itemname"] = name

        lore = self._normalize_lore(self._get_dict_value(item_data, "lore"))
        if lore:
            nexo_item["lore"] = lore

        permission = self._get_dict_value(item_data, "permission")
        if not permission:
            permission = self._get_dict_value(item_data, "permission_suffix", "permission-suffix")
        if isinstance(permission, str) and permission.strip():
            nexo_item["permission"] = permission

        enchants = self._get_dict_value(item_data, "enchants", "enchantments")
        if enchants:
            nexo_item["enchants"] = enchants

        model_id = self._get_dict_value(resource, "model_id", "custom_model_data", "custom-model-data")
        if model_id is not None:
            nexo_item["model"] = model_id

        self._apply_pack(nexo_item, resource, item_data, slot)
        self._apply_components(nexo_item, item_data, slot)
        self._apply_mechanics(nexo_item, item_data)
        self._apply_attribute_modifiers(nexo_item, item_data)
        self._apply_durability(nexo_item, item_data)

        return nexo_item

    def _build_resource_data(self, item_data):
        resource = {}
        raw_resource = self._get_dict_value(item_data, "resource", default={})
        if isinstance(raw_resource, dict):
            resource.update(raw_resource)

        material = self._get_dict_value(item_data, "material")
        if material and "material" not in resource:
            resource["material"] = material

        graphics = self._get_dict_value(item_data, "graphics", default={})
        if isinstance(graphics, dict):
            texture = self._get_dict_value(graphics, "texture")
            model = self._get_dict_value(graphics, "model")
            textures = self._get_dict_value(graphics, "textures")
            # ItemsAdder 4.x graphics is the newer resource description, so it wins
            # over legacy texture/model paths while keeping legacy model_id/material.
            if texture:
                resource["textures"] = [texture] if isinstance(texture, str) else texture
                resource["generate"] = True
            if textures:
                resource["textures"] = textures
                resource["generate"] = True
            if model:
                resource["model_path"] = model
                resource["generate"] = False

        resource.setdefault("material", "PAPER")
        return resource

    def _apply_pack(self, nexo_item, resource, item_data, slot):
        pack = {}

        generate = self._get_dict_value(resource, "generate")
        if isinstance(generate, bool):
            pack["generate_model"] = generate

        model_path = self._normalize_resource_path(
            self._get_dict_value(resource, "model_path", "model")
        )
        if model_path:
            pack["model"] = self._to_resource_ref(model_path)

        texture_map = self._extract_texture_map(resource)
        textures = self._extract_texture_values(resource)
        normal_texture = texture_map.get("normal") or texture_map.get("default")
        if normal_texture:
            pack["texture"] = self._to_resource_ref(normal_texture, suffix_to_strip=".png")
        elif len(textures) == 1:
            pack["texture"] = textures[0]
        elif len(textures) > 1:
            pack["textures"] = textures
        self._apply_pack_state_models(pack, resource, str(nexo_item.get("material", "")).upper())

        custom_armor = self._build_custom_armor(item_data, slot)
        if custom_armor:
            pack["CustomArmor"] = custom_armor

        if pack:
            nexo_item["Pack"] = pack

    def _apply_components(self, nexo_item, item_data, slot):
        behaviours = self._get_dict_value(item_data, "behaviours", "behaviors", default={})
        if not isinstance(behaviours, dict):
            behaviours = {}

        explicit_slot = slot
        if not explicit_slot and behaviours.get("hat"):
            explicit_slot = "head"

        if explicit_slot:
            nexo_item.setdefault("Components", {}).setdefault("equippable", {})["slot"] = explicit_slot

    def _apply_mechanics(self, nexo_item, item_data):
        behaviours = self._get_dict_value(item_data, "behaviours", "behaviors", default={})
        if not isinstance(behaviours, dict):
            return

        mechanics = {}
        furniture = self._get_dict_value(behaviours, "furniture", default={})
        if isinstance(furniture, dict) and furniture:
            mechanics["furniture"] = self._convert_furniture(furniture, behaviours)

        if behaviours.get("hat"):
            mechanics.setdefault("hat", {})["enabled"] = True

        if mechanics:
            nexo_item["Mechanics"] = mechanics

    def _apply_attribute_modifiers(self, nexo_item, item_data):
        raw_modifiers = self._get_dict_value(item_data, "attribute_modifiers", "attribute-modifiers")
        if not isinstance(raw_modifiers, dict):
            return

        result = []
        for slot, attributes in raw_modifiers.items():
            if not isinstance(attributes, dict):
                continue
            for attribute, amount in attributes.items():
                if amount is None:
                    continue
                result.append(
                    {
                        "slot": self._normalize_modifier_slot(slot),
                        "attribute": self._normalize_attribute_name(attribute),
                        "amount": amount,
                    }
                )

        if result:
            nexo_item["AttributeModifiers"] = result

    def _apply_durability(self, nexo_item, item_data):
        durability = self._get_dict_value(item_data, "durability", default={})
        if not isinstance(durability, dict):
            return
        value = self._get_dict_value(
            durability,
            "max_custom_durability",
            "max-custom-durability",
            "durability",
            "value",
        )
        if value is not None:
            nexo_item.setdefault("Mechanics", {}).setdefault("durability", {})["value"] = value

    def _build_custom_armor(self, item_data, slot):
        equipment = self._get_dict_value(item_data, "equipment", default={})
        if not isinstance(equipment, dict):
            equipment = {}

        specific = self._get_dict_value(item_data, "specific_properties", "specific-properties", default={})
        armor_props = {}
        if isinstance(specific, dict):
            armor_props = self._get_dict_value(specific, "armor", default={})
            if not isinstance(armor_props, dict):
                armor_props = {}

        raw_id = self._get_dict_value(equipment, "id")
        if not raw_id:
            raw_id = self._get_dict_value(armor_props, "custom_armor", "custom-armor")
        if not raw_id and not slot:
            return {}

        custom_armor = {}
        if raw_id:
            custom_armor["id"] = self._normalize_item_ref(raw_id, keep_namespace=True)
            equipment_data = self._resolve_equipment_data(raw_id)
            layer_1 = self._get_dict_value(equipment_data, "layer_1", "layer1")
            layer_2 = self._get_dict_value(equipment_data, "layer_2", "layer2")
            if layer_1:
                custom_armor["layer1"] = self._to_resource_ref(layer_1, suffix_to_strip=".png")
            if layer_2:
                custom_armor["layer2"] = self._to_resource_ref(layer_2, suffix_to_strip=".png")

        return custom_armor

    def _convert_furniture(self, furniture, behaviours):
        entity = str(self._get_dict_value(furniture, "entity", default="item_display")).lower()
        if "item_frame" in entity:
            furniture_type = "ITEM_FRAME"
        elif "armor_stand" in entity:
            furniture_type = "ARMOR_STAND"
        else:
            furniture_type = "ITEM_DISPLAY"

        result = {"type": furniture_type}

        placeable_on = self._get_dict_value(furniture, "placeable_on", "placeable-on", default={})
        if isinstance(placeable_on, dict):
            result["limited_placing"] = {
                "floor": bool(self._get_dict_value(placeable_on, "floor", default=True)),
                "wall": bool(self._get_dict_value(placeable_on, "walls", "wall", default=False)),
                "roof": bool(self._get_dict_value(placeable_on, "ceiling", "roof", default=False)),
            }

        hitbox = self._get_dict_value(furniture, "hitbox", default={})
        if isinstance(hitbox, dict) and hitbox:
            converted_hitbox = {}
            for key in ("width", "height", "length"):
                value = self._get_dict_value(hitbox, key)
                if value is not None:
                    converted_hitbox[key] = value
            barriers = self._hitbox_offsets_to_barriers(hitbox)
            if barriers:
                converted_hitbox["barriers"] = barriers
            if converted_hitbox:
                result["hitbox"] = converted_hitbox

        sit = self._get_dict_value(behaviours, "furniture_sit", "furniture-sit", default={})
        if isinstance(sit, dict):
            sit_height = self._get_dict_value(sit, "sit_height", "sit-height")
            if sit_height is not None:
                try:
                    seat_y = float(sit_height) - 0.85
                except (TypeError, ValueError):
                    seat_y = 0
                result["seats"] = [f"0,{seat_y:g},0"]

        if self._get_dict_value(furniture, "fixed_rotation", "fixed-rotation"):
            result["restricted_rotation"] = "STRICT"

        for source_key, target_key in (
            ("light_level", "light_level"),
            ("light-level", "light_level"),
            ("small", "small"),
            ("solid", "solid"),
        ):
            value = self._get_dict_value(furniture, source_key)
            if value is not None:
                result[target_key] = value

        display_transformation = self._get_dict_value(
            furniture,
            "display_transformation",
            "display-transformation",
            "display_transform",
            "display-transform",
        )
        if display_transformation is not None:
            result.setdefault("properties", {})["display_transformation"] = display_transformation

        return result

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
                    for expanded in self._expand_category_item_ref(value):
                        if expanded not in items:
                            items.append(expanded)

            icon = self._normalize_item_ref(
                self._get_dict_value(category_data, "icon", default=items[0] if items else ""),
                keep_namespace=True,
            )
            entry = {
                "name": str(self._get_dict_value(category_data, "name", default=category_id)),
                "icon": icon,
                "items": items,
            }
            permission = self._get_dict_value(category_data, "permission")
            if isinstance(permission, str) and permission.strip():
                entry["permission"] = permission
            self.nexo_config["categories"][category_id] = entry

    def _convert_recipes(self, recipes):
        if not isinstance(recipes, dict):
            return

        for group_key, group_data in recipes.items():
            if not isinstance(group_data, dict):
                continue
            group = str(group_key).lower()
            for raw_id, recipe_data in group_data.items():
                if not isinstance(recipe_data, dict) or recipe_data.get("enabled") is False:
                    continue
                for recipe_id, converted in self._convert_recipe_entry(group, raw_id, recipe_data):
                    if converted:
                        self.nexo_config["recipes"][recipe_id] = converted

    def _convert_recipe_entry(self, group, raw_id, recipe_data):
        recipe_id = self._local_id(raw_id)
        if group == "crafting_table":
            recipe_type = "shapeless" if self._get_dict_value(recipe_data, "shapeless") else "shaped"
            patterns = self._extract_recipe_patterns(recipe_data)
            if recipe_type == "shapeless" or not patterns:
                patterns = [("", None)]
            for suffix, pattern in patterns:
                entry = {"type": recipe_type}
                if pattern and recipe_type == "shaped":
                    entry["pattern"] = pattern
                ingredients = self._get_dict_value(recipe_data, "ingredients")
                if ingredients is not None:
                    entry["ingredients"] = self._normalize_recipe_value(ingredients)
                result = self._convert_recipe_result(self._get_dict_value(recipe_data, "result"))
                if result:
                    entry["result"] = result
                yield f"{recipe_id}{suffix}", entry
            return

        if group == "cooking":
            machines = self._get_dict_value(recipe_data, "machines", default=["furnace"])
            if isinstance(machines, str):
                machines = [machines]
            if not isinstance(machines, list) or not machines:
                machines = ["furnace"]
            for machine in machines:
                recipe_type = self._map_cooking_machine(machine)
                entry = {"type": recipe_type}
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
                    entry["experience"] = experience
                cook_time = self._get_dict_value(recipe_data, "time", "cook_time", "cookingTime")
                if cook_time is not None:
                    entry["time"] = cook_time
                suffix = "" if len(machines) == 1 else f"_{recipe_type}"
                yield f"{recipe_id}{suffix}", entry
            return

        type_map = {
            "smithing": "smithing_transform",
            "stonecutting": "stonecutting",
            "brewing": "brewing",
        }
        recipe_type = type_map.get(group)
        if not recipe_type:
            return

        entry = {"type": recipe_type}
        for key in ("template", "template-type", "base", "addition", "ingredient", "container"):
            value = self._get_dict_value(recipe_data, key)
            if value is not None:
                output_key = "template-type" if key == "template" and recipe_type == "smithing_transform" else key
                entry[output_key] = self._normalize_recipe_value(value)
        result = self._convert_recipe_result(self._get_dict_value(recipe_data, "result"))
        if result:
            entry["result"] = result
        yield recipe_id, entry

    def _convert_recipe_result(self, result):
        if result is None:
            return None
        if isinstance(result, dict):
            item_id = self._get_dict_value(result, "item", "id")
            amount = self._get_dict_value(result, "amount", "count", default=1)
        else:
            item_id = result
            amount = 1
        if item_id is None:
            return None
        converted = {"id": self._normalize_recipe_value(item_id)}
        if amount is not None:
            converted["count"] = amount
        return converted

    def _normalize_recipe_value(self, value):
        if isinstance(value, dict):
            return {k: self._normalize_recipe_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._normalize_recipe_value(v) for v in value]
        if isinstance(value, str):
            return self._normalize_recipe_item_ref(value)
        return value

    def _extract_recipe_patterns(self, recipe_data):
        patterns = []
        base_pattern = self._get_dict_value(recipe_data, "pattern")
        if base_pattern:
            patterns.append(("", base_pattern))
        numbered = []
        for key, value in recipe_data.items():
            if not isinstance(key, str):
                continue
            match = re.match(r"^pattern[_-](\d+)$", key)
            if match and value:
                numbered.append((int(match.group(1)), f"_{match.group(1)}", value))
        for _, suffix, value in sorted(numbered):
            patterns.append((suffix, value))
        return patterns

    def _resolve_equipment_data(self, raw_id):
        local_id = self._local_id(raw_id)
        for section_name in ("equipments", "armors_rendering", "legacy_armor_renderings"):
            section = self._ia_data.get(section_name, {})
            if not isinstance(section, dict):
                continue
            for candidate in (raw_id, local_id, self._normalize_item_ref(raw_id, keep_namespace=True)):
                data = section.get(candidate)
                if isinstance(data, dict):
                    return data
            for key, data in section.items():
                if self._local_id(key) == local_id and isinstance(data, dict):
                    return data
        return {}

    def _extract_equipment_slot(self, item_data, material):
        equipment = self._get_dict_value(item_data, "equipment", default={})
        if isinstance(equipment, dict):
            slot = self._normalize_slot(self._get_dict_value(equipment, "slot"))
            if slot:
                return slot

        specific = self._get_dict_value(item_data, "specific_properties", "specific-properties", default={})
        if isinstance(specific, dict):
            armor = self._get_dict_value(specific, "armor", default={})
            if isinstance(armor, dict):
                slot = self._normalize_slot(self._get_dict_value(armor, "slot"))
                if slot:
                    return slot
                if self._get_dict_value(armor, "custom_armor", "custom-armor"):
                    return self._slot_from_material(material) or "head"

        return self._slot_from_material(material)

    def _extract_texture_values(self, resource):
        values = []
        for key in ("texture", "textures"):
            value = self._get_dict_value(resource, key)
            self._collect_string_values(value, values)

        normalized = []
        seen = set()
        for value in values:
            path = self._normalize_resource_path(value, suffix_to_strip=".png")
            if not path:
                continue
            ref = self._to_resource_ref(path, suffix_to_strip=".png")
            if ref and ref not in seen:
                seen.add(ref)
                normalized.append(ref)
        return normalized

    def _collect_string_values(self, value, output):
        if isinstance(value, str):
            output.append(value)
        elif isinstance(value, list):
            for item in value:
                self._collect_string_values(item, output)
        elif isinstance(value, dict):
            for item in value.values():
                self._collect_string_values(item, output)

    def _apply_pack_state_models(self, pack, resource, material):
        texture_map = self._extract_texture_map(resource)
        if not texture_map:
            return

        normal = texture_map.get("normal") or texture_map.get("default")
        if normal and "model" not in pack:
            pack["model"] = self._to_resource_ref(normal, suffix_to_strip=".png")

        if material == "BOW":
            pulling = [texture_map.get(f"pulling_{index}") for index in range(3)]
            pulling = [self._to_resource_ref(value, suffix_to_strip=".png") for value in pulling if value]
            if pulling:
                pack["pulling_models"] = pulling
        elif material == "CROSSBOW":
            pulling = [texture_map.get(f"pulling_{index}") for index in range(3)]
            pulling = [self._to_resource_ref(value, suffix_to_strip=".png") for value in pulling if value]
            if pulling:
                pack["pulling_models"] = pulling
            arrow = texture_map.get("arrow") or texture_map.get("charged")
            rocket = texture_map.get("rocket") or texture_map.get("firework")
            if arrow:
                pack["charged_model"] = self._to_resource_ref(arrow, suffix_to_strip=".png")
            if rocket:
                pack["firework_model"] = self._to_resource_ref(rocket, suffix_to_strip=".png")
        elif material == "SHIELD":
            blocking = texture_map.get("blocking")
            if blocking:
                pack["blocking_model"] = self._to_resource_ref(blocking, suffix_to_strip=".png")
        elif material == "FISHING_ROD":
            cast = texture_map.get("cast")
            if cast:
                pack["cast_model"] = self._to_resource_ref(cast, suffix_to_strip=".png")

    def _extract_texture_map(self, resource):
        textures = self._get_dict_value(resource, "textures")
        if not isinstance(textures, dict):
            return {}
        result = {}
        for key, value in textures.items():
            if isinstance(value, str):
                result[str(key).lower().replace("-", "_")] = value
        return result

    def _hitbox_offsets_to_barriers(self, hitbox):
        offsets = []
        for key in ("width_offset", "height_offset", "length_offset"):
            value = self._get_dict_value(hitbox, key, key.replace("_", "-"))
            try:
                offsets.append(float(value or 0))
            except (TypeError, ValueError):
                offsets.append(0.0)
        if any(value != 0 for value in offsets):
            return [f"{offsets[0]:g},{offsets[1]:g},{offsets[2]:g}"]
        return []

    def _normalize_resource_path(self, value, suffix_to_strip=".json"):
        if not isinstance(value, str) or not value.strip():
            return None
        raw = value.strip().replace("\\", "/").strip("/")
        if suffix_to_strip and raw.endswith(suffix_to_strip):
            raw = raw[:-len(suffix_to_strip)]
        for suffix in (".json", ".png"):
            if raw.endswith(suffix):
                raw = raw[:-len(suffix)]
        if ":" in raw:
            namespace, raw = raw.split(":", 1)
            if namespace == "minecraft":
                return f"minecraft:{raw.strip('/')}"
        raw = raw.strip("/")
        if raw.startswith("models/"):
            raw = raw[len("models/"):]
        if raw.startswith("textures/"):
            raw = raw[len("textures/"):]
        if raw.startswith(f"{self.namespace}/"):
            raw = raw[len(self.namespace) + 1:]
        return raw

    def _to_resource_ref(self, value, suffix_to_strip=".json"):
        path = self._normalize_resource_path(value, suffix_to_strip=suffix_to_strip)
        if not path:
            return None
        if path.startswith("minecraft:"):
            return path
        return f"{self.namespace}:{path}"

    def _get_item_name(self, item_data):
        for key in ("name", "display_name", "display-name"):
            value = self._get_dict_value(item_data, key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _normalize_lore(self, value):
        if isinstance(value, list):
            return [str(line) for line in value]
        if isinstance(value, str):
            return [value]
        return None

    def _normalize_item_ref(self, value, keep_namespace=False):
        if not isinstance(value, str) or not value.strip():
            return value
        ref = value.strip()
        if ref.startswith("#") or ref.startswith("minecraft:"):
            if ref.startswith("minecraft:"):
                namespace, item_id = ref.split(":", 1)
                return f"{namespace}:{item_id.lower()}"
            return ref
        if ":" in ref:
            _, item_id = ref.split(":", 1)
            return f"{self.namespace}:{item_id}" if keep_namespace else item_id
        return f"{self.namespace}:{ref}" if keep_namespace else ref

    def _normalize_recipe_item_ref(self, value):
        if not isinstance(value, str) or not value.strip():
            return value
        ref = value.strip()
        if ref.startswith("#"):
            return ref
        if ":" in ref:
            namespace, item_id = ref.split(":", 1)
            if namespace == "minecraft":
                return f"minecraft:{item_id.lower()}"
            return f"{self.namespace}:{item_id}"
        if re.match(r"^[A-Z0-9_]+$", ref):
            return f"minecraft:{ref.lower()}"
        if self._looks_like_custom_item(ref):
            return self._normalize_item_ref(ref, keep_namespace=True)
        return ref

    def _expand_category_item_ref(self, value):
        if not isinstance(value, str) or not value.strip() or value.startswith("#"):
            return []
        ref = value.strip()
        item_ids = list((self._ia_data.get("items") or {}).keys()) if isinstance(self._ia_data, dict) else []
        if ref in {"*", "all"}:
            return [self._normalize_item_ref(item_id, keep_namespace=True) for item_id in item_ids]
        if "*" in ref:
            pattern = re.escape(self._local_id(ref)).replace("\\*", ".*")
            regex = re.compile(f"^{pattern}$")
            return [
                self._normalize_item_ref(item_id, keep_namespace=True)
                for item_id in item_ids
                if regex.match(self._local_id(item_id))
            ]
        if ref.startswith("regex:"):
            try:
                regex = re.compile(ref.split(":", 1)[1])
            except re.error:
                return []
            return [
                self._normalize_item_ref(item_id, keep_namespace=True)
                for item_id in item_ids
                if regex.match(self._local_id(item_id))
            ]
        return [self._normalize_item_ref(ref, keep_namespace=True)]

    def _looks_like_custom_item(self, value):
        if not isinstance(value, str):
            return False
        if value.startswith("#") or value.startswith("minecraft:"):
            return False
        return ":" in value or re.match(r"^[0-9a-z_.-]+$", value) is not None

    def _map_cooking_machine(self, value):
        machine = str(value).strip().lower()
        mapping = {
            "furnace": "smelting",
            "smelting": "smelting",
            "blast_furnace": "blasting",
            "blast-furnace": "blasting",
            "blasting": "blasting",
            "smoker": "smoking",
            "smoking": "smoking",
            "campfire": "campfire_cooking",
            "campfire_cooking": "campfire_cooking",
            "campfire-cooking": "campfire_cooking",
        }
        return mapping.get(machine, "smelting")

    def _normalize_slot(self, value):
        if value is None:
            return None
        slot = str(value).strip().lower()
        slot_map = {
            "helmet": "head",
            "head": "head",
            "chestplate": "chest",
            "chest": "chest",
            "leggings": "legs",
            "legs": "legs",
            "boots": "feet",
            "feet": "feet",
        }
        return slot_map.get(slot, slot or None)

    def _normalize_modifier_slot(self, value):
        slot = self._normalize_slot(value)
        return {"mainhand": "hand"}.get(slot, slot or str(value))

    def _normalize_attribute_name(self, value):
        attribute = str(value).strip().lower().replace("-", "_")
        if not attribute.startswith("generic_"):
            attribute = f"generic_{attribute}"
        return attribute

    def _slot_from_material(self, material):
        material_upper = str(material).upper()
        if material_upper.endswith("_HELMET"):
            return "head"
        if material_upper.endswith("_CHESTPLATE"):
            return "chest"
        if material_upper.endswith("_LEGGINGS"):
            return "legs"
        if material_upper.endswith("_BOOTS"):
            return "feet"
        return None

    def _is_armor_material(self, material):
        return self._slot_from_material(material) is not None

    def _armor_material_for_slot(self, slot):
        return {
            "head": "DIAMOND_HELMET",
            "chest": "DIAMOND_CHESTPLATE",
            "legs": "DIAMOND_LEGGINGS",
            "feet": "DIAMOND_BOOTS",
        }.get(slot, "DIAMOND_HELMET")

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
