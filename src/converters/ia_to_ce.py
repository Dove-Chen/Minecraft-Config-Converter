import os
import json
import re
from pathlib import Path
from .base import BaseConverter, RecipeDumper
from src.migrators.ia_to_ce import IAMigrator

class IAConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.ce_config = {
            "items": {},
            "blocks": {},
            "equipments": {},
            "templates": {},
            "images": {},
            "categories": {},
            "recipes": {}
        }
        self.ia_resourcepack_root = None
        self.ce_resourcepack_root = None
        self.generated_models = {} # 存储需要生成的模型
        self.armor_humanoid_keys = set()
        self.armor_leggings_keys = set()
        self.block_texture_keys = set()
        self.block_model_keys = set()
        self.font_image_texture_keys = set()
        self.ia_block_loots_by_type = {}
        self.block_visual_state_counters = {}
        self.ia_font_image_ids = set()

    def set_resource_paths(self, ia_root, ce_root):
        self.ia_resourcepack_root = ia_root
        self.ce_resourcepack_root = ce_root

    def _resolve_configuration_output_dirs(self, output_dir):
        sections = ("items", "blocks", "images", "categories", "recipes")
        fallback_dirs = {section: output_dir for section in sections}
        fallback_dirs["pack_root"] = None

        output_path = Path(output_dir).resolve()
        parts = output_path.parts
        config_index = None
        for index, part in enumerate(parts):
            if part.lower() == "configuration":
                config_index = index

        if config_index is None:
            return fallback_dirs

        config_root = Path(*parts[:config_index + 1])
        package_root = Path(*parts[:config_index]) if config_index > 0 else None
        return {
            "items": str(config_root / "items" / self.namespace),
            "blocks": str(config_root / "blocks" / self.namespace),
            "images": str(config_root / "images" / self.namespace),
            "categories": str(config_root / "categories" / self.namespace),
            "recipes": str(config_root / "recipes" / self.namespace),
            "pack_root": str(package_root) if package_root else None,
        }

    def _write_pack_metadata(self, package_root):
        if not package_root:
            return
        os.makedirs(package_root, exist_ok=True)
        pack_path = os.path.join(package_root, "pack.yml")
        if os.path.exists(pack_path):
            return
        self._write_yaml_with_footer(
            {
                "author": "MCC Tool",
                "version": "1.0.0",
                "description": "Converted from ItemsAdder by MCC Tool",
                "namespace": self.namespace,
            },
            pack_path,
        )

    def save_config(self, output_dir):
        """
        保存转换后的配置到输出目录中的多个文件。
        结构:
        output_dir/
          items.yml       (物品, 模板)
          armor.yml       (物品 - 护甲类型, 装备)
          categories.yml  (分类)
        """
        output_dirs = self._resolve_configuration_output_dirs(output_dir)
        items_output_dir = output_dirs["items"]
        blocks_output_dir = output_dirs["blocks"]
        images_output_dir = output_dirs["images"]
        categories_output_dir = output_dirs["categories"]
        recipes_output_dir = output_dirs["recipes"]

        self._write_pack_metadata(output_dirs.get("pack_root"))

        # 如果目录不存在则创建
        os.makedirs(items_output_dir, exist_ok=True)
        
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
            self._write_yaml_with_footer(items_data, os.path.join(items_output_dir, "items.yml"))

        # 2. 保存 armor.yml (护甲物品 + 装备)
        armor_data = {}
        if armor_items:
             armor_data["items"] = armor_items
        if self.ce_config["equipments"]:
             armor_data["equipments"] = self.ce_config["equipments"]
             
        if armor_data:
            self._write_yaml_with_footer(armor_data, os.path.join(items_output_dir, "armor.yml"))

        if self.ce_config["images"]:
            image_data = {"images": self.ce_config["images"]}
            self._write_yaml_with_footer(image_data, os.path.join(images_output_dir, "images.yml"))

        # 3. 保存 categories.yml (分类)
        if self.ce_config["categories"]:
            cat_data = {"categories": self.ce_config["categories"]}
            self._write_yaml_with_footer(cat_data, os.path.join(categories_output_dir, "categories.yml"))

        if self.ce_config["recipes"]:
            recipe_data = {"recipes": self.ce_config["recipes"]}
            self._write_yaml_with_footer(recipe_data, os.path.join(recipes_output_dir, "recipe.yml"), dumper=RecipeDumper)

        if self.ce_config["blocks"]:
            block_data = {"blocks": self.ce_config["blocks"]}
            self._write_yaml_with_footer(block_data, os.path.join(blocks_output_dir, "blocks.yml"))

        # 如果设置了路径，触发资源迁移
        if self.ia_resourcepack_root and self.ce_resourcepack_root:
            migrator = IAMigrator(
                self.ia_resourcepack_root, 
                self.ce_resourcepack_root, 
                self.namespace,
                self.armor_humanoid_keys,
                self.armor_leggings_keys,
                self.block_texture_keys,
                self.block_model_keys,
                self.font_image_texture_keys
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

        self.ia_block_loots_by_type = self._build_block_loot_index(ia_data.get("loots", {}))
        self.block_visual_state_counters = {}
        self.ia_font_image_ids = set()

        if "font_images" in ia_data:
            self._convert_font_images(ia_data["font_images"])

        # 转换物品
        if "items" in ia_data:
            self._convert_items(ia_data["items"])

        # 转换装备 (旧方式)
        if "equipments" in ia_data:
            self._convert_equipments(ia_data["equipments"])
            
        # 转换 armors_rendering (新方式)
        if "armors_rendering" in ia_data:
            self._convert_armors_rendering(ia_data["armors_rendering"])

        if "legacy_armor_renderings" in ia_data:
            self._convert_armors_rendering(ia_data["legacy_armor_renderings"])

        # 转换分类
        if "categories" in ia_data:
            self._convert_categories(ia_data["categories"])

        if "recipes" in ia_data:
            self._convert_recipes(ia_data["recipes"])
        
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
            icon = items_list[0]

        ce_category = {
            "name": f"<!i>{self.namespace.capitalize()}",
            "lore": [
                "<!i><gray>该配置由 <#FFFF00>MCC TOOL</#FFFF00> 自动生成",
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
    
    def _normalize_equipment_key(self, raw_path):
        if not raw_path:
            return None
        path = str(raw_path)
        if ":" in path:
            path = path.split(":", 1)[1]
        if path.endswith(".png"):
            path = path[:-4]
        path = path.replace("\\", "/").lstrip("/")
        if path.startswith("textures/"):
            path = path[len("textures/"):]
        return path
    
    def _register_equipment_texture(self, raw_path, is_leggings=False):
        key = self._normalize_equipment_key(raw_path)
        if not key:
            return
        if is_leggings:
            self.armor_leggings_keys.add(key)
        else:
            self.armor_humanoid_keys.add(key)

    def _build_resource_data(self, item_data):
        resource = {}
        raw_resource = item_data.get("resource", {})
        if isinstance(raw_resource, dict):
            resource.update(raw_resource)

        material = item_data.get("material")
        if material and "material" not in resource:
            resource["material"] = material

        graphics = item_data.get("graphics", {})
        if isinstance(graphics, dict):
            texture = graphics.get("texture")
            model = graphics.get("model")
            textures = graphics.get("textures")

            if texture:
                resource["textures"] = [texture] if isinstance(texture, str) else texture
                resource.setdefault("generate", True)

            if model:
                resource["model_path"] = model
                resource.setdefault("generate", False)

            if isinstance(textures, dict):
                ordered_keys = [
                    "normal",
                    "pulling_0",
                    "pulling_1",
                    "pulling_2",
                    "arrow",
                    "rocket",
                    "cast",
                    "blocking",
                    "throwing"
                ]
                flattened = []
                for key in ordered_keys:
                    value = textures.get(key)
                    if isinstance(value, str):
                        flattened.append(value)
                for value in textures.values():
                    if isinstance(value, str) and value not in flattened:
                        flattened.append(value)
                if flattened:
                    resource["textures"] = flattened
                    resource.setdefault("generate", True)

        resource.setdefault("material", "STONE")
        return resource

    def _build_block_loot_index(self, loots_data):
        index = {}
        if not isinstance(loots_data, dict):
            return index
        block_loots = loots_data.get("blocks", {})
        if not isinstance(block_loots, dict):
            return index

        for loot_key, loot_data in block_loots.items():
            if not isinstance(loot_data, dict):
                continue
            refs = [loot_key, loot_data.get("type")]
            for ref in refs:
                normalized = self._normalize_custom_id(ref)
                if normalized:
                    index[normalized] = loot_data
        return index

    def _normalize_custom_id(self, value):
        if not isinstance(value, str) or not value.strip():
            return None
        ref = value.strip()
        if ref.startswith("#"):
            return ref
        if ":" in ref:
            ns, path = ref.split(":", 1)
            if ns == "minecraft":
                return f"minecraft:{path.lower()}"
            return f"{self.namespace}:{path}"
        return f"{self.namespace}:{ref}"

    def _has_block_properties(self, item_data):
        return bool(self._get_block_properties(item_data))

    def _get_block_properties(self, item_data):
        specific = item_data.get("specific_properties", {})
        if not isinstance(specific, dict):
            return {}
        block_props = specific.get("block", {})
        return block_props if isinstance(block_props, dict) else {}

    def _first_present(self, *values):
        for value in values:
            if value is not None:
                return value
        return None

    def _normalize_block_state_type(self, block_props):
        placed_model = block_props.get("placed_model", {})
        if not isinstance(placed_model, dict):
            placed_model = {}
        raw_type = str(placed_model.get("type", block_props.get("type", "REAL_NOTE"))).strip().upper()
        mapping = {
            "REAL_NOTE": "note_block",
            "NOTE_BLOCK": "note_block",
            "REAL": "solid",
            "SOLID": "solid",
            "REAL_TRANSPARENT": "chorus",
            "REAL_WIRE": "tripwire",
            "WIRE": "tripwire"
        }
        return mapping.get(raw_type, "note_block")

    def _block_visual_state_family(self, state_type):
        mapping = {
            "note_block": "note_block",
            "solid": "note_block",
            "mushroom": "mushroom_stem",
            "chorus": "chorus_plant",
            "tripwire": "tripwire"
        }
        return mapping.get(state_type, "note_block")

    def _allocate_block_visual_state(self, state_type):
        family = self._block_visual_state_family(state_type)
        base_offsets = {
            "note_block": 1000,
            "mushroom_stem": 0,
            "chorus_plant": 0,
            "tripwire": 0
        }
        index = self.block_visual_state_counters.get(family, 0)
        self.block_visual_state_counters[family] = index + 1
        return f"{family}:{base_offsets.get(family, 0) + index}"

    def _normalize_block_texture_path(self, raw_path):
        if not raw_path:
            return ""
        path = str(raw_path).replace("\\", "/").strip()
        if ":" in path:
            path = path.split(":", 1)[1]
        for prefix in ("textures/", "assets/"):
            if path.startswith(prefix):
                path = path[len(prefix):]
        if path.lower().endswith(".png"):
            path = path[:-4]
        path = path.strip("/")
        if path.startswith("item/"):
            path = path[len("item/"):]
        if path.startswith("block/"):
            path = path[len("block/"):]
        return path

    def _normalize_block_model_path(self, raw_path):
        path = self._normalize_model_path_input(raw_path)
        if path.startswith("models/"):
            path = path[len("models/"):]
        if path.startswith("item/"):
            path = path[len("item/"):]
        if path.startswith("block/"):
            path = path[len("block/"):]
        return path.strip("/")

    def _resource_texture_values(self, resource):
        textures = resource.get("textures")
        if textures is None:
            textures = resource.get("texture")
        if isinstance(textures, str):
            return [textures]
        if isinstance(textures, list):
            return [value for value in textures if isinstance(value, str)]
        if isinstance(textures, dict):
            values = []
            for key in ("all", "side", "top", "bottom", "north", "south", "west", "east"):
                value = textures.get(key)
                if isinstance(value, str):
                    values.append(value)
            for value in textures.values():
                if isinstance(value, str) and value not in values:
                    values.append(value)
            return values
        return []

    def _block_texture_ref(self, raw_texture):
        path = self._normalize_block_texture_path(raw_texture)
        if not path:
            return "minecraft:block/stone"
        self.block_texture_keys.add(path)
        return f"{self.namespace}:block/{path}"

    def _block_model_ref(self, raw_model_path):
        path = self._normalize_block_model_path(raw_model_path)
        if not path:
            return None
        self.block_model_keys.add(path)
        return f"{self.namespace}:block/{path}"

    def _build_block_state_model(self, item_key, resource):
        model_ref = self._block_model_ref(resource.get("model_path"))
        if model_ref:
            return {"path": model_ref}, model_ref

        textures = self._resource_texture_values(resource)
        texture_ref = self._block_texture_ref(textures[0]) if textures else "minecraft:block/stone"
        model_path = self._normalize_block_model_path(item_key) or item_key
        model_ref = f"{self.namespace}:block/{model_path}"
        return {
            "path": model_ref,
            "generation": {
                "parent": "minecraft:block/cube_all",
                "textures": {
                    "all": texture_ref
                }
            }
        }, model_ref

    def _resource_location_to_model_rel(self, value):
        if not isinstance(value, str) or not value.strip():
            return None
        ref = value.strip()
        if ":" in ref:
            ns, path = ref.split(":", 1)
            if ns != self.namespace:
                return None
        else:
            path = ref
        path = path.replace("\\", "/").lstrip("/")
        if path.startswith("models/"):
            path = path[len("models/"):]
        if path.endswith(".json"):
            path = path[:-5]
        return f"{path}.json"

    def _register_block_generated_models(self, item_key, state_model, block_model_ref):
        if not isinstance(state_model, dict):
            return

        block_model_rel = self._resource_location_to_model_rel(state_model.get("path"))
        generation = state_model.get("generation")
        if block_model_rel and isinstance(generation, dict):
            parent = generation.get("parent", "minecraft:block/cube_all")
            textures = generation.get("textures", {})
            self.generated_models[block_model_rel] = {
                "parent": parent,
                "textures": textures if isinstance(textures, dict) else {}
            }

        item_model_rel = self._resource_location_to_model_rel(f"{self.namespace}:item/{item_key}")
        if item_model_rel and block_model_ref:
            self.generated_models[item_model_rel] = {
                "parent": block_model_ref
            }

    def _normalize_block_sound(self, value):
        if isinstance(value, dict):
            value = value.get("name") or value.get("sound") or value.get("id")
        if not isinstance(value, str) or not value.strip():
            return None
        sound = value.strip()
        if ":" in sound:
            return sound
        sound = sound.lower()
        if sound.startswith("block_"):
            sound = "block." + sound[len("block_"):].replace("_", ".")
        return f"minecraft:{sound}"

    def _build_block_sounds(self, block_props):
        sounds = {}
        raw_sounds = block_props.get("sound") or block_props.get("sounds")
        if not isinstance(raw_sounds, dict):
            return sounds
        for ce_key, ia_key in (
            ("break", "break"),
            ("place", "place"),
            ("hit", "hit"),
            ("step", "step"),
            ("fall", "fall")
        ):
            sound = self._normalize_block_sound(raw_sounds.get(ia_key))
            if sound:
                sounds[ce_key] = sound
        return sounds

    def _build_block_tags(self, block_props):
        tags = []
        tools = block_props.get("break_tools_whitelist") or block_props.get("tools_whitelist")
        if isinstance(tools, str):
            tools = [tools]
        if isinstance(tools, list):
            tool_text = " ".join(str(tool).lower() for tool in tools)
            tool_tags = {
                "pickaxe": "minecraft:mineable/pickaxe",
                "axe": "minecraft:mineable/axe",
                "shovel": "minecraft:mineable/shovel",
                "hoe": "minecraft:mineable/hoe"
            }
            for token, tag in tool_tags.items():
                if token in tool_text and tag not in tags:
                    tags.append(tag)
        return tags

    def _build_ce_block_settings(self, ce_id, block_props):
        placed_model = block_props.get("placed_model", {})
        if not isinstance(placed_model, dict):
            placed_model = {}

        settings = {"item": ce_id}
        hardness = self._first_present(block_props.get("hardness"), placed_model.get("hardness"))
        if hardness is not None:
            settings["hardness"] = hardness
        resistance = self._first_present(
            block_props.get("resistance"),
            block_props.get("blast_resistance"),
            block_props.get("blast-resistant")
        )
        if resistance is not None:
            settings["resistance"] = resistance
        luminance = self._first_present(block_props.get("luminance"), block_props.get("light_level"))
        if luminance is not None:
            settings["luminance"] = luminance
        sounds = self._build_block_sounds(block_props)
        if sounds:
            settings["sounds"] = sounds
        tags = self._build_block_tags(block_props)
        if tags:
            settings["tags"] = tags
        return settings

    def _ia_block_drops_self(self, block_props):
        if "drop_when_mined" in block_props:
            return bool(block_props.get("drop_when_mined"))
        if "cancel_drop" in block_props:
            return not bool(block_props.get("cancel_drop"))
        return True

    def _normalize_loot_count(self, drop_data):
        if not isinstance(drop_data, dict):
            return None
        min_amount = drop_data.get("min_amount")
        max_amount = drop_data.get("max_amount")
        amount = drop_data.get("amount")
        if min_amount is not None and max_amount is not None:
            if min_amount == max_amount:
                return min_amount
            return f"{min_amount}~{max_amount}"
        if amount is not None:
            return amount
        return None

    def _build_ce_loot_entry(self, item_id, drop_data=None):
        entry = {
            "type": "item",
            "item": self._normalize_custom_id(item_id) or item_id
        }
        count = self._normalize_loot_count(drop_data)
        if count is not None and count != 1:
            entry["functions"] = [{"type": "set_count", "count": count}]
        if isinstance(drop_data, dict):
            chance = drop_data.get("chance")
            if chance is not None:
                try:
                    chance_value = float(chance)
                    if chance_value < 100:
                        entry["conditions"] = [{"type": "random_chance", "chance": chance_value / 100.0}]
                except (TypeError, ValueError):
                    pass
        return entry

    def _build_ce_block_loot(self, ce_id, block_props):
        loot_data = self.ia_block_loots_by_type.get(ce_id)
        entries = []
        if isinstance(loot_data, dict):
            for drop_key, drop_data in loot_data.get("items", {}).items():
                if isinstance(drop_data, dict):
                    drop_item = drop_data.get("item") or drop_key
                    entries.append(self._build_ce_loot_entry(drop_item, drop_data))
                else:
                    entries.append(self._build_ce_loot_entry(drop_data or drop_key))

        if not entries and self._ia_block_drops_self(block_props):
            entries.append(self._build_ce_loot_entry(ce_id))

        if not entries:
            return None

        return {
            "pools": [
                {
                    "rolls": 1,
                    "conditions": [{"type": "survives_explosion"}],
                    "entries": entries
                }
            ]
        }

    def _handle_block(self, ce_item, item_key, ia_data, ce_id):
        block_props = self._get_block_properties(ia_data)
        resource = self._build_resource_data(ia_data)
        state_model, block_model_ref = self._build_block_state_model(item_key, resource)
        self._register_block_generated_models(item_key, state_model, block_model_ref)
        visual_state_type = self._normalize_block_state_type(block_props)

        ce_item["behavior"] = {
            "type": "block_item",
            "block": ce_id
        }
        ce_item["model"] = {
            "type": "minecraft:model",
            "path": f"{self.namespace}:item/{item_key}",
            "generation": {
                "parent": block_model_ref
            }
        }

        ce_block = {
            "settings": self._build_ce_block_settings(ce_id, block_props),
            "state": {
                "state": self._allocate_block_visual_state(visual_state_type),
                "model": state_model
            }
        }

        loot = self._build_ce_block_loot(ce_id, block_props)
        if loot:
            ce_block["loot"] = loot

        self.ce_config["blocks"][ce_id] = ce_block
    
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
        subpath = parts[-1] if parts else "unknown"
        target_folder = "humanoid_leggings" if is_leggings else "humanoid"
        final_path = f"entity/equipment/{target_folder}/{subpath}" if subpath else f"entity/equipment/{target_folder}"
        return f"{self.namespace}:{final_path}"

    def _convert_font_images(self, font_images_data):
        if not isinstance(font_images_data, dict):
            return
        self.ia_font_image_ids = {str(image_id) for image_id in font_images_data.keys()}
        for raw_id, image_data in font_images_data.items():
            if not isinstance(image_data, dict):
                continue
            local_id = self._local_image_id(raw_id)
            if not local_id:
                continue

            ce_image = {}
            file_value = image_data.get("path") or image_data.get("file") or image_data.get("texture")
            if file_value:
                ce_image["file"] = self._normalize_ce_image_file(file_value)
                texture_key = self._normalize_font_image_texture_key(file_value)
                if texture_key:
                    self.font_image_texture_keys.add(texture_key)

            height = image_data.get("scale_ratio", image_data.get("height"))
            if height is not None:
                ce_image["height"] = height
            ascent = image_data.get("y_position", image_data.get("ascent"))
            if ascent is not None:
                ce_image["ascent"] = ascent

            font = image_data.get("font")
            ce_image["font"] = font if font else "minecraft:default"

            char = image_data.get("symbol") or image_data.get("char")
            if char:
                ce_image["char"] = char
            if "shadow" in image_data:
                ce_image["shadow"] = bool(image_data["shadow"])

            self.ce_config["images"][f"{self.namespace}:{local_id}"] = ce_image

    def _local_image_id(self, raw_id):
        if raw_id is None:
            return ""
        image_id = str(raw_id).strip()
        if ":" in image_id:
            image_id = image_id.split(":", 1)[1]
        return image_id

    def _normalize_font_image_texture_key(self, raw_path):
        if not raw_path:
            return ""
        path = str(raw_path).replace("\\", "/").strip()
        if ":" in path:
            path = path.split(":", 1)[1]
        for prefix in ("assets/", "textures/"):
            if path.startswith(prefix):
                path = path[len(prefix):]
        if path.startswith(f"{self.namespace}/"):
            path = path[len(self.namespace) + 1:]
        path = path.strip("/")
        if path.endswith(".png"):
            path = path[:-4]
        return path

    def _normalize_ce_image_file(self, raw_path):
        path = str(raw_path).replace("\\", "/").strip()
        if ":" in path:
            ns, rel = path.split(":", 1)
            if ns == "minecraft":
                return f"minecraft:{rel.strip('/')}"
            path = rel
        for prefix in ("assets/", "textures/"):
            if path.startswith(prefix):
                path = path[len(prefix):]
        if path.startswith(f"{self.namespace}/"):
            path = path[len(self.namespace) + 1:]
        return f"{self.namespace}:{path.strip('/')}"

    def _convert_ia_text(self, value):
        if not isinstance(value, str):
            return value
        text = re.sub(r"%img_offset_(-?\d+)%", r"<shift:\1>", value)
        text = re.sub(r":offset_(-?\d+):", r"<shift:\1>", text)

        def replace_percent(match):
            image_id = match.group(1)
            if image_id in self.ia_font_image_ids:
                return f"<image:{self.namespace}:{image_id}>"
            return match.group(0)

        def replace_colon(match):
            image_id = match.group(1)
            if image_id in self.ia_font_image_ids:
                return f"<image:{self.namespace}:{image_id}>"
            return match.group(0)

        text = re.sub(r"%img_([A-Za-z0-9_.-]+)%", replace_percent, text)
        return re.sub(r":([A-Za-z0-9_.-]+):", replace_colon, text)

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
            # 逻辑变更：优先使用列表中的第一个物品作为图标
            # 检查第一个物品是否存在于 ce_config['items'] 中
            icon = None
            if ce_items:
                potential_icon = ce_items[0]
                # 移除命名空间进行检查 (如果存在)
                check_id = potential_icon
                if check_id in self.ce_config["items"]:
                    icon = potential_icon
            
            if not icon:
                # 只有当列表为空或第一个物品无效时，才尝试使用配置中的 icon 或默认值
                icon = cat_data.get("icon", "minecraft:stone")
                if ":" in icon:
                     parts = icon.split(":")
                     if len(parts) == 2 and parts[0] != "minecraft":
                          icon = f"{self.namespace}:{parts[1]}"
                elif icon != "minecraft:stone":
                     icon = f"{self.namespace}:{icon}"

            # Remove Minecraft color codes (e.g. §6) from category name
            cat_name = cat_data.get('name', cat_key)
            if isinstance(cat_name, str):
                cat_name = re.sub(r'[§搂][0-9a-fk-or]', '', cat_name)

            ce_category = {
                "name": f"<!i>{self._convert_ia_text(cat_name)}",
                "lore": [
                    "<!i><gray>该配置由 <#FFFF00>MCC TOOL</#FFFF00> 生成",
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
        
        resource = self._build_resource_data(data)
        material = resource.get("material", "STONE")
        display_name = data.get("name") or data.get("display_name", key)
        
        ce_item = {
            "material": material,
            "data": {
                "item_name": self._format_display_name(display_name, data)
            }
        }
        
        lore_value = data.get("lore")
        if lore_value is not None:
            ce_lore = self._normalize_lore(lore_value)
            if ce_lore is not None:
                ce_item["data"]["lore"] = ce_lore
        
        if "model_id" in resource:
            ce_item["custom_model_data"] = resource["model_id"]

        # 根据材质或行为处理特定类型
        behaviours = data.get("behaviours", {})
        
        # 优先处理 Hat 或 带有 equipment 但无 ID 的物品 (视为简单装备/帽子)
        if behaviours.get("hat") or ("equipment" in data and "id" not in data["equipment"]):
             ce_item["data"]["equippable"] = {"slot": "head"}
             self._handle_generic_model(ce_item, resource)
        elif self._is_armor(material, data):
            self._handle_armor(ce_item, data)
        elif self._has_block_properties(data):
            self._handle_block(ce_item, key, data, ce_id)
        elif behaviours.get("furniture"):
            self._handle_furniture(ce_item, data, ce_id)
        elif self._is_complex_item(material):
            self._handle_complex_item(ce_item, key, data, material)
        else:
            self._handle_generic_model(ce_item, resource)

        self.ce_config["items"][ce_id] = ce_item

    def _convert_recipes(self, recipes_data):
        if not isinstance(recipes_data, dict):
            return
        for group_key, group_data in recipes_data.items():
            if not isinstance(group_data, dict):
                continue
            for recipe_key, recipe_data in group_data.items():
                if not isinstance(recipe_data, dict):
                    continue
                if recipe_data.get("enabled") is False:
                    continue
                for ce_recipe_id, ce_type, variant_data in self._iter_recipe_variants(group_key, recipe_key, recipe_data):
                    if not ce_recipe_id:
                        continue
                    ce_recipe = self._build_ce_recipe(ce_type, variant_data)
                    if ce_recipe:
                        self.ce_config["recipes"][ce_recipe_id] = ce_recipe

    def _iter_recipe_variants(self, group_key, recipe_key, recipe_data):
        ce_type = self._map_recipe_type(group_key, recipe_data)
        if ce_type is None:
            return

        machine_types = self._map_cooking_machines(recipe_data.get("machines"))
        if str(group_key).lower() == "cooking" and machine_types:
            for machine_type in machine_types:
                yield self._normalize_recipe_id(f"{recipe_key}_{machine_type}"), machine_type, recipe_data
            return

        if ce_type == "shaped":
            patterns = self._extract_recipe_patterns(recipe_data)
            if len(patterns) > 1:
                for suffix, pattern in patterns:
                    variant_data = dict(recipe_data)
                    variant_data["pattern"] = pattern
                    variant_key = recipe_key if not suffix else f"{recipe_key}_{suffix}"
                    yield self._normalize_recipe_id(variant_key), ce_type, variant_data
                return

        yield self._normalize_recipe_id(recipe_key), ce_type, recipe_data

    def _build_ce_recipe(self, ce_type, recipe_data):
        ce_recipe = {}
        if ce_type:
            ce_recipe["type"] = ce_type
        if ce_type == "shaped":
            pattern = recipe_data.get("pattern")
            ingredients = recipe_data.get("ingredients", {})
            if pattern:
                ce_recipe["pattern"] = self._normalize_pattern(pattern, ingredients)
            if ingredients:
                ce_recipe["ingredients"] = {
                    k: self._normalize_recipe_item(v) for k, v in ingredients.items()
                }
        elif ce_type == "shapeless":
            ingredients = recipe_data.get("ingredients", [])
            ce_recipe["ingredients"] = self._normalize_shapeless_ingredients(ingredients)
        elif ce_type in ["smelting", "blasting", "smoking", "campfire_cooking"]:
            ingredient = recipe_data.get("ingredient")
            if ingredient is None:
                ingredient = recipe_data.get("ingredients")
            if isinstance(ingredient, list):
                ingredient = ingredient[0] if ingredient else None
            if ingredient is not None:
                ce_recipe["ingredient"] = self._normalize_recipe_item(ingredient)
            experience = recipe_data.get("experience")
            if experience is None:
                experience = recipe_data.get("exp")
            if experience is not None:
                ce_recipe["experience"] = experience
            time_val = recipe_data.get("time")
            if time_val is None:
                time_val = recipe_data.get("cook_time")
            if time_val is None:
                time_val = recipe_data.get("cookingTime")
            if time_val is not None:
                ce_recipe["time"] = time_val
            category = recipe_data.get("category")
            if category:
                ce_recipe["category"] = category
            group_val = recipe_data.get("group")
            if group_val:
                ce_recipe["group"] = group_val
        elif ce_type == "stonecutting":
            ingredient = recipe_data.get("ingredient")
            if ingredient is not None:
                ce_recipe["ingredient"] = self._normalize_recipe_item(ingredient)
            group_val = recipe_data.get("group")
            if group_val:
                ce_recipe["group"] = group_val
        elif ce_type == "smithing_transform":
            template = recipe_data.get("template") or recipe_data.get("template-type")
            base = recipe_data.get("base")
            addition = recipe_data.get("addition")
            if template:
                ce_recipe["template-type"] = self._normalize_recipe_item(template)
            if base:
                ce_recipe["base"] = self._normalize_recipe_item(base)
            if addition:
                ce_recipe["addition"] = self._normalize_recipe_item(addition)
            merge_components = recipe_data.get("merge-components")
            if merge_components is not None:
                ce_recipe["merge-components"] = merge_components
        elif ce_type == "brewing":
            ingredient = recipe_data.get("ingredient")
            container = recipe_data.get("container")
            if ingredient:
                ce_recipe["ingredient"] = self._normalize_recipe_item(ingredient)
            if container:
                ce_recipe["container"] = self._normalize_recipe_item(container)

        result = recipe_data.get("result")
        if result is not None:
            result_id = None
            result_count = None
            if isinstance(result, dict):
                result_id = result.get("item") or result.get("id")
                result_count = result.get("amount") or result.get("count")
            else:
                result_id = result
            if result_id is not None:
                ce_result = {"id": self._normalize_recipe_item(result_id)}
                if result_count is None:
                    result_count = 1
                ce_result["count"] = result_count
                ce_recipe["result"] = ce_result

        return ce_recipe

    def _normalize_recipe_id(self, raw_id):
        if not raw_id:
            return None
        raw_id = str(raw_id)
        if ":" in raw_id:
            return raw_id
        return f"{self.namespace}:{raw_id}"

    def _normalize_recipe_item(self, value):
        if value is None:
            return value
        if isinstance(value, dict):
            item_id = value.get("item") or value.get("id")
            if item_id is None:
                return None
            return self._normalize_recipe_item(item_id)
        if isinstance(value, str):
            item = value.strip()
            if not item:
                return item
            if item.startswith("#"):
                tag = item[1:]
                if ":" in tag:
                    ns, path = tag.split(":", 1)
                    if ns == "minecraft":
                        return f"#minecraft:{path.lower()}"
                    return f"#{ns}:{path}"
                return f"#minecraft:{tag.lower()}"
            if ":" in item:
                ns, path = item.split(":", 1)
                if ns == "minecraft":
                    return f"minecraft:{path.lower()}"
                return f"{ns}:{path}"
            custom_ref = self._normalize_known_custom_recipe_item(item)
            if custom_ref:
                return custom_ref
            return f"minecraft:{item.lower()}"
        return value

    def _normalize_known_custom_recipe_item(self, item):
        if not isinstance(item, str):
            return None
        candidates = [
            item,
            item.lower()
        ]
        for candidate in candidates:
            if f"{self.namespace}:{candidate}" in self.ce_config["items"]:
                return f"{self.namespace}:{candidate}"
        return None

    def _normalize_pattern(self, pattern, ingredients):
        if not isinstance(pattern, list):
            return pattern
        keys = set(ingredients.keys()) if isinstance(ingredients, dict) else set()
        normalized = []
        for row in pattern:
            row_str = str(row)
            if not keys:
                normalized.append(row_str)
                continue
            new_row = "".join(ch if ch in keys else " " for ch in row_str)
            normalized.append(new_row)
        return normalized

    def _normalize_shapeless_ingredients(self, ingredients):
        if isinstance(ingredients, list):
            normalized = []
            for item in ingredients:
                if isinstance(item, list):
                    normalized.append([self._normalize_recipe_item(x) for x in item])
                else:
                    normalized.append(self._normalize_recipe_item(item))
            return normalized
        if isinstance(ingredients, dict):
            return [self._normalize_recipe_item(v) for v in ingredients.values()]
        return ingredients

    def _extract_recipe_patterns(self, recipe_data):
        patterns = []
        base_pattern = recipe_data.get("pattern")
        if base_pattern:
            patterns.append(("", base_pattern))

        indexed_patterns = []
        for key, value in recipe_data.items():
            if not isinstance(key, str) or not key.startswith("pattern_"):
                continue
            suffix = key[len("pattern_"):]
            if not suffix:
                continue
            indexed_patterns.append((suffix, value))
        indexed_patterns.sort(key=lambda item: (not item[0].isdigit(), int(item[0]) if item[0].isdigit() else item[0]))
        patterns.extend(indexed_patterns)
        return patterns

    def _map_cooking_machines(self, machines):
        if machines is None:
            return []
        if isinstance(machines, str):
            raw_machines = [machines]
        elif isinstance(machines, list):
            raw_machines = machines
        else:
            return []

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
            "campfire-cooking": "campfire_cooking"
        }
        result = []
        for machine in raw_machines:
            key = str(machine).strip().lower()
            ce_type = mapping.get(key)
            if ce_type and ce_type not in result:
                result.append(ce_type)
        return result

    def _map_recipe_type(self, group_key, recipe_data):
        group = str(group_key).lower()
        if isinstance(recipe_data, dict):
            if recipe_data.get("shapeless") is True:
                return "shapeless"
            machine_types = self._map_cooking_machines(recipe_data.get("machines"))
            if group == "cooking" and machine_types:
                return machine_types[0]
        mapping = {
            "crafting_table": "shaped",
            "shapeless": "shapeless",
            "shapeless_crafting": "shapeless",
            "furnace": "smelting",
            "smelting": "smelting",
            "blast_furnace": "blasting",
            "blasting": "blasting",
            "smoker": "smoking",
            "smoking": "smoking",
            "campfire": "campfire_cooking",
            "campfire_cooking": "campfire_cooking",
            "cooking": "smelting",
            "stonecutting": "stonecutting",
            "smithing": "smithing_transform",
            "smithing_transform": "smithing_transform",
            "brewing": "brewing"
        }
        if group in mapping:
            return mapping[group]
        if isinstance(recipe_data, dict):
            if "pattern" in recipe_data:
                return "shaped"
            if isinstance(recipe_data.get("ingredients"), list):
                return "shapeless"
        return None

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
        
        # 统一槽位大小写，避免 FEET/Head 等写法导致后续逻辑失效
        def _normalize_slot(raw_slot):
            if raw_slot is None:
                return None
            slot_map = {
                "head": "head",
                "helmet": "head",
                "chest": "chest",
                "chestplate": "chest",
                "legs": "legs",
                "leggings": "legs",
                "feet": "feet",
                "boots": "feet"
            }
            key = str(raw_slot).strip().lower()
            return slot_map.get(key, key)

        # 检查旧版 equipment
        if "equipment" in ia_data:
            equipment_id = ia_data["equipment"].get("id")
            
        # 检查 specific_properties armor
        if not equipment_id and "specific_properties" in ia_data:
            armor_props = ia_data["specific_properties"].get("armor", {})
            equipment_id = armor_props.get("custom_armor")
            if "slot" in armor_props:
                slot = _normalize_slot(armor_props["slot"]) or slot

        # 如果需要，从材质推断槽位 (尽管 specific_properties 通常会设置它)
        material = ce_item["material"]
        if material.endswith("_CHESTPLATE"): slot = "chest"
        elif material.endswith("_LEGGINGS"): slot = "legs"
        elif material.endswith("_BOOTS"): slot = "feet"
        
        if equipment_id:
            # 如果材质是默认的 STONE，更新材质以确保其可穿戴
            if ce_item["material"] == "STONE":
                if slot == "head": ce_item["material"] = "DIAMOND_HELMET"
                elif slot == "chest": ce_item["material"] = "DIAMOND_CHESTPLATE"
                elif slot == "legs": ce_item["material"] = "DIAMOND_LEGGINGS"
                elif slot == "feet": ce_item["material"] = "DIAMOND_BOOTS"
            
            # 处理 ID 中可能存在的命名空间
            # 形式: namespace:id -> 移除 namespace 部分
            if ":" in equipment_id:
                 equipment_id = equipment_id.split(":")[1]

            ce_item["settings"] = {
                "equipment": {
                    "asset_id": f"{self.namespace}:{equipment_id}",
                    "slot": slot
                }
            }
        
        # 如果存在则添加模型
        self._handle_generic_model(ce_item, self._build_resource_data(ia_data))

    def _handle_furniture(self, ce_item, ia_data, ce_id):
        furniture_data = ia_data.get("behaviours", {}).get("furniture", {})
        sit_data = ia_data.get("behaviours", {}).get("furniture_sit")
        entity_type = furniture_data.get("entity", "armor_stand")
        
        # 通过JSON模型计算Y轴偏移量
        resource = self._build_resource_data(ia_data)
        model_path = resource.get("model_path")
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

        self._handle_generic_model(ce_item, resource)

    def _calculate_model_y_translation(self, model_path):
        """
        根据模型元素的 Y 轴坐标计算 Y 轴偏移。
        默认 = 0.5
        如果有负数 Y 坐标且小于 -2.0 -> += 1 (即 1.5)
        如果是正数或微小负数 -> 0.5
        """
        if not model_path or not self.ia_resourcepack_root:
            return 0.5
        
        # 确保 model_path 是字符串
        model_path = str(model_path)
            
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
                # 检查 from/to Y 坐标是否小于 -7.0 (索引 1)
                from_y = el.get("from", [0,0,0])[1]
                to_y = el.get("to", [0,0,0])[1]
                
                # 如果 Y 坐标小于 -7.0，认为模型有负数 Y 坐标，防止误差
                if from_y < -7.0 or to_y < -7.0:
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
        display_transformation = furniture_data.get("display_transformation") or {}
        if "scale" in display_transformation:
             scale_data = display_transformation["scale"]
        # 其次检查直接的 scale 属性 (向后兼容或 armor_stand)
        elif "scale" in furniture_data:
            scale_data = furniture_data["scale"]
            
        if scale_data and isinstance(scale_data, dict):
            s_x = scale_data.get("x", 1.0)
            s_y = scale_data.get("y", 1.0)
            s_z = scale_data.get("z", 1.0)
            
            scale_flag = False
            # 针对 shizuart 作者的优化
            if "shizuart" in self.namespace.lower():
                s_x *= 2.0
                s_y *= 2.0
                s_z *= 2.0
                scale_flag = True
            # 应用 Scale 修正到 Translation Y
            # 逻辑: translation_y = original_translation_y * max(scale)
            max_scale = max(s_x, s_y, s_z)
            if scale_flag == False:
                translation_y = translation_y * max_scale
        # 如果是天花板或墙面家具就将 Y 轴偏移设为 0
        if placement_type == "ceiling" or placement_type == "wall":
            translation_y = 0
        translation_x = 0
        translation_z = 0
        # X/Z 轴偏移: 针对偶数尺寸的家具进行中心修正
        # 如果尺寸为偶数，模型中心通常在方块边缘，需要偏移 0.5 才能对齐网格
        # translation_x = 0.5 if width % 2 == 0 else 0
        # translation_z = -0.5 if length % 2 == 0 else 0
        
        #临时性针对大型家具模型偏移措施[后期应当修改]
        if height == 2 and width == 3 and length == 2:
            translation_z = 0.5

        # 处理 Rotation (display_transformation)
        rotation_str = None
        
        # 仅当 placement_type 为 wall 时才处理 rotation
        if placement_type == "wall":
            # 检查 right_rotation
            # 规则: angle 为 -90 时取正数 (绝对值)
            if "right_rotation" in display_transformation:
                rr = display_transformation["right_rotation"]
                if isinstance(rr, dict) and "axis_angle" in rr:
                    angle = rr["axis_angle"].get("angle", 0)
                    axis = rr["axis_angle"].get("axis", {"x": 0, "y": 0, "z": 0})
                    
                    # 取绝对值
                    angle = abs(angle)
                    
                    rx = angle if axis.get("x") else 0
                    ry = angle if axis.get("y") else 0
                    rz = angle if axis.get("z") else 0
                    
                    if rx != 0 or ry != 0 or rz != 0:
                        rotation_str = f"{rx:g},{ry:g},{rz:g}"

            # 检查 left_rotation (覆盖 right_rotation)
            # 规则: angle 不变
            if "left_rotation" in display_transformation:
                lr = display_transformation["left_rotation"]
                if isinstance(lr, dict) and "axis_angle" in lr:
                    angle = lr["axis_angle"].get("angle", 0)
                    axis = lr["axis_angle"].get("axis", {"x": 0, "y": 0, "z": 0})
                    
                    rx = angle if axis.get("x") else 0
                    ry = angle if axis.get("y") else 0
                    rz = angle if axis.get("z") else 0
                    
                    if rx != 0 or ry != 0 or rz != 0:
                        rotation_str = f"{rx:g},{ry:g},{rz:g}"

        element_entry = {
            "item": ce_id,
            "display_transform": "none",
            # "shadow-radius": 0.4,
            # "shadow-strength": 0.5,
            "billboard": "FIXED",
            "translation": f"{translation_x:g},{translation_y:g},{translation_z:g}"
        }
        
        if rotation_str:
            element_entry["rotation"] = rotation_str

        # 针对墙面家具的修正
        if placement_type == "wall":
            element_entry["position"] = "0,0,0.5"
        # 针对天花板家具的修正
        elif placement_type == "ceiling":
            element_entry["position"] = "0,-1,0"

        if scale_data:
            element_entry["scale"] = f"{s_x:g},{s_y:g},{s_z:g}"

        block_config = {
            "loot_spawn_offset": "0,0.4,0",
            "rules": {
                "rotation": "eight",
                "alignment": "center"
            },
            "elements": [element_entry]
        }
        
        # 处理 Hitbox
        #将家具拆分为多个 1x1 的 Shulker 碰撞箱
        # 墙面家具不需要碰撞箱
        hitboxes = []
        
        # 获取 IA 偏移 (如果有 hitbox 定义)
        w_offset = 0
        h_offset = 0
        l_offset = 0
        
        has_hitbox_def = "hitbox" in furniture_data
        if has_hitbox_def:
            ia_hitbox = furniture_data["hitbox"]
            w_offset = ia_hitbox.get("width_offset", 0)
            h_offset = ia_hitbox.get("height_offset", 0)
            l_offset = ia_hitbox.get("length_offset", 0)

        # 天花板家具修正：Hitbox 需要向下移动
        if placement_type == "ceiling":
            h_offset -= height

        is_solid = furniture_data.get("solid", True)
        
        # 逻辑修改: 即使没有 hitbox 定义，只要有 sit_data，也应该生成交互碰撞箱
        # 或者如果有 hitbox 定义
        
        if placement_type != "wall":
            if sit_data:
                # 提取座位高度
                ia_sit_height = sit_data.get("sit_height", 0.5)
                # 修正: 保持原有的计算逻辑，但移除 hitbox 依赖
                ce_seat_y = ia_sit_height - 0.85
                
                # 根据 width 生成多个座位
                seats = []
                w_range = int(round(width))
                if w_range <= 1:
                    seats.append(f"0,{ce_seat_y:g},0")
                else:
                    for i in range(w_range):
                        offset_x = i - (w_range - 1) / 2.0
                        seats.append(f"{offset_x:g},{ce_seat_y:g},0")

                hitboxes.append({
                    "position": f"{w_offset:g},{h_offset:g},{l_offset:g}",
                    "type": "interaction",
                    "blocks_building": is_solid,
                    "width": width,
                    "height": height,
                    "interactive": True,
                    "seats": seats
                })
            
            elif has_hitbox_def:
                if is_solid:
                    # 遍历体积生成 1x1 碰撞箱
                    w_range = int(round(width))
                    h_range = int(round(height))
                    l_range = int(round(length))
                    
                    w_range = max(1, w_range)
                    h_range = max(1, h_range)
                    l_range = max(1, l_range)

                    for y in range(h_range):
                        for x in range(w_range):
                            for z in range(l_range):
                                rel_x = x - (w_range - 1) / 2.0
                                rel_y = y 
                                rel_z = z - (l_range - 1) / 2.0
                                
                                final_x = rel_x + w_offset
                                final_y = rel_y + h_offset
                                final_z = rel_z + l_offset
                                
                                import math
                                final_x = math.floor(final_x + 0.5)
                                final_y = math.floor(final_y + 0.5)
                                final_z = math.floor(final_z + 0.5)
                                
                                pos_str = f"{int(final_x)},{int(final_y)},{int(final_z)}"
                                
                                hitboxes.append({
                                    "position": pos_str,
                                    "type": "shulker",
                                    "blocks_building": True,
                                    "interactive": True
                                })
                else:
                    # 非实体，生成一个交互框
                    hitboxes.append({
                        "position": f"{w_offset:g},{h_offset:g},{l_offset:g}",
                        "type": "interaction",
                        "blocks_building": False,
                        "width": width,
                        "height": height,
                        "interactive": True
                    })

        if placement_type == "ceiling" and not hitboxes:
            # 针对没有碰撞体积的情况下天花板家具要额外加入 position: 0,-1,0
            hitboxes.append({
                "type": "interaction",
                "position": "0,-1,0",
                "width": width,
                "height": height,
                "interactive": True,
                "blocks_building": False
            })

        elif placement_type == "wall" and not hitboxes:
            # 针对没有碰撞体积的情况下墙面家具要额外加入 position: 0,-0.5,0
            hitboxes.append({
                "type": "interaction",
                "position": "0,-0.5,0",
                "width": width,
                "height": height,
                "interactive": True,
                "blocks_building": False
            })

        if hitboxes:
            block_config["hitboxes"] = hitboxes
            
        return block_config

    def _is_complex_item(self, material):
        return material in ["BOW", "CROSSBOW", "FISHING_ROD", "SHIELD"]

    def _get_model_ref(self, path):
        """
        获取 CraftEngine 格式的模型引用，自动处理 item/ 前缀
        """
        if path.startswith("item/"):
             return f"{self.namespace}:{path}"
        return f"{self.namespace}:item/{path}"

    def _find_model_path_variant(self, base_path, variants):
        """
        在资源包中查找存在的模型变体。
        base_path: 基础模型路径 (e.g. "namespace:path/to/bow")
        variants: 候选后缀列表 (e.g. ["_0", "_pulling_0"])
        
        返回: 找到的第一个存在的路径 (添加了后缀的完整路径)，如果都没找到，返回默认的第一个变体路径。
        """
        if not self.ia_resourcepack_root:
             return f"{base_path}{variants[0]}"
             
        # 解析 base_path
        # 可能是 "namespace:path" 或 "path" (使用 self.namespace)
        if ":" in base_path:
            ns, rel_path = base_path.split(":", 1)
        else:
            ns = self.namespace
            rel_path = base_path
        
        # 确保移除 .json
        if rel_path.endswith(".json"):
            rel_path = rel_path[:-5]
            
        # 尝试每个变体
        for suffix in variants:
            check_path = f"{rel_path}{suffix}"
            
            # 1. 尝试 assets/<namespace>/models/<check_path>.json
            full_path = os.path.join(self.ia_resourcepack_root, "assets", ns, "models", f"{check_path}.json")
            if os.path.exists(full_path):
                 return check_path if ":" not in base_path else f"{ns}:{check_path}"
                 
            # 2. 尝试 <namespace>/models/<check_path>.json (非标准)
            full_path_2 = os.path.join(self.ia_resourcepack_root, ns, "models", f"{check_path}.json")
            if os.path.exists(full_path_2):
                 return check_path if ":" not in base_path else f"{ns}:{check_path}"

        # 如果都没找到，返回默认 (第一个变体)
        # 移除 .json 后缀确保路径干净
        base_clean = base_path[:-5] if base_path.endswith(".json") else base_path
        return f"{base_clean}{variants[0]}"

    def _normalize_model_path_input(self, raw_path):
        if not raw_path:
            return ""
        path = str(raw_path).replace("\\", "/").strip()
        if ":" in path:
            path = path.split(":", 1)[1]
        if path.endswith(".json") or path.endswith(".png"):
            path = path.rsplit(".", 1)[0]
        if path.startswith("textures/"):
            path = path[len("textures/"):]
        return path.lstrip("/")

    def _find_existing_model_by_name(self, texture_path):
        if not self.ia_resourcepack_root or not texture_path:
            return ""
        texture_parts = [p for p in texture_path.split("/") if p]
        texture_name = texture_parts[-1] if texture_parts else ""
        if not texture_name:
            return ""
        candidate_roots = [
            os.path.join(self.ia_resourcepack_root, "assets", self.namespace, "models"),
            os.path.join(self.ia_resourcepack_root, self.namespace, "models"),
            os.path.join(self.ia_resourcepack_root, "models")
        ]
        for models_root in candidate_roots:
            if not os.path.exists(models_root):
                continue
            direct_candidates = []
            direct_candidates.append(texture_path)
            if texture_path.startswith("item/"):
                direct_candidates.append(texture_path[len("item/"):])
            if "/gear/" in texture_path:
                direct_candidates.append(texture_path.replace("/gear/", "/"))
                if texture_path.startswith("item/"):
                    direct_candidates.append(texture_path[len("item/"):].replace("/gear/", "/"))
            unique_direct_candidates = []
            for candidate in direct_candidates:
                if candidate and candidate not in unique_direct_candidates:
                    unique_direct_candidates.append(candidate)
            for candidate in unique_direct_candidates:
                if os.path.exists(os.path.join(models_root, f"{candidate}.json")):
                    return candidate
            matches = []
            target_file_name = f"{texture_name}.json"
            for root, _, files in os.walk(models_root):
                if target_file_name in files:
                    rel_model = os.path.relpath(os.path.join(root, target_file_name), models_root)
                    matches.append(rel_model.replace("\\", "/")[:-5])
            if matches:
                texture_tokens = set(texture_parts[:-1])
                scored = []
                for model_path in matches:
                    model_tokens = set([p for p in model_path.split("/")[:-1] if p])
                    overlap = len(texture_tokens.intersection(model_tokens))
                    scored.append((overlap, -len(model_path), model_path))
                scored.sort(reverse=True)
                return scored[0][2]
        return ""

    def _resolve_complex_base_model_path(self, key, resource, textures):
        model_path = self._normalize_model_path_input(resource.get("model_path", ""))
        if model_path:
            return model_path
        normalized_textures = []
        for texture in textures or []:
            normalized = self._normalize_model_path_input(texture)
            if normalized:
                normalized_textures.append(normalized)
        for texture_path in normalized_textures:
            found_path = self._find_existing_model_by_name(texture_path)
            if found_path:
                return found_path
        if normalized_textures:
            return normalized_textures[0]
        return key

    def _handle_complex_item(self, ce_item, key, ia_data, material):
        # 为此物品创建一个模板
        template_id = f"models:{self.namespace}_{key}_model"
        
        
        template_def = {}
        args = {}
        
        resource = self._build_resource_data(ia_data)
        textures = resource.get("textures")
        if not textures and resource.get("texture"):
            val = resource.get("texture")
            if isinstance(val, list):
                textures = val
            else:
                textures = [val]
        base_model_path = self._resolve_complex_base_model_path(key, resource, textures)
        
        if material in ["BOW", "CROSSBOW"] and textures:
            expanded_textures = self._expand_bow_textures(textures)
            ce_item["textures"] = self._normalize_textures_for_item(expanded_textures, ce_item)
            return
        
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
            args["bow_model"] = self._get_model_ref(base_model_path)
            
            # 动态查找 pulling_0, pulling_1, pulling_2
            # 优先级: _pulling_0 (IA常用), _0 (原版风格)
            args["bow_pulling_0_model"] = self._get_model_ref(self._find_model_path_variant(base_model_path, ["_pulling_0", "_0"]))
            args["bow_pulling_1_model"] = self._get_model_ref(self._find_model_path_variant(base_model_path, ["_pulling_1", "_1"]))
            args["bow_pulling_2_model"] = self._get_model_ref(self._find_model_path_variant(base_model_path, ["_pulling_2", "_2"]))

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
            args["model"] = self._get_model_ref(base_model_path)
            args["arrow_model"] = self._get_model_ref(self._find_model_path_variant(base_model_path, ["_charged", "_arrow"]))
            args["firework_model"] = self._get_model_ref(self._find_model_path_variant(base_model_path, ["_firework", "_rocket"]))
            
            args["pulling_0_model"] = self._get_model_ref(self._find_model_path_variant(base_model_path, ["_pulling_0", "_0"]))
            args["pulling_1_model"] = self._get_model_ref(self._find_model_path_variant(base_model_path, ["_pulling_1", "_1"]))
            args["pulling_2_model"] = self._get_model_ref(self._find_model_path_variant(base_model_path, ["_pulling_2", "_2"]))
            
        elif material == "SHIELD":
            template_def = {
                "type": "minecraft:condition",
                "property": "minecraft:using_item",
                "on-false": {"type": "minecraft:model", "path": "${shield_model}"},
                "on-true": {"type": "minecraft:model", "path": "${shield_blocking_model}"}
            }
            args["shield_model"] = self._get_model_ref(base_model_path)
            args["shield_blocking_model"] = self._get_model_ref(f"{base_model_path}_blocking")
            
        elif material == "FISHING_ROD":
             template_def = {
                "type": "minecraft:condition",
                "property": "minecraft:fishing_rod/cast",
                "on-false": {"type": "minecraft:model", "path": "${path}"},
                "on-true": {"type": "minecraft:model", "path": "${cast_path}"}
            }
             args["path"] = self._get_model_ref(base_model_path)
             args["cast_path"] = self._get_model_ref(f"{base_model_path}_cast")

        # 注册模板
        self.ce_config["templates"][template_id] = template_def
        
        # 分配给物品
        ce_item["model"] = {
            "template": template_id,
            "arguments": args
        }

    def _expand_bow_textures(self, textures):
        if not textures:
            return textures
        cleaned = []
        for tex in textures:
            tex_str = str(tex)
            if tex_str.lower().endswith(".png"):
                tex_str = tex_str[:-4]
            tex_str = tex_str.replace("\\", "/")
            if ":" in tex_str:
                tex_str = tex_str.split(":", 1)[1]
            if tex_str.startswith("textures/"):
                tex_str = tex_str[len("textures/"):]
            cleaned.append(tex_str)
        
        base = cleaned[0]
        style = "numeric"
        for tex_str in cleaned:
            if tex_str.endswith("_pulling_0"):
                base = tex_str[:-len("_pulling_0")]
                style = "pulling"
                break
        if style == "numeric":
            for tex_str in cleaned:
                if tex_str.endswith("_0"):
                    base = tex_str[:-2]
                    break
        
        if style == "pulling":
            variants = [f"{base}_pulling_0", f"{base}_pulling_1", f"{base}_pulling_2"]
        else:
            variants = [f"{base}_0", f"{base}_1", f"{base}_2"]
        
        expanded = []
        for item in [base] + variants + cleaned:
            if item not in expanded:
                expanded.append(item)
        return expanded

    def _normalize_textures_for_item(self, textures, ce_item):
        ce_textures = []
        is_armor_item = self._is_armor(ce_item.get("material", ""))
        for tex in textures:
            tex_str = str(tex)
            if tex_str.lower().endswith(".png"):
                tex_str = tex_str[:-4]
            
            tex_str = tex_str.replace("\\", "/")
            
            if ":" in tex_str:
                tex_str = tex_str.split(":", 1)[1]
                
            if tex_str.startswith("textures/"):
                tex_str = tex_str[len("textures/"):]
                
            if is_armor_item:
                if tex_str.startswith("item/armor/"):
                    final_path = tex_str
                else:
                    if tex_str.startswith("item/"):
                        tex_str = tex_str[len("item/"):]
                    if tex_str.startswith("armor/"):
                        tex_str = tex_str[len("armor/"):]
                    final_path = f"item/armor/{tex_str}"
            else:
                if not tex_str.startswith("item/") and not tex_str.startswith("block/"):
                    tex_str = f"item/{tex_str}"
                final_path = tex_str
                
            ce_textures.append(f"{self.namespace}:{final_path}")
        return ce_textures

    def _handle_generic_model(self, ce_item, resource):
        model_path = resource.get("model_path")
        
        # 情况 1: 显式模型路径
        if model_path:
            # 确保 model_path 是字符串
            model_path = str(model_path)
            
            # 如果 model_path 中包含命名空间 (例如 "namespace:path")，则移除命名空间部分
            # 因为 CraftEngine 会自动拼接当前命名空间，或者我们手动拼接时避免重复
            if ":" in model_path:
                model_path = model_path.split(":")[1]
            
            # 移除 .json 后缀
            if model_path.endswith(".json"):
                model_path = model_path[:-5]

            # 检查 model_path 是否已经包含 item/ 前缀，避免双重嵌套
            parts = model_path.split("/")
            if parts[0] == "item":
                final_path = model_path
            else:
                final_path = f"item/{model_path}"
                
            ce_item["model"] = {
                "type": "minecraft:model",
                "path": f"{self.namespace}:{final_path}"
            }
        
        # 情况 2: 处理纹理 (不再生成模型，直接使用 textures)
        else:
            textures = resource.get("textures")
            
            # 兼容 "texture" 字段 
            if not textures and resource.get("texture"):
                val = resource.get("texture")
                if isinstance(val, list):
                    textures = val
                else:
                    textures = [val]

            if textures:
                ce_item["textures"] = self._normalize_textures_for_item(textures, ce_item)
                
                # 之前生成模型的代码已移除
                # if textures:
                #     # ... (旧代码)

    def _convert_equipments(self, equipments_data):
        for eq_key, eq_data in equipments_data.items():
            ce_eq_id = f"{self.namespace}:{eq_key}"
            
            # 映射 IA 图层到 CE Humanoid 图层
            ce_eq = {
                "type": "component"
            }
            
            if "layer_1" in eq_data:
                self._register_equipment_texture(eq_data["layer_1"], is_leggings=False)
                ce_eq["humanoid"] = self._normalize_equipment_texture_path(eq_data["layer_1"], is_leggings=False)
            if "layer_2" in eq_data:
                self._register_equipment_texture(eq_data["layer_2"], is_leggings=True)
                ce_eq["humanoid_leggings"] = self._normalize_equipment_texture_path(eq_data["layer_2"], is_leggings=True)
                
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
                self._register_equipment_texture(armor_data["layer_1"], is_leggings=False)
                ce_entry["humanoid"] = self._normalize_equipment_texture_path(armor_data["layer_1"], is_leggings=False)

            # 映射 layer_2 -> humanoid_leggings
            if "layer_2" in armor_data:
                self._register_equipment_texture(armor_data["layer_2"], is_leggings=True)
                ce_entry["humanoid_leggings"] = self._normalize_equipment_texture_path(armor_data["layer_2"], is_leggings=True)

            self.ce_config["equipments"][ce_key] = ce_entry

    def _format_display_name(self, name, data=None):
        name = self._convert_ia_text(str(name))

        if "&" in name or "§" in name:
            name = name.replace("&", "§")
            pass
            
        # 默认值
        default_color = "<white>"
        if data and "elitecreatures" in self.namespace:
             default_color = "<#FFCF20>"
             
        return f"<!i>{default_color}{name}"

    def _normalize_lore(self, lore_value):
        # 将 lore 转为字符串列表，保持内容原样
        if lore_value is None:
            return None
        if isinstance(lore_value, list):
            return [self._convert_ia_text(str(line)) for line in lore_value]
        if isinstance(lore_value, str):
            return [self._convert_ia_text(lore_value)]
        return None
