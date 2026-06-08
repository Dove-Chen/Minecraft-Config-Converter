import os
import shutil
import json
from .base import BaseMigrator

class NexoMigrator(BaseMigrator):
    def __init__(self, nexo_resourcepack_path, ce_resourcepack_path, namespace, armor_humanoid_keys=None, armor_leggings_keys=None, source_namespaces=None):
        super().__init__(nexo_resourcepack_path, ce_resourcepack_path)
        self.namespace = namespace
        self.armor_humanoid_keys = set(armor_humanoid_keys or [])
        self.armor_leggings_keys = set(armor_leggings_keys or [])
        # Nexo的命名空间直接采用配置的名字，但也需要扫描其他源命名空间
        self.source_namespaces = set(source_namespaces or [])
        self.source_namespaces.add(self.namespace)
        self.root_textures_dir = None
        self.root_models_dir = None
        
        # 自动扫描资源包中的所有命名空间，以防止配置名与资源包内命名空间不一致导致资源遗漏
        assets_path = os.path.join(self.input_path, "assets")
        if os.path.exists(assets_path):
            for d in os.listdir(assets_path):
                full_path = os.path.join(assets_path, d)
                if os.path.isdir(full_path) and d not in ["minecraft", ".mcassetsroot", "realms"]:
                    self.source_namespaces.add(d)
            mc_textures = os.path.join(assets_path, "minecraft", "textures")
            if os.path.exists(mc_textures):
                for d in os.listdir(mc_textures):
                    full_path = os.path.join(mc_textures, d)
                    if os.path.isdir(full_path):
                        self.source_namespaces.add(d)
            mc_models = os.path.join(assets_path, "minecraft", "models")
            if os.path.exists(mc_models):
                for d in os.listdir(mc_models):
                    full_path = os.path.join(mc_models, d)
                    if os.path.isdir(full_path):
                        self.source_namespaces.add(d)

        if os.path.exists(self.input_path):
            for d in os.listdir(self.input_path):
                full_path = os.path.join(self.input_path, d)
                if not os.path.isdir(full_path):
                    continue
                if d in ["assets", ".mcassetsroot", "realms"]:
                    continue
                if os.path.exists(os.path.join(full_path, "textures")) or os.path.exists(os.path.join(full_path, "models")):
                    self.source_namespaces.add(d)

        root_textures = os.path.join(self.input_path, "textures")
        if os.path.exists(root_textures):
            self.root_textures_dir = root_textures
        root_models = os.path.join(self.input_path, "models")
        if os.path.exists(root_models):
            self.root_models_dir = root_models

    def migrate(self):
        print(f"Starting migration from {self.input_path} to {self.output_path}")
        self._migrate_textures()
        self._migrate_models()
        self._migrate_sounds()
        print("Migration complete.")

    def _get_resource_dir(self, resource_type, namespace=None):
        ns = namespace if namespace else self.namespace
        # 1. assets/<namespace>/type
        path1 = os.path.join(self.input_path, "assets", ns, resource_type)
        if os.path.exists(path1):
            return path1
        # 2. assets/minecraft/type/<namespace> 
        
        # 3. <namespace>/type
        path2 = os.path.join(self.input_path, ns, resource_type)
        if os.path.exists(path2):
            return path2
            
        return None

    def _migrate_textures(self):
        # 遍历所有源命名空间
        for ns in self.source_namespaces:
            src_dirs = []
            # 1. assets/ns/textures
            p1 = os.path.join(self.input_path, "assets", ns, "textures")
            if os.path.exists(p1): src_dirs.append(p1)
            # 2. assets/minecraft/textures/ns (常见模式)
            p2 = os.path.join(self.input_path, "assets", "minecraft", "textures", ns)
            if os.path.exists(p2): src_dirs.append(p2)
            # 3. 直接在包根目录下的 textures (非标准但可能存在)
            p3 = os.path.join(self.input_path, ns, "textures")
            if os.path.exists(p3): src_dirs.append(p3)
            
            # 4. 如果没找到，尝试在 assets/minecraft/textures 下查找
            # 但这可能会扫描过多内容，所以我们只作为最后的尝试
            if not src_dirs and ns == self.namespace: # 仅对主命名空间尝试通用目录
                p4 = os.path.join(self.input_path, "assets", "minecraft", "textures")
                if os.path.exists(p4):
                    # 仅当没有更具体的目录时
                    pass 
                if self.root_textures_dir:
                    src_dirs.append(self.root_textures_dir)

            for src_dir in src_dirs:
                for root, _, files in os.walk(src_dir):
                    for file in files:
                        if not file.endswith((".png", ".mcmeta")):
                            continue
                            
                        rel_path = os.path.relpath(root, src_dir)
                        src_file = os.path.join(root, file)
                        
                        # 标准化键
                        key_path = os.path.join(rel_path, file)
                        key = self._normalize_key(key_path)
                        
                        should_inject_namespace = True
                        if key in self.armor_humanoid_keys:
                            armor_name = os.path.basename(key)
                            dest_rel = f"entity/equipment/humanoid/{armor_name}.png"
                            should_inject_namespace = False
                        elif key in self.armor_leggings_keys:
                            armor_name = os.path.basename(key)
                            dest_rel = f"entity/equipment/humanoid_leggings/{armor_name}.png"
                            should_inject_namespace = False
                        elif self._is_armor_icon_texture(file, rel_path):
                            dest_rel = self._armor_icon_dest_rel(rel_path, file, include_ext=True)
                            should_inject_namespace = False
                        elif self._is_armor_texture(file, rel_path):
                            dest_rel = self._armor_texture_dest_rel(rel_path, file, include_ext=True)
                            should_inject_namespace = False
                        else:
                            # 默认为 item/
                            # 如果 rel_path 以 item 开头，保留它
                            
                            # 相对于 "item/" 的基础路径或只是路径
                            base_rel = rel_path
                            if not (base_rel.startswith("item") or base_rel.startswith("items") or base_rel.startswith("block")):
                                base_rel = os.path.join("item", base_rel)
                                
                            dest_rel = os.path.join(base_rel, file)

                        # 如果源命名空间与目标命名空间不同，注入源命名空间到路径中
                        if ns != self.namespace and should_inject_namespace:
                            dest_rel_norm = dest_rel.replace("\\", "/")
                            if dest_rel_norm.startswith("item/"):
                                dest_rel = os.path.join("item", ns, dest_rel_norm[5:])
                            elif dest_rel_norm.startswith("block/"):
                                dest_rel = os.path.join("block", ns, dest_rel_norm[6:])
                            else:
                                dest_rel = os.path.join(ns, dest_rel)

                        dest_dir = os.path.join(self.output_path, "assets", self.namespace, "textures", os.path.dirname(dest_rel))
                        os.makedirs(dest_dir, exist_ok=True)
                        shutil.copy2(src_file, os.path.join(self.output_path, "assets", self.namespace, "textures", dest_rel))

    def _migrate_models(self):
        # 遍历所有源命名空间
        for ns in self.source_namespaces:
            src_dirs = []
            # 1. assets/ns/models
            p1 = os.path.join(self.input_path, "assets", ns, "models")
            if os.path.exists(p1): src_dirs.append(p1)
            # 2. assets/minecraft/models/ns
            p2 = os.path.join(self.input_path, "assets", "minecraft", "models", ns)
            if os.path.exists(p2): src_dirs.append(p2)
            # 3. 直接在包根目录下的 models
            p3 = os.path.join(self.input_path, ns, "models")
            if os.path.exists(p3): src_dirs.append(p3)
            if ns == self.namespace and self.root_models_dir:
                src_dirs.append(self.root_models_dir)
            
            for src_dir in src_dirs:
                for root, _, files in os.walk(src_dir):
                    for file in files:
                        if not file.endswith(".json"):
                            continue
                        
                        rel_path = os.path.relpath(root, src_dir)
                        src_file = os.path.join(root, file)
                        
                        # 逻辑类似于纹理但更简单（无盔甲检查）
                        base_rel = rel_path
                        if not (base_rel.startswith("item") or base_rel.startswith("items") or base_rel.startswith("block")):
                             base_rel = os.path.join("item", base_rel)
                             
                        dest_rel = os.path.join(base_rel, file)
                        
                        # 如果源命名空间与目标命名空间不同，注入源命名空间到路径中
                        if ns != self.namespace:
                            dest_rel_norm = dest_rel.replace("\\", "/")
                            if dest_rel_norm.startswith("item/"):
                                dest_rel = os.path.join("item", ns, dest_rel_norm[5:])
                            elif dest_rel_norm.startswith("block/"):
                                dest_rel = os.path.join("block", ns, dest_rel_norm[6:])
                            else:
                                dest_rel = os.path.join(ns, dest_rel)

                        dest_dir = os.path.join(self.output_path, "assets", self.namespace, "models", os.path.dirname(dest_rel))
                        os.makedirs(dest_dir, exist_ok=True)
                        dest_file = os.path.join(dest_dir, file)
                        
                        self._process_model_file(src_file, dest_file, source_ns=ns)

    def _migrate_sounds(self):
        for ns in self.source_namespaces:
            src_dirs = []
            candidates = [
                os.path.join(self.input_path, "assets", ns, "sounds"),
                os.path.join(self.input_path, "assets", "minecraft", "sounds", ns),
                os.path.join(self.input_path, ns, "sounds"),
            ]
            if ns == self.namespace:
                candidates.append(os.path.join(self.input_path, "sounds"))

            for candidate in candidates:
                if os.path.isdir(candidate) and candidate not in src_dirs:
                    src_dirs.append(candidate)

            for src_dir in src_dirs:
                for root, _, files in os.walk(src_dir):
                    for file in files:
                        if not file.lower().endswith((".ogg", ".wav", ".json", ".mcmeta")):
                            continue
                        rel_path = os.path.relpath(root, src_dir)
                        dest_rel = os.path.join(rel_path, file)
                        if ns != self.namespace:
                            dest_rel = os.path.join(ns, dest_rel)
                        dest_dir = os.path.join(self.output_path, "assets", self.namespace, "sounds", os.path.dirname(dest_rel))
                        os.makedirs(dest_dir, exist_ok=True)
                        src_file = os.path.join(root, file)
                        shutil.copy2(src_file, os.path.join(self.output_path, "assets", self.namespace, "sounds", dest_rel))

            sounds_json_candidates = [
                os.path.join(self.input_path, "assets", ns, "sounds.json"),
                os.path.join(self.input_path, ns, "sounds.json"),
            ]
            for sounds_json in sounds_json_candidates:
                if not os.path.isfile(sounds_json):
                    continue
                dest_name = "sounds.json" if ns == self.namespace else f"{ns}_sounds.json"
                dest_dir = os.path.join(self.output_path, "assets", self.namespace)
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(sounds_json, os.path.join(dest_dir, dest_name))

    def _process_model_file(self, src_file, dest_file, source_ns=None):
        try:
            with open(src_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 更新纹理
            if "textures" in data:
                new_textures = {}
                for key, val in data["textures"].items():
                    # val 可能是 "namespace:path/to/texture" 或 "path/to/texture"
                    print(f"Processing texture key {key}: {val}")
                    if ":" in val:
                        ns, path = val.split(":", 1)
                        print(f"Split into ns={ns}, path={path}")
                        if ns == self.namespace or ns in self.source_namespaces:
                            new_path = self._adjust_texture_path(path)
                            if ns != self.namespace:
                                new_path = self._inject_namespace_path(new_path, ns)
                            new_textures[key] = f"{self.namespace}:{new_path}"
                        else:
                            new_textures[key] = val
                    else:
                        # 假设源命名空间或目标命名空间
                        ns = source_ns if source_ns else self.namespace
                        new_path = self._adjust_texture_path(val)
                        if ns != self.namespace:
                            new_path = self._inject_namespace_path(new_path, ns)
                        new_textures[key] = f"{self.namespace}:{new_path}"
                        
                data["textures"] = new_textures

            # 更新覆盖
            if "overrides" in data:
                for override in data["overrides"]:
                    if "model" in override:
                        model_val = override["model"]
                        if ":" in model_val:
                            ns, path = model_val.split(":", 1)
                            if ns == self.namespace or ns in self.source_namespaces:
                                new_path = self._adjust_model_path(path)
                                if ns != self.namespace:
                                    new_path = self._inject_namespace_path(new_path, ns)
                                override["model"] = f"{self.namespace}:{new_path}"
                        else:
                            ns = source_ns if source_ns else self.namespace
                            new_path = self._adjust_model_path(model_val)
                            if ns != self.namespace:
                                new_path = self._inject_namespace_path(new_path, ns)
                            override["model"] = f"{self.namespace}:{new_path}"

            with open(dest_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error processing model {src_file}: {e}")

    def _adjust_texture_path(self, path):
        # 调整路径以指向新位置 (item/...)
        key = self._normalize_key(path)
        if key in self.armor_humanoid_keys:
            armor_name = os.path.basename(key)
            return f"entity/equipment/humanoid/{armor_name}"
        elif key in self.armor_leggings_keys:
            armor_name = os.path.basename(key)
            return f"entity/equipment/humanoid_leggings/{armor_name}"
        path_norm = self._normalize_key(path)
        name = os.path.basename(path_norm)
        rel_path = os.path.dirname(path_norm)
        if self._is_armor_icon_texture(name, rel_path):
            return self._armor_icon_dest_rel(rel_path, name, include_ext=False)
        if self._is_armor_texture(name, rel_path):
            return self._armor_texture_dest_rel(rel_path, name, include_ext=False)

        path_clean = self._strip_namespace_prefix(path)
        if not path_clean.startswith("item/") and not path_clean.startswith("block/"):
            return self._to_posix(f"item/{path_clean}")
        return self._to_posix(path_clean)

    def _adjust_model_path(self, path):
        path_clean = self._strip_namespace_prefix(path)
        if not path_clean.startswith("item/") and not path_clean.startswith("block/"):
            return self._to_posix(f"item/{path_clean}")
        return self._to_posix(path_clean)

    def _strip_namespace_prefix(self, path):
        path_norm = str(path).replace("\\", "/").lstrip("/")
        if path_norm.startswith(f"{self.namespace}/"):
            return path_norm[len(self.namespace) + 1:]
        return path_norm

    def _normalize_key(self, path):
        # 移除扩展名
        if path.endswith(".png"):
            path = path[:-4]
        path = path.replace("\\", "/").lstrip("/")
        if path.startswith("textures/"):
            path = path[len("textures/"):]
        return path

    def _is_armor_icon_texture(self, name, rel_path):
        rel_l = rel_path.replace("\\", "/").lower()
        if rel_l.startswith("item/") or rel_l == "item":
            return False
        key = self._normalize_key(os.path.join(rel_path, name))
        if key in self.armor_humanoid_keys or key in self.armor_leggings_keys:
            return False
        base = os.path.splitext(name.lower())[0]
        has_armor_context = any(token in rel_l for token in ("armor", "armour", "icon", "icons"))
        if base in {"helmet", "chestplate", "leggings", "boots"}:
            if not has_armor_context:
                return False
            return True
        if base.endswith(("_helmet", "_chestplate", "_leggings", "_boots")):
            return True
        if "icon" in base:
            return True
        if "icon" in rel_l or "icons" in rel_l:
            return True
        return False

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

    def _armor_icon_dest_rel(self, rel_path, name, include_ext=False):
        rel_l = rel_path.replace("\\", "/")
        parts = [p for p in rel_l.split("/") if p and p != "."]
        excluded = {"textures", "armor", "armour"}
        prefix = [p for p in parts if p.lower() not in excluded]
        base = os.path.splitext(name)[0]
        if prefix:
            path = os.path.join("item", *prefix, "armor", base)
        else:
            path = os.path.join("item", "armor", base)
        if include_ext:
            ext = os.path.splitext(name)[1]
            return self._to_posix(f"{path}{ext}")
        return self._to_posix(path)

    def _armor_texture_dest_rel(self, rel_path, name, include_ext=False):
        target_folder = "humanoid_leggings" if self._is_leggings_texture(name, rel_path) else "humanoid"
        base = os.path.splitext(name)[0]
        path = os.path.join("entity", "equipment", target_folder, base)
        if include_ext:
            ext = os.path.splitext(name)[1]
            return self._to_posix(f"{path}{ext}")
        return self._to_posix(path)

    def _to_posix(self, path):
        return str(path).replace("\\", "/")

    def _inject_namespace_path(self, path, ns):
        path_norm = path.replace("\\", "/").lstrip("/")
        if path_norm.startswith("entity/"):
            return path_norm
        if path_norm.startswith("item/"):
            rest = path_norm[5:]
            if rest.startswith(f"{ns}/{ns}/"):
                rest = rest[len(ns)+1:]
                return f"item/{rest}"
            if rest.startswith(f"{ns}/"):
                return f"item/{rest}"
            return f"item/{ns}/{rest}"
        if path_norm.startswith("block/"):
            rest = path_norm[6:]
            if rest.startswith(f"{ns}/{ns}/"):
                rest = rest[len(ns)+1:]
                return f"block/{rest}"
            if rest.startswith(f"{ns}/"):
                return f"block/{rest}"
            return f"block/{ns}/{rest}"
        if path_norm.startswith(f"{ns}/{ns}/"):
            return path_norm[len(ns)+1:]
        if path_norm.startswith(f"{ns}/"):
            return path_norm
        return f"{ns}/{path_norm}"
