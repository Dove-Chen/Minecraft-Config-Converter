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

            if "resourcepack" in dirs:
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
            
            is_ia = self._is_ia_config(data)
            is_ce = self._is_ce_config(data)
            is_nexo = self._is_nexo_config(data)
            is_oraxen = self._is_oraxen_config(data)

            if is_ia:
                if "ItemsAdder" not in self.report["formats"]:
                    self.report["formats"].append("ItemsAdder")
                
                if "items" in data:
                    self.report["completeness"]["items_config"] = True
                    self.report["content_types"].add("装备")
                    if isinstance(data["items"], dict):
                        self.report["details"]["item_count"] += len(data["items"])
                        # 进一步检测类型
                        for item in data["items"].values():
                            if "behaviours" in item:
                                if "furniture" in item["behaviours"]:
                                    self.report["content_types"].add("装饰")
                                
                if "categories" in data:
                    self.report["completeness"]["categories_config"] = True
                    
            if is_ce:
                    if "CraftEngine" not in self.report["formats"]:
                        self.report["formats"].append("CraftEngine")
                        
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

    def _is_ia_config(self, data):
        # 简单的启发式检测 IA 配置
        keys = ["items", "categories", "equipments", "armors_rendering", "recipes", "loots", "info"]
        # ItemsAdder 配置通常有 info.namespace
        if "info" in data and "namespace" in data["info"]:
            return True
        # 或者包含特定的 IA 键
        for k in keys:
            if k in data:
                # 进一步检查结构以避免误判
                if k == "items" and isinstance(data[k], dict):
                    # 检查 item 结构是否有 IA 特征 (如 resource)
                    first_item = next(iter(data[k].values()), {})
                    if "resource" in first_item or "behaviours" in first_item:
                        return True
        return False

    def _is_ce_config(self, data):
        # 检测 CraftEngine 配置
        # CE 配置通常在 items 下有 'model' 且 model.type 为 minecraft:model 等
        if "items" in data:
            for item in data["items"].values():
                if "behavior" in item and "type" in item["behavior"]:
                    if item["behavior"]["type"] == "furniture_item":
                        return True
                if "model" in item:
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
