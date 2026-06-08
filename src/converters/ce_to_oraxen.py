import os

from .base import BaseConverter
from .ce_to_ia import CEToIAConverter
from .ia_to_oraxen import IAToOraxenConverter


class CEToOraxenConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.oraxen_config = {
            "items": {},
            "categories": {},
            "recipes": {},
        }
        self.ce_resourcepack_roots = []
        self.oraxen_pack_root = None
        self._oraxen_converter = IAToOraxenConverter()

    def set_resource_paths(self, ce_roots, oraxen_pack_root):
        self.ce_resourcepack_roots = []
        if isinstance(ce_roots, (list, tuple)):
            for path in ce_roots:
                if isinstance(path, str) and path.strip():
                    normalized = os.path.normpath(path)
                    if normalized not in self.ce_resourcepack_roots:
                        self.ce_resourcepack_roots.append(normalized)
        elif isinstance(ce_roots, str) and ce_roots.strip():
            self.ce_resourcepack_roots.append(os.path.normpath(ce_roots))
        self.oraxen_pack_root = oraxen_pack_root

    def convert(self, ce_data, namespace=None):
        if namespace:
            self.namespace = namespace

        ia_config = CEToIAConverter().convert(ce_data if isinstance(ce_data, dict) else {}, namespace=self.namespace)
        self._oraxen_converter = IAToOraxenConverter()
        self.oraxen_config = self._oraxen_converter.convert(ia_config, namespace=self.namespace)
        return self.oraxen_config

    def save_config(self, output_root):
        pack_root = self.oraxen_pack_root or os.path.join(output_root, "pack")
        if self.ce_resourcepack_roots:
            self._oraxen_converter.set_resource_paths(self.ce_resourcepack_roots, pack_root)
        self._oraxen_converter.save_config(output_root)
