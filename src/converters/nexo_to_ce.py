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

    def _convert_items(self, items_data):
        if not isinstance(items_data, dict):
            return
        
        # 递归函数查找物品
        def recurse(data, prefix=""):
            for key, value in data.items():
                if not isinstance(value, dict):
                    continue
                
                # 检查是否为物品
                if "material" in value or "itemname" in value:
                    self._convert_item(key, value)
                else:
                    # 递归
                    recurse(value, prefix + key + "_")

        recurse(items_data)

    def _convert_item(self, key, data):
        ce_id = f"{self.namespace}:{key}"
        
        material = data.get("material", "STONE")
        item_name = data.get("itemname", key)
        
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

        pack = data.get("Pack", {})
        mechanics = data.get("Mechanics", {})
        
        # 确定物品类型并处理特定逻辑
        if self._is_armor(material):
            self._handle_armor(ce_item, data)
        elif "furniture" in mechanics:
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

    def _handle_armor(self, ce_item, nexo_data):
        pack = nexo_data.get("Pack", {})
        custom_armor = pack.get("CustomArmor", {})
        
        slot = "head"
        material = ce_item["material"]
        if material.endswith("_CHESTPLATE"): slot = "chest"
        elif material.endswith("_LEGGINGS"): slot = "legs"
        elif material.endswith("_BOOTS"): slot = "feet"

        layer1 = custom_armor.get("layer1")
        layer2 = custom_armor.get("layer2")
        texture_path = pack.get("texture") or custom_armor.get("texture")

        if layer1:
            self._register_equipment_texture(layer1, is_leggings=False)
        if layer2:
            self._register_equipment_texture(layer2, is_leggings=True)

        asset_seed = custom_armor.get("id") or custom_armor.get("asset_id") or layer1 or layer2 or texture_path
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
        else:
            self._handle_generic_model(ce_item, pack)

    def _handle_furniture(self, ce_item, nexo_data, ce_id):
        mechanics = nexo_data.get("Mechanics", {})
        furniture = mechanics.get("furniture", {})
        properties = furniture.get("properties", {})
        hitbox_config = furniture.get("hitbox", {})
        seat_config = furniture.get("seat", {})
        limited_placing = furniture.get("limited_placing", {})

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

        # 放置
        placement = {}
        # Nexo: 屋顶, 地板, 墙壁
        # CE: 天花板, 地面, 墙壁
        
        # 从属性转换/缩放
        trans_str = properties.get("translation", "0,0,0")
        scale_str = properties.get("scale", "1,1,1")
        rotation_type = properties.get("tracking_rotation", "FIXED") # FIXED -> 旋转: 任意?
        
        # 解析转换
        try:
            tx, ty, tz = map(float, trans_str.split(","))
        except:
            tx, ty, tz = 0, 0, 0

        # 解析缩放
        try:
            sx, sy, sz = map(float, scale_str.split(","))
        except:
            sx, sy, sz = 1, 1, 1
            
        element_base = {
            "item": ce_id,
            "display-transform": "NONE",
            "billboard": "FIXED",
            "translation": f"{tx:g},{ty:g},{tz:g}",
        }
        if sx != 1 or sy != 1 or sz != 1:
             element_base["scale"] = f"{sx:g},{sy:g},{sz:g}"

        # 碰撞箱
        hitboxes = []
        barriers = hitbox_config.get("barriers", [])
        
        # 转换障碍物 (潜影盒)
        for barrier in barriers:
            # 障碍物是 "x,y,z" 字符串
            try:
                bx, by, bz = map(float, barrier.split(","))
                # CE 期望潜影盒的整数位置
                hitboxes.append({
                    "position": f"{int(bx)},{int(by)},{int(bz)}",
                    "type": "shulker",
                    "blocks-building": True,
                    "interactive": True
                })
            except:
                pass

        # 处理座位
        # Nexo 在 'seats' 字符串列表中定义座位
        seats_list = furniture.get("seats", [])
        if seats_list:
             # 需要为座位找到父碰撞箱或创建交互碰撞箱
             
             # 转换座位位置
             ce_seats = []
             for s in seats_list:
                 try:
                     sex, sey, sez = map(float, s.split(","))
                     ce_seats.append(f"{sex:g},{sey:g},{sez:g}")
                 except:
                     pass
             
             if ce_seats:
                 hitboxes.append({
                     "position": "0,0,0",
                     "type": "interaction",
                     "blocks-building": True,
                     "width": 1,
                     "height": 1,
                     "interactive": True,
                     "seats": ce_seats
                 })
        elif not hitboxes:
             # 如果为空，添加默认交互碰撞箱
             hitboxes.append({
                "position": "0,0,0",
                "type": "interaction",
                "blocks-building": True,
                "interactive": True
            })

        placement_config = {
            "loot-spawn-offset": "0,0.4,0",
            "rules": {
                "rotation": "ANY",
                "alignment": "ANY"
            },
            "elements": [element_base],
        }
        
        if hitboxes:
            placement_config["hitboxes"] = hitboxes

        if limited_placing.get("floor"):
            placement["ground"] = placement_config
        if limited_placing.get("wall"):
            wall_config = placement_config.copy()
            placement["wall"] = wall_config
        if limited_placing.get("roof"):
            placement["ceiling"] = placement_config

        ce_item["behavior"]["furniture"]["placement"] = placement
        
        self._handle_generic_model(ce_item, nexo_data.get("Pack", {}))

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
