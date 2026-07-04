document.addEventListener('DOMContentLoaded', () => {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const progressSection = document.getElementById('progress-section');
    const progressFill = document.getElementById('progress-fill');
    const statusText = document.getElementById('status-text');
    const resultSection = document.getElementById('result-section');
    const downloadLink = document.getElementById('download-link');
    const errorSection = document.getElementById('error-section');
    const errorMessage = document.getElementById('error-message');

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            handleFile(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFile(e.target.files[0]);
        }
    });

    function handleFile(file) {
        if (!file.name.toLowerCase().endsWith('.zip')) {
            showError("请上传 .zip 格式的文件。");
            return;
        }

        // Reset UI
        dropZone.style.display = 'none';
        errorSection.style.display = 'none';
        progressSection.style.display = 'block';
        
        uploadFile(file);
    }

    function uploadFile(file) {
        const formData = new FormData();
        formData.append('file', file);

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/analyze', true);

        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                const percentComplete = (e.loaded / e.total) * 80;
                updateProgress(percentComplete, "正在上传并分析...");
            }
        };

        xhr.onload = function() {
            if (xhr.status === 200) {
                updateProgress(100, "分析完成");
                const response = JSON.parse(xhr.responseText);
                showAnalysisReport(response.report, response.session_id);
            } else {
                let errorMsg = "发生未知错误。";
                try {
                    const response = JSON.parse(xhr.responseText);
                    errorMsg = response.error || errorMsg;
                } catch(e) {}
                showError(errorMsg);
            }
        };

        xhr.onerror = function() {
            showError("发生网络错误。");
        };

        xhr.send(formData);
    }

    function startConversion(sessionId) {
        const formData = new FormData();
        formData.append('session_id', sessionId);
        
        const sourceInput = document.getElementById('selected-source');
        if (sourceInput && sourceInput.value) {
            formData.append('source_format', sourceInput.value);
        }

        const targetInput = document.getElementById('selected-target');
        if (targetInput && targetInput.value) {
            formData.append('target_format', targetInput.value);
        } else {
            const targetSelect = document.getElementById('target-format-select');
            if (targetSelect) {
                formData.append('target_format', targetSelect.value);
            }
        }

        const namespaceInput = document.getElementById('namespace-input');
        if (namespaceInput && namespaceInput.value.trim()) {
            formData.append('namespace', namespaceInput.value.trim());
        }

        const batchNamespaceInputs = Array.from(document.querySelectorAll('.batch-namespace-input'));
        if (batchNamespaceInputs.length > 0) {
            const namespaceOverrides = {};
            batchNamespaceInputs.forEach(input => {
                const sourceNamespace = input.dataset.sourceNamespace;
                const targetNamespace = input.value.trim();
                if (sourceNamespace && targetNamespace) {
                    namespaceOverrides[sourceNamespace] = targetNamespace;
                }
            });
            if (Object.keys(namespaceOverrides).length > 0) {
                formData.append('namespace_overrides', JSON.stringify(namespaceOverrides));
            }
        }

        const fixRotationsInput = document.getElementById('fix-illegal-model-rotations');
        if (fixRotationsInput && fixRotationsInput.checked) {
            formData.append('fix_illegal_model_rotations', '1');
        }
        
        progressSection.style.display = 'block';
        updateProgress(0, "正在转换...");
        
        const reportSection = document.getElementById('report-section');
        if(reportSection) reportSection.style.display = 'none';

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/convert', true);
        
        xhr.onload = function() {
            if (xhr.status === 200) {
                updateProgress(100, "转换完成");
                const response = JSON.parse(xhr.responseText);
                showResult(response.download_url);
            } else {
                let errorMsg = "转换失败。";
                try {
                    const response = JSON.parse(xhr.responseText);
                    errorMsg = response.error || errorMsg;
                } catch(e) {}
                showError(errorMsg);
            }
        };
        
        let p = 0;
        const interval = setInterval(() => {
            if(xhr.readyState === 4) {
                clearInterval(interval);
                return;
            }
            if(p < 90) {
                p += 5;
                updateProgress(p, "正在转换...");
            }
        }, 200);
        
        xhr.send(formData);
    }

    function showAnalysisReport(report, sessionId) {
        progressSection.style.display = 'none';
        
        // 支持的插件列表 (后端未返回时使用默认值)
        const supportedPlugins = report.supported_plugins || [
            {id: "ItemsAdder", name: "ItemsAdder", icon: "📦"},
            {id: "Nexo", name: "Nexo", icon: "🧩"},
            {id: "Oraxen", name: "Oraxen", icon: "💎"},
            {id: "CraftEngine", name: "CraftEngine", icon: "⚙️"},
            {id: "MythicCrucible", name: "MythicCrucible", icon: "⚔️"},
            {id: "HMCCosmetics", name: "HMCCosmetics", icon: "👒"}
        ];

        const itemsAdderPackages = Array.isArray(report.itemsadder_packages) ? report.itemsadder_packages : [];
        const hasItemsAdderBatch = itemsAdderPackages.length > 1;

        function escapeHtml(value) {
            return String(value ?? '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        function generateBatchNamespaceList() {
            if (!hasItemsAdderBatch) return '';
            return `
                <div class="batch-namespace-section" id="batch-namespace-section">
                    <div class="batch-namespace-header">
                        <span>批量命名空间</span>
                        <span>${itemsAdderPackages.length} 个内容包</span>
                    </div>
                    <div class="batch-namespace-list">
                        ${itemsAdderPackages.map(pkg => {
                            const sourceNamespace = pkg.source_namespace || 'converted';
                            const targetNamespace = pkg.target_namespace || sourceNamespace;
                            return `
                                <div class="batch-namespace-row">
                                    <div class="batch-namespace-source">
                                        <span class="batch-source-name">${escapeHtml(sourceNamespace)}</span>
                                        <span class="batch-source-meta">${Number(pkg.item_count || 0)} items</span>
                                    </div>
                                    <input
                                        type="text"
                                        class="text-input batch-namespace-input"
                                        data-source-namespace="${escapeHtml(sourceNamespace)}"
                                        value="${escapeHtml(targetNamespace)}"
                                        title="仅允许小写字母、数字、下划线、连字符和点"
                                    >
                                </div>
                            `;
                        }).join('')}
                    </div>
                </div>
            `;
        }

        // 默认选择
        let selectedSource = report.source_formats[0] || null;
        // 自动选择第一个可用的目标
        let selectedTarget = null;
        if (report.available_targets && report.available_targets.length > 0) {
             selectedTarget = report.available_targets[0];
        }

        // 生成插件网格 HTML
        function generatePluginGrid(isSource) {
            return supportedPlugins.map(p => {
                let isSelectable = false;
                let isSelected = false;

                if (isSource) {
                    // 源插件：必须在检测到的格式中
                    if (report.source_formats.includes(p.id)) {
                        isSelectable = true;
                        if (p.id === selectedSource) isSelected = true;
                    }
                } else {
                    // 目标插件：必须不在检测到的格式中 (Constraint 3) 且在可用目标中
                    if (!report.source_formats.includes(p.id)) {
                        if (report.available_targets.includes(p.id)) {
                            isSelectable = true;
                            if (p.id === selectedTarget) isSelected = true;
                        }
                        // 也可以显示为禁用状态，如果不满足条件
                    }
                }

                const classes = `plugin-card ${isSelectable ? 'selectable' : ''} ${isSelected ? 'selected' : ''}`;
                
                // 判断是 emoji 还是图片路径
                const iconContent = (p.icon.includes('/') || p.icon.includes('.')) 
                    ? `<img src="${p.icon}" alt="${p.name}">`
                    : p.icon;

                return `
                    <div class="${classes}" data-id="${p.id}">
                        <div class="plugin-icon">${iconContent}</div>
                        <div class="plugin-name">${p.name}</div>
                    </div>
                `;
            }).join('');
        }

        // 生成警告信息
        let warningHtml = '';
        if (report.warnings && report.warnings.length > 0) {
            warningHtml = `
                <div class="warning-box">
                    ${report.warnings.map(w => `<p>⚠️ ${w}</p>`).join('')}
                </div>
            `;
        }

        let reportHtml = `
            <div id="report-section" class="report-section">
                <h3>📦 包内容分析</h3>
                ${warningHtml}
                
                <div class="plugin-selection-container">
                    <div class="plugin-column">
                        <h4>源插件</h4>
                        <div class="plugin-grid" id="source-plugins-grid">
                            ${generatePluginGrid(true)}
                        </div>
                    </div>
                    <div class="arrow-separator">➜</div>
                    <div class="plugin-column">
                        <h4>目标插件</h4>
                        <div class="plugin-grid" id="target-plugins-grid">
                            ${generatePluginGrid(false)}
                        </div>
                    </div>
                </div>

                <input type="hidden" id="selected-source" value="${selectedSource || ''}">
                <input type="hidden" id="selected-target" value="${selectedTarget || ''}">

                <div class="report-grid">
                    <div class="report-item" style="grid-column: span 2;">
                        <span class="label">当前文件:</span>
                        <span class="value filename">${report.filename || '未知'}</span>
                    </div>
                    
                    <div class="report-item" id="single-namespace-item">
                        <span class="label">命名空间 (可选):</span>
                        <input type="text" id="namespace-input" class="text-input" placeholder="留空使用默认值" title="仅允许小写字母、数字、下划线、连字符和点">
                    </div>
                    <div class="report-item">
                        <span class="label">包含内容:</span>
                        <span class="value">${report.content_types.join(', ') || '无'}</span>
                    </div>
                    <div class="report-item">
                        <span class="label">完整性检查:</span>
                        <ul class="check-list">
                            <li class="${report.completeness.items_config ? 'ok' : 'fail'}">物品配置</li>
                            <li class="${report.completeness.categories_config ? 'ok' : 'fail'}">分类配置</li>
                            <li class="${report.completeness.resource_files ? 'ok' : 'fail'}">资源文件</li>
                        </ul>
                    </div>
                    <div class="report-item">
                        <span class="label">详细统计:</span>
                        <ul class="stats-list">
                            <li>物品: ${report.details.item_count}</li>
                            <li>纹理: ${report.details.texture_count}</li>
                            <li>模型: ${report.details.model_count}</li>
                        </ul>
                    </div>
                </div>
                ${generateBatchNamespaceList()}
                <div class="conversion-options" id="craftengine-options">
                    <label class="checkbox-option">
                        <input type="checkbox" id="fix-illegal-model-rotations" checked>
                        <span>修正非法模型旋转角</span>
                    </label>
                </div>
                <div class="actions">
                    <button id="start-convert-btn" class="btn-primary" ${!selectedTarget ? 'disabled' : ''}>开始转换</button>
                    <button onclick="location.reload()" class="btn-secondary">取消</button>
                </div>
            </div>
        `;
        
        const main = document.querySelector('main');
        const existing = document.getElementById('report-section');
        if(existing) existing.remove();
        
        main.insertAdjacentHTML('beforeend', reportHtml);
        
        // 绑定点击事件
        const sourceGrid = document.getElementById('source-plugins-grid');
        const targetGrid = document.getElementById('target-plugins-grid');

        function syncConversionOptions() {
            const target = document.getElementById('selected-target').value;
            const craftEngineOptions = document.getElementById('craftengine-options');
            if (craftEngineOptions) {
                craftEngineOptions.style.display = target === 'CraftEngine' ? 'flex' : 'none';
            }
        }

        function syncBatchNamespaceList() {
            const source = document.getElementById('selected-source').value;
            const batchSection = document.getElementById('batch-namespace-section');
            const singleNamespaceItem = document.getElementById('single-namespace-item');
            const showBatch = hasItemsAdderBatch && source === 'ItemsAdder';
            if (batchSection) {
                batchSection.style.display = showBatch ? 'block' : 'none';
            }
            if (singleNamespaceItem) {
                singleNamespaceItem.style.display = showBatch ? 'none' : 'block';
            }
        }
        
        sourceGrid.addEventListener('click', (e) => {
            const card = e.target.closest('.plugin-card.selectable');
            if(card) {
                const id = card.dataset.id;
                document.getElementById('selected-source').value = id;
                sourceGrid.querySelectorAll('.plugin-card').forEach(c => c.classList.remove('selected'));
                card.classList.add('selected');
                syncBatchNamespaceList();
            }
        });
        
        targetGrid.addEventListener('click', (e) => {
            const card = e.target.closest('.plugin-card.selectable');
            if(card) {
                const id = card.dataset.id;
                document.getElementById('selected-target').value = id;
                targetGrid.querySelectorAll('.plugin-card').forEach(c => c.classList.remove('selected'));
                card.classList.add('selected');
                document.getElementById('start-convert-btn').disabled = false;
                syncConversionOptions();
            }
        });
        
        syncConversionOptions();
        syncBatchNamespaceList();
        document.getElementById('start-convert-btn').onclick = () => startConversion(sessionId);
    }

    function updateProgress(percent, text) {
        progressFill.style.width = percent + '%';
        statusText.textContent = text;
    }

    function showResult(url) {
        progressSection.style.display = 'none';
        resultSection.style.display = 'block';
        downloadLink.href = url;
    }

    function showError(msg) {
        progressSection.style.display = 'none';
        dropZone.style.display = 'none';
        errorSection.style.display = 'block';
        errorMessage.textContent = msg;
    }

});
