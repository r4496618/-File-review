import os
import hashlib
import argparse
import unicodedata
from bisect import bisect_left, bisect_right
from typing import List, Dict
import json
import sys
import pythoncom
import time


class FileDeduplicator:
    def _create_shortcut(self, target_path, source_path):
        """创建Windows快捷方式"""
        if not self.link_mode:
            return False
            
        try:
            # 动态导入模块
            from win32com.client import Dispatch
            
            shell = Dispatch('WScript.Shell')
            shortcut = shell.CreateShortCut(source_path + '.lnk')
            shortcut.Targetpath = target_path
            shortcut.WorkingDirectory = os.path.dirname(target_path)
            shortcut.save()
            return True
        except ImportError:
            print("检测到缺少pywin32依赖，正在尝试自动安装...")
            try:
                import subprocess
                subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'pywin32'])
                print("安装成功，请重新运行程序")
                sys.exit(0)
            except Exception as e:
                print(f"自动安装失败: {str(e)}，请手动执行: pip install pywin32")
                return False
        except Exception as e:
            print(f"创建快捷方式失败: {str(e)}")
            return False

    def __del__(self):
        """析构函数自动保存哈希缓存"""
        self._save_hash_cache()
    """
    重复文件检测器核心类
    功能：
    1. 扫描指定目录并建立文件索引
    2. 基于文件名相似度和文件大小检测重复文件
    3. 提供交互式删除功能
    4. 支持缓存机制加速重复检测
    """

    def __init__(self, hash_check=False, link_mode=False):
        """初始化类属性"""
        self.hash_check = hash_check
        self.link_mode = link_mode
        # 文件元数据缓存路径（记录文件大小、名称哈希等信息）
        self.file_cache = 'file_cache.json'
        # 重复文件组缓存路径
        self.duplicate_cache = 'duplicate_cache.json'
        # 文件名相似度阈值（0.0-1.0）
        self.similarity_threshold = 0.9
        # 文件索引字典 {文件路径: 元数据}
        self.file_index = self._load_cache(self.file_cache)
        # 重复文件组缓存
        self.duplicate_index = self._load_cache(self.duplicate_cache)
        # 中断标志位（用于信号处理）
        self.should_stop = False
        # 哈希缓存字典
        self.hash_cache = {}

        # 注册Ctrl+C信号处理器
        import signal
        signal.signal(signal.SIGINT, self._handle_interrupt)

    def _handle_interrupt(self, signum, frame):
        """
        信号处理函数 - 处理键盘中断(Ctrl+C)
        参数：
            signum: 信号编号
            frame: 当前堆栈帧
        """
        print("\n收到停止信号，正在安全退出...")
        self.should_stop = True

    def _load_cache(self, cache_file):
        """
        加载JSON格式缓存文件
        参数：
            cache_file: 缓存文件路径
        返回：
            dict: 加载的缓存数据，失败返回空字典
        功能说明：
            1. 自动处理旧版本缓存格式升级
            2. 新增sorted_size字段用于优化排序比较
        """
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    # 兼容旧版本缓存：添加sorted_size字段
                    for path, file_info in data.items():
                        path = unicodedata.normalize('NFC', path)
                        if 'sorted_size' not in file_info:
                            # 将原始size复制到sorted_size用于排序比较
                            file_info['sorted_size'] = file_info['size']
                    return data
        except Exception as e:
            print(f"加载缓存失败: {str(e)}")
        return {}

    def _fuzzy_match(self, s1: str, s2: str) -> float:
        """
        计算两个文件名的相似度（基于Levenshtein距离算法）
        参数：
            s1: 文件名1（自动去除扩展名）
            s2: 文件名2（自动去除扩展名）
        返回：
            float: 相似度比例（0.0-1.0）
        算法步骤：
            1. 预处理：转小写并移除文件扩展名
            2. 计算最小编辑距离
            3. 转换为相似度比例
        """
        # 预处理：去除扩展名并转为小写
        s1 = unicodedata.normalize('NFC', os.path.splitext(s1)[0].lower())
        s2 = unicodedata.normalize('NFC', os.path.splitext(s2)[0].lower())
        
        # 确保s1长度大于等于s2
        if len(s1) < len(s2):
            return self._fuzzy_match(s2, s1)

        max_len = max(len(s1), len(s2))
        if max_len == 0:
            return 1.0

        # 计算Levenshtein距离并转换为相似度
        distance = self._levenshtein_distance(s1, s2)
        return 1 - distance / max_len

    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """
        动态规划实现Levenshtein编辑距离计算
        参数：
            s1: 字符串1
            s2: 字符串2
        返回：
            int: 将s1转换为s2所需的最小操作次数
        算法说明：
            操作包括：插入、删除、替换
            时间复杂度：O(n*m), 空间复杂度：O(n)
        """
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)

        # 初始化动态规划矩阵（仅保留前一行和当前行）
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                # 计算三种操作的代价值
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        return previous_row[-1]

    def _save_hash_cache(self):
        try:
            with open('hash_cache.json', 'w') as f:
                json.dump(self.hash_cache, f)
        except Exception as e:
            print(f"保存哈希缓存失败: {str(e)}")

    def scan_files(self, root_dirs: List[str], extensions: List[str] = None, 
                 keywords: List[str] = None, exclude_dirs: List[str] = None,
                 similarity: float = None, no_extension: List[str] = None, 
                 no_keyword: List[str] = None) -> None:
        """
        扫描指定目录并建立文件索引
        参数：
            root_dir: 要扫描的根目录
            extensions: 文件扩展名过滤器列表
            keywords: 文件名关键词过滤器列表
            similarity: 临时覆盖类相似度阈值
        流程说明：
            1. 检查中断标志位
            2. 遍历目录树
            3. 应用扩展名和关键词过滤
            4. 记录文件元数据
            5. 按sorted_size排序后更新索引
        """

        # 更新相似度阈值
        if similarity is not None:
            self.similarity_threshold = similarity

        # 强制完全重建文件索引
        self.file_index = {}
        new_files = {}
        self.root_dirs = [os.path.abspath(d) for d in root_dirs]
        exclude_paths = [os.path.abspath(d) for d in (exclude_dirs or [])]

        # 初始化排除参数
        no_extension = no_extension or []
        no_keyword = no_keyword or []
        processed_no_ext = [ext.lower().lstrip('.') for ext in no_extension]
        normalized_no_kw = [unicodedata.normalize('NFC', kw.lower()) for kw in no_keyword]
        for root_dir in root_dirs:
            for dirpath, _, filenames in os.walk(root_dir):
                # 排除路径检查
                if any(os.path.commonpath([os.path.abspath(dirpath), ep]) == ep for ep in exclude_paths):
                    continue
                if self.should_stop:
                    print("扫描已中止")
                    return
                
                for fname in filenames:
                    if self.should_stop:
                        return
                    fname = os.fsdecode(fname)
                    fname = unicodedata.normalize('NFC', fname)
                    full_path = os.path.join(dirpath, fname)

                    # 跳过未修改的已记录文件
                    if full_path in self.file_index:
                        current_size = os.path.getsize(full_path)
                        if current_size == self.file_index[full_path]['size']:
                            continue

                    # 应用扩展名过滤
                    if extensions:
                        processed_extensions = [ext.lower().lstrip('.') for ext in extensions]
                        # 应用扩展名过滤检查
                        if not os.path.splitext(fname)[1].lower().lstrip('.') in processed_extensions:
                            continue
                    
                    # 应用关键词过滤
                    if keywords:
                        normalized_name = unicodedata.normalize('NFC', os.path.splitext(fname)[0].lower())
                        normalized_keywords = [unicodedata.normalize('NFC', kw.lower()) for kw in keywords]
                        if not any(kw in normalized_name for kw in normalized_keywords):
                            continue

                    # 排除过滤检查
                    if no_extension or no_keyword:
                        file_ext = os.path.splitext(fname)[1].lower().lstrip('.')
                        file_name = os.path.splitext(fname)[0].lower()
                    
                    # 检查排除扩展名
                    if no_extension:
                        if processed_no_ext and file_ext in processed_no_ext:
                            continue
                        
                    # 检查排除关键词
                    if no_keyword:
                        if normalized_no_kw and any(kw in file_name for kw in normalized_no_kw):
                            continue
                    
                    # 记录文件元数据
                    file_size = os.path.getsize(full_path)
                    new_files[full_path] = {
                        'size': file_size,
                        'name': os.path.splitext(fname)[0].lower(),
                        'hash': '',
                        'sorted_size': file_size
                    }

        # 按sorted_size排序后合并到文件索引
        sorted_files = sorted(new_files.items(), key=lambda x: x[1]['sorted_size'])

        
        # 二次过滤确保索引文件合规
        filtered_files = {
            k:v for k,v in sorted_files
            if os.path.splitext(k)[1].lower().lstrip('.') not in processed_no_ext
            and not any(kw in os.path.splitext(os.path.basename(k))[0].lower() for kw in normalized_no_kw)
        }

        
        # 覆盖式更新文件索引
        self.file_index = filtered_files
        
        start_time8 = time.perf_counter()
        # 应用排除过滤
        filtered_index = {}
        for path, meta in self.file_index.items():
            file_ext = os.path.splitext(path)[1].lower().lstrip('.')
            file_name = os.path.splitext(os.path.basename(path))[0].lower()
            
            # 排除扩展名
            if file_ext in processed_no_ext:
                continue
            
            # 排除关键词
            normalized_name = unicodedata.normalize('NFC', file_name)
            if any(nk in normalized_name for nk in normalized_no_kw):
                continue
            
            filtered_index[path] = meta

        # 应用排除过滤
        processed_no_ext = [ext.lower().lstrip('.') for ext in (no_extension or [])]
        normalized_no_kw = [unicodedata.normalize('NFC', kw.lower()) for kw in (no_keyword or [])]

        filtered_index = {}
        for path, meta in self.file_index.items():
            file_ext = os.path.splitext(path)[1].lower().lstrip('.')
            file_name = os.path.splitext(os.path.basename(path))[0].lower()
            
            if file_ext in processed_no_ext:
                continue
            if any(nk in unicodedata.normalize('NFC', file_name) for nk in normalized_no_kw):
                continue
            
            filtered_index[path] = meta

        # 持久化前再次验证过滤条件
        final_cache = {}
        for path, meta in filtered_index.items():
            if os.path.splitext(path)[1].lower().lstrip('.') in processed_no_ext:
                continue
            file_name = os.path.splitext(os.path.basename(path))[0].lower()
            if any(nk in unicodedata.normalize('NFC', file_name) for nk in normalized_no_kw):
                continue
            final_cache[path] = meta
        
        # 持久化更新文件缓存
        with open(self.file_cache, 'w') as f:
            json.dump(final_cache, f)

        # 扫描完成后保存哈希缓存
        self._save_hash_cache()



    def delete_duplicates(self, duplicates: Dict[str, List[str]], confirm=True):
        """
        删除重复文件（保留每个分组第一个文件）
        参数：
            duplicates: 重复文件分组字典
            confirm: 是否进行交互式确认
        返回：
            list: 已删除文件路径列表
        交互流程：
            1. 显示重复文件列表
            2. 用户选择(y/N/q)
            3. 执行删除并更新缓存
        """
        deleted_files = []
        for group_id, group in duplicates.items():
            if self.should_stop:
                return deleted_files
            
            if len(group) > 1:
                if confirm:
                    print(f"\n发现重复组 ({len(group)} 个文件):")
                    print("\n".join(f"[{i+1}] {path}" for i, path in enumerate(group)))
                    print(f"请选择操作：[y]保留第一个/[n]保留全部/[数字]指定保留（多个逗号分隔）/q退出：")
                    choice = input("请输入操作选择: ").strip().lower()
                    
                    if choice == 'q':
                        self.should_stop = True
                        return deleted_files
                    
                    # 处理不同输入模式
                    keep_indices = set()
                    if choice == 'y':
                        keep_indices = {0}
                    elif choice == 'n':
                        keep_indices = set(range(len(group)))
                    elif choice.isdigit() or ',' in choice:
                        try:
                            keep_indices = {max(0, int(i)-1) for i in choice.split(',')}
                            keep_indices = {idx for idx in keep_indices if 0 <= idx < len(group)}
                        except:
                            print("输入格式错误，将保留第一个文件")
                            keep_indices = {0}
                    else:
                        print("输入无效，将保留第一个文件")
                        keep_indices = {0}
                else:
                    # 自动模式直接保留第一个
                    keep_indices = {0}
                
                # 删除未保留文件
                for idx, path in enumerate(group):
                    if idx not in keep_indices:
                            try:
                                # 修改文件属性移除只读
                                if os.path.exists(path):
                                    os.chmod(path, 0o777)
                                # 创建快捷方式逻辑
                                if self.link_mode and keep_indices:
                                    first_kept = group[min(keep_indices)]
                                    if os.path.exists(first_kept):
                                        link_path = path + '.lnk'
                                        self._create_shortcut(first_kept, path)
                                # 带重试的删除逻辑
                                max_retries = 3
                                for attempt in range(max_retries):
                                    try:
                                        os.remove(path)
                                        break
                                    except PermissionError as pe:
                                        if attempt < max_retries - 1:
                                            time.sleep(0.5)
                                            continue
                                        raise
                                deleted_files.append(path)
                                if path in self.file_index:
                                    del self.file_index[path]
                                # 新增哈希缓存清理
                                if path in self.hash_cache:
                                    del self.hash_cache[path]
                                self._save_hash_cache()  # 保存缓存更新
                            except Exception as e:
                                print(f"删除文件失败 {path}: {str(e)}")

        # 更新持久化存储
        with open(self.file_cache, 'w') as f:
            json.dump(self.file_index, f)

        # 扫描完成后保存哈希缓存
        self._save_hash_cache()
        # 重新计算重复文件组
        new_duplicates = self.calculate_similarity(self.similarity_threshold)
        with open(self.duplicate_cache, 'w', encoding='utf-8') as f:
            json.dump(self.duplicate_index, f)
        return deleted_files

    def calculate_similarity(self, threshold: float) -> Dict[str, List[str]]:
        """
        计算文件相似度并分组
        参数：
            threshold: 相似度阈值
        返回：
            dict: 分组字典 {组ID: 文件路径列表}
        优化策略：
            1. 按sorted_size排序减少比较范围
            2. 仅比较相邻±10%范围的文件
            3. 添加根目录一致性检查
        """

        self.similarity_threshold = threshold
        groups = {}
        seen = set()
        
        # 按 sorted_size 排序后的文件列表
        sorted_files = sorted(self.file_index.items(), key=lambda x: x[1]['sorted_size'])
        # 提取所有文件的大小，用于二分搜索
        sizes = [data['sorted_size'] for _, data in sorted_files]
        
        for i, (path, data) in enumerate(sorted_files):
            if path in seen:
                continue
            
            group = [path]
            si = data['sorted_size']
            
            # 计算尺寸范围
            lower = si * 1  # Si * (1 - 0.05)
            upper = si / 1  # Si / (1 - 0.05)
            
            # 使用二分搜索找到满足尺寸范围的索引
            j = bisect_left(sizes, lower)
            k = bisect_right(sizes, upper)
            
            # 检查范围 [j, k) 内的文件
            for idx in range(j, k):
                other_path, other_data = sorted_files[idx]
                if path != other_path and other_path not in seen:
                    # 可选：如果 file_index 已确保文件存在，则移除此检查
                    if os.path.exists(other_path):
                        # 直接检查模糊匹配，因为尺寸条件已由范围保证
                        if self._fuzzy_match(data['name'], other_data['name']) >= threshold:
                            group.append(other_path)
                            seen.add(other_path)
            
            # 记录有效分组
            if len(group) > 1:
                if self.hash_check:
                    # 检查组内文件大小是否一致
                    group_sizes = {self.file_index[path]['sorted_size'] for path in group}
                    if len(group_sizes) != 1:
                        continue  # 大小不一致，跳过哈希校验

                    # 哈希校验
                    base_hash = None
                    same_hash = True
                    for file_path in group:
                        current_hash = self._calculate_hash(file_path)
                        if current_hash is None:  # 文件读取失败
                            same_hash = False
                            break
                        if base_hash is None:
                            base_hash = current_hash
                        elif current_hash != base_hash:
                            same_hash = False
                            break
                    if same_hash:
                        group_id = f"group_{len(groups) + 1}"
                        groups[group_id] = group
                    #groups[f"group_{len(groups)+1}"] = group
        return groups

    def export_duplicates(self, duplicates: Dict[str, List[str]], output_file: str, hash_check=False):
        """
        导出重复文件列表到JSON文件
        参数：
            duplicates: 重复文件分组字典
            output_file: 输出文件路径
            hash_check: 是否进行哈希校验
        返回：
            bool: 是否导出成功
        """
        try:
            # 执行哈希校验
            if hash_check:
                valid_duplicates = {}
                for group_id, group in duplicates.items():
                    hashes = set()
                    valid_files = []
                    for path in group:
                        if os.path.exists(path):
                            hashes.add(self._calculate_hash(path))
                            valid_files.append(path)
                    # 仅保留哈希值一致的有效分组
                    if len(hashes) == 1 and len(valid_files) > 1:
                        valid_duplicates[group_id] = valid_files
                duplicates = valid_duplicates
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(duplicates, f, indent=2, ensure_ascii=False)
            # 更新内存中的重复索引
            self.duplicate_index = duplicates
            with open(self.duplicate_cache, 'w', encoding='utf-8') as f:
                json.dump(self.duplicate_index, f)
            return True
        except Exception as e:
            print(f"导出失败: {str(e)}")
            return False
        
    def _calculate_hash(self, file_path: str) -> str:
        """计算文件的MD5哈希值"""
        if file_path in self.hash_cache:
            return self.hash_cache[file_path]
        
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            file_hash = hash_md5.hexdigest()
            self.hash_cache[file_path] = file_hash
            return file_hash
        except Exception as e:
            print(f"计算文件哈希失败 {file_path}: {str(e)}")
            return ""


def main():
    """
    命令行入口函数
    参数说明：
        directory: 必需参数，要扫描的目录
        -e/--extensions: 可选扩展名过滤（多个用空格分隔）
        -k/--keywords: 可选关键词过滤（多个用空格分隔）
        -t/--threshold: 相似度阈值（默认0.9）
        -d/--delete: 自动删除模式
        -o/--output: 结果输出文件
        -y/--yes: 跳过确认直接删除
    """
    parser = argparse.ArgumentParser(description='重复文件查找工具')
    parser.add_argument('directories', nargs='+', help='要扫描的目录（可多个）')
    parser.add_argument('-e', '--extensions', nargs='*', help='文件扩展名过滤')
    parser.add_argument('-ne', '--noextension', nargs='+', help='排除扩展名列表')
    parser.add_argument('-k', '--keywords', nargs='*', help='文件名关键词过滤')
    parser.add_argument('-nk', '--nokeyword', nargs='+', help='排除关键词列表')
    parser.add_argument('-t', '--threshold', type=float, default=0.9, help='相似度阈值 (0.0-1.0)')
    parser.add_argument('-d', '--delete', action='store_true', help='自动删除重复文件（保留每个分组第一个文件）')
    parser.add_argument('-o', '--output', help='结果输出文件')
    parser.add_argument('-l', '--link', action='store_true', help='删除时创建快捷方式链接到保留文件')
    parser.add_argument('-c', '--hash-check', action='store_true', help='启用哈希校验确保重复文件内容完全一致')
    parser.add_argument('-y', '--yes', action='store_true', help='跳过确认直接删除')
    
    args = parser.parse_args()
    

    dedup = FileDeduplicator(hash_check=args.hash_check, link_mode=args.link)
    root_dirs = [os.path.abspath(d) for d in args.directories]
    print(f"输入的目录参数: {args.directories}")
    for d in root_dirs:
        print(f"转换后的绝对路径: {d}")
    print(f"正在扫描目录: {', '.join(root_dirs)}...")
    start_time1 = time.perf_counter()
    dedup.scan_files(root_dirs, args.extensions, args.keywords, no_keyword=args.nokeyword, no_extension=args.noextension, similarity=args.threshold)
    end_time1 = time.perf_counter()
    time_part1 = end_time1 - start_time1
    print("正在分析重复文件...")
    start_time2 = time.perf_counter()
    results = dedup.calculate_similarity(args.threshold)
    end_time2 = time.perf_counter()
    time_part2 = end_time2 - start_time2

    start_time3 = time.perf_counter()
    # 处理结果输出
    if args.output:
        print(f"正在导出结果到 {args.output}...")
        dedup.export_duplicates(results, args.output, args.hash_check)
    else:
        # 默认保存到重复缓存
        dedup.export_duplicates(results, dedup.duplicate_cache, args.hash_check)
    
    # 更新为校验后的结果
    results = dedup.duplicate_index
    
    print("\n发现重复文件组:")                                                                                 
    for group in results.values():
        print("\n".join(group))
    
    # 执行删除操作
    if args.delete:
        print("正在删除重复文件...")
        deleted = dedup.delete_duplicates(results, confirm=not args.yes)
        print(f"已删除 {len(deleted)} 个重复文件")

    end_time3 = time.perf_counter()
    time_part3 = end_time3 - start_time3

    print(f"扫描目录 运行时间: {time_part1:.6f} 秒")
    print(f"重复查找 运行时间: {time_part2:.6f} 秒")
    print(f"删除文件 运行时间: {time_part3:.6f} 秒")
    print(f"总运行时间: {time_part1 + time_part2 + time_part3:.6f} 秒")

    
if __name__ == '__main__':
    main()
