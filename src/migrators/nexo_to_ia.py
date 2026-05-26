import os
import shutil
import json
from .base import BaseMigrator


class NexoToIAMigrator(BaseMigrator):
    def __init__(self, nexo_resourcepack_path, ia_resourcepack_path, namespace):
        super().__init__(nexo_resourcepack_path, ia_resourcepack_path)
        self.namespace = namespace
        # 支持单路径与多路径输入，便于处理 external_packs 解包目录
        if isinstance(nexo_resourcepack_path, (list, tuple)):
            self.input_paths = [os.path.normpath(p) for p in nexo_resourcepack_path if isinstance(p, str) and p.strip()]
        elif isinstance(nexo_resourcepack_path, str) and nexo_resourcepack_path.strip():
            self.input_paths = [os.path.normpath(nexo_resourcepack_path)]
        else:
            self.input_paths = []

    def migrate(self):
        # 按输入顺序迁移：后面的目录会覆盖前面的同名文件
        for input_root in self.input_paths:
            models_sources = self._collect_resource_dirs("models", input_root)
            textures_sources = self._collect_resource_dirs("textures", input_root)

            for src_dir in models_sources:
                self._copy_tree(src_dir, os.path.join(self.output_path, "assets", self.namespace, "models"))
            for src_dir in textures_sources:
                self._copy_tree(src_dir, os.path.join(self.output_path, "assets", self.namespace, "textures"))

    def _collect_resource_dirs(self, resource_type, input_root):
        dirs = []
        candidates = [
            os.path.join(input_root, "assets", "minecraft", resource_type, self.namespace),
            os.path.join(input_root, "assets", self.namespace, resource_type),
            os.path.join(input_root, resource_type, self.namespace),
            os.path.join(input_root, self.namespace, resource_type),
        ]

        assets_root = os.path.join(input_root, "assets")
        if os.path.isdir(assets_root):
            for ns in os.listdir(assets_root):
                ns_root = os.path.join(assets_root, ns)
                if ns.lower() == "minecraft" or not os.path.isdir(ns_root):
                    continue
                candidates.append(os.path.join(ns_root, resource_type))

        minecraft_resource_root = os.path.join(input_root, "assets", "minecraft", resource_type)
        if os.path.isdir(minecraft_resource_root):
            for ns in os.listdir(minecraft_resource_root):
                ns_root = os.path.join(minecraft_resource_root, ns)
                if os.path.isdir(ns_root) and ns.lower() not in {"item", "block", "entity", "builtin"}:
                    candidates.append(ns_root)

        candidates.append(os.path.join(input_root, resource_type))

        for path in candidates:
            if not os.path.isdir(path):
                continue
            normalized = os.path.normpath(path)
            should_skip = False
            for kept in dirs:
                if self._is_path_inside(normalized, kept) or self._is_path_inside(kept, normalized):
                    should_skip = True
                    break
            if not should_skip:
                dirs.append(normalized)
        return dirs

    def _is_path_inside(self, child_path, parent_path):
        try:
            return os.path.commonpath([child_path, parent_path]) == os.path.normpath(parent_path)
        except ValueError:
            return False

    def _copy_tree(self, src_root, dst_root):
        for root, _, files in os.walk(src_root):
            rel = os.path.relpath(root, src_root)
            if rel == ".":
                rel = ""
            target_dir = os.path.join(dst_root, rel)
            os.makedirs(target_dir, exist_ok=True)
            for file_name in files:
                src_file = os.path.join(root, file_name)
                dst_file = os.path.join(target_dir, file_name)
                if src_file.lower().endswith(".json"):
                    self._copy_and_rewrite_model(src_file, dst_file)
                else:
                    shutil.copy2(src_file, dst_file)

    def _copy_and_rewrite_model(self, src_file, dst_file):
        try:
            with open(src_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            shutil.copy2(src_file, dst_file)
            return

        self._rewrite_model_json(data)
        with open(dst_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    def _rewrite_model_json(self, data):
        if not isinstance(data, dict):
            return

        textures = data.get("textures")
        if isinstance(textures, dict):
            for key, value in textures.items():
                textures[key] = self._rewrite_resource_ref(value)

        parent = data.get("parent")
        if isinstance(parent, str):
            data["parent"] = self._rewrite_resource_ref(parent, is_parent=True)

        overrides = data.get("overrides")
        if isinstance(overrides, list):
            for node in overrides:
                if isinstance(node, dict) and isinstance(node.get("model"), str):
                    node["model"] = self._rewrite_resource_ref(node["model"])

    def _rewrite_resource_ref(self, value, is_parent=False):
        if not isinstance(value, str):
            return value
        raw = value.strip().replace("\\", "/")
        if not raw:
            return raw
        if raw.startswith("#"):
            return raw

        if ":" in raw:
            ns, path = raw.split(":", 1)
            if ns == "minecraft":
                if path.startswith(("item/", "block/", "builtin/")):
                    return raw if is_parent else f"minecraft:{path}"
                if path.startswith("entity/"):
                    return raw
                return f"{self.namespace}:{self._strip_minecraft_wrapped_path(path)}"
            return f"{self.namespace}:{self._strip_known_namespace_prefix(path, ns)}"

        if raw.startswith(("item/", "block/", "builtin/")):
            return raw if is_parent else f"{self.namespace}:{raw}"

        cleaned = raw.lstrip("/")
        cleaned = self._strip_known_namespace_prefix(cleaned)
        return f"{self.namespace}:{cleaned}"

    def _strip_known_namespace_prefix(self, path, source_namespace=None):
        cleaned = str(path).replace("\\", "/").lstrip("/")
        prefixes = [self.namespace]
        if source_namespace and source_namespace not in prefixes:
            prefixes.append(source_namespace)
        for prefix in prefixes:
            if cleaned.startswith(f"{prefix}/"):
                return cleaned[len(prefix) + 1:]
        return cleaned

    def _strip_minecraft_wrapped_path(self, path):
        cleaned = str(path).replace("\\", "/").lstrip("/")
        parts = [part for part in cleaned.split("/") if part]
        if len(parts) > 1 and parts[0] not in {"item", "block", "entity", "builtin"}:
            return "/".join(parts[1:])
        return cleaned
