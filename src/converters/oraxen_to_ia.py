import os
import re
from .base import BaseConverter
from src.migrators.oraxen_to_ia import OraxenToIAMigrator


class OraxenToIAConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.ia_config = {
            "info": {"namespace": self.namespace},
            "items": {},
            "categories": {},
            "equipments": {}
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
        self._armor_candidates = []

        if isinstance(oraxen_data, dict):
            for key, value in oraxen_data.items():
                if isinstance(value, dict):
                    self._convert_item(key, value)

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
            return

        behaviours = {}

        hat = mechanics.get("hat", {})
        if isinstance(hat, dict) and hat.get("enabled"):
            behaviours["hat"] = True

        furniture = mechanics.get("furniture", {})
        if isinstance(furniture, dict) and furniture:
            ia_furniture = {}
            entity_type = str(furniture.get("type", "ITEM_FRAME")).lower()
            ia_furniture["entity"] = "item_frame" if "item_frame" in entity_type else "armor_stand"

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

        model_path = self._normalize_model_path(pack.get("model"))
        if model_path:
            resource["model_path"] = model_path

        textures = pack.get("textures")
        if isinstance(textures, list) and textures:
            normalized = [self._normalize_texture_path(x) for x in textures if isinstance(x, str)]
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

        if armor_slot:
            self._armor_candidates.append({
                "item_id": item_id,
                "slot": armor_slot,
                "color": data.get("color"),
                "textures": pack.get("textures")
            })

    def _finalize_armors(self):
        armor_items = {}
        for candidate in self._armor_candidates:
            item_id = candidate.get("item_id")
            slot = candidate.get("slot")
            if not item_id or not slot:
                continue
            if item_id not in self.ia_config["items"]:
                continue
            armor_items[item_id] = slot

        if not armor_items:
            self.ia_config["equipments"] = {}
            return

        layer_1, layer_2 = self._detect_armor_layers()
        if not layer_1 or not layer_2:
            return

        equipment_id = f"{self.namespace.replace('_', '')}armor"
        self.ia_config["equipments"] = {
            equipment_id: {
                "layer_1": layer_1,
                "layer_2": layer_2
            }
        }

        for item_id, slot in armor_items.items():
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
