import os
import re

from .base import BaseConverter, RecipeDumper
from src.migrators.ce_to_nexo import CEToNexoMigrator


class CEToNexoConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.nexo_config = {
            "items": {},
            "categories": {},
            "recipes": {},
        }
        self.ce_resourcepack_roots = []
        self.nexo_pack_root = None
        self._ce_data = {}

    def set_resource_paths(self, ce_roots, nexo_pack_root):
        self.ce_resourcepack_roots = []
        if isinstance(ce_roots, (list, tuple)):
            for path in ce_roots:
                if isinstance(path, str) and path.strip():
                    normalized = os.path.normpath(path)
                    if normalized not in self.ce_resourcepack_roots:
                        self.ce_resourcepack_roots.append(normalized)
        elif isinstance(ce_roots, str) and ce_roots.strip():
            self.ce_resourcepack_roots.append(os.path.normpath(ce_roots))
        self.nexo_pack_root = nexo_pack_root

    def convert(self, ce_data, namespace=None):
        if namespace:
            self.namespace = namespace

        self.nexo_config = {
            "items": {},
            "categories": {},
            "recipes": {},
        }
        self._ce_data = ce_data if isinstance(ce_data, dict) else {}

        self._convert_items(self._ce_data.get("items", {}))
        self._convert_categories(self._ce_data.get("categories", {}))
        self._convert_recipes(self._ce_data.get("recipes", {}))

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

        if self.ce_resourcepack_roots and self.nexo_pack_root:
            CEToNexoMigrator(
                self.ce_resourcepack_roots,
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
            nexo_item = self._convert_item(raw_id, item_id, item_data)
            if nexo_item:
                self.nexo_config["items"][item_id] = nexo_item

    def _convert_item(self, raw_id, item_id, item_data):
        nexo_item = {}

        material = self._get_dict_value(item_data, "material", default="PAPER")
        if material:
            nexo_item["material"] = str(material).upper()

        name = self._get_item_name(item_data)
        if name:
            nexo_item["itemname"] = name

        lore = self._get_dict_value(self._get_dict_value(item_data, "data", default={}), "lore")
        normalized_lore = self._normalize_lore(lore)
        if normalized_lore:
            nexo_item["lore"] = normalized_lore

        custom_model_data = self._get_dict_value(item_data, "custom_model_data", "custom-model-data")
        if custom_model_data is not None:
            nexo_item["model"] = custom_model_data

        pack = {}
        self._apply_resource(pack, item_data)
        self._apply_equipment(nexo_item, pack, item_data)
        if pack:
            nexo_item["Pack"] = pack

        components = {}
        self._apply_equippable_component(components, item_data)
        if components:
            nexo_item["Components"] = components

        mechanics = {}
        self._apply_furniture(mechanics, raw_id, item_data)
        if mechanics:
            nexo_item["Mechanics"] = mechanics

        return nexo_item

    def _apply_resource(self, pack, item_data):
        model_path = self._extract_model_path(self._get_dict_value(item_data, "model", "models"))
        if not model_path:
            model_path = self._extract_model_path(
                self._get_dict_value(item_data, "item_model", "item-model", "client_bound_model", "client-bound-model")
            )
        if model_path:
            pack["model"] = self._to_resource_ref(model_path)

        textures = self._extract_textures(item_data)
        if len(textures) == 1:
            pack["texture"] = textures[0]
        elif len(textures) > 1:
            pack["textures"] = textures

    def _apply_equipment(self, nexo_item, pack, item_data):
        settings = self._get_dict_value(item_data, "settings", default={})
        if not isinstance(settings, dict):
            return
        equipment = self._get_dict_value(settings, "equipment", default={})
        if not isinstance(equipment, dict):
            return

        asset_id = self._get_dict_value(equipment, "asset_id", "asset-id")
        slot = self._normalize_slot(self._get_dict_value(equipment, "slot", default=None))
        if slot:
            nexo_item.setdefault("Components", {}).setdefault("equippable", {})["slot"] = slot

        custom_armor = {}
        if asset_id:
            custom_armor["id"] = self._normalize_item_ref(asset_id, keep_namespace=True)
        equipment_data = self._resolve_equipment_data(asset_id)
        layer_1 = self._get_dict_value(equipment_data, "humanoid")
        layer_2 = self._get_dict_value(equipment_data, "humanoid_leggings", "humanoid-leggings")
        if layer_1:
            custom_armor["layer1"] = self._to_resource_ref(layer_1)
        if layer_2:
            custom_armor["layer2"] = self._to_resource_ref(layer_2)
        if custom_armor:
            pack["CustomArmor"] = custom_armor

    def _apply_equippable_component(self, components, item_data):
        data = self._get_dict_value(item_data, "data", default={})
        if not isinstance(data, dict):
            data = {}
        equippable = self._get_dict_value(data, "equippable", default={})
        if isinstance(equippable, dict):
            slot = self._normalize_slot(self._get_dict_value(equippable, "slot", default=None))
            if slot:
                components.setdefault("equippable", {})["slot"] = slot

        settings = self._get_dict_value(item_data, "settings", default={})
        equipment = self._get_dict_value(settings, "equipment", default={}) if isinstance(settings, dict) else {}
        if isinstance(equipment, dict):
            slot = self._normalize_slot(self._get_dict_value(equipment, "slot", default=None))
            if slot:
                components.setdefault("equippable", {})["slot"] = slot

    def _apply_furniture(self, mechanics, raw_id, item_data):
        behavior = self._get_dict_value(item_data, "behavior", default={})
        if not isinstance(behavior, dict):
            return
        if self._get_dict_value(behavior, "type") != "furniture_item":
            return

        furniture_data = self._get_dict_value(behavior, "furniture", default={})
        if isinstance(furniture_data, str):
            furniture_data = self._resolve_furniture_data(furniture_data)
        if not isinstance(furniture_data, dict):
            furniture_data = {}

        placement = self._get_dict_value(furniture_data, "placement", "variants", default={})
        if not isinstance(placement, dict):
            placement = {}

        nexo_furniture = {
            "type": "ITEM_DISPLAY",
            "limited_placing": {
                "floor": "ground" in placement or not placement,
                "wall": "wall" in placement,
                "roof": "ceiling" in placement,
            },
        }

        first_variant = self._first_variant(placement)
        hitbox = self._first_hitbox(first_variant)
        if hitbox:
            nexo_furniture["hitbox"] = self._convert_hitbox(hitbox)
            seats = self._get_dict_value(hitbox, "seats", default=[])
            if isinstance(seats, list) and seats:
                nexo_furniture["seats"] = seats

        element = self._first_element(first_variant)
        properties = {}
        if isinstance(element, dict):
            translation = self._get_dict_value(element, "translation")
            scale = self._get_dict_value(element, "scale")
            if translation:
                properties["translation"] = translation
            if scale:
                properties["scale"] = scale
        if properties:
            nexo_furniture["properties"] = properties

        mechanics["furniture"] = nexo_furniture

    def _convert_categories(self, categories):
        if not isinstance(categories, dict):
            return
        for raw_id, category_data in categories.items():
            if not isinstance(category_data, dict):
                continue
            category_id = self._local_id(raw_id)
            items = []
            for value in self._get_dict_value(category_data, "list", "items", default=[]):
                if isinstance(value, str) and not value.startswith("#"):
                    items.append(self._normalize_item_ref(value, keep_namespace=True))
            icon = self._normalize_item_ref(
                self._get_dict_value(category_data, "icon", default=items[0] if items else ""),
                keep_namespace=True,
            )
            entry = {
                "name": self._to_plain_text(self._get_dict_value(category_data, "name", default=category_id)),
                "icon": icon,
                "items": items,
            }
            permission = self._extract_permission(category_data)
            if permission:
                entry["permission"] = permission
            self.nexo_config["categories"][category_id] = entry

    def _convert_recipes(self, recipes):
        if not isinstance(recipes, dict):
            return
        for raw_id, recipe_data in recipes.items():
            if not isinstance(recipe_data, dict):
                continue
            recipe_id = self._local_id(raw_id)
            self.nexo_config["recipes"][recipe_id] = self._normalize_recipe(recipe_data)

    def _normalize_recipe(self, recipe_data):
        result = {}
        recipe_type = self._get_dict_value(recipe_data, "type", default=None)
        if recipe_type:
            result["type"] = recipe_type
        for key in ("pattern", "ingredients", "ingredient", "template", "base", "addition", "result", "time", "experience"):
            value = self._get_dict_value(recipe_data, key)
            if value is not None:
                result[key] = self._normalize_recipe_value(value)
        return result or dict(recipe_data)

    def _normalize_recipe_value(self, value):
        if isinstance(value, dict):
            return {k: self._normalize_recipe_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._normalize_recipe_value(v) for v in value]
        if isinstance(value, str):
            return self._normalize_item_ref(value, keep_namespace=True) if self._looks_like_custom_item(value) else value
        return value

    def _resolve_equipment_data(self, asset_id):
        equipments = self._ce_data.get("equipments", {})
        if not isinstance(equipments, dict) or not asset_id:
            return {}
        candidates = [asset_id, self._normalize_item_ref(asset_id, keep_namespace=True), self._local_id(asset_id)]
        for candidate in candidates:
            if candidate in equipments and isinstance(equipments[candidate], dict):
                return equipments[candidate]
        wanted = self._local_id(asset_id)
        for key, value in equipments.items():
            if self._local_id(key) == wanted and isinstance(value, dict):
                return value
        return {}

    def _resolve_furniture_data(self, furniture_ref):
        furniture = self._ce_data.get("furniture", {})
        if not isinstance(furniture, dict):
            return {}
        for candidate in (furniture_ref, self._normalize_item_ref(furniture_ref, keep_namespace=True), self._local_id(furniture_ref)):
            value = furniture.get(candidate)
            if isinstance(value, dict):
                return value
        wanted = self._local_id(furniture_ref)
        for key, value in furniture.items():
            if self._local_id(key) == wanted and isinstance(value, dict):
                return value
        return {}

    def _first_variant(self, placement):
        if not isinstance(placement, dict):
            return {}
        for key in ("ground", "wall", "ceiling"):
            value = placement.get(key)
            if isinstance(value, dict):
                return value
        for value in placement.values():
            if isinstance(value, dict):
                return value
        return {}

    def _first_hitbox(self, variant):
        hitboxes = self._get_dict_value(variant, "hitboxes", default=[])
        if not isinstance(hitboxes, list):
            return None
        for hitbox in hitboxes:
            if isinstance(hitbox, dict):
                return hitbox
        return None

    def _first_element(self, variant):
        elements = self._get_dict_value(variant, "elements", default=[])
        if not isinstance(elements, list):
            return None
        for element in elements:
            if isinstance(element, dict):
                return element
        return None

    def _convert_hitbox(self, hitbox):
        result = {}
        for key in ("width", "height", "length"):
            value = self._get_dict_value(hitbox, key)
            if value is not None:
                result[key] = value
        if not result:
            result = {"width": 1, "height": 1, "length": 1}
        return result

    def _extract_textures(self, item_data):
        values = []
        for key in ("texture", "textures"):
            value = self._get_dict_value(item_data, key)
            self._collect_string_values(value, values)

        normalized = []
        seen = set()
        for value in values:
            path = self._to_resource_ref(value, suffix_to_strip=".png")
            if path and path not in seen:
                seen.add(path)
                normalized.append(path)
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

    def _extract_model_path(self, model_value):
        if isinstance(model_value, str):
            return model_value
        if isinstance(model_value, dict):
            path = self._get_dict_value(model_value, "path")
            if path:
                return path
            arguments = self._get_dict_value(model_value, "arguments", default={})
            if isinstance(arguments, dict):
                for value in arguments.values():
                    found = self._extract_model_path(value)
                    if found:
                        return found
            for key in ("model", "normal", "default"):
                value = self._get_dict_value(model_value, key)
                found = self._extract_model_path(value)
                if found:
                    return found
            for value in model_value.values():
                found = self._extract_model_path(value)
                if found:
                    return found
        return None

    def _to_resource_ref(self, value, suffix_to_strip=".json"):
        if not isinstance(value, str) or not value.strip():
            return None
        raw = value.strip().replace("\\", "/").strip("/")
        if suffix_to_strip and raw.endswith(suffix_to_strip):
            raw = raw[:-len(suffix_to_strip)]
        if suffix_to_strip == ".json" and raw.endswith(".png"):
            raw = raw[:-4]
        if suffix_to_strip == ".png" and raw.endswith(".json"):
            raw = raw[:-5]
        if ":" in raw:
            namespace, path = raw.split(":", 1)
            if namespace == "minecraft":
                return raw
            return f"{self.namespace}:{path.strip('/')}"
        return f"{self.namespace}:{raw}"

    def _get_item_name(self, item_data):
        data = self._get_dict_value(item_data, "data", default={})
        if not isinstance(data, dict):
            data = {}
        name = self._get_dict_value(data, "item_name", "item-name", "custom_name", "custom-name", "display_name", "display-name")
        if isinstance(name, str) and name.strip():
            return name
        return None

    def _normalize_lore(self, lore):
        if isinstance(lore, list):
            return lore
        if isinstance(lore, str):
            return [lore]
        return None

    def _normalize_slot(self, value):
        if not isinstance(value, str) or not value.strip():
            return None
        slot = value.strip().lower()
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
        return slot_map.get(slot, slot)

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

    def _extract_permission(self, category_data):
        conditions = self._get_dict_value(category_data, "conditions", default=[])
        if isinstance(conditions, list):
            for condition in conditions:
                if not isinstance(condition, dict):
                    continue
                if self._get_dict_value(condition, "type") == "permission":
                    permission = self._get_dict_value(condition, "permission")
                    if permission:
                        return permission
        permission = self._get_dict_value(category_data, "permission")
        return permission if isinstance(permission, str) and permission.strip() else None

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
        normalized = {}
        for key, value in data.items():
            if isinstance(key, str):
                normalized[key.lower().replace("-", "_")] = value
        for key in keys:
            if not isinstance(key, str):
                continue
            value = normalized.get(key.lower().replace("-", "_"))
            if value is not None:
                return value
        return default

