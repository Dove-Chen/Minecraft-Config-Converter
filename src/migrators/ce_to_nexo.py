import json
import os
import shutil

from .base import BaseMigrator


class CEToNexoMigrator(BaseMigrator):
    def __init__(self, ce_resourcepack_paths, nexo_pack_path, namespace):
        super().__init__(ce_resourcepack_paths, nexo_pack_path)
        self.namespace = namespace
        if isinstance(ce_resourcepack_paths, (list, tuple)):
            self.input_paths = [
                os.path.normpath(path)
                for path in ce_resourcepack_paths
                if isinstance(path, str) and path.strip()
            ]
        elif isinstance(ce_resourcepack_paths, str) and ce_resourcepack_paths.strip():
            self.input_paths = [os.path.normpath(ce_resourcepack_paths)]
        else:
            self.input_paths = []

    def migrate(self):
        for input_root in self.input_paths:
            for resource_type in ("models", "textures", "sounds"):
                for src_dir in self._collect_resource_dirs(input_root, resource_type):
                    dst_dir = os.path.join(
                        self.output_path,
                        "assets",
                        self.namespace,
                        resource_type,
                    )
                    self._copy_tree(src_dir, dst_dir)

    def _collect_resource_dirs(self, input_root, resource_type):
        candidates = [
            os.path.join(input_root, "assets", self.namespace, resource_type),
            os.path.join(input_root, "assets", "minecraft", resource_type, self.namespace),
            os.path.join(input_root, self.namespace, resource_type),
            os.path.join(input_root, resource_type, self.namespace),
            os.path.join(input_root, resource_type),
        ]

        assets_root = os.path.join(input_root, "assets")
        if os.path.isdir(assets_root):
            for namespace in os.listdir(assets_root):
                namespace_root = os.path.join(assets_root, namespace)
                if not os.path.isdir(namespace_root):
                    continue
                candidates.append(os.path.join(namespace_root, resource_type))

        dirs = []
        for path in candidates:
            if not os.path.isdir(path):
                continue
            normalized = os.path.normpath(path)
            if any(self._is_path_inside(normalized, kept) or self._is_path_inside(kept, normalized) for kept in dirs):
                continue
            dirs.append(normalized)
        return dirs

    def _copy_tree(self, src_root, dst_root):
        for root, _, files in os.walk(src_root):
            rel_dir = os.path.relpath(root, src_root)
            target_dir = dst_root if rel_dir == "." else os.path.join(dst_root, rel_dir)
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
            json.dump(data, f, ensure_ascii=False, indent=4)

    def _rewrite_model_json(self, data):
        if not isinstance(data, dict):
            return

        parent = data.get("parent")
        if isinstance(parent, str):
            data["parent"] = self._rewrite_resource_ref(parent, is_parent=True)

        textures = data.get("textures")
        if isinstance(textures, dict):
            for key, value in textures.items():
                textures[key] = self._rewrite_resource_ref(value)

        overrides = data.get("overrides")
        if isinstance(overrides, list):
            for override in overrides:
                if isinstance(override, dict) and isinstance(override.get("model"), str):
                    override["model"] = self._rewrite_resource_ref(override["model"])

    def _rewrite_resource_ref(self, value, is_parent=False):
        if not isinstance(value, str):
            return value
        raw = value.strip().replace("\\", "/")
        if not raw or raw.startswith("#"):
            return raw
        if ":" in raw:
            namespace, path = raw.split(":", 1)
            if namespace == "minecraft":
                return raw
            return f"{self.namespace}:{path.lstrip('/')}"
        if is_parent and raw.startswith(("item/", "block/", "builtin/")):
            return f"minecraft:{raw}"
        return f"{self.namespace}:{raw.lstrip('/')}"

    def _is_path_inside(self, child_path, parent_path):
        try:
            return os.path.commonpath([child_path, parent_path]) == os.path.normpath(parent_path)
        except ValueError:
            return False

