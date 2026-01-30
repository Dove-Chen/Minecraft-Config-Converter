import os
import json
from turtle import position
from .base import BaseConverter
from src.migrators.ia_to_ce import IAMigrator

class IAConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.ce_config = {
            "items": {},
            "equipments": {},
            "templates": {},
            "categories": {}
        }
        self.ia_resourcepack_root = None
        self.ce_resourcepack_root = None
        self.generated_models = {} # 存储需要生成的模型

    def set_resource_paths(self, ia_root, ce_root):
        self.ia_resourcepack_root = ia_root
        self.ce_resourcepack_root = ce_root

    def save_config(self, output_dir):
        """
        保存转换后的配置到输出目录中的多个文件。
        结构:
        output_dir/
          items.yml       (物品, 模板)
          armor.yml       (物品 - 护甲类型, 装备)
          categories.yml  (分类)
        """
        # 如果目录不存在则创建
        os.makedirs(output_dir, exist_ok=True)
        
        # 将物品分为护甲物品和其他物品
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

        # 1. 保存 items.yml (其他物品 + 模板)
        items_data = {}
        if self.ce_config["templates"]:
            items_data["templates"] = self.ce_config["templates"]
        if other_items:
            items_data["items"] = other_items
            
        if items_data:
            self._write_yaml_with_footer(items_data, os.path.join(output_dir, "items.yml"))

        # 2. 保存 armor.yml (护甲物品 + 装备)
        armor_data = {}
        if armor_items:
             armor_data["items"] = armor_items
        if self.ce_config["equipments"]:
             armor_data["equipments"] = self.ce_config["equipments"]
             
        if armor_data:
            self._write_yaml_with_footer(armor_data, os.path.join(output_dir, "armor.yml"))

        # 3. 保存 categories.yml (分类)
        if self.ce_config["categories"]:
            cat_data = {"categories": self.ce_config["categories"]}
            self._write_yaml_with_footer(cat_data, os.path.join(output_dir, "categories.yml"))

        # 如果设置了路径，触发资源迁移
        if self.ia_resourcepack_root and self.ce_resourcepack_root:
            migrator = IAMigrator(
                self.ia_resourcepack_root, 
                self.ce_resourcepack_root, 
                self.namespace
            )
            migrator.migrate()
            
        # 写入生成的模型
        if self.ce_resourcepack_root and self.generated_models:
            models_root = os.path.join(self.ce_resourcepack_root, "assets", self.namespace, "models")
            for rel_path, content in self.generated_models.items():
                full_path = os.path.join(models_root, rel_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w', encoding='utf-8') as f:
                    json.dump(content, f, indent=4)

    def convert(self, ia_data, namespace=None):
        if namespace:
            self.namespace = namespace
        elif "info" in ia_data and "namespace" in ia_data["info"]:
            self.namespace = ia_data["info"]["namespace"]

        # 转换物品
        if "items" in ia_data:
            self._convert_items(ia_data["items"])

        # 转换装备 (旧方式)
        if "equipments" in ia_data:
            self._convert_equipments(ia_data["equipments"])
            
        # 转换 armors_rendering (新方式)
        if "armors_rendering" in ia_data:
            self._convert_armors_rendering(ia_data["armors_rendering"])

        # 转换分类
        if "categories" in ia_data:
            self._convert_categories(ia_data["categories"])
        
        # 自动生成分类 (如果不存在)
        if not self.ce_config["categories"] and self.ce_config["items"]:
            self._generate_default_category()

        return self.ce_config

    def _generate_default_category(self):
        """
        当输入未提供分类时，生成一个包含所有物品的默认分类。
        """
        cat_id = f"{self.namespace}:default"
        
        # 收集所有物品 ID
        items_list = list(self.ce_config["items"].keys())
        
        # 尝试寻找合适的图标 (第一个物品)
        icon = "minecraft:chest"
        if items_list:
            first_item = self.ce_config["items"][items_list[0]]
            # 如果物品有自定义模型，尝试使用该物品作为图标
            if "model" in first_item:
                 icon = items_list[0]
            else:
                 icon = first_item.get("material", "minecraft:chest")

        ce_category = {
            "name": f"<!i>{self.namespace.capitalize()}",
            "lore": [
                "<!i><gray>该配置由 <#FFFF00>MMC TOOL</#FFFF00> 自动生成",
                "<!i><gray>闲鱼店铺: <#FFFF00>快乐售货铺</#FFFF00>",
                "<!i><dark_gray>感谢您的支持！</dark_gray>"
            ],
            "priority": 1,
            "icon": icon,
            "list": items_list,
            "hidden": False
        }
        
        self.ce_config["categories"][cat_id] = ce_category

    def _convert_items(self, items_data):
        for item_key, item_data in items_data.items():
            self._convert_item(item_key, item_data)

    def _convert_categories(self, categories_data):
        """
        将 ItemsAdder 分类转换为 CraftEngine 分类
        """
        for cat_key, cat_data in categories_data.items():
            ce_cat_id = f"{self.namespace}:{cat_key}"
            
            # 映射物品列表
            ia_items = cat_data.get("items", [])
            ce_items = []
            for item in ia_items:
                if ":" in item:
                    # 如果包含了命名空间，则尝试替换为当前命名空间
                    parts = item.split(":")
                    if len(parts) == 2:
                        # 强制替换命名空间为当前目标命名空间
                        ce_items.append(f"{self.namespace}:{parts[1]}")
                    else:
                         ce_items.append(item)
                else:
                    ce_items.append(f"{self.namespace}:{item}")

            # 映射图标
            icon = cat_data.get("icon", "minecraft:stone")
            if ":" in icon:
                 parts = icon.split(":")
                 if len(parts) == 2 and parts[0] != "minecraft":
                      icon = f"{self.namespace}:{parts[1]}"
            else:
                 icon = f"{self.namespace}:{icon}"

            ce_category = {
                "name": f"<!i>{cat_data.get('name', cat_key)}",
                "lore": [
                    "<!i><gray>该配置由 <#FFFF00>MMC TOOL</#FFFF00> 生成",
                    "<!i><gray>闲鱼店铺: <#FFFF00>快乐售货铺</#FFFF00>",
                    "<!i><dark_gray>感谢您的支持！</dark_gray>"
                ],
                "priority": 1, # 默认值
                "icon": icon,
                "list": ce_items,
                "hidden": not cat_data.get("enabled", True)
            }
            
            self.ce_config["categories"][ce_cat_id] = ce_category

    def _convert_item(self, key, data):
        ce_id = f"{self.namespace}:{key}"
        
        resource = data.get("resource", {})
        material = resource.get("material", "STONE")
        display_name = data.get("display_name", key)
        
        ce_item = {
            "material": material,
            "data": {
                "item-name": self._format_display_name(display_name, data)
            }
        }

        # 根据材质或行为处理特定类型
        behaviours = data.get("behaviours", {})
        
        if self._is_armor(material, data):
            self._handle_armor(ce_item, data)
        elif behaviours.get("furniture"):
            self._handle_furniture(ce_item, data, ce_id)
        elif self._is_complex_item(material):
            self._handle_complex_item(ce_item, key, data, material)
        elif behaviours.get("hat"):
             ce_item["data"]["equippable"] = {"slot": "head"}
             self._handle_generic_model(ce_item, resource)
        else:
            self._handle_generic_model(ce_item, resource)

        self.ce_config["items"][ce_id] = ce_item

    def _is_armor(self, material, ia_data=None):
        suffixes = ["_HELMET", "_CHESTPLATE", "_LEGGINGS", "_BOOTS"]
        if any(material.endswith(s) for s in suffixes):
            return True
            
        if ia_data:
            if "specific_properties" in ia_data and "armor" in ia_data["specific_properties"]:
                return True
            if "equipment" in ia_data:
                return True
                
        return False

    def _handle_armor(self, ce_item, ia_data):
        equipment_id = None
        slot = "head"

        # 检查旧版 equipment
        if "equipment" in ia_data:
            equipment_id = ia_data["equipment"].get("id")
            
        # 检查 specific_properties armor
        if not equipment_id and "specific_properties" in ia_data:
            armor_props = ia_data["specific_properties"].get("armor", {})
            equipment_id = armor_props.get("custom_armor")
            if "slot" in armor_props:
                slot = armor_props["slot"]

        # 如果需要，从材质推断槽位 (尽管 specific_properties 通常会设置它)
        material = ce_item["material"]
        if material.endswith("_CHESTPLATE"): slot = "chest"
        elif material.endswith("_LEGGINGS"): slot = "legs"
        elif material.endswith("_BOOTS"): slot = "feet"
        
        if equipment_id:
            # 如果材质是默认的 STONE，更新材质以确保其可穿戴
            if ce_item["material"] == "STONE":
                if slot == "head": ce_item["material"] = "LEATHER_HELMET"
                elif slot == "chest": ce_item["material"] = "LEATHER_CHESTPLATE"
                elif slot == "legs": ce_item["material"] = "LEATHER_LEGGINGS"
                elif slot == "feet": ce_item["material"] = "LEATHER_BOOTS"
            
            # 处理 ID 中可能存在的命名空间
            # 形式: namespace:id -> 移除 namespace 部分
            if ":" in equipment_id:
                 equipment_id = equipment_id.split(":")[1]

            ce_item["settings"] = {
                "equipment": {
                    "asset-id": f"{self.namespace}:{equipment_id}",
                    "slot": slot
                }
            }
        
        # 如果存在则添加模型
        self._handle_generic_model(ce_item, ia_data.get("resource", {}))

    def _handle_furniture(self, ce_item, ia_data, ce_id):
        furniture_data = ia_data.get("behaviours", {}).get("furniture", {})
        sit_data = ia_data.get("behaviours", {}).get("furniture_sit")
        entity_type = furniture_data.get("entity", "armor_stand")
        
        # 通过JSON模型计算Y轴偏移量
        model_path = ia_data.get("resource", {}).get("model_path")
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
        
        # 处理放置规则 (Placement)
        placement = {}
        placeable_on = furniture_data.get("placeable_on", {})
        
        # 如果未指定，默认为地面
        if not placeable_on:
            placeable_on = {"floor": True}

        if placeable_on.get("floor"):
            placement["ground"] = self._create_placement_block(ce_id, furniture_data, "ground", sit_data, entity_type, translation_y)
        if placeable_on.get("walls"):
            placement["wall"] = self._create_placement_block(ce_id, furniture_data, "wall", sit_data, entity_type, translation_y)
        if placeable_on.get("ceiling"):
            placement["ceiling"] = self._create_placement_block(ce_id, furniture_data, "ceiling", sit_data, entity_type, translation_y)
            
        ce_item["behavior"]["furniture"]["placement"] = placement

        self._handle_generic_model(ce_item, ia_data.get("resource", {}))

    def _calculate_model_y_translation(self, model_path):
        """
        根据模型元素的 Y 轴坐标计算 Y 轴偏移。
        默认 = 0.5
        如果有负数 Y 坐标且小于 -2.0 -> += 1 (即 1.5)
        如果是正数或微小负数 -> 0.5
        """
        if not model_path or not self.ia_resourcepack_root:
            return 0.5
            
        target_namespace = self.namespace
        clean_path = model_path
        if ":" in model_path:
            parts = model_path.split(":")
            target_namespace = parts[0]
            clean_path = parts[1]
            
        full_path = os.path.join(self.ia_resourcepack_root, "assets", target_namespace, "models", f"{clean_path}.json")
        print(f"Full path: {full_path}")
        if not os.path.exists(full_path):
            return 0.5
            
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                model_data = json.load(f)
                
            elements = model_data.get("elements", [])
            has_negative = False
            for el in elements:
                # 检查 from/to Y 坐标是否小于 -2.0 (索引 1)
                from_y = el.get("from", [0,0,0])[1]
                to_y = el.get("to", [0,0,0])[1]
                
                # 如果 Y 坐标小于 -2.0，认为模型有负数 Y 坐标，防止误差
                if from_y < -2.0 or to_y < -2.0:
                    has_negative = True
                    break
            
            if has_negative:
                return 1.5
            else:
                return 0.5
                
        except Exception as e:
            print(f"Error reading model {full_path}: {e}")
            return 0.5

    def _create_placement_block(self, ce_id, furniture_data, placement_type, sit_data=None, entity_type="armor_stand", custom_translation_y=None):
        """
        创建家具放置块 (ground, wall, ceiling) 的通用配置
        """
        # 计算 Translation
        height = 1
        width = 1
        length = 1
        
        if "hitbox" in furniture_data:
             hitbox = furniture_data["hitbox"]
             height = hitbox.get("height", 1)
             width = hitbox.get("width", 1)
             length = hitbox.get("length", 1)
        
        # Y 轴偏移: 根据模型计算
        if custom_translation_y is not None:
            translation_y = custom_translation_y
        else:
            translation_y = height / 2.0
        
        # 处理 Scale (提前处理以便影响 Translation)
        scale_data = None
        s_x, s_y, s_z = 1.0, 1.0, 1.0
        
        # 优先检查 item_display 的 display_transformation.scale
        if "display_transformation" in furniture_data and "scale" in furniture_data["display_transformation"]:
             scale_data = furniture_data["display_transformation"]["scale"]
        # 其次检查直接的 scale 属性 (向后兼容或 armor_stand)
        elif "scale" in furniture_data:
            scale_data = furniture_data["scale"]
            
        if scale_data and isinstance(scale_data, dict):
            s_x = scale_data.get("x", 1.0)
            s_y = scale_data.get("y", 1.0)
            s_z = scale_data.get("z", 1.0)
            
            # 应用 Scale 修正到 Translation Y
            # 逻辑: translation_y = original_translation_y * max(scale)
            max_scale = max(s_x, s_y, s_z)
            translation_y = translation_y * max_scale

        translation_x = 0
        translation_z = 0
        # X/Z 轴偏移: 针对偶数尺寸的家具进行中心修正
        # 如果尺寸为偶数，模型中心通常在方块边缘，需要偏移 0.5 才能对齐网格
        # translation_x = 0.5 if width % 2 == 0 else 0
        # translation_z = -0.5 if length % 2 == 0 else 0
        
        #临时性针对大型家具模型偏移措施[后期应当修改]
        if height == 2 and width == 3 and length == 2:
            translation_z = 0.5

        element_entry = {
            "item": ce_id,
            "display-transform": "NONE",
            "shadow-radius": 0.4,
            "shadow-strength": 0.5,
            "billboard": "FIXED",
            "translation": f"{translation_x:g},{translation_y:g},{translation_z:g}"
        }

        # 针对墙面家具的修正
        if placement_type == "wall":
            element_entry["position"] = "0.5,0,0.5"
        # 针对天花板家具的修正
        elif placement_type == "ceiling":
            element_entry["position"] = "0,-2,0"

        if scale_data:
            element_entry["scale"] = f"{s_x:g},{s_y:g},{s_z:g}"

        block_config = {
            "loot-spawn-offset": "0,0.4,0",
            "rules": {
                "rotation": "ANY",
                "alignment": "ANY"
            },
            "elements": [element_entry]
        }
        
        # 处理 Hitbox
        #将家具拆分为多个 1x1 的 Shulker 碰撞箱
        if "hitbox" in furniture_data:
            ia_hitbox = furniture_data["hitbox"]
            is_solid = furniture_data.get("solid", True)
            
            # 获取 IA 偏移
            w_offset = ia_hitbox.get("width_offset", 0)
            h_offset = ia_hitbox.get("height_offset", 0)
            l_offset = ia_hitbox.get("length_offset", 0)
            
            # 天花板家具修正：Hitbox 需要向下移动
            if placement_type == "ceiling":
                h_offset -= 1.0

            hitboxes = []
            
            # 只有 solid 的家具才生成 shulker 碰撞箱矩阵
            # 非 solid 的家具可能需要 interaction 类型 (暂不处理或生成单个)
            # 特殊情况: 如果是可坐的 (sit_data)，使用 interaction 类型以支持座位
            # 并且根据 solid 属性设置 blocks-building
            if sit_data:
                # 提取座位高度
                
                ia_sit_height = sit_data.get("sit_height", 0.5)
                ce_seat_y = ia_sit_height - 0.85
                
                # 根据 width 生成多个座位
                # 逻辑：在 X 轴上分布座位
                seats = []
                w_range = int(round(width))
                if w_range <= 1:
                    seats.append(f"0,{ce_seat_y:g},0")
                else:
                    # 居中分布
                    # 例如 width=3: -1, 0, 1
                    # width=2: -0.5, 0.5
                    for i in range(w_range):
                        offset_x = i - (w_range - 1) / 2.0
                        seats.append(f"{offset_x:g},{ce_seat_y:g},0")

                hitboxes.append({
                    "position": f"{w_offset:g},{h_offset:g},{l_offset:g}",
                    "type": "interaction",
                    "blocks-building": is_solid,
                    "width": width,
                    "height": height,
                    "interactive": True,
                    "seats": seats
                })

            elif is_solid:
                # 遍历体积生成 1x1 碰撞箱
                # width -> x, height -> y, length -> z
                # 确保转换为整数循环范围
                w_range = int(round(width))
                h_range = int(round(height))
                l_range = int(round(length))
                
                # 如果尺寸小于 1，至少生成 1 个
                w_range = max(1, w_range)
                h_range = max(1, h_range)
                l_range = max(1, l_range)

                for y in range(h_range):
                    for x in range(w_range):
                        for z in range(l_range):
                            # 计算相对中心的位置
                            # 居中逻辑: (i - (count - 1) / 2)
                            
                            rel_x = x - (w_range - 1) / 2.0
                            rel_y = y 
                            
                            rel_z = z - (l_range - 1) / 2.0
                            
                            # 应用偏移
                            final_x = rel_x + w_offset
                            final_y = rel_y + h_offset
                            final_z = rel_z + l_offset
                            
                            # Shulker 位置应该是整数 (格式化去除 .0)
                            pos_str = f"{final_x:g},{final_y:g},{final_z:g}"
                            
                            hitboxes.append({
                                "position": pos_str,
                                "type": "shulker",
                                "blocks-building": True,
                                "interactive": True
                            })
            else:
                # 非实体，生成一个交互框
                hitboxes.append({
                    "position": f"{w_offset:g},{h_offset:g},{l_offset:g}",
                    "type": "interaction",
                    "blocks-building": False,
                    "width": width,
                    "height": height,
                    "interactive": True
                })

            block_config["hitboxes"] = hitboxes
            
        return block_config

    def _is_complex_item(self, material):
        return material in ["BOW", "CROSSBOW", "FISHING_ROD", "SHIELD"]

    def _handle_complex_item(self, ce_item, key, ia_data, material):
        # 为此物品创建一个模板
        template_id = f"models:{self.namespace}_{key}_model"
        
        
        template_def = {}
        args = {}
        
        resource = ia_data.get("resource", {})
        base_model_path = resource.get("model_path", "")
        
        if material == "BOW":
            template_def = {
                "type": "minecraft:condition",
                "property": "minecraft:using_item",
                "on-false": {"type": "minecraft:model", "path": "${bow_model}"},
                "on-true": {
                    "type": "minecraft:range_dispatch",
                    "property": "minecraft:use_duration",
                    "scale": 0.05,
                    "entries": [
                        {"threshold": 0.65, "model": {"type": "minecraft:model", "path": "${bow_pulling_1_model}"}},
                        {"threshold": 0.9, "model": {"type": "minecraft:model", "path": "${bow_pulling_2_model}"}}
                    ],
                    "fallback": {"type": "minecraft:model", "path": "${bow_pulling_0_model}"}
                }
            }
            # 推断路径
            args["bow_model"] = f"{self.namespace}:item/{base_model_path}"
            args["bow_pulling_0_model"] = f"{self.namespace}:item/{base_model_path}_0"
            args["bow_pulling_1_model"] = f"{self.namespace}:item/{base_model_path}_1"
            args["bow_pulling_2_model"] = f"{self.namespace}:item/{base_model_path}_2"

        elif material == "CROSSBOW":
            template_def = {
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
                         {"threshold": 0.58, "model": {"type": "minecraft:model", "path": "${pulling_1_model}"}},
                         {"threshold": 1.0, "model": {"type": "minecraft:model", "path": "${pulling_2_model}"}}
                     ],
                     "fallback": {"type": "minecraft:model", "path": "${pulling_0_model}"}
                }
            }
            args["model"] = f"{self.namespace}:item/{base_model_path}"
            args["arrow_model"] = f"{self.namespace}:item/{base_model_path}_charged"
            args["firework_model"] = f"{self.namespace}:item/{base_model_path}_firework"
            args["pulling_0_model"] = f"{self.namespace}:item/{base_model_path}_0"
            args["pulling_1_model"] = f"{self.namespace}:item/{base_model_path}_1"
            args["pulling_2_model"] = f"{self.namespace}:item/{base_model_path}_2"
            
        elif material == "SHIELD":
            template_def = {
                "type": "minecraft:condition",
                "property": "minecraft:using_item",
                "on-false": {"type": "minecraft:model", "path": "${shield_model}"},
                "on-true": {"type": "minecraft:model", "path": "${shield_blocking_model}"}
            }
            args["shield_model"] = f"{self.namespace}:item/{base_model_path}"
            args["shield_blocking_model"] = f"{self.namespace}:item/{base_model_path}_blocking"
            
        elif material == "FISHING_ROD":
             template_def = {
                "type": "minecraft:condition",
                "property": "minecraft:fishing_rod/cast",
                "on-false": {"type": "minecraft:model", "path": "${path}"},
                "on-true": {"type": "minecraft:model", "path": "${cast_path}"}
            }
             args["path"] = f"{self.namespace}:item/{base_model_path}"
             args["cast_path"] = f"{self.namespace}:item/{base_model_path}_cast"

        # 注册模板
        self.ce_config["templates"][template_id] = template_def
        
        # 分配给物品
        ce_item["model"] = {
            "template": template_id,
            "arguments": args
        }

    def _handle_generic_model(self, ce_item, resource):
        model_path = resource.get("model_path")
        
        # 情况 1: 显式模型路径
        if model_path:
            # 如果 model_path 中包含命名空间 (例如 "namespace:path")，则移除命名空间部分
            # 因为 CraftEngine 会自动拼接当前命名空间，或者我们手动拼接时避免重复
            if ":" in model_path:
                model_path = model_path.split(":")[1]
                
            ce_item["model"] = {
                "type": "minecraft:model",
                "path": f"{self.namespace}:item/{model_path}"
            }
        
        # 情况 2: 从纹理生成模型
        elif resource.get("generate") is True:
            textures = resource.get("textures")
            
            # 兼容 "texture" 字段 
            if not textures and resource.get("texture"):
                val = resource.get("texture")
                if isinstance(val, list):
                    textures = val
                else:
                    textures = [val]

            if textures:
                # 使用第一个纹理路径作为模型路径的基础
                
                texture_path = textures[0]
                # 如果存在 .png 扩展名则移除 
                if texture_path.endswith(".png"):
                    texture_path = texture_path[:-4]
                    
                ce_item["model"] = {
                    "type": "minecraft:model",
                    "path": f"{self.namespace}:item/{texture_path}"
                }

                # 注册此模型以进行生成
                
                model_key = f"item/{texture_path}.json"
                self.generated_models[model_key] = {
                    "parent": "minecraft:item/generated",
                    "textures": {
                        "layer0": f"{self.namespace}:item/{texture_path}"
                    }
                }

    def _convert_equipments(self, equipments_data):
        for eq_key, eq_data in equipments_data.items():
            ce_eq_id = f"{self.namespace}:{eq_key}"
            
            # 映射 IA 图层到 CE Humanoid 图层
            ce_eq = {
                "type": "component"
            }
            
            if "layer_1" in eq_data:
                ce_eq["humanoid"] = f"{self.namespace}:{eq_data['layer_1']}"
            if "layer_2" in eq_data:
                ce_eq["humanoid-leggings"] = f"{self.namespace}:{eq_data['layer_2']}"
                
            self.ce_config["equipments"][ce_eq_id] = ce_eq

    def _convert_armors_rendering(self, armors_rendering_data):
        """
        将 IA 的 'armors_rendering' 转换为 CraftEngine 的 'equipments'。
        """
        for armor_name, armor_data in armors_rendering_data.items():
            ce_key = f"{self.namespace}:{armor_name}"
            
            ce_entry = {
                "type": "component"
            }
            
            # 映射 layer_1 -> humanoid
            if "layer_1" in armor_data:
                # IA: armor/layer_1
                # CE: namespace:armor/layer_1 
                layer_1_path = armor_data["layer_1"]

                if layer_1_path.endswith(".png"):
                     layer_1_path = layer_1_path[:-4]
                
                ce_entry["humanoid"] = f"{self.namespace}:{layer_1_path}"

            # 映射 layer_2 -> humanoid-leggings
            if "layer_2" in armor_data:
                layer_2_path = armor_data["layer_2"]
                if layer_2_path.endswith(".png"):
                     layer_2_path = layer_2_path[:-4]
                ce_entry["humanoid-leggings"] = f"{self.namespace}:{layer_2_path}"

            self.ce_config["equipments"][ce_key] = ce_entry

    def _format_display_name(self, name, data=None):

        if "&" in name or "§" in name:
            name = name.replace("&", "§")
            pass
            
        # 默认值
        default_color = "<white>"
        if data and "elitecreatures" in self.namespace:
             default_color = "<#FFCF20>"
             
        return f"<!i>{default_color}{name}"
