import os
import shutil
import json
from .base import BaseMigrator

class IAMigrator(BaseMigrator):
    def __init__(self, ia_resourcepack_path, ce_resourcepack_path, namespace):
        super().__init__(ia_resourcepack_path, ce_resourcepack_path)
        self.namespace = namespace

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
        self.generate_missing_item_models()
        
        print("迁移完成。")

    def _migrate_textures(self):
        """
        ItemsAdder: assets/<namespace>/textures/<path>
        CraftEngine: assets/<namespace>/textures/item/<path> (标准约定)
        """
        src_dir = os.path.join(self.input_path, "assets", self.namespace, "textures")
        if not os.path.exists(src_dir):
            print(f"警告: 在 {src_dir} 未找到纹理")
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
                
                # 确定目标位置
                # IA 护甲图层 (皮肤) 通常在文件名中包含 "layer_"。
                # 我们希望保持它们的原始结构 (或者如果我们要更严格，则移动到 entity/)。
                # 但护甲图标 (物品) 应该去 textures/item/。
                
                if "layer_" in file:
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
        src_dir = os.path.join(self.input_path, "assets", self.namespace, "models")
        if not os.path.exists(src_dir):
            return

        for root, _, files in os.walk(src_dir):
            for file in files:
                if not file.endswith(".json"):
                    continue
                
                rel_path = os.path.relpath(root, src_dir)
                src_file = os.path.join(root, file)
                
                # 移动到 CE 中的 item/ 子目录
                dest_rel = os.path.join("item", rel_path)
                dest_dir = os.path.join(self.output_path, "assets", self.namespace, "models", dest_rel)
                os.makedirs(dest_dir, exist_ok=True)
                
                dest_file = os.path.join(dest_dir, file)
                
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
                        if "layer" not in path_part and "armor" not in path_part and not path_part.startswith("item/"):
                             new_path = f"item/{path_part}"
                        else:
                             new_path = path_part
                             
                        new_val = f"{self.namespace}:{new_path}"
                        new_textures[key] = new_val
                    else:
                        # 没有命名空间（例如 "#texture" 引用或纯路径），保持原样或添加当前命名空间
                        if val.startswith("#"):
                             new_textures[key] = val
                        else:
                             # 可能是相对路径，加上命名空间
                             if "layer" not in val and "armor" not in val and not val.startswith("item/"):
                                  new_path = f"item/{val}"
                             else:
                                  new_path = val
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

            with open(dest_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
                
        except Exception as e:
            print(f"处理模型 {src_file} 时出错: {e}")

    def _migrate_sounds(self):
        # 占位符
        pass
