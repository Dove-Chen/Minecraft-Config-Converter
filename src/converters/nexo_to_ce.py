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
        self.fix_illegal_model_rotations = False

    def set_resource_paths(self, nexo_root, ce_root):
        self.nexo_resourcepack_root = nexo_root
        self.ce_resourcepack_root = ce_root

    def set_fix_illegal_model_rotations(self, enabled):
        self.fix_illegal_model_rotations = bool(enabled)

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
                source_namespaces=self.source_namespaces,
                fix_illegal_model_rotations=self.fix_illegal_model_rotations
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
        self.ce_config = {
            "items": {},
            "equipments": {},
            "templates": {},
            "categories": {},
            "recipes": {}
        }
        self.generated_models = {}
        self.armor_humanoid_keys = set()
        self.armor_leggings_keys = set()
        self.source_namespaces = set()
        if not isinstance(nexo_data, dict):
            return self.ce_config
        
        # Nexo 结构通常是根目录下的扁平物品键，或者是嵌套的。
        # 但通常 Nexo 物品只是文件中的键。
        # 我们需要区分物品和其他可能的键（如果有）。
        # 然而，查看示例，文件似乎就是物品列表。
        
        wrapped_items = self._get_dict_value(nexo_data, "items", "Items", default=None)
        if isinstance(wrapped_items, dict):
            self._convert_items(wrapped_items)
            self._convert_items(nexo_data)
        else:
            self._convert_items(nexo_data)

        self._convert_categories(self._get_dict_value(nexo_data, "categories", "Categories", default={}))
        self._convert_recipes(self._get_dict_value(nexo_data, "recipes", "Recipes", default={}))
        
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
                lowered[k.lower().replace("-", "_")] = v
        for key in keys:
            if isinstance(key, str):
                v = lowered.get(key.lower().replace("-", "_"))
                if v is not None:
                    return v
        return default

    def _local_id(self, raw_id):
        if not isinstance(raw_id, str):
            return str(raw_id)
        if ":" in raw_id:
            return raw_id.split(":", 1)[1]
        return raw_id

    def _normalize_namespaced_id(self, raw_id, fallback="entry"):
        local_id = self._local_id(raw_id)
        local_id = re.sub(r"[^0-9a-z_.-]", "_", str(local_id).lower()).strip("_")
        if not local_id:
            local_id = fallback
        return f"{self.namespace}:{local_id}"

    def _normalize_item_ref(self, value, keep_tag_namespace=True):
        if not isinstance(value, str) or not value.strip():
            return value
        ref = value.strip()
        if ref.startswith("#"):
            tag = ref[1:]
            if ":" in tag:
                ns, item_id = tag.split(":", 1)
                if ns == "minecraft":
                    return f"#minecraft:{item_id.lower()}"
                return f"#{self.namespace}:{item_id}"
            return f"#{self.namespace}:{tag}" if keep_tag_namespace else ref
        if ref.startswith("minecraft:"):
            ns, item_id = ref.split(":", 1)
            return f"{ns}:{item_id.lower()}"
        if ":" in ref:
            _, item_id = ref.split(":", 1)
            return f"{self.namespace}:{item_id}"
        return f"{self.namespace}:{ref}"

    def _looks_like_custom_item(self, value):
        if not isinstance(value, str):
            return False
        ref = value.strip()
        if not ref or ref.startswith("#") or ref.startswith("minecraft:"):
            return False
        if ":" in ref:
            return True
        return f"{self.namespace}:{ref.lower()}" in self.ce_config["items"]

    def _normalize_recipe_id(self, raw_id):
        if not raw_id:
            return None
        if isinstance(raw_id, str) and ":" in raw_id:
            ns, item_id = raw_id.split(":", 1)
            if ns == "minecraft":
                return f"minecraft:{item_id.lower()}"
            return f"{self.namespace}:{item_id}"
        local_id = re.sub(r"[^0-9a-z_.-]", "_", str(raw_id).lower()).strip("_")
        if not local_id:
            return None
        return f"{self.namespace}:{local_id}"

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

    def _get_components_data(self, data):
        components = self._get_dict_value(data, "Components", "components", default={})
        if isinstance(components, dict):
            return components
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

    def _normalize_slot(self, slot_value):
        if not slot_value:
            return None
        slot = str(slot_value).strip().lower()
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
        return slot_map.get(slot, slot if slot else None)

    def _to_bool(self, value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
        return bool(value)

    def _extract_non_armor_equippable_slot(self, data, mechanics=None):
        components = self._get_components_data(data)
        equippable = self._get_dict_value(components, "equippable", "Equippable", default={})
        if isinstance(equippable, dict):
            explicit_slot = self._normalize_slot(self._get_dict_value(equippable, "slot", "Slot", default=None))
            if explicit_slot:
                return explicit_slot
        if mechanics is None:
            mechanics = self._get_mechanics_data(data)
        hat_cfg = self._get_dict_value(mechanics, "hat", "Hat", default={})
        if isinstance(hat_cfg, dict):
            enabled = self._to_bool(self._get_dict_value(hat_cfg, "enabled", "enable", default=True), default=True)
            if enabled:
                return "head"
        return None

    def _apply_non_armor_equippable(self, ce_item, data, mechanics=None):
        slot = self._extract_non_armor_equippable_slot(data, mechanics=mechanics)
        if not slot:
            return
        ce_data = ce_item.setdefault("data", {})
        equippable_data = ce_data.get("equippable")
        if not isinstance(equippable_data, dict):
            equippable_data = {}
        if not equippable_data.get("slot"):
            equippable_data["slot"] = slot
        ce_data["equippable"] = equippable_data

    def _convert_items(self, items_data):
        if not isinstance(items_data, dict):
            return
        
        # 递归函数查找物品
        seen_item_keys = set()

        def make_item_key(parts):
            cleaned_parts = []
            for part in parts:
                text = str(part).strip()
                if text:
                    cleaned_parts.append(self._local_id(text))
            raw_key = "_".join(cleaned_parts)
            item_key = re.sub(r"[^0-9a-z_.-]", "_", raw_key.lower()).strip("_")
            if not item_key:
                item_key = "item"
            original_key = item_key
            index = 2
            while item_key in seen_item_keys:
                item_key = f"{original_key}_{index}"
                index += 1
            seen_item_keys.add(item_key)
            return item_key

        def recurse(data, prefix_parts=None):
            if prefix_parts is None:
                prefix_parts = []
            for key, value in data.items():
                if not isinstance(value, dict):
                    continue
                if not prefix_parts and str(key).lower() in {"items", "categories", "recipes"}:
                    continue
                
                # 检查是否为物品
                if self._is_nexo_item_data(value):
                    self._convert_item(make_item_key(prefix_parts + [key]), value)
                else:
                    # 递归
                    recurse(value, prefix_parts + [key])

        recurse(items_data)

    def _is_nexo_item_data(self, value):
        if not isinstance(value, dict):
            return False
        item_markers = (
            "material",
            "itemname",
            "customname",
            "lore",
            "Pack",
            "pack",
            "Mechanics",
            "mechanics",
            "Components",
            "components",
            "model",
            "custom_model_data",
            "custom-model-data",
            "AttributeModifiers",
            "attribute_modifiers",
            "permission",
            "enchants",
            "enchantments",
        )
        return any(self._get_dict_value(value, marker, default=None) is not None for marker in item_markers)

    def _convert_item(self, key, data):
        ce_id = f"{self.namespace}:{key}"
        
        material = self._get_dict_value(data, "material", default="STONE")
        item_name = self._get_dict_value(data, "itemname", "customname", default=key)
        
        ce_item = {
            "material": material,
            "data": {
                "item_name": self._format_display_name(item_name)
            }
        }
        
        lore_value = self._get_dict_value(data, "lore", default=None)
        if lore_value:
            ce_lore = self._normalize_lore(lore_value)
            if ce_lore:
                ce_item["data"]["lore"] = ce_lore
        
        pack = self._get_pack_data(data)
        custom_model_data = self._get_dict_value(
            data,
            "model",
            "custom_model_data",
            "custom-model-data",
            default=None,
        )
        if custom_model_data is None:
            custom_model_data = self._get_dict_value(
                pack,
                "custom_model_data",
                "custom-model-data",
                default=None,
            )
        if custom_model_data is not None:
             ce_item["custom_model_data"] = custom_model_data

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

        if not self._is_armor(material):
            self._apply_non_armor_equippable(ce_item, data, mechanics=mechanics)

        self.ce_config["items"][ce_id] = ce_item

    def _convert_categories(self, categories_data):
        if not isinstance(categories_data, dict):
            return
        for raw_id, category_data in categories_data.items():
            if not isinstance(category_data, dict):
                continue

            ce_category_id = self._normalize_namespaced_id(raw_id, fallback="category")
            raw_items = self._get_dict_value(category_data, "items", "list", default=[])
            ce_items = []
            if isinstance(raw_items, str):
                raw_items = [raw_items]
            if isinstance(raw_items, list):
                for item in raw_items:
                    if not isinstance(item, str):
                        continue
                    normalized = self._normalize_item_ref(item)
                    if normalized not in ce_items:
                        ce_items.append(normalized)

            icon = self._get_dict_value(category_data, "icon", default=ce_items[0] if ce_items else "minecraft:stone")
            icon = self._normalize_item_ref(icon) if isinstance(icon, str) else "minecraft:stone"
            hidden_value = self._get_dict_value(category_data, "hidden", default=None)
            enabled_value = self._get_dict_value(category_data, "enabled", default=None)
            if hidden_value is not None:
                hidden = self._to_bool(hidden_value, default=False)
            elif enabled_value is not None:
                hidden = not self._to_bool(enabled_value, default=True)
            else:
                hidden = False

            ce_category = {
                "name": self._format_display_name(
                    self._get_dict_value(category_data, "name", "display_name", "display-name", default=self._local_id(raw_id))
                ),
                "priority": self._get_dict_value(category_data, "priority", default=1),
                "icon": icon,
                "list": ce_items,
                "hidden": hidden
            }

            lore = self._normalize_lore(self._get_dict_value(category_data, "lore", default=None))
            if lore:
                ce_category["lore"] = lore

            conditions = self._get_dict_value(category_data, "conditions", default=None)
            if isinstance(conditions, list):
                ce_category["conditions"] = conditions

            permission = self._get_dict_value(category_data, "permission", default=None)
            if isinstance(permission, str) and permission.strip():
                ce_category.setdefault("conditions", []).append({
                    "type": "permission",
                    "permission": permission.strip()
                })

            self.ce_config["categories"][ce_category_id] = ce_category

    def _convert_recipes(self, recipes_data):
        if not isinstance(recipes_data, dict):
            return
        for group_key, group_data in recipes_data.items():
            if not isinstance(group_data, dict):
                continue

            if self._is_recipe_group(group_key, group_data):
                for recipe_key, recipe_data in group_data.items():
                    if not isinstance(recipe_data, dict):
                        continue
                    self._add_recipe_variants(group_key, recipe_key, recipe_data)
            else:
                self._add_recipe_variants(None, group_key, group_data)

    def _is_recipe_group(self, group_key, group_data):
        group = str(group_key).lower()
        groups = {
            "crafting_table",
            "crafting",
            "shapeless",
            "shapeless_crafting",
            "cooking",
            "furnace",
            "smelting",
            "blast_furnace",
            "blasting",
            "smoker",
            "smoking",
            "campfire",
            "campfire_cooking",
            "stonecutting",
            "smithing",
            "smithing_transform",
            "brewing",
        }
        if group not in groups:
            return False
        recipe_keys = {
            "type",
            "pattern",
            "ingredients",
            "ingredient",
            "result",
            "template",
            "template-type",
            "base",
            "addition",
            "time",
            "experience",
            "exp",
            "cook_time",
            "machines",
            "shapeless",
        }
        return not any(self._get_dict_value(group_data, key, default=None) is not None for key in recipe_keys)

    def _add_recipe_variants(self, group_key, recipe_key, recipe_data):
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

        machine_types = self._map_cooking_machines(self._get_dict_value(recipe_data, "machines", default=None))
        if group_key and str(group_key).lower() == "cooking" and machine_types:
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
            pattern = self._get_dict_value(recipe_data, "pattern", default=None)
            ingredients = self._get_dict_value(recipe_data, "ingredients", default={})
            if pattern:
                ce_recipe["pattern"] = self._normalize_pattern(pattern, ingredients)
            if isinstance(ingredients, dict) and ingredients:
                ce_recipe["ingredients"] = {
                    key: self._normalize_recipe_item(value) for key, value in ingredients.items()
                }
        elif ce_type == "shapeless":
            ingredients = self._get_dict_value(recipe_data, "ingredients", "ingredient", default=[])
            ce_recipe["ingredients"] = self._normalize_shapeless_ingredients(ingredients)
        elif ce_type in ["smelting", "blasting", "smoking", "campfire_cooking"]:
            ingredient = self._get_dict_value(recipe_data, "ingredient", "ingredients", default=None)
            if isinstance(ingredient, list):
                ingredient = ingredient[0] if ingredient else None
            if ingredient is not None:
                ce_recipe["ingredient"] = self._normalize_recipe_item(ingredient)
            experience = self._get_dict_value(recipe_data, "experience", "exp", default=None)
            if experience is not None:
                ce_recipe["experience"] = experience
            time_val = self._get_dict_value(recipe_data, "time", "cook_time", "cookingTime", default=None)
            if time_val is not None:
                ce_recipe["time"] = time_val
            category = self._get_dict_value(recipe_data, "category", default=None)
            if category:
                ce_recipe["category"] = category
            group_val = self._get_dict_value(recipe_data, "group", default=None)
            if group_val:
                ce_recipe["group"] = group_val
        elif ce_type == "stonecutting":
            ingredient = self._get_dict_value(recipe_data, "ingredient", "ingredients", default=None)
            if isinstance(ingredient, list):
                ingredient = ingredient[0] if ingredient else None
            if ingredient is not None:
                ce_recipe["ingredient"] = self._normalize_recipe_item(ingredient)
            group_val = self._get_dict_value(recipe_data, "group", default=None)
            if group_val:
                ce_recipe["group"] = group_val
        elif ce_type == "smithing_transform":
            template = self._get_dict_value(recipe_data, "template", "template-type", default=None)
            base = self._get_dict_value(recipe_data, "base", default=None)
            addition = self._get_dict_value(recipe_data, "addition", default=None)
            if template:
                ce_recipe["template-type"] = self._normalize_recipe_item(template)
            if base:
                ce_recipe["base"] = self._normalize_recipe_item(base)
            if addition:
                ce_recipe["addition"] = self._normalize_recipe_item(addition)
            merge_components = self._get_dict_value(recipe_data, "merge-components", "merge_components", default=None)
            if merge_components is not None:
                ce_recipe["merge-components"] = merge_components
        elif ce_type == "brewing":
            ingredient = self._get_dict_value(recipe_data, "ingredient", default=None)
            container = self._get_dict_value(recipe_data, "container", default=None)
            if ingredient:
                ce_recipe["ingredient"] = self._normalize_recipe_item(ingredient)
            if container:
                ce_recipe["container"] = self._normalize_recipe_item(container)

        result = self._get_dict_value(recipe_data, "result", default=None)
        if result is not None:
            result_id = None
            result_count = None
            if isinstance(result, dict):
                result_id = self._get_dict_value(result, "item", "id", default=None)
                result_count = self._get_dict_value(result, "amount", "count", default=None)
            else:
                result_id = result
            if result_id is not None:
                ce_result = {"id": self._normalize_recipe_item(result_id)}
                ce_result["count"] = 1 if result_count is None else result_count
                ce_recipe["result"] = ce_result

        return ce_recipe

    def _normalize_recipe_item(self, value):
        if value is None:
            return value
        if isinstance(value, dict):
            item_id = self._get_dict_value(value, "item", "id", default=None)
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
                    return f"#{self.namespace}:{path}"
                return f"#minecraft:{tag.lower()}"
            if ":" in item:
                ns, path = item.split(":", 1)
                if ns == "minecraft":
                    return f"minecraft:{path.lower()}"
                return f"{self.namespace}:{path}"
            if self._looks_like_custom_item(item):
                return f"{self.namespace}:{item.lower()}"
            return f"minecraft:{item.lower()}"
        return value

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
            normalized.append("".join(ch if ch in keys else " " for ch in row_str))
        return normalized

    def _normalize_shapeless_ingredients(self, ingredients):
        if isinstance(ingredients, list):
            normalized = []
            for item in ingredients:
                if isinstance(item, list):
                    normalized.append([self._normalize_recipe_item(value) for value in item])
                else:
                    normalized.append(self._normalize_recipe_item(item))
            return normalized
        if isinstance(ingredients, dict):
            return [self._normalize_recipe_item(value) for value in ingredients.values()]
        if ingredients is None:
            return []
        return [self._normalize_recipe_item(ingredients)]

    def _extract_recipe_patterns(self, recipe_data):
        patterns = []
        base_pattern = self._get_dict_value(recipe_data, "pattern", default=None)
        if base_pattern:
            patterns.append(("", base_pattern))

        indexed_patterns = []
        for key, value in recipe_data.items():
            if not isinstance(key, str) or not key.startswith("pattern_"):
                continue
            suffix = key[len("pattern_"):]
            if suffix:
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
            "campfire-cooking": "campfire_cooking",
        }
        result = []
        for machine in raw_machines:
            key = str(machine).strip().lower()
            ce_type = mapping.get(key)
            if ce_type and ce_type not in result:
                result.append(ce_type)
        return result

    def _map_recipe_type(self, group_key, recipe_data):
        explicit_type = self._get_dict_value(recipe_data, "type", default=None)
        if explicit_type:
            group = str(explicit_type).lower()
        else:
            group = str(group_key).lower() if group_key else ""

        if self._get_dict_value(recipe_data, "shapeless", default=False) is True:
            return "shapeless"

        machine_types = self._map_cooking_machines(self._get_dict_value(recipe_data, "machines", default=None))
        if group == "cooking" and machine_types:
            return machine_types[0]

        mapping = {
            "crafting": "shaped",
            "crafting_table": "shaped",
            "shaped": "shaped",
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
            "brewing": "brewing",
        }
        if group in mapping:
            return mapping[group]
        if self._get_dict_value(recipe_data, "pattern", default=None) is not None:
            return "shaped"
        ingredients = self._get_dict_value(recipe_data, "ingredients", default=None)
        if isinstance(ingredients, list):
            return "shapeless"
        if self._get_dict_value(recipe_data, "result", default=None) is not None:
            return "shaped"
        return None

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
        material = str(material).upper()
        return any(material.endswith(s) for s in suffixes)

    def _handle_armor(self, ce_item, item_key, nexo_data, pack=None):
        if pack is None:
            pack = self._get_pack_data(nexo_data)
        custom_armor = self._get_custom_armor_data(pack)

        def _diamond_material_for_slot(slot_name):
            return {
                "head": "DIAMOND_HELMET",
                "chest": "DIAMOND_CHESTPLATE",
                "legs": "DIAMOND_LEGGINGS",
                "feet": "DIAMOND_BOOTS"
            }.get(slot_name)
        
        slot = "head"
        material = str(ce_item["material"]).upper()
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
            diamond_material = _diamond_material_for_slot(slot)
            if diamond_material:
                ce_item["material"] = diamond_material

            asset_seed = self._get_dict_value(custom_armor, "id", "asset_id", "asset-id", default=None) or layer1 or layer2 or texture_path
            asset_id = self._infer_armor_asset_id(asset_seed, slot)
            equipment_ref = f"{self.namespace}:{asset_id}"

            ce_item["settings"] = {
                "equipment": {
                    "asset_id": equipment_ref,
                    "slot": slot
                }
            }

            ce_equipment = self.ce_config["equipments"].get(equipment_ref, {"type": "component"})
            if layer1:
                ce_equipment["humanoid"] = self._normalize_equipment_texture_path(layer1, is_leggings=False)
            if layer2:
                ce_equipment["humanoid_leggings"] = self._normalize_equipment_texture_path(layer2, is_leggings=True)
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
        model_path = self._get_dict_value(pack, "model", default=None)
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
        pack = self._get_pack_data(nexo_data)
        material = str(material).upper()
        
        template_id = f"models:{self.namespace}_{key}_model"
        ce_item["model"] = {
            "template": template_id,
            "arguments": {}
        }
        
        args = ce_item["model"]["arguments"]
        
        # 基础模型
        base_model = self._get_dict_value(pack, "model", default=None)
        if base_model:
            args["model"] = self._get_model_ref(base_model)
            # 一些模板使用特定名称
            if material == "BOW": args["bow_model"] = self._get_model_ref(base_model)
            elif material == "SHIELD": args["shield_model"] = self._get_model_ref(base_model)
            elif material == "FISHING_ROD": args["path"] = self._get_model_ref(base_model)
        
        # 变体
        if material == "BOW":
            pulling = self._get_dict_value(pack, "pulling_models", "pulling-models", default=[])
            if not isinstance(pulling, list):
                pulling = []
            for i, m in enumerate(pulling):
                args[f"bow_pulling_{i}_model"] = self._get_model_ref(m)
        
        elif material == "CROSSBOW":
            pulling = self._get_dict_value(pack, "pulling_models", "pulling-models", default=[])
            if not isinstance(pulling, list):
                pulling = []
            for i, m in enumerate(pulling):
                args[f"pulling_{i}_model"] = self._get_model_ref(m)
            
            charged = self._get_dict_value(pack, "charged_model", "charged-model", default=None)
            if charged: args["arrow_model"] = self._get_model_ref(charged)
            
            firework = self._get_dict_value(pack, "firework_model", "firework-model", default=None)
            if firework: args["firework_model"] = self._get_model_ref(firework)
            
        elif material == "SHIELD":
            blocking = self._get_dict_value(pack, "blocking_model", "blocking-model", default=None)
            if blocking: args["shield_blocking_model"] = self._get_model_ref(blocking)
            
        elif material == "FISHING_ROD":
            cast = self._get_dict_value(pack, "cast_model", "cast-model", default=None)
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
        model_path = self._get_dict_value(pack, "model", default=None)
        if model_path:
            ce_item["model"] = {
                "type": "minecraft:model",
                "path": self._get_model_ref(model_path)
            }
            return

        textures = self._extract_pack_textures(pack)
        if textures:
            ce_item["textures"] = textures

    def _extract_pack_textures(self, pack):
        texture_values = []
        texture = self._get_dict_value(pack, "texture", default=None)
        textures = self._get_dict_value(pack, "textures", default=None)
        if isinstance(texture, str) and texture.strip():
            texture_values.append(texture)
        elif isinstance(texture, dict):
            texture_values.extend(value for value in texture.values() if isinstance(value, str))
        if isinstance(textures, str) and textures.strip():
            texture_values.append(textures)
        elif isinstance(textures, list):
            texture_values.extend(value for value in textures if isinstance(value, str))
        elif isinstance(textures, dict):
            texture_values.extend(value for value in textures.values() if isinstance(value, str))

        normalized = []
        seen = set()
        for value in texture_values:
            texture_path = self._normalize_armor_item_texture(value)
            if texture_path and texture_path not in seen:
                seen.add(texture_path)
                normalized.append(texture_path)
        return normalized

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
        return str(material).upper() in ["BOW", "CROSSBOW", "FISHING_ROD", "SHIELD"]

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
        source_ns = None
        if ":" in path:
            source_ns, path = path.split(":", 1)
            if source_ns and source_ns != "minecraft":
                self.source_namespaces.add(source_ns)
        path = path.replace("\\", "/").lstrip("/")
        if path.endswith(".png"):
            path = path[:-4]
        if path.startswith("textures/"):
            path = path[len("textures/"):]
        if path.startswith(f"{self.namespace}/"):
            path = path[len(self.namespace) + 1:]
        elif source_ns and source_ns not in {"minecraft", self.namespace} and not path.startswith(f"{source_ns}/"):
            if path.startswith("item/"):
                path = f"item/{source_ns}/{path[5:]}"
            elif path.startswith("block/"):
                path = f"block/{source_ns}/{path[6:]}"
            else:
                path = f"{source_ns}/{path}"
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
