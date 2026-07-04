import os
import re

from .base import BaseConverter, RecipeDumper
from src.migrators.crucible_to_ia import CrucibleToIAMigrator


class CrucibleToIAConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.namespace = "mythic"
        self.ia_config = {
            "info": {"namespace": self.namespace},
            "items": {},
            "categories": {},
            "equipments": {},
            "recipes": {},
            "font_images": {},
        }
        self.crucible_resource_roots = []
        self.ia_resourcepack_root = None
        self._source_item_ids = {}
        self._group_items = {}

    def set_resource_paths(self, crucible_roots, ia_root):
        if isinstance(crucible_roots, (list, tuple)):
            self.crucible_resource_roots = [
                os.path.normpath(path)
                for path in crucible_roots
                if isinstance(path, str) and path.strip()
            ]
        elif isinstance(crucible_roots, str) and crucible_roots.strip():
            self.crucible_resource_roots = [os.path.normpath(crucible_roots)]
        else:
            self.crucible_resource_roots = []
        self.ia_resourcepack_root = ia_root

    def convert(self, crucible_data, namespace=None):
        if namespace:
            self.namespace = namespace
        elif isinstance(crucible_data, dict):
            inferred = self._infer_namespace(crucible_data)
            if inferred:
                self.namespace = inferred

        self.ia_config = {
            "info": {"namespace": self.namespace},
            "items": {},
            "categories": {},
            "equipments": {},
            "recipes": {},
            "font_images": {},
        }
        self._group_items = {}

        items = self._extract_items(crucible_data)
        self._source_item_ids = {
            str(raw_id): self._sanitize_id(raw_id)
            for raw_id in items.keys()
        }
        for raw_id, item_data in items.items():
            if isinstance(item_data, dict):
                self._convert_item(raw_id, item_data)

        self._convert_font_images(self._extract_font_images(crucible_data))
        self._generate_group_categories()
        self._generate_default_category()
        return self.ia_config

    def save_config(self, output_dir):
        os.makedirs(output_dir, exist_ok=True)

        armor_items = {}
        normal_items = {}
        block_items = {}
        for item_id, item_data in self.ia_config["items"].items():
            specific = item_data.get("specific_properties", {})
            if isinstance(specific, dict) and isinstance(specific.get("block"), dict):
                block_items[item_id] = item_data
            elif isinstance(item_data.get("equipment"), dict):
                armor_items[item_id] = item_data
            else:
                normal_items[item_id] = item_data

        if normal_items:
            self._write_yaml_with_footer(
                {"info": self.ia_config["info"], "items": normal_items},
                os.path.join(output_dir, f"{self.namespace}.yml"),
            )

        if block_items:
            self._write_yaml_with_footer(
                {"info": self.ia_config["info"], "items": block_items},
                os.path.join(output_dir, f"{self.namespace}_blocks.yml"),
            )

        if armor_items or self.ia_config["equipments"]:
            self._write_yaml_with_footer(
                {
                    "info": self.ia_config["info"],
                    "equipments": self.ia_config["equipments"],
                    "items": armor_items,
                },
                os.path.join(output_dir, f"{self.namespace}_armor.yml"),
            )

        if self.ia_config["categories"]:
            self._write_yaml_with_footer(
                {"info": self.ia_config["info"], "categories": self.ia_config["categories"]},
                os.path.join(output_dir, f"{self.namespace}_category.yml"),
            )

        if self.ia_config["recipes"]:
            self._write_yaml_with_footer(
                {"info": self.ia_config["info"], "recipes": self.ia_config["recipes"]},
                os.path.join(output_dir, f"{self.namespace}_recipes.yml"),
                dumper=RecipeDumper,
            )

        if self.ia_config["font_images"]:
            self._write_yaml_with_footer(
                {"info": self.ia_config["info"], "font_images": self.ia_config["font_images"]},
                os.path.join(output_dir, f"{self.namespace}_font_images.yml"),
            )

        if self.crucible_resource_roots and self.ia_resourcepack_root:
            CrucibleToIAMigrator(
                self.crucible_resource_roots,
                self.ia_resourcepack_root,
                self.namespace,
            ).migrate()

    def _convert_item(self, raw_id, data):
        item_id = self._source_item_ids.get(str(raw_id), self._sanitize_id(raw_id))
        ia_item = {}

        enabled = self._get_dict_value(data, "Enabled", "enabled")
        if enabled is not None:
            ia_item["enabled"] = bool(enabled)

        display = self._get_dict_value(data, "Display", "display", "Name", "name")
        if isinstance(display, str) and display.strip():
            ia_item["display_name"] = display

        lore = self._get_dict_value(data, "Lore", "lore")
        if isinstance(lore, list):
            ia_item["lore"] = [str(line) for line in lore]
        elif isinstance(lore, str) and lore.strip():
            ia_item["lore"] = [lore]

        permission = self._get_nested_value(data, ("Options", "Permission"))
        if not permission:
            permission = self._get_dict_value(data, "Permission", "permission")
        if isinstance(permission, str) and permission.strip():
            ia_item["permission"] = permission

        enchants = self._get_dict_value(data, "Enchantments", "Enchant", "enchants")
        if enchants:
            ia_item["enchants"] = enchants

        attributes = self._convert_attributes(self._get_dict_value(data, "Attributes", "attributes"))
        if attributes:
            ia_item["attribute_modifiers"] = attributes

        durability = self._convert_durability(data)
        if durability:
            ia_item["durability"] = durability

        resource = self._build_resource(data)
        graphics = self._build_graphics(data)
        if self._should_use_graphics(data, graphics):
            ia_item["material"] = str(resource.get("material", "PAPER")).lower()
            ia_item["graphics"] = graphics
        elif resource:
            ia_item["resource"] = resource

        behaviours = self._build_behaviours(data)
        if behaviours:
            ia_item["behaviours"] = behaviours

        specific_properties = self._build_specific_properties(data, item_id, ia_item)
        if specific_properties:
            ia_item["specific_properties"] = specific_properties

        equipment = self._build_equipment(data, item_id, ia_item)
        if equipment:
            ia_item["equipment"] = equipment

        self.ia_config["items"][item_id] = ia_item
        self._add_group_item(data, item_id)
        self._convert_item_recipes(item_id, data)

    def _build_resource(self, data):
        material = self._get_dict_value(data, "Material", "material", "Id", "ID", "id", default="PAPER")
        resource = {"material": str(material).upper()}

        model_id = self._get_dict_value(data, "CustomModelData", "custom_model_data", "Model", "model")
        if isinstance(model_id, (int, float)):
            resource["model_id"] = int(model_id)
        elif isinstance(model_id, str) and model_id.strip().isdigit():
            resource["model_id"] = int(model_id.strip())

        generation = self._get_dict_value(data, "Generation", "generation")
        self._apply_generation_to_resource(resource, generation)

        custom_block = self._get_dict_value(data, "CustomBlock", "custom_block", default={})
        if isinstance(custom_block, dict):
            texture = self._get_dict_value(custom_block, "Texture", "texture")
            textures = self._get_dict_value(custom_block, "Textures", "textures")
            block_model = self._get_dict_value(custom_block, "Model", "model")
            if texture and "textures" not in resource:
                resource["textures"] = [self._normalize_resource_path(texture, suffix_to_strip=".png")]
                resource["generate"] = True
            elif textures and "textures" not in resource:
                resource["textures"] = self._normalize_texture_collection(textures)
                resource["generate"] = True
            if isinstance(block_model, str) and block_model.strip() and "model_path" not in resource:
                resource["model_path"] = self._normalize_resource_path(block_model)
                resource["generate"] = False

        resource.setdefault("generate", False if "model_path" in resource else True)
        return resource

    def _apply_generation_to_resource(self, resource, generation):
        if isinstance(generation, str) and generation.strip():
            path = self._normalize_resource_path(generation)
            kind = self._detect_generation_kind(path)
            if kind == "texture":
                resource["textures"] = [path]
                resource["generate"] = True
            else:
                resource["model_path"] = path
                resource["generate"] = False
            return

        if not isinstance(generation, dict):
            return

        model = self._get_dict_value(generation, "Model", "model")
        texture = self._get_dict_value(generation, "Texture", "texture")
        textures = self._get_dict_value(generation, "Textures", "textures")
        if model:
            resource["model_path"] = self._normalize_resource_path(model)
            resource["generate"] = False
        if texture:
            resource["textures"] = [self._normalize_resource_path(texture, suffix_to_strip=".png")]
            resource["generate"] = True
        if textures:
            resource["textures"] = self._normalize_texture_collection(textures)
            resource["generate"] = True

    def _build_graphics(self, data):
        generation = self._get_dict_value(data, "Generation", "generation")
        if not isinstance(generation, (dict, str)):
            return {}

        states = {}
        use_models = False

        if isinstance(generation, str):
            normal = self._normalize_resource_path(generation)
            if normal:
                states["normal"] = normal
                use_models = self._detect_generation_kind(normal) != "texture"
        else:
            model = self._get_dict_value(generation, "Model", "model")
            texture = self._get_dict_value(generation, "Texture", "texture")
            if model:
                states["normal"] = self._normalize_resource_path(model)
                use_models = True
            elif texture:
                states["normal"] = self._normalize_resource_path(texture, suffix_to_strip=".png")

        state_map = {
            "Pulling": "pulling",
            "pulling": "pulling",
            "Charged": "arrow",
            "charged": "arrow",
            "Firework": "rocket",
            "firework": "rocket",
            "Casting": "cast",
            "casting": "cast",
            "Blocking": "blocking",
            "blocking": "blocking",
        }
        for source_key, target_key in state_map.items():
            value = self._get_dict_value(generation, source_key)
            if value is None:
                continue
            if target_key == "pulling":
                pulling = self._normalize_pulling_values(value)
                states.update(pulling)
                if any(self._detect_generation_kind(path) == "model" for path in pulling.values()):
                    use_models = True
            else:
                path = self._normalize_state_path(value)
                states[target_key] = path
                if self._detect_generation_kind(path) == "model":
                    use_models = True

        armor = self._get_dict_value(generation, "Armor", "armor", default={})
        if isinstance(armor, dict):
            icon_texture = self._get_dict_value(armor, "Icon", "Texture", "texture")
            if icon_texture and "normal" not in states:
                states["normal"] = self._normalize_resource_path(icon_texture, suffix_to_strip=".png")

        self._add_discovered_item_state_models(data, states)
        if any(self._detect_generation_kind(path) == "model" for path in states.values()):
            use_models = True

        if not states:
            return {}
        if len(states) == 1 and "normal" in states:
            return {"model": states["normal"]} if use_models else {"texture": states["normal"]}
        return {"models": states} if use_models else {"textures": states}

    def _should_use_graphics(self, data, graphics):
        if not graphics:
            return False
        material = str(self._get_dict_value(data, "Material", "material", "Id", "ID", "id", default="")).upper()
        if material not in {"BOW", "CROSSBOW", "FISHING_ROD", "SHIELD", "TRIDENT"}:
            return False
        states = graphics.get("models") or graphics.get("textures")
        if not isinstance(states, dict):
            return False
        return any(key != "normal" for key in states.keys())

    def _add_discovered_item_state_models(self, data, states):
        material = str(self._get_dict_value(data, "Material", "material", "Id", "ID", "id", default="")).upper()
        normal = states.get("normal")
        if not isinstance(normal, str) or not normal:
            return
        if material in {"BOW", "CROSSBOW"}:
            for index in range(3):
                key = f"pulling_{index}"
                candidate = f"{normal}_pulling_{index}"
                if key not in states and self._detect_generation_kind(candidate) == "model":
                    states[key] = candidate
        if material == "CROSSBOW" and "arrow" not in states:
            charged = f"{normal}_charged"
            if self._detect_generation_kind(charged) == "model":
                states["arrow"] = charged

    def _build_behaviours(self, data):
        item_type = str(self._get_dict_value(data, "Type", "type", default="ITEM")).upper()
        behaviours = {}

        equip_slot = self._normalize_slot(
            self._get_dict_value(data, "EquipSlot", "equip_slot")
            or self._get_nested_value(data, ("Equippable", "Slot"))
        )
        if item_type == "HAT" or equip_slot == "head":
            behaviours["hat"] = True

        furniture = self._get_dict_value(data, "Furniture", "furniture", default={})
        if item_type == "FURNITURE" or isinstance(furniture, dict) and furniture:
            behaviours["furniture"] = self._convert_furniture(furniture if isinstance(furniture, dict) else {})
            sit = self._convert_furniture_sit(furniture if isinstance(furniture, dict) else {})
            if sit:
                behaviours["furniture_sit"] = sit

        return behaviours

    def _convert_furniture(self, furniture):
        entity = str(self._get_dict_value(furniture, "Type", "type", default="DISPLAY")).upper()
        if entity in {"ITEM_FRAME", "ITEMFRAME", "FRAME"}:
            ia_entity = "item_frame"
        elif entity in {"ARMOR_STAND", "ARMORSTAND", "STAND"}:
            ia_entity = "armor_stand"
        else:
            ia_entity = "item_display"

        result = {"entity": ia_entity}

        hitbox = self._get_dict_value(furniture, "Hitbox", "hitbox", default={})
        converted_hitbox = {}
        if isinstance(hitbox, dict):
            height = self._get_dict_value(hitbox, "Height", "height")
            width = self._get_dict_value(hitbox, "Width", "width")
            length = self._get_dict_value(hitbox, "Length", "length")
            if height is not None:
                converted_hitbox["height"] = height
            if width is not None:
                converted_hitbox["width"] = width
                converted_hitbox.setdefault("length", width)
            if length is not None:
                converted_hitbox["length"] = length

        barriers = self._get_dict_value(furniture, "Barriers", "barriers")
        if barriers:
            result["solid"] = True
            converted_hitbox.setdefault("width", 1)
            converted_hitbox.setdefault("height", 1)
            converted_hitbox.setdefault("length", 1)
            offsets = self._first_barrier_offsets(barriers)
            converted_hitbox.update(offsets)

        if converted_hitbox:
            converted_hitbox.setdefault("width_offset", 0)
            converted_hitbox.setdefault("height_offset", 0)
            converted_hitbox.setdefault("length_offset", 0)
            result["hitbox"] = converted_hitbox

        placement = str(self._get_dict_value(furniture, "Placement", "placement", default="FLOOR")).upper()
        result["placeable_on"] = self._convert_placement(placement)

        can_rotate = self._get_dict_value(furniture, "CanRotate", "can_rotate")
        if can_rotate is False:
            result["fixed_rotation"] = True

        light_level = self._max_light_level(self._get_dict_value(furniture, "Lights", "lights"))
        if light_level is not None:
            result["light_level"] = light_level

        scale = self._parse_vector(self._get_dict_value(furniture, "Scale", "scale"))
        if scale:
            result["display_transformation"] = {
                "scale": {"x": scale[0], "y": scale[1], "z": scale[2]}
            }

        return result

    def _convert_furniture_sit(self, furniture):
        seats = self._get_dict_value(furniture, "Seats", "seats")
        if not isinstance(seats, list) or not seats:
            return {}
        first = seats[0]
        parts = self._parse_vector(first)
        if not parts:
            return {}
        return {"sit_height": parts[1] + 0.85}

    def _build_specific_properties(self, data, item_id, ia_item):
        specific = {}
        item_type = str(self._get_dict_value(data, "Type", "type", default="ITEM")).upper()

        custom_block = self._get_dict_value(data, "CustomBlock", "custom_block", default={})
        if item_type == "BLOCK" or isinstance(custom_block, dict) and custom_block:
            block_data = custom_block if isinstance(custom_block, dict) else {}
            block_props = {
                "placed_model": {
                    "type": self._convert_block_type(self._get_dict_value(block_data, "Type", "type", default="NOTE_BLOCK"))
                }
            }
            block_id = self._get_dict_value(block_data, "Id", "ID", "id")
            if block_id is not None:
                block_props["placed_model"]["id"] = block_id
            hardness = self._get_dict_value(block_data, "Hardness", "hardness")
            if hardness is not None:
                block_props["hardness"] = hardness
            tools = self._get_dict_value(block_data, "Tools", "tools")
            if tools:
                block_props["break_tools_whitelist"] = self._convert_tool_list(tools)
            require_tool = self._get_dict_value(block_data, "RequireToolForDrops", "require_tool_for_drops")
            if require_tool is not None:
                block_props["drop_when_mined"] = not bool(require_tool) or bool(tools)
            drop_self = self._get_dict_value(block_data, "DropSelf", "drop_self")
            if drop_self is not None:
                block_props["drop_when_mined"] = bool(drop_self)
            specific["block"] = block_props

        armor_slot = self._infer_armor_slot(data, ia_item)
        if armor_slot:
            specific.setdefault("armor", {})["slot"] = armor_slot

        return specific

    def _build_equipment(self, data, item_id, ia_item):
        slot = self._infer_armor_slot(data, ia_item)
        if not slot:
            return {}

        generation = self._get_dict_value(data, "Generation", "generation", default={})
        armor = {}
        if isinstance(generation, dict):
            armor = self._get_dict_value(generation, "Armor", "armor", default={})
            if not isinstance(armor, dict):
                armor = {}

        texture = self._get_dict_value(armor, "Texture", "texture")
        if not texture:
            equippable_model = self._get_nested_value(data, ("Equippable", "Model"))
            texture = equippable_model
        if not texture:
            return {}

        armor_id = self._armor_id_from_texture(texture)
        layer_1 = f"{self._normalize_resource_path(texture, suffix_to_strip='.png')}_layer_1"
        layer_2 = f"{self._normalize_resource_path(texture, suffix_to_strip='.png')}_layer_2"
        self.ia_config["equipments"][armor_id] = {
            "layer_1": layer_1,
            "layer_2": layer_2,
        }
        return {"id": armor_id, "slot": slot.upper()}

    def _convert_item_recipes(self, item_id, data):
        recipes = self._get_dict_value(data, "Recipes", "recipes")
        if not isinstance(recipes, dict):
            return
        for raw_recipe_id, recipe_data in recipes.items():
            if not isinstance(recipe_data, dict):
                continue
            recipe_type = str(self._get_dict_value(recipe_data, "Type", "type", default=raw_recipe_id)).upper()
            recipe_id = self._sanitize_id(f"{item_id}_{raw_recipe_id}")
            amount = self._get_dict_value(recipe_data, "Amount", "amount", default=1)
            if recipe_type in {"SHAPED", "SHAPELESS"}:
                entry = {"enabled": True}
                if recipe_type == "SHAPELESS":
                    entry["shapeless"] = True
                    entry["ingredients"] = self._convert_shapeless_ingredients(
                        self._get_dict_value(recipe_data, "Ingredients", "ingredients", default=[])
                    )
                else:
                    pattern, ingredients = self._convert_shaped_ingredients(
                        self._get_dict_value(recipe_data, "Ingredients", "ingredients", default=[])
                    )
                    entry["pattern"] = pattern
                    entry["ingredients"] = ingredients
                entry["result"] = {"item": f"{self.namespace}:{item_id}", "amount": amount}
                self.ia_config["recipes"].setdefault("crafting_table", {})[recipe_id] = entry
            elif recipe_type in {"FURNACE", "CAMPFIRE", "BLASTING", "SMOKING"}:
                entry = {
                    "enabled": True,
                    "machines": [self._convert_cooking_machine(recipe_type)],
                    "ingredient": self._normalize_recipe_ref(
                        self._get_dict_value(recipe_data, "Ingredient", "ingredient")
                    ),
                    "result": {"item": f"{self.namespace}:{item_id}", "amount": amount},
                }
                experience = self._get_dict_value(recipe_data, "Experience", "experience")
                if experience is not None:
                    entry["exp"] = experience
                cooking_time = self._get_dict_value(recipe_data, "CookingTime", "cooking_time", "time")
                if cooking_time is not None:
                    entry["cook_time"] = cooking_time
                self.ia_config["recipes"].setdefault("cooking", {})[recipe_id] = entry
            elif recipe_type == "STONECUTTING":
                self.ia_config["recipes"].setdefault("stonecutting", {})[recipe_id] = {
                    "enabled": True,
                    "ingredient": self._normalize_recipe_ref(
                        self._get_dict_value(recipe_data, "Ingredient", "ingredient")
                    ),
                    "result": {"item": f"{self.namespace}:{item_id}", "amount": amount},
                }
            elif recipe_type == "SMITHING":
                entry = {"enabled": True, "result": {"item": f"{self.namespace}:{item_id}", "amount": amount}}
                for source_key, target_key in (
                    ("Template", "template"),
                    ("Base", "base"),
                    ("Addition", "addition"),
                ):
                    value = self._get_dict_value(recipe_data, source_key, source_key.lower())
                    if value is not None:
                        entry[target_key] = self._normalize_recipe_ref(value)
                self.ia_config["recipes"].setdefault("smithing", {})[recipe_id] = entry
            elif recipe_type == "BREWING":
                entry = {"enabled": True, "result": {"item": f"{self.namespace}:{item_id}", "amount": amount}}
                ingredient = self._get_dict_value(recipe_data, "Ingredient", "ingredient")
                input_item = self._get_dict_value(recipe_data, "InputItem", "input_item", "Container", "container")
                if ingredient is not None:
                    entry["ingredient"] = self._normalize_recipe_ref(ingredient)
                if input_item is not None:
                    entry["container"] = self._normalize_recipe_ref(input_item)
                self.ia_config["recipes"].setdefault("brewing", {})[recipe_id] = entry

    def _convert_font_images(self, font_images):
        if not isinstance(font_images, dict):
            return
        for raw_id, data in font_images.items():
            if not isinstance(data, dict):
                continue
            image_id = self._sanitize_id(raw_id)
            entry = {}
            file_value = self._get_dict_value(data, "File", "file")
            if file_value:
                entry["path"] = self._normalize_resource_path(file_value, suffix_to_strip=".png")
            char = self._get_dict_value(data, "Char", "char")
            if char:
                entry["symbol"] = char
            ascent = self._get_dict_value(data, "Ascent", "ascent")
            if ascent is not None:
                entry["y_position"] = ascent
            height = self._get_dict_value(data, "Height", "height")
            if height is not None:
                entry["scale_ratio"] = height
            if entry:
                self.ia_config["font_images"][image_id] = entry

    def _extract_items(self, data):
        if not isinstance(data, dict):
            return {}
        wrapped = self._get_dict_value(data, "items", "Items")
        if isinstance(wrapped, dict):
            return {
                key: value
                for key, value in wrapped.items()
                if isinstance(value, dict) and self._looks_like_crucible_item(value)
            }
        return {
            key: value
            for key, value in data.items()
            if isinstance(value, dict) and self._looks_like_crucible_item(value)
        }

    def _extract_font_images(self, data):
        if not isinstance(data, dict):
            return {}
        return self._get_dict_value(data, "font_images", "FontImages", "font-images", default={})

    def _looks_like_crucible_item(self, value):
        if not isinstance(value, dict):
            return False
        markers = (
            "Id",
            "Material",
            "Display",
            "Lore",
            "Model",
            "CustomModelData",
            "Generation",
            "Type",
            "Furniture",
            "CustomBlock",
            "Recipes",
            "EquipSlot",
            "Equippable",
            "Options",
        )
        return any(self._get_dict_value(value, marker) is not None for marker in markers)

    def _infer_namespace(self, data):
        generation = self._get_dict_value(data, "Generation", "generation", default={})
        if isinstance(generation, dict):
            namespace = self._get_dict_value(generation, "Namespace", "namespace")
            if isinstance(namespace, str) and re.match(r"^[0-9a-z_.-]+$", namespace):
                return namespace
        return None

    def _convert_attributes(self, attributes):
        if not isinstance(attributes, dict):
            return {}
        converted = {}
        for raw_slot, slot_attributes in attributes.items():
            if not isinstance(slot_attributes, dict):
                continue
            slot = self._normalize_slot(raw_slot) or str(raw_slot).lower()
            converted[slot] = {}
            for raw_attribute, value in slot_attributes.items():
                converted[slot][self._normalize_attribute(raw_attribute)] = value
        return {slot: attrs for slot, attrs in converted.items() if attrs}

    def _convert_durability(self, data):
        durability = {}
        max_durability = self._get_dict_value(data, "MaxDurability", "max_durability")
        if isinstance(max_durability, (int, float)):
            durability["max_custom_durability"] = int(max_durability)
        return durability

    def _normalize_texture_collection(self, value):
        if isinstance(value, str):
            return [self._normalize_resource_path(value, suffix_to_strip=".png")]
        if isinstance(value, list):
            return [
                self._normalize_resource_path(item, suffix_to_strip=".png")
                for item in value
                if isinstance(item, str)
            ]
        if isinstance(value, dict):
            return [
                self._normalize_resource_path(item, suffix_to_strip=".png")
                for item in value.values()
                if isinstance(item, str)
            ]
        return value

    def _normalize_pulling_values(self, value):
        values = value if isinstance(value, list) else [value]
        result = {}
        for index, item in enumerate(values):
            if item is None:
                continue
            result[f"pulling_{index}"] = self._normalize_state_path(item)
        return result

    def _normalize_state_path(self, value):
        if isinstance(value, str):
            path = value.split()[0]
            return self._normalize_resource_path(path)
        return self._normalize_resource_path(value)

    def _convert_placement(self, placement):
        placement = str(placement).upper()
        if placement == "ANY":
            return {"floor": True, "walls": True, "ceiling": True}
        if placement == "CEILING":
            return {"floor": False, "walls": False, "ceiling": True}
        if placement in {"HANGING", "WALL"}:
            return {"floor": False, "walls": True, "ceiling": False}
        return {"floor": True, "walls": False, "ceiling": False}

    def _first_barrier_offsets(self, barriers):
        if not isinstance(barriers, list) or not barriers:
            return {}
        parts = self._parse_vector(barriers[0])
        if not parts:
            return {}
        return {
            "width_offset": parts[0],
            "height_offset": parts[1],
            "length_offset": parts[2],
        }

    def _max_light_level(self, lights):
        if lights is True:
            return 15
        if not isinstance(lights, list):
            return None
        levels = []
        for light in lights:
            if not isinstance(light, str):
                continue
            parts = light.replace(",", " ").split()
            if parts and parts[-1].lstrip("-").isdigit():
                levels.append(int(parts[-1]))
        return max(levels) if levels else None

    def _parse_vector(self, value):
        if isinstance(value, str):
            parts = re.split(r"[,\s]+", value.strip())
        elif isinstance(value, (list, tuple)):
            parts = list(value)
        elif isinstance(value, dict):
            parts = [value.get("x"), value.get("y"), value.get("z")]
        else:
            return None
        if len(parts) < 3:
            return None
        try:
            return float(parts[0]), float(parts[1]), float(parts[2])
        except (TypeError, ValueError):
            return None

    def _convert_block_type(self, value):
        block_type = str(value).upper().replace("-", "_")
        if block_type in {"TRIPWIRE", "WIRE", "STRING"}:
            return "REAL_WIRE"
        if block_type in {"CHORUS", "CHORUS_PLANT"}:
            return "REAL_TRANSPARENT"
        return "REAL_NOTE"

    def _convert_tool_list(self, tools):
        if not isinstance(tools, list):
            return tools
        result = []
        for tool in tools:
            if isinstance(tool, str) and tool.strip():
                result.append(self._normalize_recipe_ref(tool.split()[0]))
        return result

    def _infer_armor_slot(self, data, ia_item):
        slot = self._normalize_slot(
            self._get_dict_value(data, "EquipSlot", "equip_slot")
            or self._get_nested_value(data, ("Equippable", "Slot"))
        )
        if slot in {"head", "chest", "legs", "feet"} and self._is_armor_like(data, ia_item):
            return slot
        material = str(ia_item.get("resource", {}).get("material", "")).upper()
        if material.endswith("_HELMET"):
            return "head"
        if material.endswith("_CHESTPLATE"):
            return "chest"
        if material.endswith("_LEGGINGS"):
            return "legs"
        if material.endswith("_BOOTS"):
            return "feet"
        return None

    def _is_armor_like(self, data, ia_item):
        generation = self._get_dict_value(data, "Generation", "generation", default={})
        if isinstance(generation, dict) and isinstance(self._get_dict_value(generation, "Armor", "armor"), dict):
            return True
        material = str(ia_item.get("resource", {}).get("material", "")).upper()
        return any(material.endswith(suffix) for suffix in ("_HELMET", "_CHESTPLATE", "_LEGGINGS", "_BOOTS"))

    def _armor_id_from_texture(self, value):
        path = self._normalize_resource_path(value, suffix_to_strip=".png")
        base = os.path.basename(path)
        for suffix in ("_layer_1", "_layer_2", "_helmet", "_chestplate", "_leggings", "_boots"):
            if base.endswith(suffix):
                base = base[:-len(suffix)]
        return self._sanitize_id(base or f"{self.namespace}_armor")

    def _convert_shaped_ingredients(self, ingredients):
        rows = ingredients if isinstance(ingredients, list) else []
        symbols = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        ingredient_symbols = {}
        next_symbol = 0
        pattern = []
        converted_ingredients = {}
        for row in rows:
            cells = [cell.strip() for cell in str(row).split("|")]
            row_pattern = ""
            for cell in cells:
                if not cell or cell.upper() == "AIR":
                    row_pattern += " "
                    continue
                normalized = self._normalize_recipe_ref(cell)
                if normalized not in ingredient_symbols:
                    symbol = symbols[next_symbol]
                    next_symbol += 1
                    ingredient_symbols[normalized] = symbol
                    converted_ingredients[symbol] = normalized
                row_pattern += ingredient_symbols[normalized]
            pattern.append(row_pattern)
        return pattern, converted_ingredients

    def _convert_shapeless_ingredients(self, ingredients):
        if isinstance(ingredients, dict):
            values = ingredients.values()
        elif isinstance(ingredients, list):
            values = ingredients
        else:
            values = []
        return [
            self._normalize_recipe_ref(item)
            for item in values
            if isinstance(item, str) and item.strip() and item.strip().upper() != "AIR"
        ]

    def _convert_cooking_machine(self, recipe_type):
        return {
            "FURNACE": "furnace",
            "CAMPFIRE": "campfire",
            "BLASTING": "blast_furnace",
            "SMOKING": "smoker",
        }.get(recipe_type, "furnace")

    def _normalize_recipe_ref(self, value):
        if value is None:
            return value
        if isinstance(value, dict):
            item_id = self._get_dict_value(value, "item", "id")
            return self._normalize_recipe_ref(item_id)
        ref = str(value).strip()
        if not ref:
            return ref
        if ref.startswith("#") or ref.startswith("minecraft:"):
            return ref
        if ":" in ref:
            namespace, item_id = ref.split(":", 1)
            if namespace == "minecraft":
                return f"minecraft:{item_id.lower()}"
            mapped = self._source_item_ids.get(item_id) or self._source_item_ids.get(item_id.lower())
            return f"{self.namespace}:{mapped or self._sanitize_id(item_id)}"
        mapped = self._source_item_ids.get(ref) or self._source_item_ids.get(ref.lower())
        if mapped:
            return f"{self.namespace}:{mapped}"
        return ref.upper() if re.match(r"^[a-zA-Z0-9_]+$", ref) else ref

    def _add_group_item(self, data, item_id):
        group = self._get_dict_value(data, "Group", "group")
        if not isinstance(group, str) or not group.strip():
            return
        category = self._sanitize_id(group)
        self._group_items.setdefault(category, []).append(f"{self.namespace}:{item_id}")

    def _generate_group_categories(self):
        for category_id, items in self._group_items.items():
            if not items:
                continue
            self.ia_config["categories"][category_id] = {
                "enabled": True,
                "name": category_id,
                "icon": items[0],
                "permission": f"ia.menu.{category_id}",
                "items": items,
            }

    def _generate_default_category(self):
        if self.ia_config["categories"] or not self.ia_config["items"]:
            return
        items = [f"{self.namespace}:{item_id}" for item_id in self.ia_config["items"].keys()]
        self.ia_config["categories"][self.namespace] = {
            "enabled": True,
            "name": self.namespace,
            "icon": items[0],
            "permission": f"ia.menu.{self.namespace}",
            "items": items,
        }

    def _detect_generation_kind(self, path):
        if not path:
            return None
        rel = str(path).replace("\\", "/").strip("/")
        for root in self.crucible_resource_roots:
            model_candidates = [
                os.path.join(root, "Assets", "models", f"{rel}.json"),
                os.path.join(root, "Assets", "models", f"{rel}.bbmodel"),
                os.path.join(root, "models", f"{rel}.json"),
                os.path.join(root, "models", f"{rel}.bbmodel"),
                os.path.join(root, "assets", self.namespace, "models", f"{rel}.json"),
                os.path.join(root, "assets", "minecraft", "models", f"{rel}.json"),
            ]
            texture_candidates = [
                os.path.join(root, "Assets", "textures", f"{rel}.png"),
                os.path.join(root, "textures", f"{rel}.png"),
                os.path.join(root, "assets", self.namespace, "textures", f"{rel}.png"),
                os.path.join(root, "assets", "minecraft", "textures", f"{rel}.png"),
            ]
            if any(os.path.isfile(candidate) for candidate in model_candidates):
                return "model"
            if any(os.path.isfile(candidate) for candidate in texture_candidates):
                return "texture"
        return None

    def _normalize_resource_path(self, value, suffix_to_strip=".json"):
        if not isinstance(value, str):
            return value
        raw = value.strip().replace("\\", "/").strip("/")
        if not raw:
            return raw
        if suffix_to_strip and raw.endswith(suffix_to_strip):
            raw = raw[:-len(suffix_to_strip)]
        for suffix in (".json", ".png", ".bbmodel"):
            if raw.endswith(suffix):
                raw = raw[:-len(suffix)]
        if ":" in raw:
            namespace, raw = raw.split(":", 1)
            if namespace == "minecraft":
                return f"minecraft:{raw.strip('/')}"
        for prefix in ("models/", "textures/"):
            if raw.startswith(prefix):
                raw = raw[len(prefix):]
        if raw.startswith(f"{self.namespace}/"):
            raw = raw[len(self.namespace) + 1:]
        return raw.strip("/")

    def _normalize_slot(self, value):
        if value is None:
            return None
        slot = str(value).strip().lower()
        slot_map = {
            "helmet": "head",
            "head": "head",
            "chest": "chest",
            "chestplate": "chest",
            "legs": "legs",
            "leggings": "legs",
            "feet": "feet",
            "boots": "feet",
            "hand": "mainhand",
            "mainhand": "mainhand",
            "offhand": "offhand",
        }
        return slot_map.get(slot, slot or None)

    def _normalize_attribute(self, value):
        attribute = str(value).strip().lower().replace("_", "-")
        mapping = {
            "health": "max-health",
            "attack-damage": "attack-damage",
            "damage": "attack-damage",
            "attack-speed": "attack-speed",
            "armor-toughness": "armor-toughness",
        }
        return mapping.get(attribute, attribute)

    def _sanitize_id(self, value):
        text = str(value or "").strip()
        text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
        text = re.sub(r"[^0-9A-Za-z_.-]+", "_", text).strip("_.-")
        text = text.lower()
        return text or "item"

    def _get_nested_value(self, data, path):
        current = data
        for key in path:
            if not isinstance(current, dict):
                return None
            current = self._get_dict_value(current, key)
        return current

    def _get_dict_value(self, data, *keys, default=None):
        if not isinstance(data, dict):
            return default
        for key in keys:
            if key in data:
                return data[key]
        lowered = {}
        normalized = {}
        for key, value in data.items():
            if isinstance(key, str):
                lowered[key.lower()] = value
                normalized[key.lower().replace("-", "_")] = value
        for key in keys:
            if not isinstance(key, str):
                continue
            lowered_key = key.lower()
            if lowered_key in lowered:
                return lowered[lowered_key]
            normalized_key = lowered_key.replace("-", "_")
            if normalized_key in normalized:
                return normalized[normalized_key]
        return default
