import os
import shutil
import json
from .base import BaseMigrator
from .model_utils import normalize_illegal_element_rotations

class IAMigrator(BaseMigrator):
    def __init__(
        self,
        ia_resourcepack_path,
        ce_resourcepack_path,
        namespace,
        armor_humanoid_keys=None,
        armor_leggings_keys=None,
        block_texture_keys=None,
        block_model_keys=None,
        font_image_texture_keys=None,
        fix_illegal_model_rotations=False
    ):
        super().__init__(ia_resourcepack_path, ce_resourcepack_path)
        self.namespace = namespace
        self.armor_humanoid_keys = set(armor_humanoid_keys or [])
        self.armor_leggings_keys = set(armor_leggings_keys or [])
        self.block_texture_keys = set(block_texture_keys or [])
        self.block_model_keys = set(block_model_keys or [])
        self.font_image_texture_keys = set(font_image_texture_keys or [])
        self.fix_illegal_model_rotations = bool(fix_illegal_model_rotations)

    def migrate(self):
        """执行完整的迁移过程。"""
        print(f"开始从 {self.input_path} 迁移到 {self.output_path}")
        
        # 1. 迁移纹理
        self._migrate_textures()
        
        # 2. 迁移模型
        self._migrate_models()
        
        # 3. 迁移声音 (如果有 - 占位符)
        self._migrate_sounds()
        
        # 4. 生成缺失的物品模型 (针对 generate: true 的物品)
        # self.generate_missing_item_models()
        
        print("迁移完成。")
    
    def set_armor_texture_keys(self, humanoid_keys, leggings_keys):
        self.armor_humanoid_keys = set(humanoid_keys or [])
        self.armor_leggings_keys = set(leggings_keys or [])

    def set_block_resource_keys(self, texture_keys, model_keys):
        self.block_texture_keys = set(texture_keys or [])
        self.block_model_keys = set(model_keys or [])

    def _get_resource_dir(self, resource_type):
        """
        辅助方法：查找正确的资源目录。
        尝试顺序：
        1. assets/<namespace>/<resource_type> (标准结构)
        2. <namespace>/<resource_type> (缺失 assets 文件夹结构)
        3. <resource_type> (扁平结构)
        """
        # 1. 标准: assets/namespace/type
        path1 = os.path.join(self.input_path, "assets", self.namespace, resource_type)
        if os.path.exists(path1):
            return path1
        # IA packs sometimes use a resource namespace that differs from info.namespace.
        assets_root = os.path.join(self.input_path, "assets")
        if os.path.isdir(assets_root):
            candidates = []
            for asset_namespace in sorted(os.listdir(assets_root)):
                candidate = os.path.join(assets_root, asset_namespace, resource_type)
                if os.path.isdir(candidate):
                    candidates.append(candidate)
            if len(candidates) == 1:
                return candidates[0]
            for candidate in candidates:
                source_namespace = os.path.basename(os.path.dirname(candidate))
                if source_namespace != "minecraft":
                    return candidate
            
        # 2. 缺失 assets: namespace/type
        path2 = os.path.join(self.input_path, self.namespace, resource_type)
        if os.path.exists(path2):
            return path2
            
        # 3. 扁平: type (仅当 input_path 已经是命名空间根目录时)
        path3 = os.path.join(self.input_path, resource_type)
        if os.path.exists(path3):
            return path3
            
        return None

    def _is_leggings_texture(self, name, rel_path):
        name_l = name.lower()
        rel_l = rel_path.replace("\\", "/").lower()
        if "layer_2" in name_l or "layer2" in name_l:
            return True
        if "legging" in name_l or "leggings" in name_l:
            return True
        if "legging" in rel_l or "leggings" in rel_l:
            return True
        if "layer_2" in rel_l or "layer2" in rel_l:
            return True
        return False

    def _normalize_texture_key_from_path(self, path_part):
        path = path_part.replace("\\", "/").lstrip("/")
        if path.startswith("./"):
            path = path[2:]
        if path.startswith("textures/"):
            path = path[len("textures/"):]
        if path.endswith(".png"):
            path = path[:-4]
        return path

    def _armor_key_to_dest_rel(self, key, is_leggings):
        # print(f"输入路径: {key}")
        path = key.replace("\\", "/").lstrip("/")
        # print(f"原始路径: {path}")
        if path.startswith("textures/"):
            path = path[len("textures/"):]
        if path.startswith("entity/equipment/humanoid_legging/"):
            return path.replace("entity/equipment/humanoid_legging/", "entity/equipment/humanoid_leggings/", 1)
        if path.startswith("entity/equipment/humanoid/") or path.startswith("entity/equipment/humanoid_leggings/"):
            return path
        if "/" not in path and "\\" not in path:
            target_folder = "humanoid_leggings" if is_leggings else "humanoid"
            return f"entity/equipment/{target_folder}"
        parts = [p for p in path.split("/") if p]
        excluded = {"textures", "entity", "equipment", "humanoid", "humanoid_legging", "humanoid_leggings", "armor", "armour"}
        subparts = [p for p in parts if p.lower() not in excluded]
        has_duplicate = len(subparts) >= 2 and subparts[-1].lower() == subparts[-2].lower()
        if has_duplicate:
            subparts = subparts[:-2]
        subpath = "/".join(subparts)
        target_folder = "humanoid_leggings" if is_leggings else "humanoid"
        # if subpath:
        #     return f"entity/equipment/{target_folder}/{subpath}"
        return f"entity/equipment/{target_folder}"

    def _block_texture_key_to_dest_rel(self, key, directory=False):
        path = key.replace("\\", "/").lstrip("/")
        if path.startswith("textures/"):
            path = path[len("textures/"):]
        if path.startswith("item/"):
            path = path[len("item/"):]
        if path.startswith("block/"):
            dest = path
        else:
            dest = f"block/{path}"
        if directory:
            return os.path.dirname(dest)
        return dest

    def _block_model_key_to_dest_rel(self, key):
        path = key.replace("\\", "/").lstrip("/")
        if path.startswith("models/"):
            path = path[len("models/"):]
        if path.startswith("item/"):
            path = path[len("item/"):]
        if path.startswith("block/"):
            return path
        return f"block/{path}"

    def _is_armor_icon_texture(self, name, rel_path):
        rel_l = rel_path.replace("\\", "/").lower()
        key = self._normalize_texture_key_from_path(os.path.join(rel_path, name))
        if key in self.armor_humanoid_keys or key in self.armor_leggings_keys:
            return False
        base = os.path.splitext(name.lower())[0]
        if base in {"helmet", "chestplate", "leggings", "boots"}:
            return True
        if base.endswith(("_helmet", "_chestplate", "_leggings", "_boots")):
            return True
        if "icon" in base:
            return True
        if "icon" in rel_l or "icons" in rel_l:
            return True
        return False

    def _is_armor_texture(self, name, rel_path):
        rel_l = rel_path.replace("\\", "/").lower()
        if rel_l.startswith("item/") or rel_l == "item":
            return False
        if self._is_armor_icon_texture(name, rel_path):
            return False
        name_l = name.lower()
        if "layer_1" in name_l or "layer_2" in name_l:
            return True
        if "armor" in name_l or "armour" in name_l:
            return True
        if "armor" in rel_l or "armour" in rel_l:
            return True
        if "equipment" in rel_l or "humanoid" in rel_l:
            return True
        return False

    def _build_item_armor_dir(self, rel_path):
        rel_l = rel_path.replace("\\", "/")
        parts = [p for p in rel_l.split("/") if p and p != "."]
        excluded = {"textures", "item", "armor", "armour"}
        prefix = [p for p in parts if p.lower() not in excluded]
        if prefix:
            return os.path.join("item", "armor", *prefix)
        return os.path.join("item", "armor")

    def _build_armor_texture_dir(self, rel_path, name):
        rel_l = rel_path.replace("\\", "/")
        parts = [p for p in rel_l.split("/") if p and p != "."]
        excluded = {"textures", "entity", "equipment", "humanoid", "humanoid_legging", "humanoid_leggings", "armor", "armour"}
        prefix = [p for p in parts if p.lower() not in excluded]
        target_folder = "humanoid_leggings" if self._is_leggings_texture(name, rel_path) else "humanoid"
        basename = os.path.splitext(name)[0]
        if prefix and prefix[-1].lower() == basename.lower():
            prefix = prefix[:-1]
        if prefix:
            return os.path.join("entity", "equipment", target_folder, *prefix)
        return os.path.join("entity", "equipment", target_folder)

    def _normalize_texture_path(self, path_part):
        path = path_part.replace("\\", "/").lstrip("/")
        if path.startswith("textures/"):
            path = path[len("textures/"):]
        key = self._normalize_texture_key_from_path(path)
        if key in self.font_image_texture_keys:
            return key
        if key in self.block_texture_keys:
            return self._block_texture_key_to_dest_rel(key)
        if key in self.armor_humanoid_keys:
            return self._armor_key_to_dest_rel(key, is_leggings=False)
        if key in self.armor_leggings_keys:
            return self._armor_key_to_dest_rel(key, is_leggings=True)
        if self._is_armor_icon_texture(path.split("/")[-1], path):
            parts = [p for p in path.split("/") if p]
            excluded = {"textures", "item", "armor", "armour"}
            basename = parts[-1] if parts else ""
            prefix = [p for p in parts[:-1] if p.lower() not in excluded]
            if basename:
                subpath = "/".join(prefix + [basename])
            else:
                subpath = "/".join(prefix)
            if subpath:
                return f"item/armor/{subpath}"
            return "item/armor"
        if self._is_armor_texture(path.split("/")[-1], path):
            parts = [p for p in path.split("/") if p]
            excluded = {"textures", "entity", "equipment", "humanoid", "humanoid_legging", "humanoid_leggings", "armor", "armour"}
            basename = parts[-1] if parts else ""
            prefix = [p for p in parts[:-1] if p.lower() not in excluded]
            if prefix and basename and prefix[-1].lower() == basename.lower():
                prefix = prefix[:-1]
            target_folder = "humanoid_leggings" if self._is_leggings_texture(basename, path) else "humanoid"
            if basename:
                subpath = "/".join(prefix + [basename])
            else:
                subpath = "/".join(prefix)
            if subpath:
                return f"entity/equipment/{target_folder}/{subpath}"
            return f"entity/equipment/{target_folder}"
        if path.startswith("item/"):
            return path
        return f"item/{path}"

    def _migrate_textures(self):
        """
        ItemsAdder: assets/<namespace>/textures/<path>
        CraftEngine: assets/<namespace>/textures/item/<path> (标准约定)
        """
        src_dir = self._get_resource_dir("textures")
        if not src_dir:
            print(f"警告: 在 {self.input_path} 未找到纹理目录 (namespace: {self.namespace})")
            return

        # 我们需要小心。ItemsAdder 允许 textures/ 下有任意结构。
        # CraftEngine 偏好严格分类 (item/, block/, entity/)。
        # 目前，我们将假设大多数是物品并将它们移动到 textures/item/。
        # 除了通常去 entity/equipment/ 的护甲图层。
        
        for root, _, files in os.walk(src_dir):
            for file in files:
                if not file.endswith((".png", ".mcmeta")):
                    continue
                    
                rel_path = os.path.relpath(root, src_dir)
                src_file = os.path.join(root, file)
                key = self._normalize_texture_key_from_path(os.path.join(rel_path, file))
                if key in self.font_image_texture_keys:
                    dest_rel = os.path.dirname(key)
                elif key in self.block_texture_keys:
                    dest_rel = self._block_texture_key_to_dest_rel(key, directory=True)
                elif key in self.armor_humanoid_keys:
                    dest_rel = self._armor_key_to_dest_rel(key, is_leggings=False)
                elif key in self.armor_leggings_keys:
                    dest_rel = self._armor_key_to_dest_rel(key, is_leggings=True)
                elif self._is_armor_icon_texture(file, rel_path):
                    dest_rel = self._build_item_armor_dir(rel_path)
                elif self._is_armor_texture(file, rel_path):
                    dest_rel = self._build_armor_texture_dir(rel_path, file)
                else:
                    parts = rel_path.split(os.sep)
                    if parts[0] == "item":
                        dest_rel = rel_path
                    else:
                        dest_rel = os.path.join("item", rel_path)

                dest_dir = os.path.join(self.output_path, "assets", self.namespace, "textures", dest_rel)
                os.makedirs(dest_dir, exist_ok=True)
                
                dest_file = os.path.join(dest_dir, file)
                shutil.copy2(src_file, dest_file)
                # print(f"已复制纹理: {file} -> {dest_rel}")

    def _migrate_models(self):
        """
        ItemsAdder: assets/<namespace>/models/<path>
        CraftEngine: assets/<namespace>/models/item/<path>
        """
        src_dir = self._get_resource_dir("models")
        if not src_dir:
            return

        for root, _, files in os.walk(src_dir):
            for file in files:
                if not file.endswith(".json"):
                    continue
                
                rel_path = os.path.relpath(root, src_dir)
                src_file = os.path.join(root, file)
                
                # 移动到 CE 中的 item/ 子目录，防止双重 item/
                model_key = os.path.join(rel_path, file[:-5]).replace("\\", "/")
                if model_key.startswith("./"):
                    model_key = model_key[2:]

                if model_key in self.block_model_keys:
                    dest_key = self._block_model_key_to_dest_rel(model_key)
                    dest_rel = os.path.dirname(dest_key)
                    dest_file_name = os.path.basename(dest_key) + ".json"
                else:
                    parts = rel_path.split(os.sep)
                    if parts[0] == "item":
                        dest_rel = rel_path
                    else:
                        dest_rel = os.path.join("item", rel_path)
                    dest_file_name = file
                    
                dest_dir = os.path.join(self.output_path, "assets", self.namespace, "models", dest_rel)
                os.makedirs(dest_dir, exist_ok=True)
                
                dest_file = os.path.join(dest_dir, dest_file_name)
                
                # 我们需要处理 JSON 内容以修复纹理路径
                self._process_model_file(src_file, dest_file)

    def generate_missing_item_models(self):
        """
        扫描输出纹理并生成基本的物品模型（如果不存在）。
        这处理了使用 IA 'generate: true' 的情况。
        """
        # 目标模型目录: assets/<namespace>/models/item/
        models_dir = os.path.join(self.output_path, "assets", self.namespace, "models", "item")
        # 目标纹理目录: assets/<namespace>/textures/item/
        textures_dir = os.path.join(self.output_path, "assets", self.namespace, "textures", "item")
        
        if not os.path.exists(textures_dir):
            return

        for root, _, files in os.walk(textures_dir):
            for file in files:
                if not file.endswith(".png"):
                    continue
                
                # 来自 textures/item/ 的相对路径
                rel_path = os.path.relpath(root, textures_dir)
                texture_name = file[:-4]
                
                # 对应的模型路径
                if rel_path == ".":
                    model_rel_dir = models_dir
                    texture_ref = f"{self.namespace}:item/{texture_name}"
                else:
                    model_rel_dir = os.path.join(models_dir, rel_path)
                    # 纹理引用必须使用正斜杠
                    rel_path_fwd = rel_path.replace("\\", "/")
                    texture_ref = f"{self.namespace}:item/{rel_path_fwd}/{texture_name}"

                model_file_path = os.path.join(model_rel_dir, f"{texture_name}.json")
                
                # 如果模型不存在，则创建它
                if not os.path.exists(model_file_path):
                    os.makedirs(model_rel_dir, exist_ok=True)
                    self._create_basic_item_model(model_file_path, texture_ref)
                    # print(f"已生成缺失的模型: {model_file_path}")

    def _create_basic_item_model(self, file_path, texture_ref):
        data = {
            "parent": "minecraft:item/generated",
            "textures": {
                "layer0": texture_ref
            }
        }
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

    def _process_model_file(self, src_file, dest_file):
        try:
            with open(src_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 移除非 minecraft 的 parent 引用
            if "parent" in data:
                parent_val = data["parent"]
                if not parent_val.startswith("minecraft:"):
                    del data["parent"]

            # 修复纹理路径
            # IA: <namespace>:<path> (相对于 textures/)
            # CE: <namespace>:item/<path> (我们将它们移动到了 item/)
            # 
            # 如果转换过程中更改了命名空间，
            # 模型文件中的旧命名空间引用也必须更新为新的命名空间。
            
            if "textures" in data:
                new_textures = {}
                for key, val in data["textures"].items():
                    # 检查是否包含命名空间引用 (:)
                    if ":" in val:
                        parts = val.split(":", 1)
                        ns = parts[0]
                        path_part = parts[1]
                        
                        # 如果是外部引用 (minecraft 或其他)，保持原样
                        if ns == "minecraft":
                             new_textures[key] = val
                             continue
                             
                        # 如果是旧命名空间（或者是当前处理的命名空间），我们需要更新它
                        # 应用路径调整逻辑 (移动到 item/)
                        new_path = self._normalize_texture_path(path_part)
                        new_val = f"{self.namespace}:{new_path}"
                        new_textures[key] = new_val
                    else:
                        # 没有命名空间（例如 "#texture" 引用或纯路径），保持原样或添加当前命名空间
                        if val.startswith("#"):
                             new_textures[key] = val
                        else:
                             # 可能是相对路径，加上命名空间
                             new_path = self._normalize_texture_path(val)
                             new_textures[key] = f"{self.namespace}:{new_path}"

                data["textures"] = new_textures
            
            # 修复 overrides/predicates (如果有) (指向其他模型)
            if "overrides" in data:
                for override in data["overrides"]:
                    if "model" in override:
                        model_val = override["model"]
                        if ":" in model_val:
                            parts = model_val.split(":", 1)
                            ns = parts[0]
                            path_part = parts[1]
                            
                            if ns != "minecraft":
                                if not path_part.startswith("item/"):
                                    path_part = f"item/{path_part}"
                                override["model"] = f"{self.namespace}:{path_part}"

            if self.fix_illegal_model_rotations:
                changed = normalize_illegal_element_rotations(data)
                if changed:
                    print(f"已修正模型非法元素旋转角 {changed} 处: {src_file}")

            with open(dest_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
                
        except Exception as e:
            print(f"处理模型 {src_file} 时出错: {e}")

    def _migrate_sounds(self):
        src_dir = self._get_resource_dir("sounds")
        if src_dir:
            for root, _, files in os.walk(src_dir):
                for file in files:
                    if not file.lower().endswith((".ogg", ".wav", ".mcmeta")):
                        continue

                    rel_path = os.path.relpath(root, src_dir)
                    dest_dir = os.path.join(self.output_path, "assets", self.namespace, "sounds", rel_path)
                    os.makedirs(dest_dir, exist_ok=True)
                    shutil.copy2(os.path.join(root, file), os.path.join(dest_dir, file))

        for sounds_json in (
            os.path.join(self.input_path, "assets", self.namespace, "sounds.json"),
            os.path.join(self.input_path, self.namespace, "sounds.json"),
            os.path.join(self.input_path, "sounds.json"),
        ):
            if not os.path.isfile(sounds_json):
                continue
            dest_dir = os.path.join(self.output_path, "assets", self.namespace)
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(sounds_json, os.path.join(dest_dir, "sounds.json"))
            break
