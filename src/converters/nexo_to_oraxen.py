import os

from .base import BaseConverter
from .ia_to_oraxen import IAToOraxenConverter
from .nexo_to_ia import NexoToIAConverter


class NexoToOraxenConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.oraxen_config = {
            "items": {},
            "categories": {},
            "recipes": {},
        }
        self.nexo_resourcepack_roots = []
        self.oraxen_pack_root = None
        self._oraxen_converter = IAToOraxenConverter()

    def set_resource_paths(self, nexo_root, oraxen_pack_root, additional_nexo_roots=None):
        self.nexo_resourcepack_roots = []
        if isinstance(nexo_root, str) and nexo_root.strip():
            self.nexo_resourcepack_roots.append(os.path.normpath(nexo_root))
        if isinstance(additional_nexo_roots, (list, tuple)):
            for path in additional_nexo_roots:
                if isinstance(path, str) and path.strip():
                    normalized = os.path.normpath(path)
                    if normalized not in self.nexo_resourcepack_roots:
                        self.nexo_resourcepack_roots.append(normalized)
        self.oraxen_pack_root = oraxen_pack_root

    def convert(self, nexo_data, namespace=None):
        if namespace:
            self.namespace = namespace

        ia_config = NexoToIAConverter().convert(nexo_data if isinstance(nexo_data, dict) else {}, namespace=self.namespace)
        self._oraxen_converter = IAToOraxenConverter()
        self.oraxen_config = self._oraxen_converter.convert(ia_config, namespace=self.namespace)
        return self.oraxen_config

    def save_config(self, output_root):
        pack_root = self.oraxen_pack_root or os.path.join(output_root, "pack")
        if self.nexo_resourcepack_roots:
            self._oraxen_converter.set_resource_paths(self.nexo_resourcepack_roots, pack_root)
        self._oraxen_converter.save_config(output_root)
