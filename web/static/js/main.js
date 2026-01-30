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
        if (!file.name.endsWith('.zip')) {
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
        
        const targetSelect = document.getElementById('target-format-select');
        if (targetSelect) {
            formData.append('target_format', targetSelect.value);
        }

        const namespaceInput = document.getElementById('namespace-input');
        if (namespaceInput && namespaceInput.value.trim()) {
            formData.append('namespace', namespaceInput.value.trim());
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
        
        // 生成目标格式选择器
        let targetOptions = '';
        if (report.available_targets && report.available_targets.length > 0) {
            targetOptions = report.available_targets.map(t => `<option value="${t}">${t}</option>`).join('');
        } else {
            targetOptions = '<option value="" disabled selected>无可用转换</option>';
        }

        // 格式化源格式标签
        let sourceFormatsHtml = report.source_formats && report.source_formats.length > 0 
            ? report.source_formats.map(f => `<span class="value source-format">${f}</span>`).join(' ')
            : '<span class="value source-format">未知</span>';

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
                <div class="report-grid">
                    <div class="report-item" style="grid-column: span 2;">
                        <span class="label">当前文件:</span>
                        <span class="value filename">${report.filename || '未知'}</span>
                    </div>
                    <div class="report-item">
                        <span class="label">检测到的格式:</span>
                        <div class="format-list">${sourceFormatsHtml}</div>
                    </div>
                    <div class="report-item">
                        <span class="label">目标格式:</span>
                        <select id="target-format-select" class="target-select" ${report.available_targets.length === 0 ? 'disabled' : ''}>
                            ${targetOptions}
                        </select>
                    </div>
                    <div class="report-item">
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
                <div class="actions">
                    <button id="start-convert-btn" class="btn-primary" ${report.available_targets.length === 0 ? 'disabled' : ''}>开始转换</button>
                    <button onclick="location.reload()" class="btn-secondary">取消</button>
                </div>
            </div>
        `;
        
        const main = document.querySelector('main');
        const existing = document.getElementById('report-section');
        if(existing) existing.remove();
        
        main.insertAdjacentHTML('beforeend', reportHtml);
        
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

    // 心跳包保证服务器存活
    setInterval(() => {
        fetch('/api/heartbeat', { method: 'POST' })
            .catch(() => {
                console.log("Heartbeat failed.");
            });
    }, 2000); // 每两秒发送一次心跳包
});
