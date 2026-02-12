from flask import Flask, render_template, request, send_file, jsonify
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
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.converters.ia_to_ce import IAConverter
from src.analyzer import PackageAnalyzer

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'temp_uploads')
app.config['OUTPUT_FOLDER'] = os.path.join(os.getcwd(), 'temp_output')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB 限制

# 确保临时目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

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
            filename = file.filename
            file_path = os.path.join(session_upload_dir, filename)
            file.save(file_path)

            extract_dir = os.path.join(session_upload_dir, "extracted")
            if filename.endswith('.zip'):
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
            else:
                return jsonify({'error': '请上传 .zip 文件'}), 400

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
                available_targets.append("CraftEngine")
                
            if "CraftEngine" in detected_formats:
                 # 未来支持 CE -> IA
                 pass

            report["source_formats"] = detected_formats # 改名以反映复数
            report["available_targets"] = available_targets
            report["warnings"] = warnings
            report["filename"] = filename
            
            return jsonify({
                'status': 'success',
                'report': report,
                'session_id': session_id
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/convert', methods=['POST'])
def convert():
    # 支持两种模式：
    # 1. 传统的直接上传文件并转换 (保持兼容)
    # 2. 接受 session_id (从 /api/analyze 获取) 进行转换
    
    session_id = request.form.get('session_id')
    target_format = request.form.get('target_format', 'CraftEngine') # 默认 CE
    
    if session_id:
        # 使用已存在的会话
        session_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
        extract_dir = os.path.join(session_upload_dir, "extracted")
        if not os.path.exists(extract_dir):
            return jsonify({'error': '会话已过期或不存在'}), 400
            
        session_output_dir = os.path.join(app.config['OUTPUT_FOLDER'], session_id)
        os.makedirs(session_output_dir, exist_ok=True)
        
    elif 'file' in request.files:
        # 传统模式
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': '未选择文件'}), 400
            
        session_id = str(uuid.uuid4())
        session_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
        session_output_dir = os.path.join(app.config['OUTPUT_FOLDER'], session_id)
        os.makedirs(session_upload_dir, exist_ok=True)
        os.makedirs(session_output_dir, exist_ok=True)

        filename = file.filename
        file_path = os.path.join(session_upload_dir, filename)
        file.save(file_path)

        extract_dir = os.path.join(session_upload_dir, "extracted")
        if filename.endswith('.zip'):
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        else:
            return jsonify({'error': '请上传 .zip 文件'}), 400
    else:
        return jsonify({'error': '无效的请求'}), 400

    try:
        if target_format == "CraftEngine":
            # 3. 定位配置和资源 (ItemsAdder -> CraftEngine 逻辑)
            # 改进逻辑: 扫描所有 YAML 文件并根据内容进行分类
            ia_items_configs = []
            ia_categories_configs = []
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
                            with open(full_path, 'r', encoding='utf-8') as yml_file:
                                data = yaml.safe_load(yml_file)
                                if not data:
                                    continue
                                
                                # 检查关键签名
                                if "items" in data or "equipments" in data or "armors_rendering" in data:
                                    ia_items_configs.append(full_path)
                                elif "categories" in data:
                                    ia_categories_configs.append(full_path)
                        except Exception:
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
            merged_items_data = {"items": {}, "equipments": {}, "armors_rendering": {}, "templates": {}, "info": {}}
            
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

            output_filename = f"{original_filename} [{target_format} by MCC].zip"
            # 简单的文件名清理，防止非法字符
            output_filename = re.sub(r'[\\/*?:"<>|]', "", output_filename)
            
            output_zip_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            # 我们希望压缩包解压后直接是 resources 文件夹，或者 CraftEngine 文件夹

            shutil.make_archive(output_zip_path[:-4], 'zip', session_output_dir, "CraftEngine")

            # 清理会话文件 
            # shutil.rmtree(session_upload_dir)
            # shutil.rmtree(session_output_dir)

            return jsonify({
                'status': 'success',
                'download_url': f'/api/download/{output_filename}'
            })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(app.config['OUTPUT_FOLDER'], filename), as_attachment=True)

import webbrowser
from threading import Timer, Lock

# ... existing imports ...

# ... existing code ...

@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    """关闭服务器"""
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        # 如果不是使用 Werkzeug 运行 (例如生产环境 WSGI)，这可能会失败或需要替代方案
        # 但对于本地 PyInstaller 使用，通常是 Werkzeug。
        # 替代方案: sys.exit()
        import sys
        import threading
        
        def kill():
            sys.exit(0)
            
        threading.Timer(1.0, kill).start()
        return jsonify({'status': 'server shutting down...'})
        
    func()
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
