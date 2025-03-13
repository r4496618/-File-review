import os
import hashlib
import argparse
from typing import List, Dict
import json

class FileDeduplicator:
    def __init__(self):
        self.file_cache = 'file_cache.json'
        self.duplicate_cache = 'duplicate_cache.json'
        self.similarity_threshold = 0.9  # 默认相似度阈值
        self.file_index = self._load_cache(self.file_cache)
        self.duplicate_index = self._load_cache(self.duplicate_cache)

    def _load_cache(self, cache_file):
        """加载已有缓存文件"""
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载缓存失败: {str(e)}")
        return {}

    def _fuzzy_match(self, s1: str, s2: str) -> float:
        """计算两个字符串的相似度（基于Levenshtein距离）"""
        # 预处理：去除扩展名并转为小写
        s1 = os.path.splitext(s1)[0].lower()
        s2 = os.path.splitext(s2)[0].lower()
        
        if len(s1) < len(s2):
            return self._fuzzy_match(s2, s1)

        max_len = max(len(s1), len(s2))
        if max_len == 0:
            return 1.0

        distance = self._levenshtein_distance(s1, s2)
        return 1 - distance / max_len

    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """计算Levenshtein编辑距离"""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        return previous_row[-1]

    def scan_files(self, root_dir: str, extensions: List[str] = None, 
                 keywords: List[str] = None, similarity: float = None) -> None:
        if similarity is not None:
            self.similarity_threshold = similarity

        new_files = {}
        for dirpath, _, filenames in os.walk(root_dir):
            for fname in filenames:
                full_path = os.path.join(dirpath, fname)
                if full_path in self.file_index:
                    current_size = os.path.getsize(full_path)
                    if current_size == self.file_index[full_path]['size']:
                        continue

                if extensions and not fname.lower().endswith(tuple(extensions)):
                    continue
                                # 添加文件名交叉比对逻辑
                if any(existing_file for existing_file in self.file_index.values() 
                    if existing_file['size'] == os.path.getsize(full_path) 
                    and self._fuzzy_match(existing_file['name'], os.path.splitext(fname)[0]) >= self.similarity_threshold):
                    continue

                    if keywords:
                        matches = [self._fuzzy_match(kw, os.path.splitext(fname)[0]) >= self.similarity_threshold 
                              for kw in keywords]
                    if not any(matches):
                        continue
            
                # 无条件添加通过筛选的文件
                new_files[full_path] = {
                    'size': os.path.getsize(full_path),
                    'name': os.path.splitext(fname)[0].lower()
                }

        self.file_index.update(new_files)
        with open(self.file_cache, 'w') as f:
            json.dump(self.file_index, f)

    def delete_duplicates(self, duplicates: Dict[str, List[str]], confirm=True):
        deleted_files = []
        for group_id, group in duplicates.items():
            if len(group) > 1:
                for path in group[1:]:
                    try:
                        os.remove(path)
                        deleted_files.append(path)
                        if path in self.file_index:
                            del self.file_index[path]
                    except Exception as e:
                        print(f"删除文件失败 {path}: {str(e)}")
        # 更新文件索引缓存
        with open(self.file_cache, 'w') as f:
            json.dump(self.file_index, f)
        # 重新计算并更新重复文件缓存
        new_duplicates = self.calculate_similarity(self.similarity_threshold)
        with open(self.duplicate_cache, 'w') as f:
            json.dump(new_duplicates, f)
        return deleted_files

    def calculate_similarity(self, threshold: float) -> Dict[str, List[str]]:
        self.similarity_threshold = threshold  # 同步阈值到类属性
        groups = {}
        seen = set()
        for path, data in self.file_index.items():
            if path in seen:
                continue
            group = [path]
            for other_path, other_data in self.file_index.items():
                if path != other_path and other_path not in seen:
                    if data['size'] == other_data['size'] and \
                       self._fuzzy_match(data['name'], other_data['name']) >= threshold:
                        group.append(other_path)
                        seen.add(other_path)
            if len(group) > 1:
                groups[f"group_{len(groups)+1}"] = group
        return groups

    def export_duplicates(self, duplicates: Dict[str, List[str]], output_file: str):
        try:
            with open(output_file, 'w') as f:
                json.dump(duplicates, f, indent=2, ensure_ascii=False)
            # 同时更新内存中的重复索引
            self.duplicate_index = duplicates
            with open(self.duplicate_cache, 'w') as f:
                json.dump(self.duplicate_index, f)
            return True
        except Exception as e:
            print(f"导出失败: {str(e)}")
            return False


def main():
    parser = argparse.ArgumentParser(description='重复文件查找工具')
    parser.add_argument('directory', help='要扫描的目录')
    parser.add_argument('-e', '--extensions', nargs='*', help='文件扩展名过滤')
    parser.add_argument('-k', '--keywords', nargs='*', help='文件名关键词过滤')
    parser.add_argument('-t', '--threshold', type=float, default=0.9, 
                      help='相似度阈值 (0.0-1.0)')
    parser.add_argument('-d', '--delete', action='store_true', 
                      help='自动删除重复文件（保留每个分组第一个文件）')
    parser.add_argument('-o', '--output', help='结果输出文件')
    parser.add_argument('-y', '--yes', action='store_true', 
                      help='跳过确认直接删除')
    
    args = parser.parse_args()
    
    dedup = FileDeduplicator()
    print(f"正在扫描目录: {args.directory}...")
    dedup.scan_files(args.directory, args.extensions, args.keywords, similarity=args.threshold)
    
    print("正在分析重复文件...")
    results = dedup.calculate_similarity(args.threshold)
    
    print("\n发现重复文件组:")
    for group in results.values():
        print("\n".join(group))
    if args.output:
        print(f"正在导出结果到 {args.output}...")
        dedup.export_duplicates(results, args.output)
    else:
        # 默认保存到重复缓存
        dedup.export_duplicates(results, dedup.duplicate_cache)
    
    if args.delete:
        print("正在删除重复文件...")
        deleted = dedup.delete_duplicates(results, confirm=not args.yes)
        print(f"已删除 {len(deleted)} 个重复文件")

if __name__ == '__main__':
    main()