import yaml
import os
import re


def _quote_bare_ampersand_values(content):
    """
    将形如 `key: &e` 的裸值改写为字符串 `key: "&e"`。
    仅用于 YAML 解析失败时的兜底修复，避免把颜色代码误识别为锚点。
    """
    pattern = re.compile(
        r"^(\s*[^#:\n][^:\n]*:\s*)(&[^\s#]+)(\s*(#.*)?)\r?$",
        re.MULTILINE
    )

    def _replacer(match):
        prefix = match.group(1)
        value = match.group(2)
        suffix = match.group(3) or ""
        return f'{prefix}"{value}"{suffix}'

    return pattern.sub(_replacer, content, count=0)

def safe_load_yaml(file_path):
    """
    安全加载 YAML 文件，处理常见的制表符缩进等问题。
    
    :param file_path: YAML 文件路径
    :return: 解析后的数据 (字典或列表)
    :raises: 如果加载失败，抛出 yaml.YAMLError 或 OSError
    """
    try:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                # 尝试 GBK (常见于中文 Windows 环境)
                with open(file_path, 'r', encoding='gbk') as f:
                    content = f.read()
            except UnicodeDecodeError:
                # 尝试 latin-1 (保证能读取，但可能乱码)
                with open(file_path, 'r', encoding='latin-1') as f:
                    content = f.read()
            
        return yaml.safe_load(content)
    except yaml.scanner.ScannerError as e:
        # 检查错误是否可能是由制表符引起的
        if '\t' in content:
            # 尝试将制表符替换为 2 个空格 (常见约定)
            sanitized_content = content.replace('\t', '  ')
            try:
                return yaml.safe_load(sanitized_content)
            except yaml.YAMLError:
                # 如果 2 个空格不起作用，尝试 4 个空格
                sanitized_content = content.replace('\t', '    ')
                return yaml.safe_load(sanitized_content)
        raise e
    except yaml.YAMLError as e:
        # 兼容处理：某些配置把颜色代码写成 `display_name: &e`，会被 YAML 当作锚点并触发 duplicate anchor
        if "duplicate anchor" in str(e):
            sanitized_content = _quote_bare_ampersand_values(content)
            if sanitized_content != content:
                return yaml.safe_load(sanitized_content)
        raise e
    except Exception as e:
        raise e
