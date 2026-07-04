from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
import os
import shutil
import zipfile
import uuid
import re
import json
import yaml

# 瀵煎叆鏍稿績閫昏緫
import sys
# 灏嗛」鐩牴鐩綍娣诲姞鍒?python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.converters.ia_to_ce import IAConverter
from src.converters.ia_to_nexo import IAToNexoConverter
from src.converters.ia_to_oraxen import IAToOraxenConverter
from src.converters.nexo_to_ce import NexoConverter
from src.converters.nexo_to_ia import NexoToIAConverter
from src.converters.nexo_to_oraxen import NexoToOraxenConverter
from src.converters.oraxen_to_ia import OraxenToIAConverter
from src.converters.ce_to_ia import CEToIAConverter
from src.converters.ce_to_nexo import CEToNexoConverter
from src.converters.ce_to_oraxen import CEToOraxenConverter
from src.converters.crucible_to_ia import CrucibleToIAConverter
from src.migrators.crucible_to_ia import CrucibleToIAMigrator
from src.analyzer import PackageAnalyzer
from src.utils.yaml_loader import safe_load_yaml

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'temp_uploads')
app.config['OUTPUT_FOLDER'] = os.path.join(os.getcwd(), 'temp_output')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB 闄愬埗

# 鏀寔鐨勬彃浠跺垪琛?
SUPPORTED_PLUGINS = [
    {"id": "ItemsAdder", "name": "ItemsAdder", "icon": "/static/images/itemsadder.webp"},
    {"id": "Nexo", "name": "Nexo", "icon": "/static/images/nexo.webp"},
    {"id": "Oraxen", "name": "Oraxen", "icon": "/static/images/oraxen.webp"},
    {"id": "CraftEngine", "name": "CraftEngine", "icon": "/static/images/craftengine.webp"},
    {"id": "MythicCrucible", "name": "MythicCrucible", "icon": "/static/images/mythiccrucible.webp"}
    # {"id": "HMCCosmetics", "name": "HMCCosmetics", "icon": "馃憭"}
]

# 纭繚涓存椂鐩綍瀛樺湪
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

UPLOAD_METADATA_FILENAME = ".upload.json"

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
            raise ValueError("妫€娴嬪埌涓嶅畨鍏ㄧ殑璺緞")
    except ValueError:
        raise ValueError("妫€娴嬪埌涓嶅畨鍏ㄧ殑璺緞")
    return target_path

def _upload_basename(raw_filename):
    return re.split(r"[\\/]", raw_filename or "")[-1]

def _clean_download_filename(raw_filename, fallback):
    cleaned = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "", raw_filename or "")
    cleaned = re.sub(r"\s+", "_", cleaned).strip(" ._")
    return cleaned or fallback

def _sanitize_upload_filename(raw_filename):
    base_name = _upload_basename(raw_filename)
    stem, _ = os.path.splitext(base_name)
    safe_stem = secure_filename(stem) or "upload"
    return f"{safe_stem}.zip"

def _write_upload_metadata(session_upload_dir, original_filename):
    metadata_path = _safe_join_under(session_upload_dir, UPLOAD_METADATA_FILENAME)
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump({"original_filename": original_filename}, f, ensure_ascii=False)

def _get_original_upload_filename(session_upload_dir):
    metadata_path = _safe_join_under(session_upload_dir, UPLOAD_METADATA_FILENAME)
    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        filename = _upload_basename(data.get("original_filename", ""))
        if filename:
            return filename
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return None

def _save_uploaded_zip(file, session_upload_dir):
    raw_filename = file.filename or ""
    base_name = _upload_basename(raw_filename)
    if os.path.splitext(base_name)[1].lower() != ".zip":
        raise ValueError("请上传 .zip 文件")
    filename = _sanitize_upload_filename(raw_filename)
    file_path = _safe_join_under(session_upload_dir, filename)
    file.save(file_path)
    _write_upload_metadata(session_upload_dir, base_name)
    return base_name, file_path

def _get_original_upload_stem(session_upload_dir):
    original_filename = _get_original_upload_filename(session_upload_dir)
    if original_filename:
        return os.path.splitext(original_filename)[0]
    try:
        for file_name in os.listdir(session_upload_dir):
            if file_name.lower().endswith(".zip"):
                return os.path.splitext(file_name)[0]
    except OSError:
        pass
    return "converted"

def _build_output_filename(original_stem, target_format):
    original_stem = original_stem or "converted"
    target_format = target_format or "converted"
    marker = f"{target_format}_by_MCC"
    raw_name = f"{original_stem}_{marker}.zip"
    return _clean_download_filename(raw_name, "converted_by_MCC.zip")

def _next_available_output_path(output_filename):
    candidate_name = output_filename
    stem, ext = os.path.splitext(output_filename)
    counter = 2
    while True:
        output_path = _safe_join_under(app.config['OUTPUT_FOLDER'], candidate_name)
        if not os.path.exists(output_path):
            return candidate_name, output_path
        candidate_name = f"{stem}_{counter}{ext or '.zip'}"
        counter += 1

def _form_flag_enabled(name):
    value = request.form.get(name, "")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze():
    if 'file' not in request.files:
        return jsonify({'error': '娌℃湁鏀跺埌鏂囦欢'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '鏈€夋嫨鏂囦欢'}), 400

    if file:
        session_id = str(uuid.uuid4())
        session_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
        os.makedirs(session_upload_dir, exist_ok=True)

        try:
            filename, file_path = _save_uploaded_zip(file, session_upload_dir)

            extract_dir = os.path.join(session_upload_dir, "extracted")
            _safe_extract_zip(file_path, extract_dir)

            # 杩愯鍒嗘瀽
            analyzer = PackageAnalyzer(extract_dir)
            report = analyzer.analyze()
            
            # 鏍规嵁妫€娴嬪埌鐨勬牸寮忕‘瀹氬彲鐢ㄧ殑鐩爣鏍煎紡
            # 閫昏緫锛?
            # 1. 璇嗗埆婧愭牸寮?(鍙兘鍖呭惈澶氫釜)
            # 2. 濡傛灉鍖呭惈 ItemsAdder -> 鍏佽杞负 CraftEngine (闄ら潪宸插寘鍚?CraftEngine)
            # 3. 濡傛灉鍖呭惈 CraftEngine -> 鏆傛棤杞崲 (鎴栧厑璁歌浆涓?ItemsAdder)
            # 4. 濡傛灉鍖呭惈 Nexo -> 鏆傛棤杞崲
            
            detected_formats = report["formats"]
            available_targets = []
            warnings = []
            
            if "ItemsAdder" in detected_formats:
                if "CraftEngine" in detected_formats:
                    warnings.append("Detected existing CraftEngine config. Conversion may overwrite or conflict.")
                if "CraftEngine" not in available_targets:
                    available_targets.append("CraftEngine")
                if "Nexo" not in available_targets:
                    available_targets.append("Nexo")
                if "Oraxen" not in available_targets:
                    available_targets.append("Oraxen")
            
            if "Nexo" in detected_formats:
                if "CraftEngine" in detected_formats:
                    warnings.append("Detected existing CraftEngine config. Conversion may overwrite or conflict.")
                if "CraftEngine" not in available_targets:
                    available_targets.append("CraftEngine")
                if "ItemsAdder" in detected_formats:
                    warnings.append("Detected existing ItemsAdder config. Conversion may overwrite or conflict.")
                if "ItemsAdder" not in available_targets:
                    available_targets.append("ItemsAdder")
                if "Oraxen" not in available_targets:
                    available_targets.append("Oraxen")

            if "Oraxen" in detected_formats:
                if "ItemsAdder" in detected_formats:
                    warnings.append("Detected existing ItemsAdder config. Conversion may overwrite or conflict.")
                if "ItemsAdder" not in available_targets:
                    available_targets.append("ItemsAdder")
                if "CraftEngine" not in available_targets:
                    available_targets.append("CraftEngine")
                if "Nexo" not in available_targets:
                    available_targets.append("Nexo")
                
            if "CraftEngine" in detected_formats:
                if "ItemsAdder" in detected_formats:
                    warnings.append("Detected existing ItemsAdder config. Conversion may overwrite or conflict.")
                if "ItemsAdder" not in available_targets:
                    available_targets.append("ItemsAdder")
                if "Nexo" in detected_formats:
                    warnings.append("Detected existing Nexo config. Conversion may overwrite or conflict.")
                if "Nexo" not in available_targets:
                    available_targets.append("Nexo")
                if "Oraxen" not in available_targets:
                    available_targets.append("Oraxen")

            report["source_formats"] = detected_formats # 鏀瑰悕浠ュ弽鏄犲鏁?
            if "MythicCrucible" in detected_formats:
                for target in ("ItemsAdder", "CraftEngine", "Nexo", "Oraxen"):
                    if target not in detected_formats and target not in available_targets:
                        available_targets.append(target)

            report["available_targets"] = available_targets
            report["warnings"] = warnings
            report["filename"] = filename
            report["supported_plugins"] = SUPPORTED_PLUGINS
            report["itemsadder_packages"] = []
            report["batch_mode"] = False

            if "ItemsAdder" in detected_formats:
                try:
                    ia_packages = _load_itemsadder_packages(extract_dir)
                    report["itemsadder_packages"] = [
                        {
                            "source_namespace": package.get("namespace", "converted"),
                            "target_namespace": package.get("namespace", "converted"),
                            "item_count": len(package.get("data", {}).get("items", {}) or {}),
                            "has_resourcepack": bool(package.get("resourcepack_path")),
                        }
                        for package in ia_packages
                    ]
                    report["batch_mode"] = len(report["itemsadder_packages"]) > 1
                except Exception as e:
                    print(f"Error loading ItemsAdder batch metadata: {e}")
            
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
    # 鏀寔涓ょ妯″紡锛?
    # 1. 浼犵粺鐨勭洿鎺ヤ笂浼犳枃浠跺苟杞崲 (淇濇寔鍏煎)
    # 2. 鎺ュ彈 session_id (浠?/api/analyze 鑾峰彇) 杩涜杞崲
    
    session_id = request.form.get('session_id')
    target_format = request.form.get('target_format', 'CraftEngine') # 榛樿 CE
    source_format = request.form.get('source_format') # 鏂板: 鏄庣‘婧愭牸寮?
    
    if session_id:
        if not _is_valid_session_id(session_id):
            return jsonify({'error': '鏃犳晥鐨勪細璇?ID'}), 400
        # 浣跨敤宸插瓨鍦ㄧ殑浼氳瘽
        session_upload_dir = _safe_join_under(app.config['UPLOAD_FOLDER'], session_id)
        extract_dir = _safe_join_under(session_upload_dir, "extracted")
        if not os.path.exists(extract_dir):
            return jsonify({'error': 'Session expired or not found'}), 400
            
        session_output_dir = _safe_join_under(app.config['OUTPUT_FOLDER'], session_id)
        os.makedirs(session_output_dir, exist_ok=True)
        
    elif 'file' in request.files:
        # 浼犵粺妯″紡
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': '鏈€夋嫨鏂囦欢'}), 400
            
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
        return jsonify({'error': 'Invalid request'}), 400

    try:
        if target_format == "CraftEngine":
            if source_format == "Nexo":
                return _convert_nexo_to_ce(extract_dir, session_output_dir, session_upload_dir, target_format)
            if source_format == "Oraxen":
                return _convert_oraxen_to_ce(extract_dir, session_output_dir, session_upload_dir, target_format)
            if source_format == "MythicCrucible":
                return _convert_crucible_to_ce(extract_dir, session_output_dir, session_upload_dir, target_format)
            else:
                return _convert_ia_to_ce(extract_dir, session_output_dir, session_upload_dir, target_format)

        if target_format == "ItemsAdder":
            if source_format == "CraftEngine":
                return _convert_ce_to_ia(extract_dir, session_output_dir, session_upload_dir, target_format)
            if source_format == "Oraxen":
                return _convert_oraxen_to_ia(extract_dir, session_output_dir, session_upload_dir, target_format)
            if source_format == "Nexo":
                return _convert_nexo_to_ia(extract_dir, session_output_dir, session_upload_dir, target_format)
            if source_format == "MythicCrucible":
                return _convert_crucible_to_ia(extract_dir, session_output_dir, session_upload_dir, target_format)
            return jsonify({'error': '鐩墠浠呮敮鎸?CraftEngine/Oraxen/Nexo -> ItemsAdder'}), 400

        if target_format == "Nexo":
            if source_format == "CraftEngine":
                return _convert_ce_to_nexo(extract_dir, session_output_dir, session_upload_dir, target_format)
            if source_format == "Oraxen":
                return _convert_oraxen_to_nexo(extract_dir, session_output_dir, session_upload_dir, target_format)
            if source_format == "MythicCrucible":
                return _convert_crucible_to_nexo(extract_dir, session_output_dir, session_upload_dir, target_format)
            if source_format == "ItemsAdder" or not source_format:
                return _convert_ia_to_nexo(extract_dir, session_output_dir, session_upload_dir, target_format)
            return jsonify({'error': '鐩墠浠呮敮鎸?CraftEngine/ItemsAdder -> Nexo'}), 400

        if target_format == "Oraxen":
            if source_format == "CraftEngine":
                return _convert_ce_to_oraxen(extract_dir, session_output_dir, session_upload_dir, target_format)
            if source_format == "Nexo":
                return _convert_nexo_to_oraxen(extract_dir, session_output_dir, session_upload_dir, target_format)
            if source_format == "MythicCrucible":
                return _convert_crucible_to_oraxen(extract_dir, session_output_dir, session_upload_dir, target_format)
            if source_format == "ItemsAdder" or not source_format:
                return _convert_ia_to_oraxen(extract_dir, session_output_dir, session_upload_dir, target_format)
            return jsonify({'error': '鐩墠浠呮敮鎸?CraftEngine/Nexo/ItemsAdder -> Oraxen'}), 400
        
        return jsonify({'error': f'涓嶆敮鎸佺殑鐩爣鏍煎紡: {target_format}'}), 400

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
    # 闃叉 zip 璺緞绌胯秺锛岀‘淇濇潯鐩В鍘嬪悗浠嶄綅浜庣洰鏍囩洰褰?
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
                raise ValueError(f"妫€娴嬪埌涓嶅畨鍏ㄧ殑鍘嬬缉鏉＄洰: {name}")
            zip_ref.extract(member, destination_dir)

def _find_resourcepack_root(search_dir):
    # 浼樺厛杩斿洖鍖呭惈 assets 鐨勭洰褰曪紝鍏舵杩斿洖鍖呭惈 models/textures 鐨勭洰褰?
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
    directory_entries = [
        entry
        for entry in os.listdir(external_dir)
        if os.path.isdir(os.path.join(external_dir, entry))
    ]
    directory_entries.sort(key=lambda x: x.lower())
    for entry in directory_entries:
        entry_path = os.path.join(external_dir, entry)
        pack_root = _find_resourcepack_root(entry_path)
        if pack_root:
            normalized = os.path.normpath(pack_root)
            if normalized not in paths:
                paths.append(normalized)

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
    # 灏嗗涓祫婧愬寘鐩綍鎸夐『搴忓彔鍔犲埌鍚屼竴鐩綍锛屽悗鑰呰鐩栧墠鑰?
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

def _merge_nexo_config_data(target, data):
    if not isinstance(target, dict) or not isinstance(data, dict):
        return target

    section_names = {"items", "categories", "recipes"}
    for key, value in data.items():
        normalized_key = key.lower() if isinstance(key, str) else key
        if normalized_key in section_names and isinstance(value, dict):
            target_key = None
            for existing_key in target.keys():
                if isinstance(existing_key, str) and existing_key.lower() == normalized_key:
                    target_key = existing_key
                    break
            if target_key is None:
                target_key = normalized_key
                target[target_key] = {}
            if isinstance(target.get(target_key), dict):
                target[target_key].update(value)
            else:
                target[target_key] = dict(value)
            continue
        target[key] = value
    return target


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

def _is_crucible_item_data(value):
    if not isinstance(value, dict):
        return False
    base_item = _get_case_insensitive_dict_value(value, "Id", "ID", "Material", "material")
    markers = (
        "Generation",
        "Type",
        "Furniture",
        "CustomBlock",
        "Recipes",
        "EquipSlot",
        "EquipConditions",
        "Equippable",
    )
    has_marker = any(_get_case_insensitive_dict_value(value, key) is not None for key in markers)
    return (base_item is not None and has_marker) or _get_case_insensitive_dict_value(value, "Furniture", "CustomBlock") is not None

def _merge_crucible_data(target, data):
    if not isinstance(data, dict):
        return
    items = _get_case_insensitive_dict_value(data, "items", "Items")
    if isinstance(items, dict):
        for item_id, item_data in items.items():
            if _is_crucible_item_data(item_data):
                target.setdefault("items", {})[item_id] = item_data
    else:
        for item_id, item_data in data.items():
            if _is_crucible_item_data(item_data):
                target.setdefault("items", {})[item_id] = item_data

    font_images = _get_case_insensitive_dict_value(data, "font_images", "font-images", "FontImages")
    if isinstance(font_images, dict):
        target.setdefault("font_images", {}).update(font_images)

def _load_crucible_package(extract_dir):
    merged_data = {"items": {}, "font_images": {}}
    item_configs = []
    font_image_configs = []

    for root, _, files in os.walk(extract_dir):
        for file_name in files:
            if not file_name.endswith((".yml", ".yaml")):
                continue
            full_path = os.path.join(root, file_name)
            data = safe_load_yaml(full_path)
            if not isinstance(data, dict):
                continue
            lower_name = file_name.lower()
            if lower_name in {"font-images.yml", "font-images.yaml", "font_images.yml", "font_images.yaml"}:
                merged_data["font_images"].update(data)
                font_image_configs.append(full_path)
                continue

            before_count = len(merged_data["items"])
            _merge_crucible_data(merged_data, data)
            if len(merged_data["items"]) > before_count:
                item_configs.append(full_path)

    return merged_data, _collect_crucible_resource_roots(extract_dir), item_configs, font_image_configs

def _collect_crucible_resource_roots(extract_dir):
    roots = []

    def add_root(path):
        if not isinstance(path, str) or not os.path.isdir(path):
            return
        normalized = os.path.normpath(path)
        if normalized not in roots:
            roots.append(normalized)

    for root, dirs, _ in os.walk(extract_dir):
        dir_lookup = {d.lower(): d for d in dirs}
        if "assets" in dir_lookup:
            add_root(root)
        if "models" in dir_lookup or "textures" in dir_lookup or "sounds" in dir_lookup:
            add_root(root)
        if "generation" in dir_lookup:
            generation_root = os.path.join(root, dir_lookup["generation"])
            merge_root = os.path.join(generation_root, "merge")
            if os.path.isdir(os.path.join(merge_root, "assets")):
                add_root(merge_root)
        if "packs" in dir_lookup:
            packs_root = os.path.join(root, dir_lookup["packs"])
            for pack_name in os.listdir(packs_root):
                pack_root = os.path.join(packs_root, pack_name)
                if os.path.isdir(os.path.join(pack_root, "Assets")):
                    add_root(pack_root)

    return roots

def _infer_crucible_namespace(crucible_data, resource_roots):
    generation = _get_case_insensitive_dict_value(crucible_data, "Generation", "generation", default={})
    if isinstance(generation, dict):
        namespace = _get_case_insensitive_dict_value(generation, "Namespace", "namespace")
        if _is_valid_namespace(namespace):
            return namespace

    scores = {}
    for root in resource_roots or []:
        assets_root = os.path.join(root, "assets")
        if not os.path.isdir(assets_root):
            continue
        for namespace in os.listdir(assets_root):
            if namespace == "minecraft" or not _is_valid_namespace(namespace):
                continue
            namespace_root = os.path.join(assets_root, namespace)
            if os.path.isdir(namespace_root):
                scores[namespace] = scores.get(namespace, 0) + 1
    if scores:
        return max(scores.items(), key=lambda x: x[1])[0]
    return "mythic"

def _resolve_crucible_output_namespace(crucible_data, resource_roots):
    user_namespace = request.form.get('namespace')
    if user_namespace:
        if not _is_valid_namespace(user_namespace):
            return None, jsonify({'error': 'Invalid namespace'}), 400
        return user_namespace, None, None
    return _infer_crucible_namespace(crucible_data, resource_roots), None, None

def _build_crucible_intermediate_ia_pack(resource_roots, session_upload_dir, namespace, marker):
    if not resource_roots:
        return None
    base_dir = os.path.abspath(session_upload_dir)
    ia_pack_dir = os.path.abspath(os.path.join(base_dir, marker))
    try:
        if os.path.commonpath([base_dir, ia_pack_dir]) != base_dir:
            raise ValueError("Invalid intermediate path")
    except ValueError:
        raise ValueError("Invalid intermediate path")
    if os.path.isdir(ia_pack_dir):
        shutil.rmtree(ia_pack_dir, ignore_errors=True)
    os.makedirs(ia_pack_dir, exist_ok=True)
    CrucibleToIAMigrator(resource_roots, ia_pack_dir, namespace).migrate()
    return ia_pack_dir

def _load_crucible_ia_data(extract_dir, session_upload_dir, marker):
    crucible_data, resource_roots, item_configs, font_image_configs = _load_crucible_package(extract_dir)
    if not item_configs and not font_image_configs:
        return None, None, None, jsonify({'error': 'No MythicCrucible item config files found'}), 400

    namespace, error_response, status_code = _resolve_crucible_output_namespace(crucible_data, resource_roots)
    if error_response:
        return None, None, None, error_response, status_code

    ia_data = CrucibleToIAConverter().convert(crucible_data, namespace=namespace)
    ia_pack = _build_crucible_intermediate_ia_pack(resource_roots, session_upload_dir, namespace, marker)
    return ia_data, ia_pack, namespace, None, None

def _convert_crucible_to_ia(extract_dir, session_output_dir, session_upload_dir, target_format):
    crucible_data, resource_roots, item_configs, font_image_configs = _load_crucible_package(extract_dir)
    if not item_configs and not font_image_configs:
        return jsonify({'error': 'No MythicCrucible item config files found'}), 400

    namespace, error_response, status_code = _resolve_crucible_output_namespace(crucible_data, resource_roots)
    if error_response:
        return error_response, status_code

    converter = CrucibleToIAConverter()
    ia_output_base = os.path.join(session_output_dir, "ItemsAdder", "contents", namespace)
    ia_config_dir = os.path.join(ia_output_base, "configs")
    ia_res_dir = os.path.join(ia_output_base, "resourcepack")
    if resource_roots:
        converter.set_resource_paths(resource_roots, ia_res_dir)
    converter.convert(crucible_data, namespace=namespace)
    converter.save_config(ia_config_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="ItemsAdder")

def _convert_crucible_to_ce(extract_dir, session_output_dir, session_upload_dir, target_format):
    ia_data, ia_pack, namespace, error_response, status_code = _load_crucible_ia_data(
        extract_dir, session_upload_dir, "_crucible_ia_ce"
    )
    if error_response:
        return error_response, status_code

    converter = IAConverter()
    converter.set_fix_illegal_model_rotations(_form_flag_enabled("fix_illegal_model_rotations"))
    ce_output_base = os.path.join(session_output_dir, "CraftEngine", "resources", namespace)
    ce_config_dir = os.path.join(ce_output_base, "configuration")
    ce_res_dir = os.path.join(ce_output_base, "resourcepack")
    if ia_pack:
        converter.set_resource_paths(ia_pack, ce_res_dir)
    converter.convert(ia_data, namespace=namespace)
    converter.save_config(ce_config_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format)

def _convert_crucible_to_nexo(extract_dir, session_output_dir, session_upload_dir, target_format):
    ia_data, ia_pack, namespace, error_response, status_code = _load_crucible_ia_data(
        extract_dir, session_upload_dir, "_crucible_ia_nexo"
    )
    if error_response:
        return error_response, status_code

    converter = IAToNexoConverter()
    nexo_root = os.path.join(session_output_dir, "Nexo")
    nexo_items_dir = os.path.join(nexo_root, "items")
    nexo_pack_dir = os.path.join(nexo_root, "pack")
    if ia_pack:
        converter.set_resource_paths(ia_pack, nexo_pack_dir)
    converter.convert(ia_data, namespace=namespace)
    converter.save_config(nexo_items_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="Nexo")

def _convert_crucible_to_oraxen(extract_dir, session_output_dir, session_upload_dir, target_format):
    ia_data, ia_pack, namespace, error_response, status_code = _load_crucible_ia_data(
        extract_dir, session_upload_dir, "_crucible_ia_oraxen"
    )
    if error_response:
        return error_response, status_code

    converter = IAToOraxenConverter()
    oraxen_root = os.path.join(session_output_dir, "Oraxen")
    oraxen_pack_dir = os.path.join(oraxen_root, "pack")
    if ia_pack:
        converter.set_resource_paths(ia_pack, oraxen_pack_dir)
    converter.convert(ia_data, namespace=namespace)
    converter.save_config(oraxen_root)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="Oraxen")

def _find_oraxen_scan_root(extract_dir):
    scan_root = extract_dir
    for root, dirs, _ in os.walk(extract_dir):
        for d in dirs:
            if d.lower() == "oraxen":
                return os.path.join(root, d)
    return scan_root

def _load_oraxen_package(extract_dir):
    scan_root = _find_oraxen_scan_root(extract_dir)
    oraxen_pack_path = None
    item_configs = []
    categories_configs = []
    recipe_configs = []

    for root, dirs, files in os.walk(scan_root):
        dir_lookup = {d.lower(): d for d in dirs}
        if oraxen_pack_path is None:
            if "pack" in dir_lookup:
                oraxen_pack_path = os.path.join(root, dir_lookup["pack"])
            elif "assets" in dir_lookup:
                oraxen_pack_path = root
            elif "models" in dir_lookup or "textures" in dir_lookup:
                oraxen_pack_path = root

        rel_root = os.path.relpath(root, scan_root).replace("\\", "/").lower()
        for file_name in files:
            if not file_name.endswith((".yml", ".yaml")):
                continue
            lower_name = file_name.lower()
            if lower_name in {"settings.yml", "settings.yaml", "config.yml", "configuration.yml"}:
                continue
            full_path = os.path.join(root, file_name)
            data = safe_load_yaml(full_path)
            if not isinstance(data, dict):
                continue
            if isinstance(data.get("categories"), dict):
                categories_configs.append(full_path)
            if isinstance(data.get("recipes"), dict) or rel_root.startswith("recipes") or "/recipes" in rel_root:
                recipe_configs.append(full_path)
            sample = next(iter(data.values()), None)
            if isinstance(data.get("items"), dict):
                item_configs.append(full_path)
            elif isinstance(sample, dict) and (
                "Pack" in sample
                or "pack" in sample
                or "displayname" in sample
                or "material" in sample
                or "Mechanics" in sample
                or "mechanics" in sample
            ):
                item_configs.append(full_path)

    merged_data = {"items": {}, "categories": {}, "recipes": {}}
    for config_path in item_configs:
        data = safe_load_yaml(config_path)
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("items"), dict):
            merged_data["items"].update(data["items"])
        else:
            for key, value in data.items():
                if key in {"categories", "recipes"}:
                    continue
                if isinstance(value, dict):
                    merged_data["items"][key] = value

    for config_path in categories_configs:
        data = safe_load_yaml(config_path)
        if isinstance(data, dict) and isinstance(data.get("categories"), dict):
            merged_data["categories"].update(data["categories"])

    for config_path in recipe_configs:
        data = safe_load_yaml(config_path)
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("recipes"), dict):
            for group_key, group_data in data["recipes"].items():
                if isinstance(group_data, dict):
                    merged_data["recipes"].setdefault(group_key, {}).update(group_data)
            continue
        recipe_type = re.sub(r'[^0-9a-z_.-]', '_', os.path.splitext(os.path.basename(config_path))[0].lower())
        for recipe_id, recipe_data in data.items():
            if isinstance(recipe_data, dict):
                merged_data["recipes"].setdefault(recipe_type, {})[recipe_id] = recipe_data

    return merged_data, oraxen_pack_path, item_configs

def _resolve_oraxen_output_namespace(merged_data, item_configs, oraxen_pack_path):
    user_namespace = request.form.get('namespace')
    if user_namespace:
        if not _is_valid_namespace(user_namespace):
            return None, jsonify({'error': 'Invalid namespace'}), 400
        return user_namespace, None, None

    fallback_namespace = "converted"
    if item_configs:
        first_file = os.path.basename(item_configs[0])
        if first_file:
            fallback_namespace = re.sub(r'[^0-9a-z_.-]', '_', os.path.splitext(first_file)[0].lower())
    namespace = _resolve_oraxen_namespace(merged_data.get("items", merged_data), fallback_namespace, oraxen_pack_path)
    if not _is_valid_namespace(namespace):
        namespace = "converted"
    return namespace, None, None

def _empty_itemsadder_data():
    return {
        "items": {},
        "equipments": {},
        "armors_rendering": {},
        "legacy_armor_renderings": {},
        "templates": {},
        "font_images": {},
        "categories": {},
        "recipes": {},
        "loots": {},
        "info": {},
    }

def _has_itemsadder_config_sections(data):
    if not isinstance(data, dict):
        return False
    return any(
        isinstance(data.get(section_name), dict)
        for section_name in (
            "items",
            "equipments",
            "armors_rendering",
            "legacy_armor_renderings",
            "templates",
            "font_images",
            "categories",
            "recipes",
            "loots",
        )
    )

def _merge_itemsadder_data(target, source):
    if not isinstance(source, dict):
        return

    info = source.get("info")
    if isinstance(info, dict) and not target.get("info"):
        target["info"] = dict(info)

    for section_name in (
        "items",
        "equipments",
        "armors_rendering",
        "legacy_armor_renderings",
        "templates",
        "font_images",
        "categories",
    ):
        section = source.get(section_name)
        if isinstance(section, dict):
            target.setdefault(section_name, {}).update(section)

    recipes = source.get("recipes")
    if isinstance(recipes, dict):
        for group_key, group_data in recipes.items():
            if isinstance(group_data, dict):
                target.setdefault("recipes", {}).setdefault(group_key, {}).update(group_data)

    loots = source.get("loots")
    if isinstance(loots, dict):
        for loot_group, loot_group_data in loots.items():
            if isinstance(loot_group_data, dict):
                target.setdefault("loots", {}).setdefault(loot_group, {}).update(loot_group_data)

def _find_itemsadder_scan_root(extract_dir):
    scan_root = extract_dir
    for root, dirs, _ in os.walk(extract_dir):
        for dir_name in dirs:
            if dir_name.lower() == "itemsadder":
                return os.path.join(root, dir_name)
    return scan_root

def _infer_itemsadder_package_root(config_path, scan_root):
    try:
        rel_path = os.path.relpath(config_path, scan_root)
    except ValueError:
        return scan_root

    parts = os.path.normpath(rel_path).split(os.sep)
    lowered = [part.lower() for part in parts]
    if "contents" in lowered:
        index = lowered.index("contents")
        if index + 1 < len(parts):
            return os.path.join(scan_root, *parts[:index + 2])
    if "configs" in lowered:
        index = lowered.index("configs")
        if index > 0:
            return os.path.join(scan_root, *parts[:index])
    return scan_root

def _infer_itemsadder_namespace_from_root(package_root, scan_root):
    candidate = None
    try:
        rel_path = os.path.relpath(package_root, scan_root)
        parts = [] if rel_path == "." else os.path.normpath(rel_path).split(os.sep)
    except ValueError:
        parts = []

    lowered = [part.lower() for part in parts]
    if "contents" in lowered:
        index = lowered.index("contents")
        if index + 1 < len(parts):
            candidate = parts[index + 1]

    if not candidate:
        candidate = os.path.basename(package_root)

    candidate = (candidate or "").strip().lower()
    if candidate in {"", ".", "itemsadder", "configs", "resourcepack", "contents"}:
        return None

    candidate = re.sub(r'[^0-9a-z_.-]', '_', candidate)
    return candidate if _is_valid_namespace(candidate) else None

def _find_direct_itemsadder_resourcepack_path(search_dir):
    if not os.path.isdir(search_dir):
        return None
    try:
        dirs = [
            name
            for name in os.listdir(search_dir)
            if os.path.isdir(os.path.join(search_dir, name))
        ]
    except OSError:
        return None

    dir_lookup = {name.lower(): name for name in dirs}
    if "resourcepack" in dir_lookup:
        return os.path.join(search_dir, dir_lookup["resourcepack"])
    if "assets" in dir_lookup:
        return search_dir
    if any(name in dir_lookup for name in ("models", "textures", "sounds")):
        return search_dir
    return None

def _find_itemsadder_resourcepack_path(search_dir):
    direct = _find_direct_itemsadder_resourcepack_path(search_dir)
    if direct:
        return direct

    for root, dirs, _ in os.walk(search_dir):
        dir_lookup = {dir_name.lower(): dir_name for dir_name in dirs}
        if "resourcepack" in dir_lookup:
            return os.path.join(root, dir_lookup["resourcepack"])
        if "assets" in dir_lookup:
            return root
        if any(name in dir_lookup for name in ("models", "textures", "sounds")):
            return root
    return None

def _unique_existing_paths(paths):
    result = []
    for path in paths:
        if not path or not os.path.exists(path):
            continue
        normalized = os.path.normpath(path)
        if normalized not in result:
            result.append(normalized)
    return result

def _collect_itemsadder_resource_dirs(input_root, resource_type, namespace):
    candidates = []
    if namespace:
        candidates.append(os.path.join(input_root, "assets", namespace, resource_type))
        candidates.append(os.path.join(input_root, namespace, resource_type))

    assets_root = os.path.join(input_root, "assets")
    if os.path.isdir(assets_root):
        for source_namespace in sorted(os.listdir(assets_root)):
            namespace_root = os.path.join(assets_root, source_namespace)
            if os.path.isdir(namespace_root):
                candidates.append(os.path.join(namespace_root, resource_type))

    candidates.append(os.path.join(input_root, resource_type))

    dirs = []
    for path in candidates:
        if not os.path.isdir(path):
            continue
        normalized = os.path.normpath(path)
        if normalized not in dirs:
            dirs.append(normalized)
    return dirs

def _copy_tree_contents(src_root, dst_root):
    for root, _, files in os.walk(src_root):
        rel_dir = os.path.relpath(root, src_root)
        target_dir = dst_root if rel_dir == "." else os.path.join(dst_root, rel_dir)
        os.makedirs(target_dir, exist_ok=True)
        for file_name in files:
            shutil.copy2(os.path.join(root, file_name), os.path.join(target_dir, file_name))

def _collect_itemsadder_sounds_json_paths(input_root, namespace):
    candidates = []
    if namespace:
        candidates.append(os.path.join(input_root, "assets", namespace, "sounds.json"))
        candidates.append(os.path.join(input_root, namespace, "sounds.json"))

    assets_root = os.path.join(input_root, "assets")
    if os.path.isdir(assets_root):
        for source_namespace in sorted(os.listdir(assets_root)):
            namespace_root = os.path.join(assets_root, source_namespace)
            if os.path.isdir(namespace_root):
                candidates.append(os.path.join(namespace_root, "sounds.json"))

    candidates.append(os.path.join(input_root, "sounds.json"))
    return _unique_existing_paths(candidates)

def _merge_sounds_json_files(source_paths, output_path):
    merged = {}
    for source_path in _unique_existing_paths(source_paths):
        try:
            with open(source_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if isinstance(data, dict):
            merged.update(data)

    if not merged:
        return False

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return True

def _merge_itemsadder_resourcepacks_for_namespace(resourcepack_paths, output_root, namespace):
    if os.path.isdir(output_root):
        shutil.rmtree(output_root, ignore_errors=True)

    copied_any = False
    sounds_json_paths = []
    for input_root in _unique_existing_paths(resourcepack_paths):
        for resource_type in ("models", "textures", "sounds"):
            for src_dir in _collect_itemsadder_resource_dirs(input_root, resource_type, namespace):
                dst_dir = os.path.join(output_root, "assets", namespace, resource_type)
                _copy_tree_contents(src_dir, dst_dir)
                copied_any = True
        sounds_json_paths.extend(_collect_itemsadder_sounds_json_paths(input_root, namespace))

    if _merge_sounds_json_files(sounds_json_paths, os.path.join(output_root, "assets", namespace, "sounds.json")):
        copied_any = True
    return output_root if copied_any else None

def _itemsadder_resourcepack_needs_namespace_copy(resourcepack_path, namespace):
    if not resourcepack_path or not os.path.isdir(resourcepack_path):
        return False

    assets_root = os.path.join(resourcepack_path, "assets")
    if os.path.isdir(assets_root):
        if os.path.isdir(os.path.join(assets_root, namespace)):
            return False
        try:
            return any(
                os.path.isdir(os.path.join(assets_root, name))
                for name in os.listdir(assets_root)
            )
        except OSError:
            return False

    return any(
        os.path.isdir(os.path.join(resourcepack_path, folder_name))
        for folder_name in ("models", "textures", "sounds")
    )

def _prepare_itemsadder_resourcepack_path(resourcepack_paths, namespace, session_upload_dir, tag):
    paths = _unique_existing_paths(resourcepack_paths)
    if not paths:
        return None

    needs_merge = len(paths) > 1 or any(
        _itemsadder_resourcepack_needs_namespace_copy(path, namespace)
        for path in paths
    )
    if not needs_merge:
        return paths[0]

    safe_tag = re.sub(r'[^0-9A-Za-z_.-]', '_', tag or "itemsadder")
    merged_root = _safe_join_under(session_upload_dir, f"_{safe_tag}_resourcepack")
    return _merge_itemsadder_resourcepacks_for_namespace(paths, merged_root, namespace)

def _load_itemsadder_packages(extract_dir):
    scan_root = _find_itemsadder_scan_root(extract_dir)
    packages = {}

    for root, _, files in os.walk(scan_root):
        for file_name in files:
            if not file_name.endswith((".yml", ".yaml")):
                continue
            config_path = os.path.join(root, file_name)
            try:
                data = safe_load_yaml(config_path)
            except Exception as e:
                print(f"Error loading ItemsAdder config {config_path}: {e}")
                continue
            if not _has_itemsadder_config_sections(data):
                continue

            package_root = _infer_itemsadder_package_root(config_path, scan_root)
            package_key = os.path.normpath(package_root)
            package = packages.setdefault(
                package_key,
                {
                    "root": package_root,
                    "data": _empty_itemsadder_data(),
                    "item_configs": [],
                    "font_image_configs": [],
                    "categories_configs": [],
                    "recipes_configs": [],
                },
            )
            _merge_itemsadder_data(package["data"], data)

            if any(
                isinstance(data.get(section_name), dict)
                for section_name in (
                    "items",
                    "equipments",
                    "armors_rendering",
                    "legacy_armor_renderings",
                    "templates",
                )
            ):
                package["item_configs"].append(config_path)
            if isinstance(data.get("font_images"), dict):
                package["font_image_configs"].append(config_path)
            if isinstance(data.get("categories"), dict):
                package["categories_configs"].append(config_path)
            if isinstance(data.get("recipes"), dict):
                package["recipes_configs"].append(config_path)

    direct_scan_resourcepack = _find_direct_itemsadder_resourcepack_path(scan_root)
    result = []
    for package_key in sorted(packages.keys()):
        package = packages[package_key]
        path_namespace = _infer_itemsadder_namespace_from_root(package["root"], scan_root)
        info = package["data"].get("info") if isinstance(package["data"].get("info"), dict) else {}
        info_namespace = info.get("namespace") if isinstance(info, dict) else None
        namespace = info_namespace if _is_valid_namespace(info_namespace) else path_namespace
        if not _is_valid_namespace(namespace):
            namespace = "converted"

        package["namespace"] = namespace
        package["original_namespace"] = namespace
        package["data"].setdefault("info", {})["namespace"] = namespace

        resourcepack_path = _find_itemsadder_resourcepack_path(package["root"])
        if resourcepack_path is None and package["root"] != scan_root:
            resourcepack_path = direct_scan_resourcepack
        if resourcepack_path is None and (package["item_configs"] or package["font_image_configs"]):
            resourcepack_path = package["root"]
        package["resourcepack_path"] = resourcepack_path
        result.append(package)

    return result

def _get_itemsadder_namespace_overrides():
    raw_value = request.form.get("namespace_overrides")
    if not raw_value:
        return {}, None

    try:
        data = json.loads(raw_value)
    except (TypeError, ValueError):
        return None, (jsonify({'error': 'Invalid namespace overrides'}), 400)

    if not isinstance(data, dict):
        return None, (jsonify({'error': 'Invalid namespace overrides'}), 400)

    overrides = {}
    for source_namespace, target_namespace in data.items():
        if not isinstance(source_namespace, str):
            continue
        if target_namespace is None:
            continue
        target_namespace = str(target_namespace).strip()
        if not target_namespace:
            continue
        if not _is_valid_namespace(target_namespace):
            return None, (jsonify({'error': f'Invalid namespace: {target_namespace}'}), 400)
        overrides[source_namespace] = target_namespace
    return overrides, None

def _build_itemsadder_conversion_packages(packages, user_namespace, session_upload_dir, tag, namespace_overrides=None):
    namespace_overrides = namespace_overrides or {}
    grouped = {}
    for package in packages:
        source_namespace = package.get("namespace") or "converted"
        namespace = namespace_overrides.get(source_namespace) or user_namespace or source_namespace
        if not _is_valid_namespace(namespace):
            namespace = "converted"

        grouped_package = grouped.setdefault(
            namespace,
            {
                "namespace": namespace,
                "data": _empty_itemsadder_data(),
                "item_configs": [],
                "font_image_configs": [],
                "resourcepack_paths": [],
                "source_namespaces": [],
            },
        )
        _merge_itemsadder_data(grouped_package["data"], package.get("data", {}))
        grouped_package["data"].setdefault("info", {})["namespace"] = namespace
        grouped_package["item_configs"].extend(package.get("item_configs", []))
        grouped_package["font_image_configs"].extend(package.get("font_image_configs", []))
        grouped_package["source_namespaces"].append(source_namespace)
        if package.get("resourcepack_path"):
            grouped_package["resourcepack_paths"].append(package["resourcepack_path"])

    result = []
    for namespace, package in grouped.items():
        package["resourcepack_path"] = _prepare_itemsadder_resourcepack_path(
            package["resourcepack_paths"],
            namespace,
            session_upload_dir,
            f"{tag}_{namespace}",
        )
        result.append(package)
    return result

def _load_itemsadder_package(extract_dir):
    packages = _load_itemsadder_packages(extract_dir)
    merged_data = _empty_itemsadder_data()
    ia_items_configs = []
    resourcepack_paths = []
    original_namespace = "converted"

    for index, package in enumerate(packages):
        _merge_itemsadder_data(merged_data, package.get("data", {}))
        ia_items_configs.extend(package.get("item_configs", []))
        if package.get("resourcepack_path"):
            resourcepack_paths.append(package["resourcepack_path"])
        if index == 0:
            original_namespace = package.get("namespace") or original_namespace

    if not _is_valid_namespace(original_namespace):
        original_namespace = "converted"

    unique_resourcepack_paths = _unique_existing_paths(resourcepack_paths)
    ia_resourcepack_path = unique_resourcepack_paths[0] if len(unique_resourcepack_paths) == 1 else None

    return merged_data, ia_resourcepack_path, ia_items_configs, original_namespace

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
    for section_name in ("items", "blocks", "equipments", "images", "categories", "recipes", "furniture"):
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
    for section_name in ("items", "blocks", "equipments", "images", "categories", "recipes", "furniture"):
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
        return jsonify({'error': '鏈兘鎵惧埌 CraftEngine 閰嶇疆鏂囦欢'}), 400

    user_namespace = request.form.get('namespace')
    if user_namespace:
        if not _is_valid_namespace(user_namespace):
            return jsonify({'error': 'Invalid namespace'}), 400
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

def _convert_ce_to_nexo(extract_dir, session_output_dir, session_upload_dir, target_format):
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
        return jsonify({'error': '鏈兘鎵惧埌 CraftEngine 閰嶇疆鏂囦欢'}), 400

    user_namespace = request.form.get('namespace')
    if user_namespace:
        if not _is_valid_namespace(user_namespace):
            return jsonify({'error': 'Invalid namespace'}), 400
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
        converter = CEToNexoConverter()
        nexo_root = os.path.join(session_output_dir, "Nexo")
        nexo_items_dir = os.path.join(nexo_root, "items")
        nexo_pack_dir = os.path.join(nexo_root, "pack")

        ce_resourcepack_paths = _collect_ce_resourcepack_paths(
            extract_dir,
            namespace=None if user_namespace else namespace,
        )
        if ce_resourcepack_paths:
            converter.set_resource_paths(ce_resourcepack_paths, nexo_pack_dir)

        converter.convert(merged_data, namespace=namespace)
        converter.save_config(nexo_items_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="Nexo")

def _convert_nexo_to_ce(extract_dir, session_output_dir, session_upload_dir, target_format):
    # 1. 鎵弿 Nexo 閰嶇疆鍜岃祫婧?
    nexo_items_configs = []
    nexo_resourcepack_path = None
    nexo_resourcepack_paths = []
    merged_nexo_resourcepack_path = None
    
    # 灏濊瘯鎵惧埌 Nexo 鏍圭洰褰?
    scan_root = extract_dir
    for root, dirs, files in os.walk(extract_dir):
        if "Nexo" in dirs:
            scan_root = os.path.join(root, "Nexo")
            break
        elif "nexo" in dirs:
             scan_root = os.path.join(root, "nexo")
             break

    # 鎵弿閰嶇疆鍜岃祫婧?
    for root, dirs, files in os.walk(scan_root):
        # 璧勬簮鍖呮娴嬶紙澶у皬鍐欐棤鍏筹級
        if nexo_resourcepack_path is None:
            dir_lookup = {d.lower(): d for d in dirs}
            if "pack" in dir_lookup:
                nexo_resourcepack_path = os.path.join(root, dir_lookup["pack"])
            elif "assets" in dir_lookup:
                nexo_resourcepack_path = root
             
        # 閰嶇疆鏂囦欢妫€娴?
        for f in files:
            if f.endswith((".yml", ".yaml")):
                full_path = os.path.join(root, f)
                # 绠€鍗曡繃婊わ紝閬垮厤鍔犺浇闈為厤缃?
                if "config.yml" in f: continue
                nexo_items_configs.append(full_path)

    if not nexo_items_configs:
         return jsonify({'error': '鏈兘鎵惧埌 Nexo 閰嶇疆鏂囦欢'}), 400

    if nexo_resourcepack_path:
        external_extract_root = os.path.join(session_upload_dir, "_nexo_external_packs_ce")
        merged_pack_root = os.path.join(session_upload_dir, "_nexo_merged_pack_ce")
        if os.path.isdir(external_extract_root):
            shutil.rmtree(external_extract_root, ignore_errors=True)
        if os.path.isdir(merged_pack_root):
            shutil.rmtree(merged_pack_root, ignore_errors=True)
        nexo_resourcepack_paths = _collect_nexo_resourcepack_paths(nexo_resourcepack_path, external_extract_root)
        merged_nexo_resourcepack_path = _merge_nexo_resourcepacks(nexo_resourcepack_paths, merged_pack_root)

    # 2. 杩愯杞崲
    # 鍑嗗鍛藉悕绌洪棿
    user_namespace = request.form.get('namespace')
    
    if user_namespace and re.match(r'^[0-9a-z_.-]+$', user_namespace):
        # 鐢ㄦ埛鎸囧畾浜嗗懡鍚嶇┖闂达紝鍚堝苟鎵€鏈夐厤缃?        converter = NexoConverter()
        converter.set_fix_illegal_model_rotations(_form_flag_enabled("fix_illegal_model_rotations"))
        merged_data = {}
        for config_path in nexo_items_configs:
            data = safe_load_yaml(config_path)
            if isinstance(data, dict):
                 _merge_nexo_config_data(merged_data, data)
        
        namespace = user_namespace
        ce_output_base = os.path.join(session_output_dir, "CraftEngine", "resources", namespace)
        ce_config_dir = os.path.join(ce_output_base, "configuration")
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
            _merge_nexo_config_data(grouped_data[namespace], data)

        for namespace, merged_data in grouped_data.items():
            converter = NexoConverter()
            converter.set_fix_illegal_model_rotations(_form_flag_enabled("fix_illegal_model_rotations"))
            ce_output_base = os.path.join(session_output_dir, "CraftEngine", "resources", namespace)
            ce_config_dir = os.path.join(ce_output_base, "configuration")
            ce_res_dir = os.path.join(ce_output_base, "resourcepack")

            if merged_nexo_resourcepack_path:
                converter.set_resource_paths(merged_nexo_resourcepack_path, ce_res_dir)
            
            converter.convert(merged_data, namespace=namespace)
            converter.save_config(ce_config_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format)

def _convert_ia_to_nexo_legacy(extract_dir, session_output_dir, session_upload_dir, target_format):
    ia_items_configs = []
    ia_categories_configs = []
    ia_recipes_configs = []
    ia_resourcepack_path = None

    scan_root = extract_dir
    found_ia_dir = False
    for root, dirs, _ in os.walk(extract_dir):
        for d in dirs:
            if d.lower() == "itemsadder":
                scan_root = os.path.join(root, d)
                found_ia_dir = True
                break
        if found_ia_dir:
            break

    for root, dirs, files in os.walk(scan_root):
        dir_lookup = {d.lower(): d for d in dirs}
        if ia_resourcepack_path is None:
            if "resourcepack" in dir_lookup:
                ia_resourcepack_path = os.path.join(root, dir_lookup["resourcepack"])
            elif "assets" in dir_lookup:
                ia_resourcepack_path = root
            elif "models" in dir_lookup or "textures" in dir_lookup:
                ia_resourcepack_path = root

        for file_name in files:
            if not file_name.endswith((".yml", ".yaml")):
                continue
            config_path = os.path.join(root, file_name)
            try:
                data = safe_load_yaml(config_path)
            except Exception as e:
                print(f"Error loading ItemsAdder config {config_path}: {e}")
                continue
            if not isinstance(data, dict):
                continue
            if "items" in data or "equipments" in data or "armors_rendering" in data or "legacy_armor_renderings" in data:
                ia_items_configs.append(config_path)
            if "categories" in data:
                ia_categories_configs.append(config_path)
            if "recipes" in data:
                ia_recipes_configs.append(config_path)

    if ia_resourcepack_path is None and ia_items_configs:
        ia_resourcepack_path = extract_dir

    if not ia_items_configs:
        return jsonify({'error': '鏈兘鎵惧埌鍖呭惈鐗╁搧瀹氫箟鐨?ItemsAdder 閰嶇疆鏂囦欢'}), 400

    merged_data = {
        "items": {},
        "equipments": {},
        "armors_rendering": {},
        "legacy_armor_renderings": {},
        "templates": {},
        "recipes": {},
        "loots": {},
        "info": {},
    }

    for config_path in ia_items_configs:
        data = safe_load_yaml(config_path)
        if not isinstance(data, dict):
            continue
        if "info" in data and not merged_data["info"]:
            merged_data["info"] = data["info"]
        for section_name in ("items", "equipments", "armors_rendering", "legacy_armor_renderings", "templates"):
            section = data.get(section_name)
            if isinstance(section, dict):
                merged_data.setdefault(section_name, {}).update(section)
        if isinstance(data.get("loots"), dict):
            for loot_group, loot_group_data in data["loots"].items():
                if isinstance(loot_group_data, dict):
                    merged_data.setdefault("loots", {}).setdefault(loot_group, {}).update(loot_group_data)

    if ia_categories_configs:
        merged_categories = {}
        for config_path in ia_categories_configs:
            data = safe_load_yaml(config_path)
            if isinstance(data, dict) and isinstance(data.get("categories"), dict):
                merged_categories.update(data["categories"])
                if "info" in data and not merged_data["info"]:
                    merged_data["info"] = data["info"]
        if merged_categories:
            merged_data["categories"] = merged_categories

    if ia_recipes_configs:
        merged_recipes = {}
        for config_path in ia_recipes_configs:
            data = safe_load_yaml(config_path)
            if not isinstance(data, dict):
                continue
            if "info" in data and not merged_data["info"]:
                merged_data["info"] = data["info"]
            recipes = data.get("recipes")
            if not isinstance(recipes, dict):
                continue
            for group_key, group_data in recipes.items():
                if isinstance(group_data, dict):
                    merged_recipes.setdefault(group_key, {}).update(group_data)
        if merged_recipes:
            merged_data["recipes"] = merged_recipes

    original_namespace = "converted"
    if isinstance(merged_data.get("info"), dict):
        original_namespace = merged_data["info"].get("namespace") or original_namespace
    if not _is_valid_namespace(original_namespace):
        original_namespace = "converted"

    user_namespace = request.form.get('namespace')
    if user_namespace:
        if not _is_valid_namespace(user_namespace):
            return jsonify({'error': 'Invalid namespace'}), 400
        namespace = user_namespace
    else:
        namespace = original_namespace

    if ia_resourcepack_path and os.path.exists(ia_resourcepack_path):
        assets_path = os.path.join(ia_resourcepack_path, "assets")
        if not os.path.exists(assets_path):
            has_models = os.path.exists(os.path.join(ia_resourcepack_path, "models"))
            has_textures = os.path.exists(os.path.join(ia_resourcepack_path, "textures"))
            has_sounds = os.path.exists(os.path.join(ia_resourcepack_path, "sounds"))
            if has_models or has_textures or has_sounds:
                restructured_root = os.path.join(session_upload_dir, "restructured_ia_to_nexo_rp")
                target_ns_dir = os.path.join(restructured_root, "assets", namespace)
                os.makedirs(target_ns_dir, exist_ok=True)
                for folder_name in ("models", "textures", "sounds"):
                    src_folder = os.path.join(ia_resourcepack_path, folder_name)
                    if not os.path.isdir(src_folder):
                        continue
                    dst_folder = os.path.join(target_ns_dir, folder_name)
                    if os.path.isdir(dst_folder):
                        shutil.rmtree(dst_folder, ignore_errors=True)
                    shutil.copytree(src_folder, dst_folder)
                ia_resourcepack_path = restructured_root

    converter = IAToNexoConverter()
    nexo_root = os.path.join(session_output_dir, "Nexo")
    nexo_items_dir = os.path.join(nexo_root, "items")
    nexo_pack_dir = os.path.join(nexo_root, "pack")

    if ia_resourcepack_path:
        converter.set_resource_paths(ia_resourcepack_path, nexo_pack_dir)

    converter.convert(merged_data, namespace=namespace)
    converter.save_config(nexo_items_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="Nexo")

def _convert_ia_to_nexo(extract_dir, session_output_dir, session_upload_dir, target_format):
    packages = _load_itemsadder_packages(extract_dir)
    if not any(package.get("item_configs") for package in packages):
        return jsonify({'error': 'No ItemsAdder item config files found'}), 400

    user_namespace = request.form.get('namespace')
    if user_namespace and not _is_valid_namespace(user_namespace):
        return jsonify({'error': 'Invalid namespace'}), 400
    namespace_overrides, error_response = _get_itemsadder_namespace_overrides()
    if error_response:
        return error_response

    conversion_packages = _build_itemsadder_conversion_packages(
        packages,
        None if namespace_overrides else user_namespace,
        session_upload_dir,
        "ia_to_nexo",
        namespace_overrides=namespace_overrides,
    )
    nexo_root = os.path.join(session_output_dir, "Nexo")
    nexo_items_dir = os.path.join(nexo_root, "items")
    nexo_pack_dir = os.path.join(nexo_root, "pack")

    for package in conversion_packages:
        if not package.get("item_configs"):
            continue
        converter = IAToNexoConverter()
        if package.get("resourcepack_path"):
            converter.set_resource_paths(package["resourcepack_path"], nexo_pack_dir)
        converter.convert(package["data"], namespace=package["namespace"])
        converter.save_config(nexo_items_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="Nexo")

def _convert_ia_to_ce_legacy(extract_dir, session_output_dir, session_upload_dir, target_format):
    # 3. 瀹氫綅閰嶇疆鍜岃祫婧?(ItemsAdder -> CraftEngine 閫昏緫)
    # 鏀硅繘閫昏緫: 鎵弿鎵€鏈?YAML 鏂囦欢骞舵牴鎹唴瀹硅繘琛屽垎绫?    ia_items_configs = []
    ia_font_image_configs = []
    ia_categories_configs = []
    ia_recipes_configs = []
    ia_resourcepack_path = None

    # 0. 纭畾鎵弿鏍圭洰褰?
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

    # 绗竴閬嶆壂鎻忥細鏌ユ壘閰嶇疆鏂囦欢鍜屾爣鍑嗚祫婧愬寘缁撴瀯
    for root, dirs, files in os.walk(scan_root):
        # --- 璧勬簮鍖呮娴?---
        # 浼樺厛绾?1: 鏄惧紡鐨?"resourcepack" 鐩綍
        if "resourcepack" in dirs and ia_resourcepack_path is None:
            ia_resourcepack_path = os.path.join(root, "resourcepack")
        
        # 浼樺厛绾?2: 鐩存帴鍖呭惈 assets 鐨勭洰褰?
        if "assets" in dirs and ia_resourcepack_path is None:
            ia_resourcepack_path = root

        # 浼樺厛绾?3: 鐩存帴鍖呭惈 models 鍜?textures 鐨勭洰褰?(闈炴爣鍑嗙粨鏋?
        if "models" in dirs and "textures" in dirs and ia_resourcepack_path is None:
            ia_resourcepack_path = root

        # --- 閰嶇疆鏂囦欢妫€娴?---
        for f in files:
            if f.endswith(".yml") or f.endswith(".yaml"):
                full_path = os.path.join(root, f)
                try:
                    print(f"Scanning: {full_path}")
                    data = safe_load_yaml(full_path)
                    if not data:
                        continue
                    
                    # 妫€鏌ュ叧閿鍚?                    if "items" in data or "equipments" in data or "armors_rendering" in data or "legacy_armor_renderings" in data:
                        ia_items_configs.append(full_path)
                    if "font_images" in data:
                        ia_font_image_configs.append(full_path)
                    if "categories" in data:
                        ia_categories_configs.append(full_path)
                    if "recipes" in data:
                        ia_recipes_configs.append(full_path)
                except Exception as e:
                    print(f"Error loading {full_path}: {e}")
                    continue

    # 濡傛灉浠嶆湭鎵惧埌璧勬簮鍖咃紝灏濊瘯瀵绘壘 textures/models 鐨勭埗绾?(澶勭悊闈炴爣鍑嗙粨鏋?
    if ia_resourcepack_path is None:
        # 濡傛灉鏈夐厤缃枃浠讹紝榛樿涓烘彁鍙栨牴鐩綍
        if ia_items_configs or ia_font_image_configs:
            ia_resourcepack_path = extract_dir

    if not ia_items_configs and not ia_font_image_configs:
            return jsonify({'error': '鏈兘鎵惧埌鍖呭惈鐗╁搧鎴?GUI 瀹氫箟鐨勯厤缃枃浠?(items/equipments/font_images)'}), 400

    # 4. 杩愯杞崲
    converter = IAConverter()
    converter.set_fix_illegal_model_rotations(_form_flag_enabled("fix_illegal_model_rotations"))
    
    # 鍔犺浇骞跺悎骞舵墍鏈夌墿鍝侀厤缃?
    merged_items_data = {
        "items": {},
        "equipments": {},
        "armors_rendering": {},
        "legacy_armor_renderings": {},
        "templates": {},
        "font_images": {},
        "recipes": {},
        "loots": {},
        "info": {}
    }
    
    for config_path in ia_items_configs:
        data = converter.load_config(config_path)
        if not data: continue
        
        # 鍚堝苟閫昏緫
        if "info" in data and not merged_items_data["info"]:
            merged_items_data["info"] = data["info"] # 浣跨敤鎵惧埌鐨勭涓€涓?info
        
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

        if "font_images" in data:
            merged_items_data.setdefault("font_images", {}).update(data["font_images"])

        if "loots" in data and isinstance(data["loots"], dict):
            for loot_group, loot_group_data in data["loots"].items():
                if isinstance(loot_group_data, dict):
                    merged_items_data.setdefault("loots", {}).setdefault(loot_group, {}).update(loot_group_data)

    for config_path in ia_font_image_configs:
        if config_path in ia_items_configs:
            continue
        data = converter.load_config(config_path)
        if not data:
            continue
        if "info" in data and not merged_items_data["info"]:
            merged_items_data["info"] = data["info"]
        if "font_images" in data:
            merged_items_data.setdefault("font_images", {}).update(data["font_images"])

    ia_data = merged_items_data
    
    # 濡傛灉鎵惧埌鍒欏姞杞藉垎绫?
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

    # 鍑嗗杈撳嚭璺緞
    # CraftEngine 杈撳嚭缁撴瀯: resources/<namespace>/...
    # 浣跨敤閰嶇疆涓殑鍛藉悕绌洪棿鎴栭粯璁ゅ€?
    original_namespace = ia_data.get("info", {}).get("namespace", "converted")
    namespace = original_namespace
    
    # 妫€鏌ョ敤鎴锋槸鍚︽寚瀹氫簡鍛藉悕绌洪棿
    user_namespace = request.form.get('namespace')
    if user_namespace:
        # 楠岃瘉鍛藉悕绌洪棿瑙勫垯: 0-9, a-z, _, -, .
        if not re.match(r'^[0-9a-z_.-]+$', user_namespace):
            return jsonify({'error': 'Invalid namespace'}), 400
        namespace = user_namespace

    # 鐗规畩澶勭悊锛氬鏋滆祫婧愬寘缁撴瀯鏄潪鏍囧噯鐨勶紙鐩存帴鍖呭惈 models/textures锛夛紝鍒欓噸缁勪负鏍囧噯缁撴瀯
    # 杩欓€氬父鍙戠敓鍦?ia_resourcepack_path 鎸囧悜浜嗗寘鍚?models/textures 鐨勬牴鐩綍锛屼絾缂哄皯 assets/<namespace> 鍖呰鐨勬儏鍐?
    if ia_resourcepack_path and os.path.exists(ia_resourcepack_path):
        # 妫€鏌ユ爣鍑嗙粨鏋勬槸鍚﹀瓨鍦?
        assets_path = os.path.join(ia_resourcepack_path, "assets")
        if not os.path.exists(assets_path):
            # 妫€鏌ユ槸鍚︽湁models 鎴?textures
            has_models = os.path.exists(os.path.join(ia_resourcepack_path, "models"))
            has_textures = os.path.exists(os.path.join(ia_resourcepack_path, "textures"))
            
            if has_models or has_textures:
                print(f"妫€娴嬪埌闈炴爣鍑嗚祫婧愬寘缁撴瀯锛屾鍦ㄩ噸缁勪负 assets/{namespace}/...")
                # 鍒涘缓涓€涓柊鐨勪复鏃剁洰褰曚綔涓鸿祫婧愬寘鏍圭洰褰曪紝浠ラ伩鍏嶆薄鏌撳師濮嬫彁鍙栫洰褰曟垨澶勭悊璺緞鍐茬獊
                restructured_root = os.path.join(session_upload_dir, "restructured_rp")
                target_ns_dir = os.path.join(restructured_root, "assets", namespace)
                os.makedirs(target_ns_dir, exist_ok=True)
                
                # 绉诲姩鏂囦欢澶?
                for folder_name in ["models", "textures", "sounds"]:
                    src_folder = os.path.join(ia_resourcepack_path, folder_name)
                    if os.path.exists(src_folder):
                        dst_folder = os.path.join(target_ns_dir, folder_name)
                        # 绉诲姩鏂囦欢澶?
                        shutil.move(src_folder, dst_folder)
                
                # 鏇存柊璧勬簮鍖呰矾寰勬寚鍚戞柊鐨勬爣鍑嗙粨鏋勬牴鐩綍
                ia_resourcepack_path = restructured_root
        else:
            # 鏍囧噯缁撴瀯锛氬鏋滃懡鍚嶇┖闂存敼鍙橈紝灏濊瘯閲嶅懡鍚嶆枃浠跺す浠ュ尮閰嶆柊鐨勫懡鍚嶇┖闂?
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
    ce_config_dir = os.path.join(ce_output_base, "configuration")
    ce_res_dir = os.path.join(ce_output_base, "resourcepack")
    
    # 濡傛灉鎵惧埌 resourcepack 鍒欒缃祫婧愯矾寰?
    if ia_resourcepack_path:
        converter.set_resource_paths(ia_resourcepack_path, ce_res_dir)

    converter.convert(ia_data, namespace=namespace)
    
    converter.save_config(ce_config_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format)


def _convert_ia_to_ce(extract_dir, session_output_dir, session_upload_dir, target_format):
    packages = _load_itemsadder_packages(extract_dir)
    if not any(package.get("item_configs") or package.get("font_image_configs") for package in packages):
        return jsonify({'error': 'No ItemsAdder item or GUI config files found'}), 400

    user_namespace = request.form.get('namespace')
    if user_namespace and not _is_valid_namespace(user_namespace):
        return jsonify({'error': 'Invalid namespace'}), 400
    namespace_overrides, error_response = _get_itemsadder_namespace_overrides()
    if error_response:
        return error_response

    conversion_packages = _build_itemsadder_conversion_packages(
        packages,
        None if namespace_overrides else user_namespace,
        session_upload_dir,
        "ia_to_ce",
        namespace_overrides=namespace_overrides,
    )

    for package in conversion_packages:
        if not package.get("item_configs") and not package.get("font_image_configs"):
            continue
        namespace = package["namespace"]
        converter = IAConverter()
        converter.set_fix_illegal_model_rotations(_form_flag_enabled("fix_illegal_model_rotations"))

        ce_output_base = os.path.join(session_output_dir, "CraftEngine", "resources", namespace)
        ce_config_dir = os.path.join(ce_output_base, "configuration")
        ce_res_dir = os.path.join(ce_output_base, "resourcepack")

        if package.get("resourcepack_path"):
            converter.set_resource_paths(package["resourcepack_path"], ce_res_dir)

        converter.convert(package["data"], namespace=namespace)
        converter.save_config(ce_config_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format)


def _convert_oraxen_to_ce(extract_dir, session_output_dir, session_upload_dir, target_format):
    merged_data, oraxen_pack_path, oraxen_item_configs = _load_oraxen_package(extract_dir)
    if not oraxen_item_configs:
        return jsonify({'error': '鏈兘鎵惧埌 Oraxen 鐗╁搧閰嶇疆鏂囦欢'}), 400

    namespace, error_response, status_code = _resolve_oraxen_output_namespace(
        merged_data,
        oraxen_item_configs,
        oraxen_pack_path
    )
    if error_response:
        return error_response, status_code

    ia_config = OraxenToIAConverter().convert(merged_data, namespace=namespace)

    converter = IAConverter()
    converter.set_fix_illegal_model_rotations(_form_flag_enabled("fix_illegal_model_rotations"))
    ce_output_base = os.path.join(session_output_dir, "CraftEngine", "resources", namespace)
    ce_config_dir = os.path.join(ce_output_base, "configuration")
    ce_res_dir = os.path.join(ce_output_base, "resourcepack")

    if oraxen_pack_path:
        converter.set_resource_paths(oraxen_pack_path, ce_res_dir)

    converter.convert(ia_config, namespace=namespace)
    converter.save_config(ce_config_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format)


def _convert_oraxen_to_nexo(extract_dir, session_output_dir, session_upload_dir, target_format):
    merged_data, oraxen_pack_path, oraxen_item_configs = _load_oraxen_package(extract_dir)
    if not oraxen_item_configs:
        return jsonify({'error': '鏈兘鎵惧埌 Oraxen 鐗╁搧閰嶇疆鏂囦欢'}), 400

    namespace, error_response, status_code = _resolve_oraxen_output_namespace(
        merged_data,
        oraxen_item_configs,
        oraxen_pack_path
    )
    if error_response:
        return error_response, status_code

    ia_config = OraxenToIAConverter().convert(merged_data, namespace=namespace)

    converter = IAToNexoConverter()
    nexo_root = os.path.join(session_output_dir, "Nexo")
    nexo_items_dir = os.path.join(nexo_root, "items")
    nexo_pack_dir = os.path.join(nexo_root, "pack")

    if oraxen_pack_path:
        converter.set_resource_paths(oraxen_pack_path, nexo_pack_dir)

    converter.convert(ia_config, namespace=namespace)
    converter.save_config(nexo_items_dir)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="Nexo")


def _convert_ia_to_oraxen_legacy(extract_dir, session_output_dir, session_upload_dir, target_format):
    merged_data, ia_resourcepack_path, ia_items_configs, original_namespace = _load_itemsadder_package(extract_dir)
    if not ia_items_configs and not merged_data.get("font_images"):
        return jsonify({'error': '鏈兘鎵惧埌鍖呭惈鐗╁搧瀹氫箟鐨?ItemsAdder 閰嶇疆鏂囦欢'}), 400

    user_namespace = request.form.get('namespace')
    if user_namespace:
        if not _is_valid_namespace(user_namespace):
            return jsonify({'error': 'Invalid namespace'}), 400
        namespace = user_namespace
    else:
        namespace = original_namespace

    converter = IAToOraxenConverter()
    oraxen_root = os.path.join(session_output_dir, "Oraxen")
    oraxen_pack_dir = os.path.join(oraxen_root, "pack")

    if ia_resourcepack_path:
        converter.set_resource_paths(ia_resourcepack_path, oraxen_pack_dir)

    converter.convert(merged_data, namespace=namespace)
    converter.save_config(oraxen_root)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="Oraxen")


def _convert_ia_to_oraxen(extract_dir, session_output_dir, session_upload_dir, target_format):
    packages = _load_itemsadder_packages(extract_dir)
    if not any(package.get("item_configs") or package.get("font_image_configs") for package in packages):
        return jsonify({'error': 'No ItemsAdder item config files found'}), 400

    user_namespace = request.form.get('namespace')
    if user_namespace and not _is_valid_namespace(user_namespace):
        return jsonify({'error': 'Invalid namespace'}), 400
    namespace_overrides, error_response = _get_itemsadder_namespace_overrides()
    if error_response:
        return error_response

    conversion_packages = _build_itemsadder_conversion_packages(
        packages,
        None if namespace_overrides else user_namespace,
        session_upload_dir,
        "ia_to_oraxen",
        namespace_overrides=namespace_overrides,
    )
    oraxen_root = os.path.join(session_output_dir, "Oraxen")
    oraxen_pack_dir = os.path.join(oraxen_root, "pack")

    for package in conversion_packages:
        if not package.get("item_configs") and not package.get("font_image_configs"):
            continue
        converter = IAToOraxenConverter()
        if package.get("resourcepack_path"):
            converter.set_resource_paths(package["resourcepack_path"], oraxen_pack_dir)
        converter.convert(package["data"], namespace=package["namespace"])
        converter.save_config(oraxen_root)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="Oraxen")


def _convert_ce_to_oraxen(extract_dir, session_output_dir, session_upload_dir, target_format):
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
        return jsonify({'error': '鏈兘鎵惧埌 CraftEngine 閰嶇疆鏂囦欢'}), 400

    user_namespace = request.form.get('namespace')
    if user_namespace:
        if not _is_valid_namespace(user_namespace):
            return jsonify({'error': 'Invalid namespace'}), 400
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
        converter = CEToOraxenConverter()
        oraxen_root = os.path.join(session_output_dir, "Oraxen")
        oraxen_pack_dir = os.path.join(oraxen_root, "pack")

        ce_resourcepack_paths = _collect_ce_resourcepack_paths(
            extract_dir,
            namespace=None if user_namespace else namespace,
        )
        if ce_resourcepack_paths:
            converter.set_resource_paths(ce_resourcepack_paths, oraxen_pack_dir)

        converter.convert(merged_data, namespace=namespace)
        converter.save_config(oraxen_root)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="Oraxen")


def _convert_nexo_to_oraxen(extract_dir, session_output_dir, session_upload_dir, target_format):
    nexo_items_configs = []
    nexo_categories_configs = []
    nexo_recipes_configs = []
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
            if isinstance(data.get("categories"), dict):
                nexo_categories_configs.append(full_path)
            if isinstance(data.get("recipes"), dict):
                nexo_recipes_configs.append(full_path)

    if not nexo_items_configs:
        return jsonify({'error': '鏈兘鎵惧埌 Nexo 鐗╁搧閰嶇疆鏂囦欢'}), 400

    if nexo_resourcepack_path:
        external_extract_root = os.path.join(session_upload_dir, "_nexo_external_packs_oraxen")
        if os.path.isdir(external_extract_root):
            shutil.rmtree(external_extract_root, ignore_errors=True)
        nexo_resourcepack_paths = _collect_nexo_resourcepack_paths(nexo_resourcepack_path, external_extract_root)

    user_namespace = request.form.get('namespace')
    if user_namespace:
        if not _is_valid_namespace(user_namespace):
            return jsonify({'error': 'Invalid namespace'}), 400
        namespace_map = {user_namespace: {"items": {}, "categories": {}, "recipes": {}}}
        for config_path in nexo_items_configs:
            data = safe_load_yaml(config_path)
            if isinstance(data, dict):
                namespace_map[user_namespace]["items"].update(data)
        for config_path in nexo_categories_configs:
            data = safe_load_yaml(config_path)
            if isinstance(data, dict) and isinstance(data.get("categories"), dict):
                namespace_map[user_namespace]["categories"].update(data["categories"])
        for config_path in nexo_recipes_configs:
            data = safe_load_yaml(config_path)
            if isinstance(data, dict) and isinstance(data.get("recipes"), dict):
                namespace_map[user_namespace]["recipes"].update(data["recipes"])
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
            namespace_map.setdefault(namespace, {"items": {}, "categories": {}, "recipes": {}})
            namespace_map[namespace]["items"].update(data)

        fallback_namespaces = list(namespace_map.keys())
        fallback_namespace = fallback_namespaces[0] if len(fallback_namespaces) == 1 else "converted"
        for config_path in nexo_categories_configs:
            data = safe_load_yaml(config_path)
            if isinstance(data, dict) and isinstance(data.get("categories"), dict):
                namespace_map.setdefault(fallback_namespace, {"items": {}, "categories": {}, "recipes": {}})
                namespace_map[fallback_namespace]["categories"].update(data["categories"])
        for config_path in nexo_recipes_configs:
            data = safe_load_yaml(config_path)
            if isinstance(data, dict) and isinstance(data.get("recipes"), dict):
                namespace_map.setdefault(fallback_namespace, {"items": {}, "categories": {}, "recipes": {}})
                namespace_map[fallback_namespace]["recipes"].update(data["recipes"])

    for namespace, merged_data in namespace_map.items():
        converter = NexoToOraxenConverter()
        oraxen_root = os.path.join(session_output_dir, "Oraxen")
        oraxen_pack_dir = os.path.join(oraxen_root, "pack")

        if nexo_resourcepack_path:
            converter.set_resource_paths(
                nexo_resourcepack_path,
                oraxen_pack_dir,
                additional_nexo_roots=nexo_resourcepack_paths[1:] if nexo_resourcepack_paths else None
            )

        converter.convert(merged_data, namespace=namespace)
        converter.save_config(oraxen_root)

    return _package_and_respond(session_output_dir, session_upload_dir, target_format, root_dir_name="Oraxen")


def _convert_oraxen_to_ia(extract_dir, session_output_dir, session_upload_dir, target_format):
    merged_data, oraxen_pack_path, oraxen_item_configs = _load_oraxen_package(extract_dir)
    if not oraxen_item_configs:
        return jsonify({'error': '鏈兘鎵惧埌 Oraxen 鐗╁搧閰嶇疆鏂囦欢'}), 400

    namespace, error_response, status_code = _resolve_oraxen_output_namespace(
        merged_data,
        oraxen_item_configs,
        oraxen_pack_path
    )
    if error_response:
        return error_response, status_code

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
    nexo_categories_configs = []
    nexo_recipes_configs = []
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
            if isinstance(data.get("categories"), dict):
                nexo_categories_configs.append(full_path)
            if isinstance(data.get("recipes"), dict):
                nexo_recipes_configs.append(full_path)

    if not nexo_items_configs:
        return jsonify({'error': '鏈兘鎵惧埌 Nexo 鐗╁搧閰嶇疆鏂囦欢'}), 400

    if nexo_resourcepack_path:
        # external_packs 浼氬厛瑙ｅ寘鍒颁复鏃剁洰褰曪紝鍐嶆寜椤哄簭鍙備笌璧勬簮杩佺Щ
        external_extract_root = os.path.join(session_upload_dir, "_nexo_external_packs")
        if os.path.isdir(external_extract_root):
            shutil.rmtree(external_extract_root, ignore_errors=True)
        nexo_resourcepack_paths = _collect_nexo_resourcepack_paths(nexo_resourcepack_path, external_extract_root)

    user_namespace = request.form.get('namespace')
    if user_namespace:
        if not re.match(r'^[0-9a-z_.-]+$', user_namespace):
            return jsonify({'error': 'Invalid namespace'}), 400
        merged_data = {"items": {}, "categories": {}, "recipes": {}}
        for config_path in nexo_items_configs:
            data = safe_load_yaml(config_path)
            if isinstance(data, dict):
                merged_data["items"].update(data)
        for config_path in nexo_categories_configs:
            data = safe_load_yaml(config_path)
            if isinstance(data, dict) and isinstance(data.get("categories"), dict):
                merged_data["categories"].update(data["categories"])
        for config_path in nexo_recipes_configs:
            data = safe_load_yaml(config_path)
            if isinstance(data, dict) and isinstance(data.get("recipes"), dict):
                merged_data["recipes"].update(data["recipes"])
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
                namespace_map[namespace] = {"items": {}, "categories": {}, "recipes": {}}
            namespace_map[namespace]["items"].update(data)

        fallback_namespaces = list(namespace_map.keys())
        fallback_namespace = fallback_namespaces[0] if len(fallback_namespaces) == 1 else "converted"
        for config_path in nexo_categories_configs:
            data = safe_load_yaml(config_path)
            if not isinstance(data, dict) or not isinstance(data.get("categories"), dict):
                continue
            namespace = fallback_namespace
            if namespace == "converted":
                file_name = os.path.basename(config_path)
                namespace = re.sub(r'[^0-9a-z_.-]', '_', os.path.splitext(file_name)[0].lower()) or "converted"
            namespace_map.setdefault(namespace, {"items": {}, "categories": {}, "recipes": {}})
            namespace_map[namespace]["categories"].update(data["categories"])
        for config_path in nexo_recipes_configs:
            data = safe_load_yaml(config_path)
            if not isinstance(data, dict) or not isinstance(data.get("recipes"), dict):
                continue
            namespace = fallback_namespace
            if namespace == "converted":
                file_name = os.path.basename(config_path)
                namespace = re.sub(r'[^0-9a-z_.-]', '_', os.path.splitext(file_name)[0].lower()) or "converted"
            namespace_map.setdefault(namespace, {"items": {}, "categories": {}, "recipes": {}})
            namespace_map[namespace]["recipes"].update(data["recipes"])

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
    # 5. 鍘嬬缉缁撴灉
    original_stem = _get_original_upload_stem(session_upload_dir)
    output_filename = _build_output_filename(original_stem, target_format)
    output_filename, output_zip_path = _next_available_output_path(output_filename)
    # 鎴戜滑甯屾湜鍘嬬缉鍖呰В鍘嬪悗鐩存帴鏄?resources 鏂囦欢澶癸紝鎴栬€?CraftEngine 鏂囦欢澶?
    shutil.make_archive(output_zip_path[:-4], 'zip', session_output_dir, root_dir_name)

    # 娓呯悊浼氳瘽鏂囦欢 
    # shutil.rmtree(session_upload_dir)
    # shutil.rmtree(session_output_dir)

    return jsonify({
        'status': 'success',
        'download_url': f'/api/download/{output_filename}'
    })

@app.route('/api/download/<filename>')
def download_file(filename):
    safe_name = _clean_download_filename(filename, "")
    if not safe_name or safe_name != filename or os.path.splitext(safe_name)[1].lower() != ".zip":
        return jsonify({'error': '鏃犳晥鐨勬枃浠跺悕'}), 400
    file_path = _safe_join_under(app.config['OUTPUT_FOLDER'], safe_name)
    if not os.path.isfile(file_path):
        return jsonify({'error': 'File not found or expired'}), 404
    return send_file(file_path, as_attachment=True)

import webbrowser
from threading import Timer

@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    """Shut down the server."""
    def kill():
        os._exit(0)
        
    # 寤惰繜 1 绉掓墽琛岋紝浠ヤ究杩斿洖鍝嶅簲缁欏墠绔?
    Timer(1.0, kill).start()
    return jsonify({'status': 'server shutting down...'})

def open_browser():
    webbrowser.open_new('http://127.0.0.1:5000/')



if __name__ == '__main__':
    # 浠呭湪闈炶皟璇曟ā寮忎笅鎵撳紑娴忚鍣?(閲嶈浇浼氬鑷村弻閲嶆墦寮€)
    # 浣嗗浜庢墦鍖呯殑搴旂敤锛岃皟璇曢€氬父涓?False 鎴栦笉鐩稿叧銆?
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        Timer(1.5, open_browser).start()
    app.run(debug=False, port=5000)

