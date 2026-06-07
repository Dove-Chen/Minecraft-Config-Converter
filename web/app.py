from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
import os
import shutil
import zipfile
import uuid
import re
from threading import Thread
import time
import yaml

# 导入核心逻辑
import sys
# 将项目根目录添加到 python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.converters.ia_to_ce import IAConverter
from src.converters.nexo_to_ce import NexoConverter
from src.converters.nexo_to_ia import NexoToIAConverter
from src.converters.oraxen_to_ia import OraxenToIAConverter
from src.converters.ce_to_ia import CEToIAConverter
from src.analyzer import PackageAnalyzer
from src.utils.yaml_loader import safe_load_yaml

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'temp_uploads')
app.config['OUTPUT_FOLDER'] = os.path.join(os.getcwd(), 'temp_output')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB 限制

# 支持的插件列表
SUPPORTED_PLUGINS = [
    {"id": "ItemsAdder", "name": "ItemsAdder", "icon": "/static/images/itemsadder.webp"},
    {"id": "Nexo", "name": "Nexo", "icon": "/static/images/nexo.webp"},
    {"id": "Oraxen", "name": "Oraxen", "icon": "/static/images/oraxen.webp"},
    {"id": "CraftEngine", "name": "CraftEngine", "icon": "/static/images/craftengine.webp"},
    {"id": "MythicCrucible", "name": "MythicCrucible", "icon": "/static/images/mythiccrucible.webp"}
    # {"id": "HMCCosmetics", "name": "HMCCosmetics", "icon": "👒"}
]

# 确保临时目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

def _is_valid_session_id(value):
    if not isinstance(value, str) or not value:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False

def _safe_join_under(base_dir, *parts):
    base_path = os.path.abspath(base_dir)
    target_path = os.path.abspath(os.path.join(base_path, *parts))
    try:
        if os.path.commonpath([base_path, target_path]) != base_path:
            raise ValueError("检测到不安全的路径")
    except ValueError:
        raise ValueError("检测到不安全的路径")
    return target_path

def _sanitize_upload_filename(raw_filename):
    filename = secure_filename(raw_filename or "")
    if not filename:
        filename = "upload.zip"
    return filename

def _save_uploaded_zip(file, session_upload_dir):
    filename = _sanitize_upload_filename(file.filename)
    if not filename.lower().endswith(".zip"):
        raise ValueError("请上传 .zip 文件")
    file_path = _safe_join_under(session_upload_dir, filename)
    file.save(file_path)
    return filename, file_path

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze():
    if 'file' not in request.files:
        return jsonify({'error': '没有收到文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '未选择文件'}), 400

    if file:
        session_id = str(uuid.uuid4())
        session_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
        os.makedirs(session_upload_dir, exist_ok=True)

        try:
            filename, file_path = _save_uploaded_zip(file, session_upload_dir)

            extract_dir = os.path.join(session_upload_dir, "extracted")
            _safe_extract_zip(file_path, extract_dir)

            # 运行分析
            analyzer = PackageAnalyzer(extract_dir)
            report = analyzer.analyze()
            
            # 根据检测到的格式确定可用的目标格式
            # 逻辑：
            # 1. 识别源格式 (可能包含多个)
            # 2. 如果包含 ItemsAdder -> 允许转为 CraftEngine (除非已包含 CraftEngine)
            # 3. 如果包含 CraftEngine -> 暂无转换 (或允许转为 ItemsAdder)
            # 4. 如果包含 Nexo -> 暂无转换
            
            detected_formats = report["formats"]
            available_targets = []
            warnings = []
            
            if "ItemsAdder" in detected_formats:
                if "CraftEngine" in detected_formats:
                    warnings.append("检测到包中已包含 CraftEngine 配置。转换可能会覆盖或产生冲突。")
                if "CraftEngine" not in available_targets:
                    available_targets.append("CraftEngine")
            
            if "Nexo" in detected_formats:
                if "CraftEngine" in detected_formats:
                    warnings.append("检测到包中已包含 CraftEngine 配置。转换可能会覆盖或产生冲突。")
                if "CraftEngine" not in available_targets:
                    available_targets.append("CraftEngine")
                if "ItemsAdder" in detected_formats:
                    warnings.append("检测到包中已包含 ItemsAdder 配置。转换可能会覆盖或产生冲突。")
                if "ItemsAdder" not in available_targets:
                    available_targets.append("ItemsAdder")

            if "Oraxen" in detected_formats:
                if "ItemsAdder" in detected_formats:
                    warnings.append("检测到包中已包含 ItemsAdder 配置。转换可能会覆盖或产生冲突。")
                if "ItemsAdder" not in available_targets:
                    available_targets.append("ItemsAdder")
                
            if "CraftEngine" in detected_formats:
                if "ItemsAdder" in detected_formats:
                    warnings.append("检测到包中已包含 ItemsAdder 配置。转换可能会覆盖或产生冲突。")
                if "ItemsAdder" not in available_targets:
                    available_targets.append("ItemsAdder")

            report["source_formats"] = detected_formats # 改名以反映复数
            report["available_targets"] = available_targets
            report["warnings"] = warnings
            report["filename"] = filename
            report["supported_plugins"] = SUPPORTED_PLUGINS
            
            return jsonify({
                'status': 'success',
                'report': report,
                'session_id': session_id
            })

        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/convert', methods=['POST'])
def convert():
    # 支持两种模式：
    # 1. 传统的直接上传文件并转换 (保持兼容)
    # 2. 接受 session_id (从 /api/analyze 获取) 进行转换
    
    session_id = request.form.get('session_id')
    target_format = request.form.get('target_format', 'CraftEngine') # 默认 CE
    source_format = request.form.get('source_format') # 新增: 明确源格式
    
    if session_id:
        if not _is_valid_session_id(session_id):
            return jsonify({'error': '无效的会话 ID'}), 400
        # 使用已存在的会话
        session_upload_dir = _safe_join_under(app.config['UPLOAD_FOLDER'], session_id)
        extract_dir = _safe_join_under(session_upload_dir, "extracted")
        if not os.path.exists(extract_dir):
            return jsonify({'error': '会话已过期或不存在'}), 400
            
        session_output_dir = _safe_join_under(app.config['OUTPUT_FOLDER'], session_id)
        os.makedirs(session_output_dir, exist_ok=True)
        
    elif 'file' in request.files:
        # 传统模式
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': '未选择文件'}), 400
            
        session_id = str(uuid.uuid4())
        session_upload_dir = _safe_join_under(app.config['UPLOAD_FOLDER'], session_id)
        session_output_dir = _safe_join_under(app.config['OUTPUT_FOLDER'], session_id)
        os.makedirs(session_upload_dir, exist_ok=True)
        os.makedirs(session_output_dir, exist_ok=True)

        try:
            filename, file_path = _save_uploaded_zip(file, session_upload_dir)
            extract_dir = _safe_join_under(session_upload_dir, "extracted")
            _safe_extract_zip(file_path, extract_dir)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
    else:
        return jsonify({'error': '无效的请求'}), 400

    try:
        if target_format == "CraftEngine":
            if source_format == "Nexo":
                return _convert_nexo_to_ce(extract_dir, session_output_dir, session_upload_dir, target_format)
            else:
                # 默认为 ItemsAdder 或显式指定
                return _convert_ia_to_ce(extract_dir, session_output_dir, session_upload_dir, target_format)

        if target_format == "ItemsAdder":
            if source_format == "CraftEngine":
                return _convert_ce_to_ia(extract_dir, session_output_dir, session_upload_dir, target_format)
            if source_format == "Oraxen":
                return _convert_oraxen_to_ia(extract_dir, session_output_dir, session_upload_dir, target_format)
            if source_format == "Nexo":
                return _convert_nexo_to_ia(extract_dir, session_output_dir, session_upload_dir, target_format)
            return jsonify({'error': '目前仅支持 CraftEngine/Oraxen/Nexo -> ItemsAdder'}), 400
        
        return jsonify({'error': f'不支持的目标格式: {target_format}'}), 400

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def _extract_nexo_namespace_from_path(value):
    if not value or not isinstance(value, str):
        return None
    path = value
    if ":" in path:
        path = path.split(":", 1)[1]
    path = path.replace("\\", "/").lstrip("/")
    if not path:
        return None
    first = path.split("/", 1)[0].strip().lower()
    if re.match(r'^[0-9a-z_.-]+$', first):
        return first
    return None

def _extract_nexo_explicit_namespace(value):
    if not value or not isinstance(value, str):
        return None
    path = value.strip()
    if ":" not in path:
        return None
    first = path.split(":", 1)[0].strip().lower()
    if re.match(r'^[0-9a-z_.-]+$', first):
        return first
    return None

def _get_case_insensitive_dict_value(data, *keys, default=None):
    if not isinstance(data, dict):
        return default
    for key in keys:
        if key in data:
            return data[key]
    lowered = {}
    for k, v in data.items():
        if isinstance(k, str):
            lowered[k.lower()] = v
    for key in keys:
        if isinstance(key, str):
            v = lowered.get(key.lower())
            if v is not None:
                return v
    return default

def _infer_nexo_namespace_from_data(nexo_data):
    explicit_model_scores = {}
    scores = {}
    if not isinstance(nexo_data, dict):
        return None
    for item_data in nexo_data.values():
        if not isinstance(item_data, dict):
            continue
        pack = _get_case_insensitive_dict_value(item_data, "Pack", "pack", default={})
        if isinstance(pack, dict):
            model_value = _get_case_insensitive_dict_value(pack, "model", default=None)
            explicit_model_ns = _extract_nexo_explicit_namespace(model_value)
            if explicit_model_ns:
                explicit_model_scores[explicit_model_ns] = explicit_model_scores.get(explicit_model_ns, 0) + 1
            model_ns = _extract_nexo_namespace_from_path(model_value)
            if model_ns:
                scores[model_ns] = scores.get(model_ns, 0) + 3
            custom_armor = _get_case_insensitive_dict_value(pack, "CustomArmor", "custom_armor", "customArmor", default={})
            if isinstance(custom_armor, dict):
                for key in ("layer1", "layer2", "texture"):
                    armor_ns = _extract_nexo_namespace_from_path(_get_case_insensitive_dict_value(custom_armor, key, default=None))
                    if armor_ns:
                        scores[armor_ns] = scores.get(armor_ns, 0) + 2
            texture_ns = _extract_nexo_namespace_from_path(_get_case_insensitive_dict_value(pack, "texture", default=None))
            if texture_ns:
                scores[texture_ns] = scores.get(texture_ns, 0) + 2
    if explicit_model_scores:
        return max(explicit_model_scores.items(), key=lambda x: x[1])[0]
    if not scores:
        return None
    return max(scores.items(), key=lambda x: x[1])[0]

def _infer_nexo_namespace_from_pack(nexo_resourcepack_path):
    scores = {}
    pack_paths = []
    if isinstance(nexo_resourcepack_path, (list, tuple)):
        for path in nexo_resourcepack_path:
            if isinstance(path, str) and path.strip():
                pack_paths.append(path)
    elif isinstance(nexo_resourcepack_path, str) and nexo_resourcepack_path.strip():
        pack_paths.append(nexo_resourcepack_path)

    for pack_path in pack_paths:
        assets_root = os.path.join(pack_path, "assets")
        candidate_roots = [
            os.path.join(assets_root, "minecraft", "models"),
            os.path.join(assets_root, "minecraft", "textures")
        ]
        for root in candidate_roots:
            if not os.path.isdir(root):
                continue
            for ns in os.listdir(root):
                ns_path = os.path.join(root, ns)
                if not os.path.isdir(ns_path):
                    continue
                if not re.match(r'^[0-9a-z_.-]+$', ns):
                    continue
                file_count = 0
                for _, _, files in os.walk(ns_path):
                    file_count += len(files)
                if file_count > 0:
                    scores[ns] = scores.get(ns, 0) + file_count
    if not scores:
        return None
    return max(scores.items(), key=lambda x: x[1])[0]

def _resolve_nexo_namespace(nexo_data, fallback_namespace, nexo_resourcepack_path):
    data_ns = _infer_nexo_namespace_from_data(nexo_data)
    if data_ns:
        return data_ns
    pack_ns = _infer_nexo_namespace_from_pack(nexo_resourcepack_path)
    if pack_ns:
        return pack_ns
    return fallback_namespace

def _is_safe_member_path(base_dir, member_name):
    # 防止 zip 路径穿越，确保条目解压后仍位于目标目录
    base_path = os.path.abspath(base_dir)
    normalized_member = os.path.normpath(member_name.replace("\\", "/"))
    target_path = os.path.abspath(os.path.join(base_path, normalized_member))
    try:
        return os.path.commonpath([base_path, target_path]) == base_path
    except ValueError:
        return False

def _safe_extract_zip(zip_file_path, destination_dir):
    with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
        for member in zip_ref.infolist():
            name = member.filename
            if not name:
                continue
            if not _is_safe_member_path(destination_dir, name):
                raise ValueError(f"检测到不安全的压缩条目: {name}")
            zip_ref.extract(member, destination_dir)

def _find_resourcepack_root(search_dir):
    # 优先返回包含 assets 的目录，其次返回包含 models/textures 的目录
    if not os.path.isdir(search_dir):
        return None
    if os.path.isdir(os.path.join(search_dir, "assets")):
        return search_dir
    if os.path.isdir(os.path.join(search_dir, "models")) or os.path.isdir(os.path.join(search_dir, "textures")):
        return search_dir

    for root, dirs, _ in os.walk(search_dir):
        if "assets" in dirs:
            return root
        if "models" in dirs or "textures" in dirs:
            return root
    return None

def _collect_nexo_resourcepack_paths(base_pack_dir, temp_extract_root):
    paths = []
    if not isinstance(base_pack_dir, str) or not os.path.isdir(base_pack_dir):
        return paths

    base_norm = os.path.normpath(base_pack_dir)
    paths.append(base_norm)

    external_dir = None
    for entry in os.listdir(base_pack_dir):
        entry_path = os.path.join(base_pack_dir, entry)
        if os.path.isdir(entry_path) and entry.lower() == "external_packs":
            external_dir = entry_path
            break
    if not external_dir:
        return paths

    os.makedirs(temp_extract_root, exist_ok=True)
    zip_files = [f for f in os.listdir(external_dir) if f.lower().endswith(".zip")]
    zip_files.sort(key=lambda x: x.lower())

    for index, zip_name in enumerate(zip_files):
        source_zip = os.path.join(external_dir, zip_name)
        extract_dir = os.path.join(temp_extract_root, f"{index:03d}_{os.path.splitext(zip_name)[0]}")
        os.makedirs(extract_dir, exist_ok=True)
        _safe_extract_zip(source_zip, extract_dir)

        pack_root = _find_resourcepack_root(extract_dir)
        if pack_root:
            normalized = os.path.normpath(pack_root)
            if normalized not in paths:
                paths.append(normalized)

    return paths

def _merge_nexo_resourcepacks(resourcepack_paths, merged_root):
    # 将多个资源包目录按顺序叠加到同一目录，后者覆盖前者
    if not isinstance(resourcepack_paths, (list, tuple)) or not resourcepack_paths:
        return None
    os.makedirs(merged_root, exist_ok=True)

    for root in resourcepack_paths:
        if not isinstance(root, str) or not os.path.isdir(root):
            continue
        for current_root, _, files in os.walk(root):
            rel_dir = os.path.relpath(current_root, root)
            target_dir = merged_root if rel_dir == "." else os.path.join(merged_root, rel_dir)
            os.makedirs(target_dir, exist_ok=True)
            for file_name in files:
                src_file = os.path.join(current_root, file_name)
                dst_file = os.path.join(target_dir, file_name)
                shutil.copy2(src_file, dst_file)
    return merged_root


def _extract_oraxen_namespace_from_value(value):
    if not isinstance(value, str) or not value.strip():
        return None
    path = value.strip()
    if ":" in path:
        path = path.split(":", 1)[1]
    path = path.replace("\\", "/").lstrip("/")
    if not path:
        return None
    first = path.split("/", 1)[0].strip().lower()
    if re.match(r'^[0-9a-z_.-]+$', first):
        return first
    return None


def _infer_oraxen_namespace_from_data(oraxen_data):
    if not isinstance(oraxen_data, dict):
        return None
    scores = {}
    for value in oraxen_data.values():
        if not isinstance(value, dict):
            continue
        pack = value.get("Pack", {})
        if not isinstance(pack, dict):
            continue
        model_ns = _extract_oraxen_namespace_from_value(pack.get("model"))
        if model_ns:
            scores[model_ns] = scores.get(model_ns, 0) + 3
        textures = pack.get("textures")
        if isinstance(textures, list):
            for texture in textures:
                texture_ns = _extract_oraxen_namespace_from_value(texture)
                if texture_ns:
                    scores[texture_ns] = scores.get(texture_ns, 0) + 2
        for key in ("cast_model", "blocking_model", "charged_model", "firework_model"):
            ns = _extract_oraxen_namespace_from_value(pack.get(key))
            if ns:
                scores[ns] = scores.get(ns, 0) + 1
    if not scores:
        return None
    return max(scores.items(), key=lambda x: x[1])[0]


def _infer_oraxen_namespace_from_pack(oraxen_pack_path):
    if not oraxen_pack_path:
        return None
    candidates = [
        os.path.join(oraxen_pack_path, "models"),
        os.path.join(oraxen_pack_path, "textures"),
        os.path.join(oraxen_pack_path, "assets")
    ]
    scores = {}
    for root in candidates:
        if not os.path.isdir(root):
            continue
        for ns in os.listdir(root):
            ns_path = os.path.join(root, ns)
            if not os.path.isdir(ns_path):
                continue
            if not re.match(r'^[0-9a-z_.-]+$', ns):
                continue
            file_count = 0
            for _, _, files in os.walk(ns_path):
                file_count += len(files)
            if file_count > 0:
                scores[ns] = scores.get(ns, 0) + file_count
    if not scores:
        return None
    return max(scores.items(), key=lambda x: x[1])[0]


def _resolve_oraxen_namespace(oraxen_data, fallback_namespace, oraxen_pack_path):
    data_ns = _infer_oraxen_namespace_from_data(oraxen_data)
    if data_ns:
        return data_ns
    pack_ns = _infer_oraxen_namespace_from_pack(oraxen_pack_path)
    if pack_ns:
        return pack_ns
    return fallback_namespace

def _get_config_section(data, section_name):
    if not isinstance(data, dict):
        return {}
    merged = {}
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        if key.split("#", 1)[0] != section_name:
            continue
        if isinstance(value, dict):
            merged.update(value)
    return merged

def _merge_ce_sections(data):
    merged = {}
    for section_name in ("items", "equipments", "categories", "recipes", "furniture"):
        section = _get_config_section(data, section_name)
        if section:
            merged[section_name] = section
    return merged

def _merge_ce_data(target, source):
    for section_name, section_data in source.items():
        if not isinstance(section_data, dict):
            continue
        target.setdefault(section_name, {}).update(section_data)

def _is_valid_namespace(value):
    return isinstance(value, str) and re.match(r'^[0-9a-z_.-]+$', value) is not None

def _score_namespace(scores, value, weight=1):
    if not _is_valid_namespace(value):
        return
    scores[value] = scores.get(value, 0) + weight

def _infer_ce_namespace_from_path(config_path):
    parts = os.path.normpath(config_path).split(os.sep)
    lowered = [p.lower() for p in parts]
    if "resources" in lowered:
        index = lowered.index("resources")
        if index + 1 < len(parts):
            candidate = parts[index + 1].lower()
            if _is_valid_namespace(candidate):
                return candidate
    return None

def _infer_ce_namespace(ce_data, config_path):
    scores = {}
    for section_name in ("items", "equipments", "categories", "recipes", "furniture"):
        section = ce_data.get(section_name)
        if not isinstance(section, dict):
            continue
        for raw_key in section.keys():
            if isinstance(raw_key, str) and ":" in raw_key:
                namespace = raw_key.split(":", 1)[0].lower()
                _score_namespace(scores, namespace, weight=3)

    path_namespace = _infer_ce_namespace_from_path(config_path)
    if path_namespace:
        _score_namespace(scores, path_namespace, weight=2)

    if scores:
        return max(scores.items(), key=lambda x: x[1])[0]

    fallback = re.sub(r'[^0-9a-z_.-]', '_', os.path.splitext(os.path.basename(config_path))[0].lower())
    return fallback if _is_valid_namespace(fallback) else "converted"

def _collect_ce_resourcepack_paths(extract_dir, namespace=None):
    paths = []
    for root, dirs, _ in os.walk(extract_dir):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            lower_name = dir_name.lower()
            if lower_name == "resourcepack":
                if namespace:
                    inferred = _infer_ce_namespace_from_path(dir_path)
                    if inferred and inferred != namespace:
                        continue
                normalized = os.path.normpath(dir_path)
                if normalized not in paths:
                    paths.append(normalized)
            elif lower_name == "assets":
                normalized_root = os.path.normpath(root)
                if normalized_root not in paths:
                    paths.append(normalized_root)
    return paths

def _convert_ce_to_ia(extract_dir, session_output_dir, session_upload_dir, target_format):
    ce_config_entries = []

    scan_root = extract_dir
    for root, dirs, _ in os.walk(extract_dir):
        for dir_name in dirs:
            if dir_name.lower() == "craftengine":
                scan_root = os.path.join(root, dir_name)
                break
        if scan_root != extract_dir:
            break

    for root, _, files in os.walk(scan_root):
        for file_name in files:
            if not file_name.endswith((".yml", ".yaml")):
                continue
            config_path = os.path.join(root, file_name)
            try:
                data = safe_load_yaml(config_path)
            except Exception as e:
                print(f"Error loading CraftEngine config {config_path}: {e}")
                continue
            ce_data = _merge_ce_sections(data)
            if ce_data:
                ce_config_entries.append((config_path, ce_data))

    if not ce_config_entries:
        return jsonify({'error': '未能找到 CraftEngine 配置文件'}), 400

    user_namespace = request.form.get('namespace')
    if user_namespace:
        if not _is_valid_namespace(user_namespace):
            return jsonify({'error': '命名空间包含非法字符。仅允许小写字母、数字、下划线、连字符和英文句号。'}), 400
        namespace_map = {user_namespace: {}}
        for _, ce_data in ce_config_entries:
            _merge_ce_data(namespace_map[user_namespace], ce_data)
    else:
        namespace_map = {}
        for config_path, ce_data in ce_config_entries:
            namespace = _infer_ce_namespace(ce_data, config_path)
            namespace_map.setdefault(namespace, {})
            _merge_ce_data(namespace_map[namespace], ce_data)

    for namespace, merged_data in namespace_map.items():
        converter = CEToIAConverter()
        ia_output_base = os.path.join(session_output_dir, "ItemsAdder", "contents", namespace)
        ia_config_dir = os.path.join(ia_output_base, "configs")
        ia_res_dir = os.path.join(ia_output_base, "resourcepack")

        ce_resourcepack_paths = _collect_ce_resourcepack_paths(extract_dir, namespace=None if user_namespace else namespace)
        if ce_resourcepack_paths:
            converter.set_resource_paths(ce_resourcepack_paths, ia_res_dir)

        converter.convert(merged_data, namespace=namespace)
        converter.save_config(ia_config_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="ItemsAdder")

def _convert_nexo_to_ce(extract_dir, session_output_dir, session_upload_dir, target_format):
    # 1. 扫描 Nexo 配置和资源
    nexo_items_configs = []
    nexo_resourcepack_path = None
    nexo_resourcepack_paths = []
    merged_nexo_resourcepack_path = None
    
    # 尝试找到 Nexo 根目录
    scan_root = extract_dir
    for root, dirs, files in os.walk(extract_dir):
        if "Nexo" in dirs:
            scan_root = os.path.join(root, "Nexo")
            break
        elif "nexo" in dirs:
             scan_root = os.path.join(root, "nexo")
             break

    # 扫描配置和资源
    for root, dirs, files in os.walk(scan_root):
        # 资源包检测（大小写无关）
        if nexo_resourcepack_path is None:
            dir_lookup = {d.lower(): d for d in dirs}
            if "pack" in dir_lookup:
                nexo_resourcepack_path = os.path.join(root, dir_lookup["pack"])
            elif "assets" in dir_lookup:
                nexo_resourcepack_path = root
             
        # 配置文件检测
        for f in files:
            if f.endswith((".yml", ".yaml")):
                full_path = os.path.join(root, f)
                # 简单过滤，避免加载非配置
                if "config.yml" in f: continue
                nexo_items_configs.append(full_path)

    if not nexo_items_configs:
         return jsonify({'error': '未能找到 Nexo 配置文件'}), 400

    if nexo_resourcepack_path:
        external_extract_root = os.path.join(session_upload_dir, "_nexo_external_packs_ce")
        merged_pack_root = os.path.join(session_upload_dir, "_nexo_merged_pack_ce")
        if os.path.isdir(external_extract_root):
            shutil.rmtree(external_extract_root, ignore_errors=True)
        if os.path.isdir(merged_pack_root):
            shutil.rmtree(merged_pack_root, ignore_errors=True)
        nexo_resourcepack_paths = _collect_nexo_resourcepack_paths(nexo_resourcepack_path, external_extract_root)
        merged_nexo_resourcepack_path = _merge_nexo_resourcepacks(nexo_resourcepack_paths, merged_pack_root)

    # 2. 运行转换
    # 准备命名空间
    user_namespace = request.form.get('namespace')
    
    if user_namespace and re.match(r'^[0-9a-z_.-]+$', user_namespace):
        # 用户指定了命名空间，合并所有配置
        converter = NexoConverter()
        merged_data = {}
        for config_path in nexo_items_configs:
            data = safe_load_yaml(config_path)
            if isinstance(data, dict):
                 merged_data.update(data)
        
        namespace = user_namespace
        ce_output_base = os.path.join(session_output_dir, "CraftEngine", "resources", namespace)
        ce_config_dir = os.path.join(ce_output_base, "configuration", "items", namespace)
        ce_res_dir = os.path.join(ce_output_base, "resourcepack")

        if merged_nexo_resourcepack_path:
            converter.set_resource_paths(merged_nexo_resourcepack_path, ce_res_dir)

        converter.convert(merged_data, namespace=namespace)
        converter.save_config(ce_config_dir)
        
    else:
        grouped_data = {}
        for config_path in nexo_items_configs:
            data = safe_load_yaml(config_path)
            if not isinstance(data, dict):
                continue
            
            filename = os.path.basename(config_path)
            fallback_namespace = os.path.splitext(filename)[0]
            fallback_namespace = re.sub(r'[^0-9a-z_.-]', '_', fallback_namespace.lower())
            namespace = _resolve_nexo_namespace(
                data,
                fallback_namespace,
                nexo_resourcepack_paths if nexo_resourcepack_paths else nexo_resourcepack_path
            )
            if namespace not in grouped_data:
                grouped_data[namespace] = {}
            grouped_data[namespace].update(data)

        for namespace, merged_data in grouped_data.items():
            converter = NexoConverter()
            ce_output_base = os.path.join(session_output_dir, "CraftEngine", "resources", namespace)
            ce_config_dir = os.path.join(ce_output_base, "configuration", "items", namespace)
            ce_res_dir = os.path.join(ce_output_base, "resourcepack")

            if merged_nexo_resourcepack_path:
                converter.set_resource_paths(merged_nexo_resourcepack_path, ce_res_dir)
            
            converter.convert(merged_data, namespace=namespace)
            converter.save_config(ce_config_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format)

def _convert_ia_to_ce(extract_dir, session_output_dir, session_upload_dir, target_format):
    # 3. 定位配置和资源 (ItemsAdder -> CraftEngine 逻辑)
    # 改进逻辑: 扫描所有 YAML 文件并根据内容进行分类
    ia_items_configs = []
    ia_categories_configs = []
    ia_recipes_configs = []
    ia_resourcepack_path = None

    # 0. 确定扫描根目录
    scan_root = extract_dir
    found_ia_dir = False
    for root, dirs, files in os.walk(extract_dir):
        for d in dirs:
            if d.lower() == "itemsadder":
                scan_root = os.path.join(root, d)
                found_ia_dir = True
                break
        if found_ia_dir:
            break
    
    if found_ia_dir:
            print(f"Detected ItemsAdder root at: {scan_root}")

    # 第一遍扫描：查找配置文件和标准资源包结构
    for root, dirs, files in os.walk(scan_root):
        # --- 资源包检测 ---
        # 优先级 1: 显式的 "resourcepack" 目录
        if "resourcepack" in dirs and ia_resourcepack_path is None:
            ia_resourcepack_path = os.path.join(root, "resourcepack")
        
        # 优先级 2: 直接包含 assets 的目录
        if "assets" in dirs and ia_resourcepack_path is None:
            ia_resourcepack_path = root

        # 优先级 3: 直接包含 models 和 textures 的目录 (非标准结构)
        if "models" in dirs and "textures" in dirs and ia_resourcepack_path is None:
            ia_resourcepack_path = root

        # --- 配置文件检测 ---
        for f in files:
            if f.endswith(".yml") or f.endswith(".yaml"):
                full_path = os.path.join(root, f)
                try:
                    print(f"Scanning: {full_path}")
                    data = safe_load_yaml(full_path)
                    if not data:
                        continue
                    
                    # 检查关键签名
                    if "items" in data or "equipments" in data or "armors_rendering" in data or "legacy_armor_renderings" in data:
                        ia_items_configs.append(full_path)
                    if "categories" in data:
                        ia_categories_configs.append(full_path)
                    if "recipes" in data:
                        ia_recipes_configs.append(full_path)
                except Exception as e:
                    print(f"Error loading {full_path}: {e}")
                    continue

    # 如果仍未找到资源包，尝试寻找 textures/models 的父级 (处理非标准结构)
    if ia_resourcepack_path is None:
        # 如果有配置文件，默认为提取根目录
        if ia_items_configs:
            ia_resourcepack_path = extract_dir

    if not ia_items_configs:
            return jsonify({'error': '未能找到包含物品定义的配置文件 (items/equipments)'}), 400

    # 4. 运行转换
    converter = IAConverter()
    
    # 加载并合并所有物品配置
    merged_items_data = {
        "items": {},
        "equipments": {},
        "armors_rendering": {},
        "legacy_armor_renderings": {},
        "templates": {},
        "recipes": {},
        "info": {}
    }
    
    for config_path in ia_items_configs:
        data = converter.load_config(config_path)
        if not data: continue
        
        # 合并逻辑
        if "info" in data and not merged_items_data["info"]:
            merged_items_data["info"] = data["info"] # 使用找到的第一个 info
        
        if "items" in data:
            merged_items_data.setdefault("items", {}).update(data["items"])
            
        if "equipments" in data:
            merged_items_data.setdefault("equipments", {}).update(data["equipments"])
            
        if "armors_rendering" in data:
            merged_items_data.setdefault("armors_rendering", {}).update(data["armors_rendering"])

        if "legacy_armor_renderings" in data:
            merged_items_data.setdefault("legacy_armor_renderings", {}).update(data["legacy_armor_renderings"])
            
        if "templates" in data:
            merged_items_data.setdefault("templates", {}).update(data["templates"])

    ia_data = merged_items_data
    
    # 如果找到则加载分类
    if ia_categories_configs:
        merged_categories = {}
        for cat_config in ia_categories_configs:
            data = converter.load_config(cat_config)
            if data and "categories" in data:
                merged_categories.update(data["categories"])
        
        if merged_categories:
            ia_data["categories"] = merged_categories

    if ia_recipes_configs:
        merged_recipes = {}
        for recipe_config in ia_recipes_configs:
            data = converter.load_config(recipe_config)
            if not data:
                continue
            if "info" in data and not ia_data.get("info"):
                ia_data["info"] = data["info"]
            recipes_block = data.get("recipes")
            if not isinstance(recipes_block, dict):
                continue
            for group_key, group_data in recipes_block.items():
                if group_key not in merged_recipes:
                    merged_recipes[group_key] = {}
                if isinstance(group_data, dict):
                    merged_recipes[group_key].update(group_data)
        if merged_recipes:
            ia_data["recipes"] = merged_recipes

    # 准备输出路径
    # CraftEngine 输出结构: resources/<namespace>/...
    # 使用配置中的命名空间或默认值
    original_namespace = ia_data.get("info", {}).get("namespace", "converted")
    namespace = original_namespace
    
    # 检查用户是否指定了命名空间
    user_namespace = request.form.get('namespace')
    if user_namespace:
        # 验证命名空间规则: 0-9, a-z, _, -, .
        if not re.match(r'^[0-9a-z_.-]+$', user_namespace):
            return jsonify({'error': '命名空间包含非法字符。仅允许小写字母、数字、下划线、连字符和英文句号。'}), 400
        namespace = user_namespace

    # 特殊处理：如果资源包结构是非标准的（直接包含 models/textures），则重组为标准结构
    # 这通常发生在 ia_resourcepack_path 指向了包含 models/textures 的根目录，但缺少 assets/<namespace> 包装的情况
    if ia_resourcepack_path and os.path.exists(ia_resourcepack_path):
        # 检查标准结构是否存在
        assets_path = os.path.join(ia_resourcepack_path, "assets")
        if not os.path.exists(assets_path):
            # 检查是否有models 或 textures
            has_models = os.path.exists(os.path.join(ia_resourcepack_path, "models"))
            has_textures = os.path.exists(os.path.join(ia_resourcepack_path, "textures"))
            
            if has_models or has_textures:
                print(f"检测到非标准资源包结构，正在重组为 assets/{namespace}/...")
                # 创建一个新的临时目录作为资源包根目录，以避免污染原始提取目录或处理路径冲突
                restructured_root = os.path.join(session_upload_dir, "restructured_rp")
                target_ns_dir = os.path.join(restructured_root, "assets", namespace)
                os.makedirs(target_ns_dir, exist_ok=True)
                
                # 移动文件夹
                for folder_name in ["models", "textures", "sounds"]:
                    src_folder = os.path.join(ia_resourcepack_path, folder_name)
                    if os.path.exists(src_folder):
                        dst_folder = os.path.join(target_ns_dir, folder_name)
                        # 移动文件夹
                        shutil.move(src_folder, dst_folder)
                
                # 更新资源包路径指向新的标准结构根目录
                ia_resourcepack_path = restructured_root
        else:
            # 标准结构：如果命名空间改变，尝试重命名文件夹以匹配新的命名空间
            if namespace != original_namespace:
                src_ns_path = os.path.join(assets_path, original_namespace)
                dst_ns_path = os.path.join(assets_path, namespace)
                if os.path.exists(src_ns_path) and not os.path.exists(dst_ns_path):
                    try:
                        print(f"Renaming resource pack namespace: {original_namespace} -> {namespace}")
                        shutil.move(src_ns_path, dst_ns_path)
                    except Exception as e:
                        print(f"Warning: Failed to rename namespace folder: {e}")
    
    ce_output_base = os.path.join(session_output_dir, "CraftEngine", "resources", namespace)
    ce_config_dir = os.path.join(ce_output_base, "configuration", "items", namespace)
    ce_res_dir = os.path.join(ce_output_base, "resourcepack")
    
    # 如果找到 resourcepack 则设置资源路径
    if ia_resourcepack_path:
        converter.set_resource_paths(ia_resourcepack_path, ce_res_dir)

    converter.convert(ia_data, namespace=namespace)
    
    converter.save_config(ce_config_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format)


def _convert_oraxen_to_ia(extract_dir, session_output_dir, session_upload_dir, target_format):
    oraxen_item_configs = []
    oraxen_pack_path = None

    scan_root = extract_dir
    for root, dirs, _ in os.walk(extract_dir):
        for d in dirs:
            if d.lower() == "oraxen":
                scan_root = os.path.join(root, d)
                break
        if scan_root != extract_dir:
            break

    for root, dirs, files in os.walk(scan_root):
        if "pack" in dirs and oraxen_pack_path is None:
            oraxen_pack_path = os.path.join(root, "pack")
        elif "assets" in dirs and oraxen_pack_path is None:
            oraxen_pack_path = root

        for f in files:
            if not f.endswith((".yml", ".yaml")):
                continue
            full_path = os.path.join(root, f)
            if "settings" in f.lower():
                continue
            data = safe_load_yaml(full_path)
            if not isinstance(data, dict):
                continue
            sample = next(iter(data.values()), None)
            if isinstance(sample, dict) and ("Pack" in sample or "displayname" in sample):
                oraxen_item_configs.append(full_path)

    if not oraxen_item_configs:
        return jsonify({'error': '未能找到 Oraxen 物品配置文件'}), 400

    merged_data = {}
    for config_path in oraxen_item_configs:
        data = safe_load_yaml(config_path)
        if isinstance(data, dict):
            merged_data.update(data)

    user_namespace = request.form.get('namespace')
    if user_namespace:
        if not re.match(r'^[0-9a-z_.-]+$', user_namespace):
            return jsonify({'error': '命名空间包含非法字符。仅允许小写字母、数字、下划线、连字符和英文句号。'}), 400
        namespace = user_namespace
    else:
        fallback_namespace = "converted"
        first_file = os.path.basename(oraxen_item_configs[0])
        if first_file:
            fallback_namespace = re.sub(r'[^0-9a-z_.-]', '_', os.path.splitext(first_file)[0].lower())
        namespace = _resolve_oraxen_namespace(merged_data, fallback_namespace, oraxen_pack_path)

    converter = OraxenToIAConverter()
    ia_output_base = os.path.join(session_output_dir, "ItemsAdder", "contents", namespace)
    ia_config_dir = os.path.join(ia_output_base, "configs")
    ia_res_dir = os.path.join(ia_output_base, "resourcepack")

    if oraxen_pack_path:
        converter.set_resource_paths(oraxen_pack_path, ia_res_dir)

    converter.convert(merged_data, namespace=namespace)
    converter.save_config(ia_config_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="ItemsAdder")


def _convert_nexo_to_ia(extract_dir, session_output_dir, session_upload_dir, target_format):
    nexo_items_configs = []
    nexo_resourcepack_path = None
    nexo_resourcepack_paths = []

    scan_root = extract_dir
    for root, dirs, _ in os.walk(extract_dir):
        for d in dirs:
            if d.lower() == "nexo":
                scan_root = os.path.join(root, d)
                break
        if scan_root != extract_dir:
            break

    for root, dirs, files in os.walk(scan_root):
        if nexo_resourcepack_path is None:
            dir_lookup = {d.lower(): d for d in dirs}
            if "pack" in dir_lookup:
                nexo_resourcepack_path = os.path.join(root, dir_lookup["pack"])
            elif "assets" in dir_lookup:
                nexo_resourcepack_path = root

        for f in files:
            if not f.endswith((".yml", ".yaml")):
                continue
            full_path = os.path.join(root, f)
            lower_name = f.lower()
            if lower_name in {"config.yml", "configuration.yml"}:
                continue
            data = safe_load_yaml(full_path)
            if not isinstance(data, dict):
                continue
            sample = next(iter(data.values()), None)
            if isinstance(sample, dict) and (
                _get_case_insensitive_dict_value(sample, "Pack", "pack") is not None
                or _get_case_insensitive_dict_value(sample, "itemname", "customname") is not None
            ):
                nexo_items_configs.append(full_path)

    if not nexo_items_configs:
        return jsonify({'error': '未能找到 Nexo 物品配置文件'}), 400

    if nexo_resourcepack_path:
        # external_packs 会先解包到临时目录，再按顺序参与资源迁移
        external_extract_root = os.path.join(session_upload_dir, "_nexo_external_packs")
        if os.path.isdir(external_extract_root):
            shutil.rmtree(external_extract_root, ignore_errors=True)
        nexo_resourcepack_paths = _collect_nexo_resourcepack_paths(nexo_resourcepack_path, external_extract_root)

    user_namespace = request.form.get('namespace')
    if user_namespace:
        if not re.match(r'^[0-9a-z_.-]+$', user_namespace):
            return jsonify({'error': '命名空间包含非法字符。仅允许小写字母、数字、下划线、连字符和英文句号。'}), 400
        merged_data = {}
        for config_path in nexo_items_configs:
            data = safe_load_yaml(config_path)
            if isinstance(data, dict):
                merged_data.update(data)
        namespace_map = {user_namespace: merged_data}
    else:
        namespace_map = {}
        for config_path in nexo_items_configs:
            data = safe_load_yaml(config_path)
            if not isinstance(data, dict):
                continue
            fallback_namespace = "converted"
            file_name = os.path.basename(config_path)
            if file_name:
                fallback_namespace = re.sub(r'[^0-9a-z_.-]', '_', os.path.splitext(file_name)[0].lower())
            namespace = _resolve_nexo_namespace(
                data,
                fallback_namespace,
                nexo_resourcepack_paths if nexo_resourcepack_paths else nexo_resourcepack_path
            )
            if namespace not in namespace_map:
                namespace_map[namespace] = {}
            namespace_map[namespace].update(data)

    for namespace, merged_data in namespace_map.items():
        converter = NexoToIAConverter()
        ia_output_base = os.path.join(session_output_dir, "ItemsAdder", "contents", namespace)
        ia_config_dir = os.path.join(ia_output_base, "configs")
        ia_res_dir = os.path.join(ia_output_base, "resourcepack")

        if nexo_resourcepack_path:
            converter.set_resource_paths(
                nexo_resourcepack_path,
                ia_res_dir,
                additional_nexo_roots=nexo_resourcepack_paths[1:] if nexo_resourcepack_paths else None
            )

        converter.convert(merged_data, namespace=namespace)
        converter.save_config(ia_config_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="ItemsAdder")

def _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="CraftEngine"):
    # 5. 压缩结果
    # 获取原始文件名 
    original_filename = "converted"
    try:
        for f in os.listdir(session_upload_dir):
            if f.endswith(".zip"):
                original_filename = f[:-4] # 移除 .zip
                break
    except:
        pass

    session_prefix = os.path.basename(os.path.normpath(session_upload_dir))
    output_filename = f"{session_prefix}_{original_filename} [{target_format} by MCC].zip"
    # 简单的文件名清理，防止非法字符
    output_filename = secure_filename(re.sub(r'[\\/*?:"<>|]', "", output_filename))
    
    output_zip_path = _safe_join_under(app.config['OUTPUT_FOLDER'], output_filename)
    # 我们希望压缩包解压后直接是 resources 文件夹，或者 CraftEngine 文件夹

    shutil.make_archive(output_zip_path[:-4], 'zip', session_output_dir, root_dir_name)

    # 清理会话文件 
    # shutil.rmtree(session_upload_dir)
    # shutil.rmtree(session_output_dir)

    return jsonify({
        'status': 'success',
        'download_url': f'/api/download/{output_filename}'
    })

@app.route('/api/download/<filename>')
def download_file(filename):
    safe_name = secure_filename(filename or "")
    if not safe_name or safe_name != filename:
        return jsonify({'error': '无效的文件名'}), 400
    file_path = _safe_join_under(app.config['OUTPUT_FOLDER'], safe_name)
    if not os.path.isfile(file_path):
        return jsonify({'error': '文件不存在或已过期'}), 404
    return send_file(file_path, as_attachment=True)

import webbrowser
from threading import Timer, Lock

# ... existing imports ...

# ... existing code ...

@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    """关闭服务器"""
    def kill():
        # 强制退出进程 (os._exit 能够终止整个进程，而 sys.exit 在线程中只终止线程)
        os._exit(0)
        
    # 延迟 1 秒执行，以便返回响应给前端
    Timer(1.0, kill).start()
    return jsonify({'status': 'server shutting down...'})

def open_browser():
    webbrowser.open_new('http://127.0.0.1:5000/')

# 心跳全局状态
last_heartbeat = time.time()
HEARTBEAT_TIMEOUT = 15  # 秒，增加超时时间以允许更长的启动加载

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    global last_heartbeat
    last_heartbeat = time.time()
    return jsonify({'status': 'alive'})

def check_heartbeat():
    """监控心跳并在超时时关闭"""
    global last_heartbeat
    while True:
        time.sleep(1)
        # 如果 TIMEOUT 秒内没有心跳，则关闭
        if time.time() - last_heartbeat > HEARTBEAT_TIMEOUT:
            print("心跳超时。正在关闭服务器...")
            # 使用 os._exit 从线程立即终止
            os._exit(0)

if __name__ == '__main__':
    # 仅在非调试模式下打开浏览器 (重载会导致双重打开)
    # 但对于打包的应用，调试通常为 False 或不相关。
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        Timer(1.5, open_browser).start()
        
        # 重置心跳计时器以避免在启动期间超时
        last_heartbeat = time.time()
        
        # 启动心跳监控线程
        import threading
        monitor_thread = threading.Thread(target=check_heartbeat, daemon=True)
        monitor_thread.start()
        
    app.run(debug=False, port=5000)
