import os
import yaml
from src.utils.yaml_loader import safe_load_yaml

class PackageAnalyzer:
    def __init__(self, extract_path):
        self.extract_path = extract_path
        self.report = {
            "formats": [],          # [IA, CE, NEXO]
            "content_types": set(), # {装饰, 贴图, 装备, 模型}
            "completeness": {
                "items_config": False,
                "categories_config": False,
                "resource_files": False
            },
            "details": {
                "item_count": 0,
                "texture_count": 0,
                "model_count": 0
            }
        }

    def analyze(self):
        # 1. 扫描文件结构和 YAML 内容
        has_ia_structure = False
        has_ce_structure = False
        
        for root, dirs, files in os.walk(self.extract_path):
            # 0. 基于文件夹名称的启发式检测
            # 检查当前目录名是否具有特定特征
            current_dir_name = os.path.basename(root).lower()
            
            if current_dir_name == "itemsadder" or "itemsadder" in dirs:
                if "ItemsAdder" not in self.report["formats"]:
                    self.report["formats"].append("ItemsAdder")
            
            if current_dir_name == "craftengine" or "craftengine" in dirs:
                if "CraftEngine" not in self.report["formats"]:
                    self.report["formats"].append("CraftEngine")
            
            if current_dir_name == "nexo" or "nexo" in dirs:
                if "Nexo" not in self.report["formats"]:
                    self.report["formats"].append("Nexo")

            if current_dir_name == "oraxen" or "oraxen" in dirs:
                if "Oraxen" not in self.report["formats"]:
                    self.report["formats"].append("Oraxen")

            # 检查资源文件
            if "textures" in dirs or "textures" in root:
                self.report["content_types"].add("贴图")
                self.report["details"]["texture_count"] += len([f for f in files if f.endswith(".png")])
                
            if "models" in dirs or "models" in root:
                self.report["content_types"].add("模型")
                self.report["details"]["model_count"] += len([f for f in files if f.endswith(".json")])

            if "resourcepack" in dirs or "assets" in dirs:
                self.report["completeness"]["resource_files"] = True

            for file in files:
                if file.endswith((".yml", ".yaml")):
                    self._analyze_yaml(os.path.join(root, file))

        # 转换 set 为 list 以便 JSON 序列化
        self.report["content_types"] = list(self.report["content_types"])
        
        return self.report

    def _analyze_yaml(self, file_path):
        try:
            data = safe_load_yaml(file_path)
            if not data: return

            # 检测格式 (现在是并行的，一个文件可能只属于一种格式，但整个包可能包含多种)
            # 注意：这里我们移除了 elif，因为我们想全面扫描
            # 不过通常单个 YAML 文件不太可能同时是两种格式的有效配置
            # 但为了逻辑严谨，我们分别检测
            
            plugin_context = self._get_plugin_context(file_path)
            if plugin_context == "ItemsAdder":
                is_ia = self._is_ia_config(data)
                is_ce = False
                is_nexo = False
                is_oraxen = False
            elif plugin_context == "CraftEngine":
                is_ia = False
                is_ce = self._is_ce_config(data)
                is_nexo = False
                is_oraxen = False
            elif plugin_context == "Nexo":
                is_ia = False
                is_ce = False
                is_nexo = self._is_nexo_config(data)
                is_oraxen = False
            elif plugin_context == "Oraxen":
                is_ia = False
                is_ce = False
                is_nexo = False
                is_oraxen = self._is_oraxen_config(data)
            else:
                is_ia = self._is_ia_config(data)
                is_ce = self._is_ce_config(data)
                is_nexo = self._is_nexo_config(data)
                is_oraxen = self._is_oraxen_config(data)

            if is_ia:
                if "ItemsAdder" not in self.report["formats"]:
                    self.report["formats"].append("ItemsAdder")
                
                items_section = self._get_section(data, "items")
                categories_section = self._get_section(data, "categories")
                if items_section:
                    self.report["completeness"]["items_config"] = True
                    self.report["content_types"].add("装备")
                    if isinstance(items_section, dict):
                        self.report["details"]["item_count"] += len(items_section)
                        # 进一步检测类型
                        for item in items_section.values():
                            if isinstance(item, dict) and "behaviours" in item:
                                if "furniture" in item["behaviours"]:
                                    self.report["content_types"].add("装饰")
                                
                if categories_section:
                    self.report["completeness"]["categories_config"] = True
                    
            if is_ce:
                    if "CraftEngine" not in self.report["formats"]:
                        self.report["formats"].append("CraftEngine")
                    items_section = self._get_section(data, "items")
                    categories_section = self._get_section(data, "categories")
                    if items_section:
                        self.report["completeness"]["items_config"] = True
                        self.report["details"]["item_count"] += len(items_section)
                        for item in items_section.values():
                            if isinstance(item, dict) and self._get_dict_value(item, "behavior", default={}):
                                behavior = self._get_dict_value(item, "behavior", default={})
                                if isinstance(behavior, dict) and self._get_dict_value(behavior, "type") == "furniture_item":
                                    self.report["content_types"].add("装饰")
                    if categories_section:
                        self.report["completeness"]["categories_config"] = True
                        
            if is_nexo:
                    if "Nexo" not in self.report["formats"]:
                        self.report["formats"].append("Nexo")

            if is_oraxen:
                    if "Oraxen" not in self.report["formats"]:
                        self.report["formats"].append("Oraxen")
                    if "items" not in data and self._looks_like_oraxen_items_file(data):
                        self.report["completeness"]["items_config"] = True
                        self.report["content_types"].add("装备")
                        self.report["details"]["item_count"] += len(data)
                
        except Exception:
            pass # 忽略无法解析的文件

    def _get_plugin_context(self, file_path):
        try:
            rel_path = os.path.relpath(file_path, self.extract_path)
        except ValueError:
            rel_path = file_path
        parts = [part.lower() for part in os.path.normpath(rel_path).split(os.sep)]
        plugin_map = {
            "itemsadder": "ItemsAdder",
            "craftengine": "CraftEngine",
            "nexo": "Nexo",
            "oraxen": "Oraxen"
        }
        for part in parts[:-1]:
            if part in plugin_map:
                return plugin_map[part]
        return None

    def _is_ia_config(self, data):
        # 简单的启发式检测 IA 配置
        keys = ["items", "categories", "equipments", "armors_rendering", "legacy_armor_renderings", "recipes", "loots", "info"]
        # ItemsAdder 配置通常有 info.namespace
        if "info" in data and "namespace" in data["info"]:
            return True
        # 或者包含特定的 IA 键
        for k in keys:
            section = self._get_section(data, k)
            if section:
                # 进一步检查结构以避免误判
                if k == "items" and isinstance(section, dict):
                    # 检查 item 结构是否有 IA 特征 (如 resource)
                    first_item = next(iter(section.values()), {})
                    if isinstance(first_item, dict) and ("resource" in first_item or "graphics" in first_item or "behaviours" in first_item):
                        return True
                elif k != "items":
                    return True
        return False

    def _is_ce_config(self, data):
        if self._has_section_identifier(data):
            return True
        if self._is_itemsadder_only_config(data):
            return False
        # 检测 CraftEngine 配置
        # CE 配置通常在 items 下有 model/texture/custom_model_data 等字段。
        items_section = self._get_section(data, "items")
        if isinstance(items_section, dict):
            for item in items_section.values():
                if not isinstance(item, dict):
                    continue
                behavior = self._get_dict_value(item, "behavior", default={})
                if isinstance(behavior, dict) and "type" in behavior:
                    if behavior["type"] == "furniture_item":
                        return True
                if self._get_dict_value(item, "model", "models", "texture", "textures", "item_model", "custom_model_data", "custom-model-data") is not None:
                    return True
                if "data" in item and isinstance(item["data"], dict):
                    return True
                if "material" in item and ("resource" not in item and "graphics" not in item):
                    return True
        for key in ("equipments", "categories", "recipes", "furniture"):
            if self._get_section(data, key):
                return True
        return False

    def _has_section_identifier(self, data):
        if not isinstance(data, dict):
            return False
        ce_sections = {"items", "equipments", "categories", "recipes", "furniture"}
        for key in data.keys():
            if not isinstance(key, str) or "#" not in key:
                continue
            if key.split("#", 1)[0] in ce_sections:
                return True
        return False

    def _is_itemsadder_only_config(self, data):
        if isinstance(data.get("info"), dict) and "namespace" in data["info"]:
            return True

        items_section = self._get_section(data, "items")
        if isinstance(items_section, dict):
            for item in items_section.values():
                if isinstance(item, dict) and any(key in item for key in ("resource", "graphics", "behaviours", "specific_properties", "display_name")):
                    return True

        equipments_section = self._get_section(data, "equipments")
        if isinstance(equipments_section, dict):
            for equipment in equipments_section.values():
                if isinstance(equipment, dict) and ("layer_1" in equipment or "layer_2" in equipment):
                    return True

        if self._get_section(data, "armors_rendering") or self._get_section(data, "legacy_armor_renderings"):
            return True

        categories_section = self._get_section(data, "categories")
        if isinstance(categories_section, dict):
            for category in categories_section.values():
                if isinstance(category, dict) and ("items" in category or "enabled" in category or "permission" in category):
                    return True

        recipes_section = self._get_section(data, "recipes")
        if isinstance(recipes_section, dict):
            ia_recipe_groups = {"crafting_table", "cooking", "smithing", "stonecutting", "brewing", "anvil_repair"}
            if any(str(key).lower() in ia_recipe_groups for key in recipes_section.keys()):
                return True

        return False

    def _is_nexo_config(self, data):
        # 检测 Nexo 配置
        # Nexo 类似于 IA，但有一些特定字段
        # 通常包含 'itemname', 'Pack', 'Mechanics', 'Components'
        
        if isinstance(data, dict):
             for key, value in data.items():
                 if isinstance(value, dict):
                     if "Mechanics" in value:
                         return True
                     if "Pack" in value:
                         return True
                     if "Components" in value:
                         return True
                     if "itemname" in value:
                         return True
                         
        return False

    def _is_oraxen_config(self, data):
        if not isinstance(data, dict):
            return False
        if "oraxen_inventory" in data or "glyphs" in data:
            return True
        for value in data.values():
            if not isinstance(value, dict):
                continue
            if "Pack" in value and "displayname" in value:
                return True
        return False

    def _looks_like_oraxen_items_file(self, data):
        if not isinstance(data, dict):
            return False
        score = 0
        for value in data.values():
            if not isinstance(value, dict):
                continue
            if "Pack" in value:
                score += 1
            if "displayname" in value:
                score += 1
            if "material" in value:
                score += 1
            if score >= 3:
                return True
        return False

    def _get_section(self, data, section_name):
        if not isinstance(data, dict):
            return None
        merged = {}
        found = False
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            base_key = key.split("#", 1)[0]
            if base_key != section_name:
                continue
            found = True
            if isinstance(value, dict):
                merged.update(value)
        if found:
            return merged
        return None

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
            if isinstance(key, str):
                value = normalized.get(key.lower().replace("-", "_"))
                if value is not None:
                    return value
        return default
