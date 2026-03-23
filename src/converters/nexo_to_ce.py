import os
import re
import json
from .base import BaseConverter, RecipeDumper
from src.migrators.nexo_to_ce import NexoMigrator

class NexoConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.ce_config = {
            "items": {},
            "equipments": {},
            "templates": {},
            "categories": {},
            "recipes": {}
        }
        self.nexo_resourcepack_root = None
        self.ce_resourcepack_root = None
        self.generated_models = {} 
        self.armor_humanoid_keys = set()
        self.armor_leggings_keys = set()
        self.source_namespaces = set()

    def set_resource_paths(self, nexo_root, ce_root):
        self.nexo_resourcepack_root = nexo_root
        self.ce_resourcepack_root = ce_root

    def save_config(self, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        
        armor_items = {}
        other_items = {}
        
        for key, value in self.ce_config["items"].items():
            is_armor = False
            if self._is_armor(value.get("material", "")):
                is_armor = True
            elif "settings" in value and "equipment" in value["settings"]:
                is_armor = True
                
            if is_armor:
                armor_items[key] = value
            else:
                other_items[key] = value

        items_data = {}
        if self.ce_config["templates"]:
            items_data["templates"] = self.ce_config["templates"]
        if other_items:
            items_data["items"] = other_items
            
        if items_data:
            self._write_yaml_with_footer(items_data, os.path.join(output_dir, "items.yml"))

        armor_data = {}
        if armor_items:
             armor_data["items"] = armor_items
        if self.ce_config["equipments"]:
             armor_data["equipments"] = self.ce_config["equipments"]
             
        if armor_data:
            self._write_yaml_with_footer(armor_data, os.path.join(output_dir, "armor.yml"))

        if self.ce_config["categories"]:
            cat_data = {"categories": self.ce_config["categories"]}
            self._write_yaml_with_footer(cat_data, os.path.join(output_dir, "categories.yml"))

        if self.ce_config["recipes"]:
            recipe_data = {"recipes": self.ce_config["recipes"]}
            self._write_yaml_with_footer(recipe_data, os.path.join(output_dir, "recipe.yml"), dumper=RecipeDumper)

        if self.nexo_resourcepack_root and self.ce_resourcepack_root:
            migrator = NexoMigrator(
                self.nexo_resourcepack_root, 
                self.ce_resourcepack_root, 
                self.namespace,
                self.armor_humanoid_keys,
                self.armor_leggings_keys,
                source_namespaces=self.source_namespaces
            )
            migrator.migrate()
            
        if self.ce_resourcepack_root and self.generated_models:
            models_root = os.path.join(self.ce_resourcepack_root, "assets", self.namespace, "models")
            for rel_path, content in self.generated_models.items():
                full_path = os.path.join(models_root, rel_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w', encoding='utf-8') as f:
                    json.dump(content, f, indent=4)

    def convert(self, nexo_data, namespace=None):
        if namespace:
            self.namespace = namespace
        
        # Nexo 结构通常是根目录下的扁平物品键，或者是嵌套的。
        # 但通常 Nexo 物品只是文件中的键。
        # 我们需要区分物品和其他可能的键（如果有）。
        # 然而，查看示例，文件似乎就是物品列表。
        
        self._convert_items(nexo_data)
        
        # 如果需要，自动生成分类
        if not self.ce_config["categories"] and self.ce_config["items"]:
            self._generate_default_category()

        return self.ce_config

    def _generate_default_category(self):
        cat_id = f"{self.namespace}:default"
        items_list = list(self.ce_config["items"].keys())
        icon = "minecraft:chest"
        if items_list:
            icon = items_list[0]

        ce_category = {
            "name": f"<!i>{self.namespace.capitalize()}",
            "lore": [
                "<!i><gray>该配置由<#FFFF00>MCC TOOL</#FFFF00>生成",
                "<!i><gray>闲鱼店铺: <#FFFF00>快乐售货铺</#FFFF00>",
                "<!i><dark_gray>感谢您的支持!</dark_gray>"
            ],
            "priority": 1,
            "icon": icon,
            "list": items_list,
            "hidden": False
        }
        self.ce_config["categories"][cat_id] = ce_category

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
                v = lowered.get(key.lower())
                if v is not None:
                    return v
        return default

    def _get_pack_data(self, data):
        pack = self._get_dict_value(data, "Pack", "pack", default={})
        if isinstance(pack, dict):
            return pack
        return {}

    def _get_mechanics_data(self, data):
        mechanics = self._get_dict_value(data, "Mechanics", "mechanics", default={})
        if isinstance(mechanics, dict):
            return mechanics
        return {}

    def _get_custom_armor_data(self, pack):
        custom_armor = self._get_dict_value(pack, "CustomArmor", "custom_armor", "customArmor", default={})
        if isinstance(custom_armor, dict):
            return custom_armor
        return {}

    def _split_resource_path(self, raw_path):
        if not raw_path:
            return self.namespace, None
        path = str(raw_path).replace("\\", "/").lstrip("/")
        ns = self.namespace
        rel = path
        if ":" in path:
            ns, rel = path.split(":", 1)
        return ns, rel

    def _texture_exists(self, raw_path):
        if not raw_path or not self.nexo_resourcepack_root:
            return False
        ns, rel = self._split_resource_path(raw_path)
        if not rel:
            return False
        rel_path = rel[:-4] if rel.endswith(".png") else rel
        candidates = [
            os.path.join(self.nexo_resourcepack_root, "assets", ns, "textures", f"{rel_path}.png"),
            os.path.join(self.nexo_resourcepack_root, "assets", "minecraft", "textures", ns, f"{rel_path}.png"),
            os.path.join(self.nexo_resourcepack_root, ns, "textures", f"{rel_path}.png"),
            os.path.join(self.nexo_resourcepack_root, "textures", f"{rel_path}.png")
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return True
        return False

    def _infer_armor_layers(self, item_key, icon_texture):
        if not icon_texture:
            return None, None
        ns, rel = self._split_resource_path(icon_texture)
        if not rel:
            return None, None
        directory = os.path.dirname(rel).replace("\\", "/")
        basename = os.path.splitext(os.path.basename(rel))[0]
        item_base = re.sub(r"_(helmet|chestplate|leggings|boots)$", "", str(item_key), flags=re.IGNORECASE)
        base_candidates = [item_base]
        stripped = re.sub(r"_(helmet|chestplate|leggings|boots)(_icon)?$", "", basename, flags=re.IGNORECASE)
        if stripped and stripped not in base_candidates:
            base_candidates.append(stripped)
        for base in base_candidates:
            for folder in [directory, directory.replace("/armor", "/armors"), directory.replace("/armors", "/armor"), "armor", "armors"]:
                folder = folder.strip("/")
                if folder:
                    layer1 = f"{ns}:{folder}/{base}_armor_layer_1"
                    layer2 = f"{ns}:{folder}/{base}_armor_layer_2"
                else:
                    layer1 = f"{ns}:{base}_armor_layer_1"
                    layer2 = f"{ns}:{base}_armor_layer_2"
                if self._texture_exists(layer1):
                    return layer1, layer2 if self._texture_exists(layer2) else None
        return None, None

    def _convert_items(self, items_data):
        if not isinstance(items_data, dict):
            return
        
        # 递归函数查找物品
        def recurse(data, prefix=""):
            for key, value in data.items():
                if not isinstance(value, dict):
                    continue
                
                # 检查是否为物品
                if "material" in value or "itemname" in value or "customname" in value:
                    self._convert_item(key, value)
                else:
                    # 递归
                    recurse(value, prefix + key + "_")

        recurse(items_data)

    def _convert_item(self, key, data):
        ce_id = f"{self.namespace}:{key}"
        
        material = data.get("material", "STONE")
        item_name = self._get_dict_value(data, "itemname", "customname", default=key)
        
        ce_item = {
            "material": material,
            "data": {
                "item-name": self._format_display_name(item_name)
            }
        }
        
        lore_value = data.get("lore")
        if lore_value:
            ce_lore = self._normalize_lore(lore_value)
            if ce_lore:
                ce_item["data"]["lore"] = ce_lore
        
        if "model" in data:
             ce_item["custom-model-data"] = data.get("model")

        pack = self._get_pack_data(data)
        mechanics = self._get_mechanics_data(data)
        
        # 确定物品类型并处理特定逻辑
        furniture_data = self._get_dict_value(mechanics, "furniture", "Furniture", default={})

        if self._is_armor(material):
            self._handle_armor(ce_item, key, data, pack)
        elif isinstance(furniture_data, dict) and furniture_data:
            self._handle_furniture(ce_item, data, ce_id)
        elif self._is_complex_item(material):
            self._handle_complex_item(ce_item, key, data, material)
        else:
            self._handle_generic_model(ce_item, pack)

        self.ce_config["items"][ce_id] = ce_item

    def _format_display_name(self, display_name):

        if not display_name:
            return display_name
        
        return display_name

    def _normalize_lore(self, lore):
        if isinstance(lore, list):
            return lore
        if isinstance(lore, str):
            return [lore]
        return None

    def _is_armor(self, material):
        suffixes = ["_HELMET", "_CHESTPLATE", "_LEGGINGS", "_BOOTS"]
        return any(material.endswith(s) for s in suffixes)

    def _handle_armor(self, ce_item, item_key, nexo_data, pack=None):
        if pack is None:
            pack = self._get_pack_data(nexo_data)
        custom_armor = self._get_custom_armor_data(pack)
        
        slot = "head"
        material = ce_item["material"]
        if material.endswith("_CHESTPLATE"): slot = "chest"
        elif material.endswith("_LEGGINGS"): slot = "legs"
        elif material.endswith("_BOOTS"): slot = "feet"

        layer1 = self._get_dict_value(custom_armor, "layer1", "layer_1")
        layer2 = self._get_dict_value(custom_armor, "layer2", "layer_2")
        texture_path = self._get_dict_value(pack, "texture", default=None) or self._get_dict_value(custom_armor, "texture", default=None)
        pack_textures = self._get_dict_value(pack, "textures", default=None)
        if not texture_path and isinstance(pack_textures, list) and pack_textures:
            texture_path = pack_textures[0]
        if not layer1 and not layer2 and texture_path:
            inferred_layer1, inferred_layer2 = self._infer_armor_layers(item_key, texture_path)
            if inferred_layer1:
                layer1 = inferred_layer1
            if inferred_layer2:
                layer2 = inferred_layer2

        if layer1:
            self._register_equipment_texture(layer1, is_leggings=False)
        if layer2:
            self._register_equipment_texture(layer2, is_leggings=True)

        has_custom_equipment = bool(layer1 or layer2 or self._get_dict_value(custom_armor, "id", "asset_id", "asset-id", default=None))
        if has_custom_equipment:
            asset_seed = self._get_dict_value(custom_armor, "id", "asset_id", "asset-id", default=None) or layer1 or layer2 or texture_path
            asset_id = self._infer_armor_asset_id(asset_seed, slot)
            equipment_ref = f"{self.namespace}:{asset_id}"

            ce_item["settings"] = {
                "equipment": {
                    "asset-id": equipment_ref,
                    "slot": slot
                }
            }

            ce_equipment = self.ce_config["equipments"].get(equipment_ref, {"type": "component"})
            if layer1:
                ce_equipment["humanoid"] = self._normalize_equipment_texture_path(layer1, is_leggings=False)
            if layer2:
                ce_equipment["humanoid-leggings"] = self._normalize_equipment_texture_path(layer2, is_leggings=True)
            self.ce_config["equipments"][equipment_ref] = ce_equipment

        if texture_path:
            ce_item["textures"] = [self._normalize_armor_item_texture(texture_path)]
        if not texture_path:
            self._handle_generic_model(ce_item, pack)

    def _handle_furniture(self, ce_item, nexo_data, ce_id):
        mechanics = self._get_mechanics_data(nexo_data)
        furniture = self._get_dict_value(mechanics, "furniture", "Furniture", default={})
        hitbox_config = furniture.get("hitbox", {})
        limited_placing = furniture.get("limited_placing", {})
        pack = self._get_pack_data(nexo_data)
        model_path = pack.get("model")
        translation_y = self._calculate_model_y_translation(model_path)

        ce_item["behavior"] = {
            "type": "furniture_item",
            "furniture": {
                "settings": {
                    "item": ce_id,
                    "sounds": {
                        "break": "minecraft:block.stone.break",
                        "place": "minecraft:block.stone.place"
                    }
                },
                "loot": {
                    "template": "default:loot_table/furniture",
                    "arguments": {
                        "item": ce_id
                    }
                }
            }
        }

        placement = {}
        if not limited_placing:
            limited_placing = {"floor": True}
        if limited_placing.get("floor"):
            placement["ground"] = self._create_nexo_placement_block(ce_id, furniture, hitbox_config, "ground", translation_y)
        if limited_placing.get("wall"):
            placement["wall"] = self._create_nexo_placement_block(ce_id, furniture, hitbox_config, "wall", translation_y)
        if limited_placing.get("roof"):
            placement["ceiling"] = self._create_nexo_placement_block(ce_id, furniture, hitbox_config, "ceiling", translation_y)

        ce_item["behavior"]["furniture"]["placement"] = placement
        
        self._handle_generic_model(ce_item, pack)

    def _calculate_model_y_translation(self, model_path):
        if not model_path or not self.nexo_resourcepack_root:
            return 0.5
        model_file = self._resolve_nexo_model_file(model_path)
        if not model_file or not os.path.exists(model_file):
            return 0.5
        try:
            with open(model_file, 'r', encoding='utf-8') as f:
                model_data = json.load(f)
            elements = model_data.get("elements", [])
            for el in elements:
                from_y = el.get("from", [0, 0, 0])[1]
                to_y = el.get("to", [0, 0, 0])[1]
                if from_y < -7.0 or to_y < -7.0:
                    return 1.5
            return 0.5
        except Exception:
            return 0.5

    def _resolve_nexo_model_file(self, model_path):
        path = str(model_path).replace("\\", "/").lstrip("/")
        ns = self.namespace
        rel = path
        if ":" in path:
            ns, rel = path.split(":", 1)
        else:
            parts = [p for p in path.split("/") if p]
            if len(parts) > 1:
                ns = parts[0]
                rel = "/".join(parts[1:])
        if rel.endswith(".json"):
            rel = rel[:-5]
        candidates = [
            os.path.join(self.nexo_resourcepack_root, "assets", ns, "models", f"{rel}.json"),
            os.path.join(self.nexo_resourcepack_root, "assets", "minecraft", "models", ns, f"{rel}.json"),
            os.path.join(self.nexo_resourcepack_root, ns, "models", f"{rel}.json"),
            os.path.join(self.nexo_resourcepack_root, "models", f"{rel}.json")
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return None

    def _parse_vec3(self, value, default=(0.0, 0.0, 0.0)):
        if isinstance(value, str):
            try:
                x, y, z = map(float, value.split(","))
                return x, y, z
            except Exception:
                return default
        if isinstance(value, dict):
            try:
                return float(value.get("x", 0.0)), float(value.get("y", 0.0)), float(value.get("z", 0.0))
            except Exception:
                return default
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            try:
                return float(value[0]), float(value[1]), float(value[2])
            except Exception:
                return default
        return default

    def _infer_hitbox_size_from_barriers(self, barriers):
        points = []
        for barrier in barriers or []:
            if not isinstance(barrier, str):
                continue
            try:
                bx, by, bz = map(float, barrier.split(","))
                points.append((bx, by, bz))
            except Exception:
                continue
        if not points:
            return 1, 1, 1
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        zs = [p[2] for p in points]
        width = max(1, int(round(max(xs) - min(xs) + 1)))
        height = max(1, int(round(max(ys) - min(ys) + 1)))
        length = max(1, int(round(max(zs) - min(zs) + 1)))
        return width, height, length

    def _create_nexo_placement_block(self, ce_id, furniture, hitbox_config, placement_type, base_translation_y):
        properties = furniture.get("properties", {})
        seat_config = furniture.get("seat", {})
        barriers = hitbox_config.get("barriers", [])
        width = int(hitbox_config.get("width", 1) or 1)
        height = int(hitbox_config.get("height", 1) or 1)
        length = int(hitbox_config.get("length", 1) or 1)
        if width == 1 and height == 1 and length == 1:
            width, height, length = self._infer_hitbox_size_from_barriers(barriers)

        tx, _, tz = self._parse_vec3(properties.get("translation", "0,0,0"))
        sx, sy, sz = self._parse_vec3(properties.get("scale", "1,1,1"), default=(1.0, 1.0, 1.0))
        translation_y = base_translation_y * max(sx, sy, sz)
        if placement_type in ("wall", "ceiling"):
            translation_y = 0
        translation_z = tz
        if height == 2 and width == 3 and length == 2:
            translation_z += 0.5

        element_entry = {
            "item": ce_id,
            "display-transform": "NONE",
            "billboard": "FIXED",
            "translation": f"{tx:g},{translation_y:g},{translation_z:g}"
        }
        if sx != 1 or sy != 1 or sz != 1:
            element_entry["scale"] = f"{sx:g},{sy:g},{sz:g}"
        if placement_type == "wall":
            element_entry["position"] = "0,0,0.5"
        elif placement_type == "ceiling":
            element_entry["position"] = "0,-1,0"

        block_config = {
            "loot-spawn-offset": "0,0.4,0",
            "rules": {
                "rotation": "ANY",
                "alignment": "ANY"
            },
            "elements": [element_entry]
        }

        hitboxes = []
        seats_list = furniture.get("seats", [])
        ce_seats = []
        seat_height_offset = 0.0
        try:
            seat_height_offset = float(seat_config.get("height", 0.0))
        except Exception:
            seat_height_offset = 0.0
        for seat in seats_list:
            if not isinstance(seat, str):
                continue
            try:
                sx0, sy0, sz0 = map(float, seat.split(","))
                ce_seats.append((sx0, sy0 + seat_height_offset, sz0))
            except Exception:
                continue
        if len(ce_seats) == 1:
            x0, y0, z0 = ce_seats[0]
            ce_seats.append((x0 - 1, y0, z0))

        if placement_type != "wall":
            if ce_seats:
                seat_hitbox_width = 0.7
                seat_hitbox_height = 1.2
                if "width" in hitbox_config:
                    try:
                        seat_hitbox_width = float(hitbox_config.get("width", 0.7))
                    except Exception:
                        seat_hitbox_width = 0.7
                if "height" in hitbox_config:
                    try:
                        seat_hitbox_height = float(hitbox_config.get("height", 1.2))
                    except Exception:
                        seat_hitbox_height = 1.2
                hitboxes.append({
                    "position": "0,0,0",
                    "type": "interaction",
                    "blocks-building": True,
                    "width": seat_hitbox_width,
                    "height": seat_hitbox_height,
                    "interactive": True,
                    "seats": [f"{x:g},{y:g},{z:g}" for x, y, z in ce_seats]
                })
            else:
                for barrier in barriers:
                    if not isinstance(barrier, str):
                        continue
                    try:
                        bx, by, bz = map(float, barrier.split(","))
                        hitboxes.append({
                            "position": f"{int(round(bx))},{int(round(by))},{int(round(bz))}",
                            "type": "shulker",
                            "blocks-building": True,
                            "interactive": True
                        })
                    except Exception:
                        continue

        if placement_type == "ceiling" and not hitboxes:
            hitboxes.append({
                "type": "interaction",
                "position": "0,-1,0",
                "width": width,
                "height": height,
                "interactive": True,
                "blocks-building": False
            })
        elif placement_type == "wall" and not hitboxes:
            hitboxes.append({
                "type": "interaction",
                "position": "0,-0.5,0",
                "width": width,
                "height": height,
                "interactive": True,
                "blocks-building": False
            })
        elif not hitboxes:
            hitboxes.append({
                "position": "0,0,0",
                "type": "interaction",
                "blocks-building": True,
                "interactive": True
            })

        has_interaction = any(h.get("type") == "interaction" for h in hitboxes if isinstance(h, dict))
        if has_interaction:
            hitboxes = [h for h in hitboxes if isinstance(h, dict) and h.get("type") == "interaction"]
        else:
            hitboxes = [h for h in hitboxes if isinstance(h, dict) and h.get("type") == "shulker"]

        block_config["hitboxes"] = hitboxes
        return block_config

    def _handle_complex_item(self, ce_item, key, nexo_data, material):
        pack = nexo_data.get("Pack", {})
        
        template_id = f"models:{self.namespace}_{key}_model"
        ce_item["model"] = {
            "template": template_id,
            "arguments": {}
        }
        
        args = ce_item["model"]["arguments"]
        
        # 基础模型
        base_model = pack.get("model")
        if base_model:
            args["model"] = self._get_model_ref(base_model)
            # 一些模板使用特定名称
            if material == "BOW": args["bow_model"] = self._get_model_ref(base_model)
            elif material == "SHIELD": args["shield_model"] = self._get_model_ref(base_model)
            elif material == "FISHING_ROD": args["path"] = self._get_model_ref(base_model)
        
        # 变体
        if material == "BOW":
            pulling = pack.get("pulling_models", [])
            for i, m in enumerate(pulling):
                args[f"bow_pulling_{i}_model"] = self._get_model_ref(m)
        
        elif material == "CROSSBOW":
            pulling = pack.get("pulling_models", [])
            for i, m in enumerate(pulling):
                args[f"pulling_{i}_model"] = self._get_model_ref(m)
            
            charged = pack.get("charged_model")
            if charged: args["arrow_model"] = self._get_model_ref(charged)
            
            firework = pack.get("firework_model")
            if firework: args["firework_model"] = self._get_model_ref(firework)
            
        elif material == "SHIELD":
            blocking = pack.get("blocking_model")
            if blocking: args["shield_blocking_model"] = self._get_model_ref(blocking)
            
        elif material == "FISHING_ROD":
            cast = pack.get("cast_model")
            if cast: args["cast_path"] = self._get_model_ref(cast)

        # 生成模板定义
        self._generate_template_definition(template_id, material)

    def _generate_template_definition(self, template_id, material):
        # 根据材质生成标准模板
        template = {}
        if material == "BOW":
            template = {
                "type": "minecraft:condition",
                "property": "minecraft:using_item",
                "on-false": {"type": "minecraft:model", "path": "${bow_model}"},
                "on-true": {
                    "type": "minecraft:range_dispatch",
                    "property": "minecraft:use_duration",
                    "scale": 0.05,
                    "entries": [
                        {"model": {"type": "minecraft:model", "path": "${bow_pulling_1_model}"}, "threshold": 0.65},
                        {"model": {"type": "minecraft:model", "path": "${bow_pulling_2_model}"}, "threshold": 0.9}
                    ],
                    "fallback": {"type": "minecraft:model", "path": "${bow_pulling_0_model}"}
                }
            }
        elif material == "CROSSBOW":
             template = {
                "type": "minecraft:condition",
                "property": "minecraft:using_item",
                "on-false": {
                    "type": "minecraft:select",
                    "property": "minecraft:charge_type",
                    "cases": [
                        {"when": "arrow", "model": {"type": "minecraft:model", "path": "${arrow_model}"}},
                        {"when": "rocket", "model": {"type": "minecraft:model", "path": "${firework_model}"}}
                    ],
                    "fallback": {"type": "minecraft:model", "path": "${model}"}
                },
                "on-true": {
                    "type": "minecraft:range_dispatch",
                    "property": "minecraft:crossbow/pull",
                    "entries": [
                        {"model": {"type": "minecraft:model", "path": "${pulling_1_model}"}, "threshold": 0.58},
                        {"model": {"type": "minecraft:model", "path": "${pulling_2_model}"}, "threshold": 1.0}
                    ],
                    "fallback": {"type": "minecraft:model", "path": "${pulling_0_model}"}
                }
            }
        elif material == "SHIELD":
            template = {
                "type": "minecraft:condition",
                "property": "minecraft:using_item",
                "on-false": {"type": "minecraft:model", "path": "${shield_model}"},
                "on-true": {"type": "minecraft:model", "path": "${shield_blocking_model}"}
            }
        elif material == "FISHING_ROD":
            template = {
                "type": "minecraft:condition",
                "property": "minecraft:fishing_rod/cast",
                "on-false": {"type": "minecraft:model", "path": "${path}"},
                "on-true": {"type": "minecraft:model", "path": "${cast_path}"}
            }

        if template:
            self.ce_config["templates"][template_id] = template

    def _handle_generic_model(self, ce_item, pack):
        model_path = pack.get("model")
        if model_path:
            ce_item["model"] = {
                "type": "minecraft:model",
                "path": self._get_model_ref(model_path)
            }

    def _get_model_ref(self, path):
        # 将 nexo 路径转换为 CE 引用
        # Nexo: elitecreatures/piglin_animated_weapon_set/axe
        # CE: elitecreatures:item/piglin_animated_weapon_set/axe
        # 如果路径包含 :，则分割它。
        if ":" in path:
            ns, p = path.split(":", 1)
            self.source_namespaces.add(ns)
            # 重写为目标命名空间，在路径中保留源命名空间
            # 如果与目标不同
            if ns != self.namespace:
                 p = f"{ns}/{p}"
        else:
            # 如果路径以我们正在转换的命名空间开头，我们可以分割它。
            if path.startswith(f"{self.namespace}/"):
                ns = self.namespace
                p = path[len(self.namespace)+1:]
            else:
                # 尝试检测第一部分是否为已知命名空间格式
                parts = path.split("/")
                if len(parts) > 1:
                    ns = parts[0]
                    p = path
                    self.source_namespaces.add(ns)
                else:
                    ns = self.namespace
                    p = path

        # CE 约定：namespace:item/path
        if not p.startswith("item/"):
            p = f"item/{p}"
            
        # 始终使用目标命名空间作为资源位置引用
        return f"{self.namespace}:{p}"

    def _is_complex_item(self, material):
        return material in ["BOW", "CROSSBOW", "FISHING_ROD", "SHIELD"]

    def _register_equipment_texture(self, raw_path, is_leggings=False):
        key = self._normalize_equipment_key(raw_path)
        if not key:
            return
        if is_leggings:
            self.armor_leggings_keys.add(key)
        else:
            self.armor_humanoid_keys.add(key)

    def _normalize_equipment_key(self, raw_path):
        if not raw_path:
            return None
        path = str(raw_path)
        if ":" in path:
            path = path.split(":", 1)[1]
        # 移除扩展名
        if path.endswith(".png"):
            path = path[:-4]
        path = path.replace("\\", "/").lstrip("/")
        # 移除 textures/ 前缀（如果存在）
        if path.startswith("textures/"):
            path = path[len("textures/"):]
        return path

    def _normalize_equipment_texture_path(self, raw_path, is_leggings=False):
        if not raw_path:
            return f"{self.namespace}:entity/equipment/humanoid/unknown"
        path = str(raw_path)
        if ":" in path:
            path = path.split(":", 1)[1]
        if path.endswith(".png"):
            path = path[:-4]
        path = path.replace("\\", "/").lstrip("/")
        if path.startswith("textures/"):
            path = path[len("textures/"):]
        parts = [p for p in path.split("/") if p]
        if parts and parts[0] == self.namespace:
            parts = parts[1:]
        subpath = parts[-1] if parts else "unknown"
        target_folder = "humanoid_leggings" if is_leggings else "humanoid"
        final_path = f"entity/equipment/{target_folder}/{subpath}" if subpath else f"entity/equipment/{target_folder}"
        return f"{self.namespace}:{final_path}"

    def _normalize_armor_item_texture(self, raw_path):
        path = str(raw_path)
        if ":" in path:
            path = path.split(":", 1)[1]
        path = path.replace("\\", "/").lstrip("/")
        if path.endswith(".png"):
            path = path[:-4]
        if path.startswith("textures/"):
            path = path[len("textures/"):]
        if path.startswith(f"{self.namespace}/"):
            path = path[len(self.namespace) + 1:]
        if path.startswith("item/"):
            final_path = path
        else:
            final_path = f"item/{path}"
        return f"{self.namespace}:{final_path}"

    def _infer_armor_asset_id(self, raw_path, slot):
        if not raw_path:
            return f"armor_{slot}"
        normalized = self._normalize_equipment_key(raw_path)
        if not normalized:
            return f"armor_{slot}"
        parts = [p for p in normalized.split("/") if p]
        if parts and parts[0] == self.namespace:
            parts = parts[1:]
        if "armor" in parts:
            idx = parts.index("armor")
            if idx > 0:
                return parts[idx - 1]
        basename = parts[-1] if parts else ""
        for suffix in ["_armor_layer_1", "_armor_layer_2", "_layer_1", "_layer_2", "_helmet", "_chestplate", "_leggings", "_boots"]:
            if basename.endswith(suffix):
                basename = basename[:-len(suffix)]
                break
        return basename or f"armor_{slot}"
