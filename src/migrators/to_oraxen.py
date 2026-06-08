import json
import os
import shutil

from .base import BaseMigrator


class ToOraxenMigrator(BaseMigrator):
    def __init__(self, resourcepack_paths, oraxen_pack_path, namespace):
        super().__init__(resourcepack_paths, oraxen_pack_path)
        self.namespace = namespace
        if isinstance(resourcepack_paths, (list, tuple)):
            self.input_paths = [
                os.path.normpath(path)
                for path in resourcepack_paths
                if isinstance(path, str) and path.strip()
            ]
        elif isinstance(resourcepack_paths, str) and resourcepack_paths.strip():
            self.input_paths = [os.path.normpath(resourcepack_paths)]
        else:
            self.input_paths = []

    def migrate(self):
        for input_root in self.input_paths:
            for resource_type in ("models", "textures", "sounds"):
                for src_dir in self._collect_resource_dirs(input_root, resource_type):
                    dst_dir = os.path.join(self.output_path, resource_type)
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
            if any(
                self._is_path_inside(normalized, kept) or self._is_path_inside(kept, normalized)
                for kept in dirs
            ):
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
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

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
                if is_parent and path.startswith(("item/", "block/", "builtin/")):
                    return path
                return raw
            return self._strip_known_namespace_prefix(path, namespace)

        return self._strip_known_namespace_prefix(raw)

    def _strip_known_namespace_prefix(self, path, source_namespace=None):
        cleaned = str(path).replace("\\", "/").lstrip("/")
        prefixes = [self.namespace]
        if source_namespace and source_namespace not in prefixes:
            prefixes.append(source_namespace)
        for prefix in prefixes:
            if cleaned.startswith(f"{prefix}/"):
                return cleaned[len(prefix) + 1:]
        return cleaned

    def _is_path_inside(self, child_path, parent_path):
        try:
            return os.path.commonpath([child_path, parent_path]) == os.path.normpath(parent_path)
        except ValueError:
            return False
